# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import base64
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartParser

from giq import __version__
from giq.api.access import posture as access_posture
from giq.api.dependencies import get_orchestrator
from giq.gpus import attribute_vram, get_gpus, resolve_device, selected_device
from giq.models import (
    Capabilities,
    JobRequest,
    JobResponse,
    JobStatus,
    JobStatusResponse,
    ModelDeviceRequest,
    ModelPolicyRequest,
    ModelPolicyResponse,
    ModelPolicyState,
    PauseRequest,
    PauseResponse,
    ServiceState,
    ServiceStatus,
    WorkerCapability,
    WorkerType,
)
from giq.queue import get_queue
from giq.registry import all_specs, get_spec
from giq.runner import get_runner
from giq.services.orchestration import Orchestrator
from giq.vram import can_load_model, get_vram_status

logger = logging.getLogger(__name__)

router = APIRouter()


# Ceiling for ?wait=true: an image batch ahead in the queue can hold a job
# for many minutes. Kept under 900s, a common client-side poll budget.
SYNC_WAIT_TIMEOUT_SECONDS = 880.0

# The routers are imported once, as the service starts; uptime counts from
# here. Monotonic, so a clock change does not make the service younger.
_STARTED = time.monotonic()


@router.post("/run")
async def run_job(
    request: JobRequest,
    wait: bool = False,
    orch: Orchestrator = Depends(get_orchestrator),
) -> dict:
    """Submit a new job for execution.

    With ``?wait=true`` the call blocks until the job completes and returns
    the full status payload (no client-side polling — the low-latency path
    for live audio). Client disconnect cancels a still-pending job so stale
    work doesn't pile up behind an image batch.
    """
    job_id, position = await orch.submit_job(request)
    logger.info(
        f"Job {job_id} submitted: {request.worker}/{request.model}, "
        f"{len(request.tasks) if request.tasks else 0} tasks"
    )
    if not wait:
        return JobResponse(job_id=job_id, position=position).model_dump()

    try:
        job = await orch.wait_for_job(job_id, timeout=SYNC_WAIT_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        await orch.cancel_job(job_id)
        raise
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        worker=job.request.worker,
        model=job.request.model,
        results=job.results if job.results else None,
        duration_ms=job.duration_ms,
    ).model_dump()


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str, orch: Orchestrator = Depends(get_orchestrator)
) -> JobStatusResponse:
    """Get job status and results."""
    queue = get_queue()
    job = await queue.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        worker=job.request.worker,
        model=job.request.model,
        results=job.results if job.results else None,
        duration_ms=job.duration_ms,
    )


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str, orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Cancel a pending job."""
    cancelled, reason = await orch.cancel_job(job_id)
    if not cancelled:
        if "not found" in reason.lower():
            raise HTTPException(status_code=404, detail=reason)
        return {"cancelled": False, "reason": reason}
    return {"cancelled": True}


@router.get("/gpus")
async def list_gpus() -> dict:
    """Per-GPU telemetry: identity (stable UUID), VRAM, temp, power, throttle.

    ``selected`` marks the default card. Each card also splits its used VRAM
    into ``vram_giq_gb`` (models giq is holding, with a per-process
    ``giq`` breakdown) and ``vram_other_gb`` (everything else on the card —
    the desktop, another CUDA app, a game). "Is this card full because of me?"
    is a different question from "is it full", and only the first one tells
    an operator whether giq can do anything about it.
    """
    gpus = await asyncio.to_thread(get_gpus)
    device = await asyncio.to_thread(selected_device)
    chosen = device.uuid if device else None
    owned = get_runner().owned_pids
    attribution = await asyncio.to_thread(attribute_vram, owned, gpus)
    return {
        "selected": chosen,
        "gpus": [
            {
                **g.to_dict(),
                "selected": g.uuid == chosen,
                "vram_giq_gb": attribution.get(g.uuid, {}).get("giq_gb", 0.0),
                "vram_other_gb": attribution.get(g.uuid, {}).get(
                    "other_gb", round(g.vram_used_gb, 2)
                ),
                "giq": attribution.get(g.uuid, {}).get("giq", []),
            }
            for g in gpus
        ],
    }


@router.post("/control/pause", response_model=PauseResponse)
async def pause_serving(request: PauseRequest | None = None) -> PauseResponse:
    """Suspend serving and unload every model, freeing the GPU.

    Graceful by default: in-flight jobs and live llama-server sessions get up
    to a minute to finish before the teardown. ``{"force": true}`` skips that
    wait for when the VRAM is needed right now. While paused, job submission
    returns 503 — nothing queues up behind the pause. Idempotent.
    """
    req = request or PauseRequest()
    result = await get_runner().pause(force=req.force, reason=req.reason)
    # nvidia-smi can lag CUDA teardown by a second or two; the dashboard's
    # /status poll shows the settled figure moments later.
    vram = await asyncio.to_thread(get_vram_status)
    return PauseResponse(**result, vram_free_gb=vram.free_gb, vram_total_gb=vram.total_gb)


@router.post("/control/resume", response_model=PauseResponse)
async def resume_serving() -> PauseResponse:
    """Resume serving. Residents reload within a few seconds. Idempotent."""
    result = await get_runner().resume()
    vram = await asyncio.to_thread(get_vram_status)
    return PauseResponse(**result, vram_free_gb=vram.free_gb, vram_total_gb=vram.total_gb)


def _policy_state(worker: str, model: str) -> ModelPolicyState:
    from giq.policy import get_policy_store

    store = get_policy_store()
    record = store.record_for(worker, model)
    spec = get_spec(worker, model)
    ready = get_runner().resident_models.get(f"{worker}/{model}", False)
    effective = store.effective_device(worker, model)
    gpu = resolve_device(effective) if effective else None
    return ModelPolicyState(
        worker=record.worker,
        model=record.model,
        policy=record.policy,
        source=record.source,
        reason=record.reason,
        updated_at=record.updated_at,
        vram_gb=spec.vram_gb if spec else 0.0,
        ready=ready,
        device=record.device,
        device_source=record.device_source,
        effective_device=effective,
        device_index=gpu.index if gpu else None,
        device_name=gpu.name if gpu else None,
    )


def _policy_response(worker: str, model: str, warnings: list[str]) -> ModelPolicyResponse:
    from giq.policy import get_policy_store

    store = get_policy_store()
    key = (worker, model)
    _fits, _needed, total, _device = store.pinned_fit(extra=key)
    return ModelPolicyResponse(
        state=_policy_state(worker, model),
        pinned=[f"{w}/{m}" for w, m in store.residents()],
        # This model's card, not the machine: the budget a caller is checking
        # is the one its own pin competes for.
        pinned_vram_gb=round(store.pinned_vram_gb(device=store.effective_device(*key)), 2),
        vram_total_gb=total,
        pinned_by_device={
            uuid or "unassigned": [f"{w}/{m}" for w, m in keys]
            for uuid, keys in store.pinned_by_device().items()
        },
        warnings=warnings,
    )


@router.get("/control/models", response_model=list[ModelPolicyState])
async def list_model_policies() -> list[ModelPolicyState]:
    """Residency policy for every registered model."""
    from giq.policy import get_policy_store

    return [_policy_state(r.worker, r.model) for r in get_policy_store().all_records()]


@router.post("/control/models/{worker}/{model}", response_model=ModelPolicyResponse)
async def set_model_policy(
    worker: str, model: str, request: ModelPolicyRequest
) -> ModelPolicyResponse:
    """Set a model's residency policy: pinned, auto, or off.

    ``pinned`` keeps it loaded and brings it back on boot; ``auto`` loads it on
    demand and lets the scheduler evict it; ``off`` refuses jobs for it and
    blocks every load path until it is set back.

    Changes take effect on the next residents tick (a few seconds), which is
    also when an unpinned model is actually unloaded — teardown waits out
    in-flight lane jobs first, so nothing is killed mid-generation.

    Pinning a set that cannot coexist on the card is refused with 409: the
    scheduler would thrash reloads forever trying to satisfy it. ``force``
    overrides that. Pinning a second LLM is refused outright — every
    llama-server binds the same internal port.
    """
    from giq.policy import PINNED, get_policy_store

    store = get_policy_store()
    warnings: list[str] = []

    if get_spec(worker, model) is None:
        raise HTTPException(status_code=404, detail=f"{worker}/{model} is not a registered model")

    if request.policy == PINNED:
        target = store.effective_device(worker, model)
        other_llm = store.resident_llm(exclude=(worker, model), device=target)
        if worker == "llm" and other_llm is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{other_llm[0]}/{other_llm[1]} is already pinned to the same card. One "
                    "resident LLM per card: both llama-servers would bind that card's "
                    "internal port. Unpin it, or bind one of them to another card."
                ),
            )
        fits, projected, total, device = store.pinned_fit(extra=(worker, model))
        where = _device_label(device)
        if not fits and not request.force:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"pinning {worker}/{model} would need {projected:.1f}GB of "
                    f"{total:.1f}GB on {where} — the resident set there could never all "
                    "load, and the scheduler would retry forever. Unpin something, bind it "
                    "to another card, or pass force=true."
                ),
            )
        if not fits:
            warnings.append(
                f"pinned set on {where} needs {projected:.1f}GB of {total:.1f}GB — "
                "it cannot all load"
            )

    try:
        store.set(worker, model, request.policy, request.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    from giq.stats import get_stats

    await get_stats().record_event("policy", f"{worker}/{model} -> {request.policy}")
    return _policy_response(worker, model, warnings)


def _device_label(uuid: str | None) -> str:
    """Human-readable card name for messages: "GPU 1 (RTX 5060 Ti)"."""
    gpu = resolve_device(uuid) if uuid else None
    if gpu is None:
        return "the default card"
    return f"GPU {gpu.index} ({gpu.name})"


@router.post("/control/models/{worker}/{model}/device", response_model=ModelPolicyResponse)
async def set_model_device(
    worker: str, model: str, request: ModelDeviceRequest
) -> ModelPolicyResponse:
    """Bind a model to a GPU, or unbind it with ``{"device": null}``.

    Takes an index or a UUID and stores the UUID — an index is a position in
    this boot's enumeration order and a binding has to outlive that.

    Binding decides where the model loads, which card's VRAM it is gated
    against, and which residents can be evicted to make room for it. It does
    not change residency: a pinned model stays pinned, on its new card.

    Refused when the model cannot fit the target card at all, and when the
    card's pinned set would over-commit (``force`` overrides the latter — the
    former is never useful).
    """
    from giq.policy import get_policy_store

    store = get_policy_store()
    if get_spec(worker, model) is None:
        raise HTTPException(status_code=404, detail=f"{worker}/{model} is not a registered model")

    previous = store.device_for(worker, model)
    try:
        store.set_device(worker, model, request.device)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    warnings: list[str] = []
    target = store.effective_device(worker, model)
    where = _device_label(target)

    # "Fits the card at all" is checked against the card's total, not its free
    # VRAM: a binding is durable, so what matters is whether it can EVER load
    # there, not whether it could this second.
    fits_card, reason = await asyncio.to_thread(can_load_model, worker, model, target)
    if not fits_card and "can never fit" in reason:
        store.set_device(worker, model, previous)
        raise HTTPException(status_code=409, detail=f"{worker}/{model} on {where}: {reason}")

    if store.policy_for(worker, model) == "pinned":
        other_llm = store.resident_llm(exclude=(worker, model), device=target)
        if worker == "llm" and other_llm is not None:
            store.set_device(worker, model, previous)
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{other_llm[0]}/{other_llm[1]} is already pinned to {where}. One resident "
                    "LLM per card — they would collide on that card's internal port."
                ),
            )
        pinned_fits, projected, total, _dev = store.pinned_fit(extra=(worker, model))
        if not pinned_fits and not request.force:
            store.set_device(worker, model, previous)
            raise HTTPException(
                status_code=409,
                detail=(
                    f"binding {worker}/{model} to {where} would put {projected:.1f}GB of "
                    f"pinned models on a {total:.1f}GB card. Unpin something there, or pass "
                    "force=true."
                ),
            )
        if not pinned_fits:
            warnings.append(
                f"pinned set on {where} needs {projected:.1f}GB of {total:.1f}GB — "
                "it cannot all load"
            )

    from giq.stats import get_stats

    await get_stats().record_event("device", f"{worker}/{model} -> {target or 'default'}")
    return _policy_response(worker, model, warnings)


@router.delete("/control/models/{worker}/{model}", response_model=ModelPolicyResponse)
async def clear_model_policy(worker: str, model: str) -> ModelPolicyResponse:
    """Drop an override, reverting the model to its configured default."""
    from giq.policy import get_policy_store

    if get_spec(worker, model) is None:
        raise HTTPException(status_code=404, detail=f"{worker}/{model} is not a registered model")
    get_policy_store().clear(worker, model)
    return _policy_response(worker, model, [])


@router.get("/status", response_model=ServiceStatus)
async def get_service_status() -> ServiceStatus:
    """Get current service status."""
    queue = get_queue()
    runner = get_runner()
    vram = get_vram_status()
    device = selected_device()
    mine = (await asyncio.to_thread(attribute_vram, runner.owned_pids) if device else {}).get(
        device.uuid if device else "", {}
    )

    all_jobs = await queue.get_all()
    pending = [j for j in all_jobs if j.status == JobStatus.pending]
    running = [j for j in all_jobs if j.status == JobStatus.running]

    pending_ids = [j.job_id for j in pending]
    running_ids = [j.job_id for j in running]

    pause = runner.pause_state

    vram_ok = True
    vram_message = None
    if not pause["paused"] and vram.free_gb < 10:
        vram_ok = False
        vram_message = (
            f"Low VRAM: {vram.free_gb:.1f}GB free — jobs for the resident LLM "
            f"still run; other models wait for eviction (image models need 10GB+)"
        )

    state = ServiceState.idle
    state_message = None

    if pause["paused"]:
        state = ServiceState.paused
        state_message = "Serving paused — models unloaded, GPU free; requests get 503"
        if pause["reason"]:
            state_message += f" ({pause['reason']})"
    elif running:
        state = ServiceState.running
        job = running[0]
        state_message = f"Processing {job.request.worker}/{job.request.model}"
    elif runner.active_worker:
        state = ServiceState.ready
        state_message = f"Worker {runner.active_worker}/{runner.active_model} loaded, waiting"
    elif pending:
        if vram_ok:
            state = ServiceState.ready
            state_message = f"{len(pending)} jobs queued, will process shortly"
        else:
            state = ServiceState.blocked
            state_message = f"{len(pending)} jobs waiting for VRAM ({vram.free_gb:.1f}GB free)"
    else:
        state = ServiceState.idle
        state_message = "No jobs, no worker loaded"

    return ServiceStatus(
        state=state,
        state_message=state_message,
        active_worker=runner.active_worker,
        active_model=runner.active_model,
        active=runner.active_slots,
        gpu=({"uuid": device.uuid, "index": device.index, "name": device.name} if device else None),
        vram_used_gb=vram.used_gb,
        vram_total_gb=vram.total_gb,
        vram_free_gb=vram.free_gb,
        vram_giq_gb=mine.get("giq_gb"),
        vram_other_gb=mine.get("other_gb"),
        vram_ok=vram_ok,
        vram_message=vram_message,
        queue_depth=len(pending_ids),
        jobs_pending=pending_ids,
        jobs_running=running_ids,
        paused=pause["paused"],
        paused_since=pause["since"],
        pause_reason=pause["reason"],
        access=access_posture(),
        version=__version__,
        uptime_s=round(time.monotonic() - _STARTED, 1),
    )


@router.get("/llm/endpoint")
async def get_llm_endpoint(model: str = "gemma-4-12b") -> dict:
    """Discovery endpoint for LLM clients: where is the llama-server?

    200 {model, base_url} when the model is resident and ready. 503 with a
    state hint while it's loading, evicted for other work, paused, or not yet
    loaded — clients retry; the runner's always-on loop restores residency once
    the queue drains, so this endpoint never triggers loads itself.
    """
    runner = get_runner()
    # Per model, not "any ready LLM": with one llama-server per card, the
    # first ready one can easily be a different model on a different port.
    base_url = runner.llm_base_url_for(model)
    if base_url and not runner.is_paused:
        return {"model": model, "base_url": base_url}
    # A switched-off model is not "loading" — say so, or clients keep probing
    # a server that will never come back.
    if runner.is_disabled(WorkerType.llm, model):
        raise HTTPException(
            status_code=503,
            detail={"state": "disabled", "model": model},
            headers={"Retry-After": "300"},
        )
    state = "paused" if runner.is_paused else "evicted" if runner.active_worker else "loading"
    raise HTTPException(
        status_code=503,
        detail={"state": state, "model": model},
        headers={"Retry-After": "60"} if runner.is_paused else None,
    )


@router.get("/engines")
async def list_engines(refresh: bool = False) -> dict:
    """The runtimes giq executes models with, and which build each one is.

    giq could describe every model file it knew about and nothing about the
    binaries running them — so a deleted llama.cpp source tree could go
    unnoticed for months while its binary kept serving. `version`
    is whatever the engine says about itself; a `present: false` entry is a
    declared engine whose binary is missing, which fails loudly at load.
    """
    from giq.engines import probe_all

    return {"engines": await asyncio.to_thread(probe_all, refresh)}


@router.get("/capabilities", response_model=Capabilities)
async def get_capabilities() -> Capabilities:
    """What this service can run, generated from the model registry.

    Hand-maintained before: it had drifted to omit the audio, embed and stt
    modalities entirely, omit flux_klein under both image workers (the two
    models actually in production since the sd.cpp move), and advertise a tts
    model name that was absent from the VRAM table and therefore unloadable.
    Generating it means a model is discoverable exactly when it is runnable.
    """
    workers: dict[WorkerType, WorkerCapability] = {}
    for spec in all_specs():
        worker = WorkerType(spec.worker)
        cap = workers.get(worker)
        if cap is None:
            workers[worker] = WorkerCapability(
                backend=spec.backend,
                models=[spec.model],
                max_batch=spec.max_batch,
                voices=list(spec.voices) or None,
            )
            continue
        cap.models.append(spec.model)
        # One worker type can span runtimes (ocr runs on transformers or its
        # pinned 4.57 venv depending on `engine:`), so report every backend in play.
        if spec.backend not in cap.backend:
            cap.backend = f"{cap.backend}, {spec.backend}"
        if spec.max_batch is not None:
            cap.max_batch = max(cap.max_batch or 0, spec.max_batch)
        if spec.voices:
            cap.voices = sorted({*(cap.voices or []), *spec.voices})

    return Capabilities(
        workers=workers,
        constraints={
            "max_concurrent_heavy": 1,
            "vram_total_gb": round(get_vram_status().total_gb),
        },
    )


# --- OCR ---------------------------------------------------------------------

# One document is one job, and a dozen-page pass runs minutes at ~80 tok/s.
OCR_WAIT_TIMEOUT_SECONDS = 3600.0


def upload_limit() -> int:
    """Largest body accepted by ``/ocr`` and ``/depth``, in bytes. The hard
    ceiling is the parent→child pipe: a task is one JSON line, base64 inflates
    by a third, and the line limit is 128 MiB — so 64 MB is the most a PDF or
    an image can be and still fit. The env name predates ``/depth``."""
    return int(os.environ.get("GIQ_OCR_MAX_UPLOAD_MB", "64")) * 1024 * 1024


class _InMemoryMultipart(MultiPartParser):
    """Starlette's parser spools a file part over 1 MB to a temp file on disk.

    A document service holds the document in memory: the body has already
    been read under ``upload_limit()``, so a spool threshold above it
    means nothing ever rolls over to ``/tmp`` — a plain ext4 volume here,
    where a deleted file is still a forensic artifact."""

    def __init__(self, headers: Headers, body: bytes) -> None:
        async def one_chunk():
            yield body

        super().__init__(headers, one_chunk())
        self.spool_max_size = len(body) + 1


async def _read_body_capped(request: Request, limit: int) -> bytes:
    """The whole body, in memory, or 413 before the cap is exceeded."""
    declared = request.headers.get("content-length", "")
    too_big = HTTPException(
        status_code=413,
        detail=f"document exceeds the {limit // (1024 * 1024)} MB limit "
        "(GIQ_OCR_MAX_UPLOAD_MB on the server)",
    )
    if declared.isdigit() and int(declared) > limit:
        raise too_big
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)


async def _document_from(request: Request, body: bytes) -> bytes:
    """The PDF bytes: the body itself, or the ``file`` part of a multipart body."""
    ctype = request.headers.get("content-type", "")
    if not ctype.startswith("multipart/form-data"):
        return body
    form = await _InMemoryMultipart(request.headers, body).parse()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="multipart body needs a 'file' part")
    data = await upload.read()
    await upload.close()
    return data


def parse_pages(spec: str | None) -> list[int] | None:
    """``"1-3,7"`` → ``[1, 2, 3, 7]``; None or empty means every page."""
    if not spec or not spec.strip():
        return None
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        try:
            a = int(lo)
            b = int(hi) if hi else a
        except ValueError:
            raise HTTPException(status_code=400, detail=f"bad page spec {part!r}") from None
        if a < 1 or b < a:
            raise HTTPException(status_code=400, detail=f"bad page range {part!r}")
        pages.extend(range(a, b + 1))
    return pages


@router.post(
    "/ocr",
    response_model=None,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                },
            },
        }
    },
)
async def ocr_document(
    request: Request,
    model: str = Query(default="unlimited-ocr", description="unlimited-ocr | glm-ocr"),
    dpi: int = Query(default=200, ge=50, le=400),
    pages: str | None = Query(default=None, description="e.g. 1-3,7; default all"),
    raw: bool = Query(default=False, description="add the model's tagged text"),
    strip: bool = Query(default=True, description="drop headers, footers, page numbers"),
    merge: bool = Query(default=True, description="re-join tables/paragraphs across pages"),
    response_format: str = Query(default="json", pattern="^(json|html)$"),
    orch: Orchestrator = Depends(get_orchestrator),
) -> Response | dict:
    """One PDF in, one document out: headers, footers and page numbers
    stripped, tables and paragraphs re-joined across page breaks, as HTML.

    Send the PDF as the request body (``Content-Type: application/pdf``) or
    as the ``file`` part of a multipart form; options are query parameters
    either way. ``model`` picks the engine: ``unlimited-ocr`` (one pass over
    many pages) or ``glm-ocr`` (layout detection, then each region read with
    the prompt for its kind — the stronger choice for tables). The document
    is held in memory only, never spooled to disk, and refused with 413 above
    the server's size limit.

    A convenience over ``POST /run`` with ``worker: "ocr"`` — same job, same
    queue, same stats row — for a consumer that has a file and wants a
    document, not a job id to poll. Page images go through ``/run`` with
    ``images_b64``. ``response_format=html`` returns the fragment itself.
    """
    if get_spec(WorkerType.ocr, model) is None:
        known = sorted(s.model for s in all_specs() if s.worker == "ocr")
        raise HTTPException(status_code=400, detail=f"unknown OCR model {model!r}; one of {known}")
    limit = upload_limit()
    data = await _document_from(request, await _read_body_capped(request, limit))
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="not a PDF")
    task = {
        "id": "ocr-0",
        "pdf_b64": base64.b64encode(data).decode(),
        "dpi": dpi,
        "raw": raw,
        "strip": strip,
        "merge": merge,
    }
    if page_list := parse_pages(pages):
        task["pages"] = page_list
    job_id, _ = await orch.submit_job(JobRequest(worker=WorkerType.ocr, model=model, tasks=[task]))
    logger.info(f"ocr job {job_id}: {model}, {len(data)} bytes, dpi={dpi}")
    try:
        job = await orch.wait_for_job(job_id, timeout=OCR_WAIT_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        # Client gone: do not spend minutes of GPU on a document nobody
        # will collect.
        await orch.cancel_job(job_id)
        raise
    if job.status != JobStatus.completed or not job.results:
        raise HTTPException(status_code=500, detail=job.error or "OCR failed")
    result = job.results[0]
    if result.get("error"):
        raise HTTPException(status_code=500, detail=f"OCR failed: {result['error']}")
    if response_format == "html":
        return HTMLResponse(result.get("html", ""))
    keys = ("html", "pages", "blocks", "tokens_in", "tokens_out", "truncated")
    out: dict = {k: result.get(k) for k in keys}
    out["job_id"] = job_id
    if raw:
        out["raw"] = result.get("raw")
    return out


# --- Depth -------------------------------------------------------------------

# What the body may be. Anything else is refused before it costs a job.
_IMAGE_MAGIC = ((b"\x89PNG", "png"), (b"\xff\xd8", "jpeg"), (b"RIFF", "webp"))


def _is_image(data: bytes) -> bool:
    for magic, kind in _IMAGE_MAGIC:
        if data.startswith(magic):
            return kind != "webp" or data[8:12] == b"WEBP"
    return False


@router.post(
    "/depth",
    response_model=None,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "image/png": {"schema": {"type": "string", "format": "binary"}},
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                "image/webp": {"schema": {"type": "string", "format": "binary"}},
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                },
            },
        }
    },
)
async def depth_map(
    request: Request,
    model: str = Query(default="depth-anything-v2-small", description="depth-anything-v2-small"),
    visualize: bool = Query(default=False, description="add a colour-mapped PNG (near red)"),
    response_format: str = Query(default="json", pattern="^(json|png|visualization)$"),
    orch: Orchestrator = Depends(get_orchestrator),
) -> Response | dict:
    """One image in, one depth map out, at the image's own resolution.

    Send a PNG, JPEG or WebP as the request body or as the ``file`` part of a
    multipart form. The map is a 16-bit PNG whose 0..65535 spans
    ``depth_min``..``depth_max`` of the model's prediction — for Depth
    Anything V2 that is relative inverse depth, larger nearer, no unit (see
    ``DepthResult``). ``response_format=png`` returns that PNG itself;
    ``visualization`` returns the colour-mapped one, near red and far blue.

    A convenience over ``POST /run`` with ``worker: "depth"`` — same job,
    same queue, same stats row — for a consumer that has an image and wants
    a map, not a job id to poll.
    """
    if get_spec(WorkerType.depth, model) is None:
        known = sorted(s.model for s in all_specs() if s.worker == "depth")
        raise HTTPException(
            status_code=400, detail=f"unknown depth model {model!r}; one of {known}"
        )
    data = await _document_from(request, await _read_body_capped(request, upload_limit()))
    if not _is_image(data):
        raise HTTPException(status_code=400, detail="not a PNG, JPEG or WebP image")
    want_vis = visualize or response_format == "visualization"
    task = {"id": "depth-0", "image_b64": base64.b64encode(data).decode(), "visualize": want_vis}
    job_id, _ = await orch.submit_job(
        JobRequest(worker=WorkerType.depth, model=model, tasks=[task])
    )
    logger.info(f"depth job {job_id}: {model}, {len(data)} bytes")
    try:
        job = await orch.wait_for_job(job_id, timeout=SYNC_WAIT_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        await orch.cancel_job(job_id)
        raise
    if job.status != JobStatus.completed or not job.results:
        raise HTTPException(status_code=500, detail=job.error or "depth estimation failed")
    result = job.results[0]
    if result.get("error"):
        raise HTTPException(status_code=500, detail=f"depth estimation failed: {result['error']}")
    if response_format == "png":
        return Response(base64.b64decode(result["depth_b64"]), media_type="image/png")
    if response_format == "visualization":
        return Response(base64.b64decode(result["visualization_b64"]), media_type="image/png")
    keys = ("depth_b64", "width", "height", "depth_min", "depth_max", "metric")
    out: dict = {k: result.get(k) for k in keys}
    if want_vis:
        out["visualization_b64"] = result.get("visualization_b64")
    out["job_id"] = job_id
    return out


# --- Multiview ---------------------------------------------------------------

# A 32-view job at 504 px runs seconds; the queue ahead of it is the wait.
MULTIVIEW_WAIT_TIMEOUT_SECONDS = SYNC_WAIT_TIMEOUT_SECONDS


async def _images_from(request: Request, body: bytes) -> list[bytes]:
    """Every ``files`` part of a multipart body, in order."""
    ctype = request.headers.get("content-type", "")
    if not ctype.startswith("multipart/form-data"):
        raise HTTPException(status_code=400, detail="send the images as multipart 'files' parts")
    form = await _InMemoryMultipart(request.headers, body).parse()
    uploads = [u for u in form.getlist("files") if hasattr(u, "read")]
    if not uploads:
        raise HTTPException(status_code=400, detail="multipart body needs 'files' parts")
    out: list[bytes] = []
    for upload in uploads:
        out.append(await upload.read())
        await upload.close()
    return out


@router.post(
    "/multiview",
    response_model=None,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            }
                        },
                    }
                },
            },
        }
    },
)
async def multiview_scene(
    request: Request,
    model: str = Query(default="da3-base", description="da3-base"),
    process_res: int = Query(default=504, ge=252, le=1008, description="long side, px"),
    use_ray_pose: bool = Query(default=False, description="slower, more accurate poses"),
    glb: bool = Query(default=False, description="add the fused point cloud as GLB"),
    response_format: str = Query(default="json", pattern="^(json|glb)$"),
    orch: Orchestrator = Depends(get_orchestrator),
) -> Response | dict:
    """N images of one scene in; per-view depth, camera poses and intrinsics
    out, in one shared frame.

    Send the images as repeated multipart ``files`` parts, in whatever order
    you like (the model picks its own reference view). Each view comes back
    as a 16-bit depth PNG at the model's working resolution with its 3x4
    world-to-camera matrix and 3x3 intrinsics for that size (see
    ``MultiviewView``). ``glb=true`` adds the model's fused, confidence
    filtered point cloud with camera wireframes; ``response_format=glb``
    returns just that file.

    A convenience over ``POST /run`` with ``worker: "multiview"`` — same job,
    same queue, same stats row — which also takes known poses.
    """
    if get_spec(WorkerType.multiview, model) is None:
        known = sorted(s.model for s in all_specs() if s.worker == "multiview")
        raise HTTPException(
            status_code=400, detail=f"unknown multiview model {model!r}; one of {known}"
        )
    images = await _images_from(request, await _read_body_capped(request, upload_limit()))
    for i, data in enumerate(images):
        if not _is_image(data):
            raise HTTPException(status_code=400, detail=f"file {i} is not a PNG, JPEG or WebP")
    want_glb = glb or response_format == "glb"
    task = {
        "id": "multiview-0",
        "images_b64": [base64.b64encode(d).decode() for d in images],
        "process_res": process_res,
        "use_ray_pose": use_ray_pose,
        "glb": want_glb,
    }
    job_id, _ = await orch.submit_job(
        JobRequest(worker=WorkerType.multiview, model=model, tasks=[task])
    )
    logger.info(f"multiview job {job_id}: {model}, {len(images)} views, res={process_res}")
    try:
        job = await orch.wait_for_job(job_id, timeout=MULTIVIEW_WAIT_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        await orch.cancel_job(job_id)
        raise
    if job.status != JobStatus.completed or not job.results:
        raise HTTPException(status_code=500, detail=job.error or "multiview failed")
    result = job.results[0]
    if result.get("error"):
        raise HTTPException(status_code=500, detail=f"multiview failed: {result['error']}")
    if response_format == "glb":
        return Response(base64.b64decode(result["glb_b64"]), media_type="model/gltf-binary")
    keys = ("views", "metric", "process_res")
    out: dict = {k: result.get(k) for k in keys}
    if want_glb:
        out["glb_b64"] = result.get("glb_b64")
    out["job_id"] = job_id
    return out
