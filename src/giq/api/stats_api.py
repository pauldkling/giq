# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Dashboard-facing API: usage stats, model catalog, and quick self-tests."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
import struct
import time
import wave
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from giq import paths as giq_paths
from giq import recipes
from giq.api.dependencies import get_orchestrator
from giq.engines import ENGINE_OF_BACKEND
from giq.gpus import get_gpus, resolve_device, selected_device
from giq.models import JobRequest
from giq.policy import RESIDENT_SET_HEADROOM_GB, get_policy_store
from giq.registry import all_recipes, get_recipe, resident_defaults
from giq.runner import get_runner
from giq.services.orchestration import Orchestrator
from giq.stats import get_stats
from giq.storage import StorageError, delete_model, storage_report
from giq.vram import get_vram_status, margin_for, reserve_for

logger = logging.getLogger(__name__)

router = APIRouter()

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
# The React dashboard, built by `make ui` (frontend/ → vite build). Not in
# git: the wheel carries it as a build artifact, a checkout builds it.
_UI_DIR = _STATIC_DIR / "ui"

_UI_MISSING = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>giq</title></head>
<body style="font-family: system-ui, sans-serif; padding: 2rem; line-height: 1.5">
<h1 style="font-weight: 500">UI not built</h1>
<p>The dashboard is a separate build step. Run <code>make ui</code> in the giq
checkout (it needs Node.js 22.12+ and npm), then reload this page. A server
without one installs a prebuilt dashboard instead:
<code>deploy/install-debian.sh --ui-only --ui-tarball giq-ui-&lt;version&gt;.tar.gz</code>
(made by <code>make ui-dist</code>), as docs/deployment.md describes.</p>
<p>The API is up regardless: <a href="/status">/status</a>, <a href="/docs">/docs</a>.</p>
</body></html>
"""


class _UiAssets(StaticFiles):
    """The built dashboard's hashed assets.

    Mounted at import, whether or not the UI has been built yet: without the
    directory every request is a plain 404 (StaticFiles would otherwise fail
    its startup check and turn each one into a 500), and a `make ui` run
    while giq is up is served without a restart.
    """

    async def check_config(self) -> None:
        if Path(str(self.directory)).is_dir():
            await super().check_config()


router.mount(
    "/dash/assets",
    _UiAssets(directory=_UI_DIR / "assets", check_dir=False),
    name="dash-assets",
)


@router.get("/dash", include_in_schema=False)
@router.get("/dash/", include_in_schema=False)
async def dashboard() -> Response:
    """The giq dashboard: the built React app, or a note saying how to build it."""
    index = _UI_DIR / "index.html"
    if not index.is_file():
        return HTMLResponse(_UI_MISSING, status_code=503)
    # The page names its hashed assets, so it must never be cached stale:
    # the assets themselves are immutable and cache fine.
    return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})


@router.get("/sandbox", include_in_schema=False)
async def sandbox() -> RedirectResponse:
    """The sandbox is part of the dashboard; keep old links alive."""
    return RedirectResponse("/dash#/sandbox")


# --- stats -----------------------------------------------------------------


@router.get("/stats/summary")
async def stats_summary(hours: float = Query(default=24, gt=0, le=24 * 365)) -> dict:
    """Per worker/model aggregates over the window."""
    since = time.time() - hours * 3600
    rows = await get_stats().fetch(
        """
        SELECT worker, model, COUNT(*),
               SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END),
               AVG(run_ms), MAX(run_ms), AVG(queue_wait_ms), SUM(tasks)
        FROM jobs WHERE ts >= ? GROUP BY worker, model ORDER BY COUNT(*) DESC
        """,
        (since,),
    )
    evictions = await get_stats().fetch(
        "SELECT COUNT(*) FROM events WHERE ts >= ? AND kind = 'evict'", (since,)
    )
    return {
        "hours": hours,
        "evictions": evictions[0][0] if evictions else 0,
        "models": [
            {
                "worker": w,
                "model": m,
                "jobs": n,
                "failed": failed,
                "avg_run_ms": round(avg_run) if avg_run is not None else None,
                "max_run_ms": max_run,
                "avg_queue_ms": round(avg_q) if avg_q is not None else None,
                "tasks": tasks,
            }
            for (w, m, n, failed, avg_run, max_run, avg_q, tasks) in rows
        ],
    }


_USAGE_PERIODS: dict[str, tuple[float | None, str]] = {
    # period -> (window seconds before now | None = local midnight / all-time,
    #            strftime bucket format, local time)
    "day": (None, "%Y-%m-%d %H:00"),
    "week": (7 * 86400, "%Y-%m-%d"),
    "month": (30 * 86400, "%Y-%m-%d"),
    "all": (0, "%Y-%m"),
}


def _parse_bound(value: str | None) -> float | None:
    """Accept a unix epoch or an ISO date/datetime as a range bound."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"Bad time bound {value!r}: use epoch seconds or ISO 8601"
        ) from e


@router.get("/stats/gpus/eras")
async def gpu_eras() -> dict:
    """Every card this machine has had, with per-era usage rollups.

    Survives gpu_samples' retention window — this is the permanent record of
    what hardware ran what.
    """
    rows = await get_stats().fetch(
        """
        SELECT e.gpu_uuid, e.name, e.total_gb, e.first_seen, e.last_seen,
               COUNT(j.id),
               SUM(CASE WHEN j.status != 'completed' THEN 1 ELSE 0 END),
               SUM(j.tokens_in), SUM(j.tokens_out), AVG(j.run_ms),
               MIN(j.ts), MAX(j.ts)
        FROM gpu_eras e LEFT JOIN jobs j ON j.gpu_uuid = e.gpu_uuid
        GROUP BY e.gpu_uuid ORDER BY e.first_seen
        """
    )
    return {
        "eras": [
            {
                "uuid": uuid,
                "name": name,
                "total_gb": total,
                "first_seen": first,
                "last_seen": last,
                "jobs": jobs,
                "failed": failed or 0,
                "tokens_in": tin,
                "tokens_out": tout,
                "avg_run_ms": round(avg) if avg is not None else None,
                "first_job": fj,
                "last_job": lj,
            }
            for (
                uuid,
                name,
                total,
                first,
                last,
                jobs,
                failed,
                tin,
                tout,
                avg,
                fj,
                lj,
            ) in rows
        ]
    }


@router.get("/stats/usage")
async def stats_usage(
    period: str = Query(default="week", pattern="^(day|week|month|all)$"),
    gpu: str | None = Query(default=None, description="Restrict to one GPU uuid"),
    since: str | None = Query(default=None, description="Range start: epoch or ISO 8601"),
    until: str | None = Query(default=None, description="Range end: epoch or ISO 8601"),
) -> dict:
    """Token/call rollups per model, plus a bucketed series for the chart.

    Windows: day = since local midnight (hourly buckets), week = 7d, month = 30d
    (daily buckets), all = everything (monthly buckets). An explicit
    since/until pair overrides `period` for the range but still uses its
    bucket size; `gpu` restricts every figure to one card.
    """
    window, bucket_fmt = _USAGE_PERIODS[period]
    lo, hi = _parse_bound(since), _parse_bound(until)
    if lo is None:
        if period == "day":
            lo = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        elif window:
            lo = time.time() - window
        else:
            lo = 0.0
    if hi is not None and hi <= lo:
        raise HTTPException(status_code=400, detail="`until` must be after `since`")

    where = "ts >= ?"
    params: list = [lo]
    if hi is not None:
        where += " AND ts < ?"
        params.append(hi)
    if gpu:
        where += " AND gpu_uuid = ?"
        params.append(gpu)

    models = await get_stats().fetch(
        f"""
        SELECT worker, model, COUNT(*),
               SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END),
               SUM(tasks), SUM(tokens_in), SUM(tokens_out), MAX(ts)
        FROM jobs WHERE {where} GROUP BY worker, model
        ORDER BY COALESCE(SUM(tokens_in),0) + COALESCE(SUM(tokens_out),0) DESC, COUNT(*) DESC
        """,
        tuple(params),
    )
    series = await get_stats().fetch(
        f"""
        SELECT strftime('{bucket_fmt}', ts, 'unixepoch', 'localtime') AS b,
               worker, model, COUNT(*), SUM(tokens_in), SUM(tokens_out)
        FROM jobs WHERE {where} GROUP BY b, worker, model ORDER BY b
        """,
        tuple(params),
    )
    return {
        "period": period,
        "gpu": gpu,
        "since": lo,
        "until": hi,
        "totals": {
            "jobs": sum(r[2] for r in models),
            "failed": sum(r[3] or 0 for r in models),
            "tokens_in": sum(r[5] or 0 for r in models),
            "tokens_out": sum(r[6] or 0 for r in models),
        },
        "models": [
            {
                "worker": w,
                "model": m,
                "jobs": n,
                "failed": failed or 0,
                "tasks": tasks,
                "tokens_in": tin,
                "tokens_out": tout,
                "last_ts": last,
            }
            for (w, m, n, failed, tasks, tin, tout, last) in models
        ],
        "series": [
            {"b": b, "worker": w, "model": m, "jobs": n, "tokens_in": tin, "tokens_out": tout}
            for (b, w, m, n, tin, tout) in series
        ],
    }


@router.get("/stats/timeline")
async def stats_timeline(
    hours: float = Query(default=24, gt=0, le=24 * 365),
    bucket_s: int = Query(default=3600, ge=60),
) -> dict:
    """Bucketed job counts per worker (stacked-bar source)."""
    since = time.time() - hours * 3600
    rows = await get_stats().fetch(
        """
        SELECT CAST(ts / ? AS INTEGER) * ? AS bucket, worker, COUNT(*),
               SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END), AVG(run_ms)
        FROM jobs WHERE ts >= ? GROUP BY bucket, worker ORDER BY bucket
        """,
        (bucket_s, bucket_s, since),
    )
    return {
        "bucket_s": bucket_s,
        "points": [
            {
                "t": b,
                "worker": w,
                "jobs": n,
                "failed": f,
                "avg_run_ms": round(avg) if avg is not None else None,
            }
            for (b, w, n, f, avg) in rows
        ],
    }


@router.get("/stats/vram")
async def stats_vram(hours: float = Query(default=6, gt=0, le=24 * 14)) -> dict:
    since = time.time() - hours * 3600
    rows = await get_stats().fetch(
        "SELECT ts, used_gb, free_gb, active_worker, residents_ready FROM vram_samples"
        " WHERE ts >= ? ORDER BY ts",
        (since,),
    )
    return {
        "total_gb": get_vram_status().total_gb,
        "samples": [
            {"t": t, "used": round(u, 2), "active": a, "ready": r} for (t, u, _f, a, r) in rows
        ],
    }


@router.get("/stats/gpus")
async def stats_gpus(hours: float = Query(default=6, gt=0, le=24 * 14)) -> dict:
    """Per-GPU telemetry history (temp/power/util/vram), grouped by UUID."""
    import asyncio

    since = time.time() - hours * 3600
    rows = await get_stats().fetch(
        "SELECT ts, gpu_uuid, used_gb, total_gb, temp_c, power_w, util_pct"
        " FROM gpu_samples WHERE ts >= ? ORDER BY ts",
        (since,),
    )
    live = {g.uuid: g for g in await asyncio.to_thread(get_gpus)}
    series: dict[str, dict] = {}
    for ts, uuid, used, total, temp, power, util in rows:
        entry = series.setdefault(
            uuid,
            {
                "uuid": uuid,
                "index": live[uuid].index if uuid in live else None,
                "name": live[uuid].name if uuid in live else uuid,
                "total_gb": total,
                "power_limit": live[uuid].power_limit_w if uuid in live else None,
                "samples": [],
            },
        )
        entry["samples"].append({"t": ts, "used": used, "temp": temp, "power": power, "util": util})
    ordered = sorted(series.values(), key=lambda s: (s["index"] is None, s["index"]))
    return {"hours": hours, "gpus": ordered}


@router.get("/stats/events")
async def stats_events(
    hours: float = Query(default=48, gt=0, le=24 * 30), limit: int = 200
) -> list:
    since = time.time() - hours * 3600
    rows = await get_stats().fetch(
        "SELECT ts, kind, detail FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
        (since, limit),
    )
    return [{"t": t, "kind": k, "detail": d} for (t, k, d) in rows]


@router.get("/stats/jobs")
async def stats_jobs(
    limit: int = Query(default=50, le=500),
    gpu: str | None = Query(default=None, description="Restrict to one GPU uuid"),
) -> list:
    where = "WHERE gpu_uuid = ?" if gpu else ""
    params = (gpu, limit) if gpu else (limit,)
    rows = await get_stats().fetch(
        "SELECT ts, job_id, worker, model, status, queue_wait_ms, run_ms, tasks, error,"
        f" tokens_in, tokens_out FROM jobs {where} ORDER BY ts DESC LIMIT ?",
        params,
    )
    return [
        {
            "t": t,
            "job_id": j,
            "worker": w,
            "model": m,
            "status": s,
            "queue_ms": q,
            "run_ms": r,
            "tasks": n,
            "error": e,
            "tokens_in": tin,
            "tokens_out": tout,
        }
        for (t, j, w, m, s, q, r, n, e, tin, tout) in rows
    ]


def reasoning_for(worker: str, model: str) -> str | None:
    """Whether giq starts this model's server with thinking on.

    `--reasoning on` is a server-level switch (llama-server: "use
    reasoning/thinking in the chat"), so it is a property of how giq launches
    the model, not of the request — which is why a caller cannot discover it
    and has to be told.
    """
    if worker != "llm":
        return None
    from giq.workers.engine import engine_for

    if engine_for(model) == "vllm":
        # vllm has no server-level switch: the chat template decides, and a
        # caller turns it off per request with chat_template_kwargs.
        return "template"
    from giq.workers.llm import DEFAULT_REASONING, MODEL_REASONING

    return MODEL_REASONING.get(model, DEFAULT_REASONING)


def _ref(name: str) -> str:
    """``modality/name``, the form the dashboard matches residency against until step 7."""
    recipe = get_recipe(name)
    return f"{recipe.modality}/{name}" if recipe is not None else name


@router.get("/stats/models")
async def model_catalog() -> dict:
    """Every recipe with VRAM needs and current schedulability.

    One entry per recipe. ``worker`` is its first modality, which the
    dashboard groups by; ``modalities`` is every one it serves (flux_klein
    renders and edits). ADR-003 step 6 renames the keys.
    """
    from giq.policy import get_policy_store

    runner = get_runner()
    store = get_policy_store()
    vram = get_vram_status()
    resident_ready = runner.resident_models
    resident_devices = runner.resident_devices
    resident_keys = set(store.residents())
    defaults = set(resident_defaults())

    # Everything below is per card. "Does it fit?" has no machine-wide answer
    # once models are bound: the same 13GB model fits one card and can never
    # fit the other, and evicting a resident frees nothing for a load on a
    # different card.
    cards = {gpu.uuid: gpu for gpu in await asyncio.to_thread(get_gpus)}
    evictable_by_device: dict[str | None, float] = {}
    for recipe in all_recipes():
        if resident_ready.get(recipe.name, False):
            where = resident_devices.get(recipe.name)
            evictable_by_device[where] = evictable_by_device.get(where, 0.0) + recipe.vram_gb
    evictable = sum(evictable_by_device.values())

    models = []
    for recipe in all_recipes():
        record = store.record_for(recipe.name)
        where = store.effective_device(recipe.name)
        card = resolve_device(where) if where else None
        device_index = card.index if card else None
        device_name = card.name if card else None
        # Fall back to the gate's own figures when no card resolves at all.
        card_total = cards[where].vram_total_gb if where in cards else vram.total_gb
        card_free = cards[where].vram_free_gb if where in cards else vram.free_gb
        card_evictable = evictable_by_device.get(where, 0.0)
        needed = recipe.vram_gb + margin_for(recipe.vram_gb) + reserve_for(where)
        if resident_ready.get(recipe.name, False):
            fits = "loaded"
        elif needed > card_total:
            fits = "never"
        elif needed <= card_free:
            fits = "fits_now"
        elif needed <= card_free + card_evictable:
            fits = "fits_after_eviction"
        else:
            fits = "wont_fit_now"
        models.append(
            {
                "worker": recipe.modality,
                "modalities": list(recipe.modalities),
                "model": recipe.name,
                "vram_gb": recipe.vram_gb,
                "needed_gb": round(needed, 1),
                "measured": recipe.measured,
                "backend": recipe.engine,
                "engine": recipe.engine,
                "label": recipe.display,
                "detail": recipe.detail,
                "lanes": recipe.lanes,
                "resident": recipe.name in resident_keys,
                # Whether this model is *meant* to be resident, independent of
                # what the operator has done to it. The homepage lane cards key
                # on this: a stopped resident must keep its card (and its play
                # button) instead of vanishing from the list.
                "resident_default": recipe.name in defaults,
                "ready": resident_ready.get(recipe.name, False),
                "fits": fits,
                "policy": record.policy,
                "policy_source": record.source,
                "policy_reason": record.reason,
                # Where it loads. `device` is the explicit binding (null when
                # unbound); `device_index`/`device_name` describe the card it
                # actually lands on either way.
                # "on" | "off" | "template" for LLMs, null otherwise. A model
                # that thinks needs a much larger token budget than one that
                # does not — below it, the answer is empty rather than short.
                "reasoning": reasoning_for(recipe.modality, recipe.name),
                # Accepts images alongside text. A capability of the model,
                # not a worker type — it still serves ordinary chat.
                "vision": recipe.vision,
                # Which declared engine binary executes it. Distinct from
                # `backend` (the engine's name, and `engine` for the image
                # models): the audio and embed stacks are different engines
                # running on one interpreter.
                "runtime": ENGINE_OF_BACKEND.get(recipe.engine, recipe.engine),
                "device": record.device,
                "device_source": record.device_source,
                "effective_device": where,
                "device_index": device_index,
                "device_name": device_name,
            }
        )
    # The tightest card, not the machine: two cards' pinned sets don't compete,
    # so a machine-wide total would say "fits" while one card is over-committed.
    fits, needed_gb, _total_gb, tight_device = store.pinned_fit()
    pinned_by_device = store.pinned_by_device()
    default_card = selected_device()
    # One budget per card. A single bar mixing both cards' pinned models
    # against one card's total is a sentence with two subjects.
    card_budgets = []
    for uuid, gpu in sorted(cards.items(), key=lambda kv: kv[1].index):
        pinned_gb = store.pinned_vram_gb(device=uuid)
        projected = pinned_gb + RESIDENT_SET_HEADROOM_GB + reserve_for(uuid)
        card_budgets.append(
            {
                "uuid": uuid,
                "index": gpu.index,
                "name": gpu.name,
                "total_gb": round(gpu.vram_total_gb, 2),
                "free_gb": round(gpu.vram_free_gb, 2),
                "reserve_gb": reserve_for(uuid),
                "pinned_gb": round(pinned_gb, 2),
                "pinned_needed_gb": round(projected, 2),
                "pinned_fits": projected <= gpu.vram_total_gb,
                "pinned": [_ref(n) for n in pinned_by_device.get(uuid, [])],
                "default": bool(default_card and default_card.uuid == uuid),
            }
        )
    return {
        "cards": card_budgets,
        "free_gb": round(vram.free_gb, 2),
        "total_gb": round(vram.total_gb, 2),
        "evictable_gb": round(evictable, 1),
        # Budget for the pinned set, so the dashboard can show what pinning one
        # more model would cost before the operator commits. pinned_gb is the
        # weights alone; pinned_needed_gb adds the headroom the set must leave.
        "pinned_gb": round(store.pinned_vram_gb(device=tight_device), 2),
        "pinned_needed_gb": needed_gb,
        "pinned_fits": fits,
        "pinned_device": tight_device,
        "pinned_by_device": {
            uuid or "unassigned": [_ref(n) for n in names]
            for uuid, names in store.pinned_by_device().items()
        },
        # Reload priority order — which model comes back first, and by the same
        # token which is the last to be evicted. Not the catalog's sort order.
        "pinned": [_ref(n) for n in store.residents()],
        "models": models,
    }


# --- storage ---------------------------------------------------------------


@router.get("/storage")
async def storage() -> dict:
    """Per-model disk footprint, last use, per-mount disk breakdown, the
    data directories giq resolved (``paths``), and the operator's recipe
    files (``recipes``): the directory, the files serving, the built-ins
    they replace, and the files left out with the reason.

    The directories sit here rather than on /status because this endpoint
    already answers with absolute model paths under the same access rules:
    it tells the operator nothing about the host that it did not before, and
    "which config and which state dir is this recipe using" is a storage
    question.
    """
    models, disks = await asyncio.to_thread(storage_report)
    last_used = {
        (w, m): ts
        for w, m, ts in await get_stats().fetch(
            "SELECT worker, model, MAX(ts) FROM jobs WHERE status='completed' "
            "GROUP BY worker, model"
        )
    }
    resident_keys = set(get_policy_store().residents())
    return {
        "paths": giq_paths.resolved(),
        "recipes": recipes.describe(recipes.current()),
        "disks": disks,
        "models": [
            {
                "worker": ms.worker,
                "model": ms.model,
                "size_bytes": ms.size_bytes,
                "on_disk": ms.on_disk,
                "shared_with": ms.shared_with,
                "resident": (ms.worker, ms.model) in resident_keys,
                "last_used": last_used.get((ms.worker, ms.model)),
                "paths": [str(p) for p in ms.paths],
            }
            for ms in models
        ],
    }


@router.delete("/storage/models/{worker}/{model}")
async def delete_model_weights(worker: str, model: str) -> dict:
    """Remove a model's weight files from disk (registry entry remains)."""
    runner = get_runner()
    recipe = get_recipe(model)
    if recipe is None or not recipe.serves(worker):
        raise HTTPException(status_code=404, detail=f"unknown recipe {worker}/{model}")
    model = recipe.name
    resident_keys = set(get_policy_store().residents())
    try:
        result = await asyncio.to_thread(
            delete_model, model, resident_keys=resident_keys, loaded=runner.loaded_keys()
        )
    except StorageError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    if result["deleted"]:
        await get_stats().record_event(
            "delete_model", f"{model} freed {result['freed_bytes']} bytes"
        )
        logger.info("deleted %s: %s", model, result["deleted"])
    return result


# --- quick tests -----------------------------------------------------------


def _beep_wav(seconds: float = 1.0, freq: float = 440.0) -> bytes:
    """Tiny synthesized test tone (no deps)."""
    buf = io.BytesIO()
    rate = 16000
    with wave.open(buf, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(rate * seconds)
        frames = b"".join(
            struct.pack(
                "<h",
                int(
                    6000
                    * math.sin(2 * math.pi * freq * t / rate)
                    * (0.5 + 0.5 * math.sin(2 * math.pi * 3 * t / rate))
                ),
            )
            for t in range(n)
        )
        w.writeframes(frames)
    return buf.getvalue()


@router.post("/test/{kind}")
async def quick_test(
    kind: str,
    confirm: bool = False,
    orch: Orchestrator = Depends(get_orchestrator),
) -> dict:
    """Canned end-to-end smoke test per lane. `image` evicts the resident set
    for minutes — requires ?confirm=true."""
    started = time.monotonic()

    if kind == "llm":
        request = JobRequest(
            modality="llm",
            model="gemma-4-12b",
            tasks=[
                {
                    "id": "dash-llm",
                    "user": "Reply with exactly: PONG",
                    "params": {"max_tokens": 8, "enable_thinking": False},
                }
            ],
        )
        timeout = 120.0
    elif kind == "audio":
        request = JobRequest(
            modality="audio",
            model="whisper-large-v3",
            tasks=[
                {
                    "id": "dash-audio",
                    "audio_b64": base64.b64encode(_beep_wav()).decode(),
                    "language": "en",
                    "diarize": True,
                }
            ],
        )
        timeout = 180.0
    elif kind == "embed":
        request = JobRequest(
            modality="embed",
            model="ecapa-tdnn",
            tasks=[{"id": "dash-embed", "audio_b64": base64.b64encode(_beep_wav()).decode()}],
        )
        timeout = 120.0
    elif kind == "image":
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Image test evicts all residents for minutes — pass ?confirm=true",
            )
        request = JobRequest(
            modality="text2image",
            model="flux_klein",
            tasks=[
                {"id": "dash-image", "prompt": "a tiny test pattern, colorful geometric shapes"}
            ],
        )
        timeout = 700.0
    else:
        raise HTTPException(status_code=404, detail=f"Unknown test kind: {kind}")

    job_id, _ = await orch.submit_job(request)
    job = await orch.wait_for_job(job_id, timeout=timeout)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    result = job.results[0] if job.results else {}
    snippet: dict = {"job_id": job_id, "latency_ms": elapsed_ms, "ok": True}
    if kind == "llm":
        snippet["output"] = (result.get("output") or "")[:200]
    elif kind == "audio":
        snippet["output"] = result.get("text", "") or "(silence — VAD gated the test tone)"
        snippet["language"] = result.get("language")
    elif kind == "embed":
        snippet["dim"] = result.get("dim")
    elif kind == "image":
        snippet["seed"] = result.get("seed")
        snippet["image_b64"] = result.get("image_b64")
    return snippet
