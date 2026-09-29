# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Per-model residency policy: pinned / auto / off.

The invariant worth protecting: `off` means no load path at all — not merely
"no new submissions" — and unpinning actually unloads instead of being undone
by the residents loop on its next tick.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from giq.models import JobRequest, JobStatus, WorkerType
from giq.policy import AUTO, OFF, PINNED, reset_policy_store
from giq.queue import Job, JobQueue
from giq.runner import ResidentDemoted, Runner, _Resident

RESIDENTS = [
    (WorkerType.llm, "gemma-4-12b"),
    (WorkerType.audio, "whisper-large-v3"),
    (WorkerType.embed, "ecapa-tdnn"),
]


@pytest.fixture
def store():
    """A policy store with a clean DB-backed override table."""
    from giq.stats import get_stats

    stats = get_stats()
    for worker, model in list(stats.load_policies()):
        stats.delete_policy(worker, model)
    store = reset_policy_store()
    store.load()
    yield store
    for worker, model in list(stats.load_policies()):
        stats.delete_policy(worker, model)
    reset_policy_store()


@pytest.fixture
def sixteen_gb_card(monkeypatch):
    """The card size forced rather than read from the host, so "overcommits"
    means the same thing on every machine."""
    from giq.vram import VRAMStatus

    monkeypatch.setattr(
        "giq.vram.get_vram_status",
        lambda *args, **kwargs: VRAMStatus(used_gb=0.0, total_gb=16.0, free_gb=16.0),
    )


@pytest.fixture
def queue():
    return JobQueue()


def _prime_resident(runner: Runner, key, width: int = 1):
    worker = AsyncMock()
    worker.is_ready = True
    worker.estimated_vram_gb = 4.0
    # On the card this model actually binds to — a resident sitting on the
    # wrong card is torn down and reloaded, which is not what these tests are
    # about (see test_binding for that path).
    res = _Resident(worker, width, runner._device_for(*key))
    runner._residents[key] = res
    return res


# --- defaults ---------------------------------------------------------------


def test_registry_residents_default_to_pinned(store):
    assert store.policy_for("llm", "gemma-4-12b") == PINNED
    assert store.policy_for("audio", "whisper-large-v3") == PINNED


def test_everything_else_defaults_to_auto(store):
    assert store.policy_for("text2image", "flux_klein") == AUTO
    assert store.policy_for("tts", "kokoro") == AUTO


def test_unregistered_model_is_auto_not_off(store):
    """An unknown model must not be silently blocked."""
    assert store.policy_for("llm", "no-such-model") == AUTO


# --- persistence ------------------------------------------------------------


def test_override_round_trips_through_the_db(store):
    store.set("text2image", "flux_klein", PINNED, reason="demo")
    reloaded = reset_policy_store()
    reloaded.load()
    record = reloaded.record_for("text2image", "flux_klein")
    assert record.policy == PINNED
    assert record.source == "override"
    assert record.reason == "demo"


def test_setting_a_model_back_to_its_default_clears_the_override(store):
    """Storing "same as default" would freeze a later default change in place."""
    store.set("llm", "gemma-4-12b", AUTO)
    assert store.record_for("llm", "gemma-4-12b").source == "override"
    store.set("llm", "gemma-4-12b", PINNED)
    assert store.record_for("llm", "gemma-4-12b").source == "default"

    from giq.stats import get_stats

    assert ("llm", "gemma-4-12b") not in get_stats().load_policies()


def test_clear_reverts_to_default(store):
    store.set("llm", "gemma-4-12b", OFF)
    store.clear("llm", "gemma-4-12b")
    assert store.policy_for("llm", "gemma-4-12b") == PINNED


def test_unknown_model_cannot_be_set(store):
    with pytest.raises(ValueError, match="not a registered model"):
        store.set("llm", "no-such-model", PINNED)


def test_invalid_policy_is_rejected(store):
    with pytest.raises(ValueError, match="unknown policy"):
        store.set("llm", "gemma-4-12b", "sometimes")


def test_stale_override_for_a_delisted_model_is_dropped_on_load(store):
    """A model removed from the registry must not resurrect as a resident."""
    from giq.stats import get_stats

    get_stats().save_policy("llm", "model-that-was-deleted", PINNED, None)
    fresh = reset_policy_store()
    fresh.load()
    assert ("llm", "model-that-was-deleted") not in fresh.residents()


# --- the resident set -------------------------------------------------------


def test_pinning_adds_to_the_resident_set(store):
    assert ("tts", "kokoro") not in store.residents()
    store.set("tts", "kokoro", PINNED)
    assert ("tts", "kokoro") in store.residents()


def test_unpinning_removes_from_the_resident_set(store):
    store.set("audio", "whisper-large-v3", AUTO)
    assert ("audio", "whisper-large-v3") not in store.residents()


def test_registry_residents_keep_their_priority_order(store):
    """Declared order encodes which model matters most when VRAM is tight."""
    store.set("tts", "kokoro", PINNED)
    residents = store.residents()
    assert residents[:3] == [
        ("llm", "gemma-4-12b"),
        ("audio", "whisper-large-v3"),
        ("embed", "ecapa-tdnn"),
    ]
    assert residents[3] == ("tts", "kokoro")  # operator pins follow


def test_off_is_not_resident(store):
    store.set("llm", "gemma-4-12b", OFF)
    assert ("llm", "gemma-4-12b") not in store.residents()
    assert store.is_off("llm", "gemma-4-12b")


# --- the VRAM budget --------------------------------------------------------


def test_default_pinned_set_fits(store):
    fits, projected, total, _device = store.pinned_fit()
    assert fits, f"the shipped resident set must fit: {projected} of {total}"


def test_pinning_a_huge_model_overcommits(store, sixteen_gb_card):
    fits, projected, total, _device = store.pinned_fit(extra=("text2image", "zimage"))
    assert not fits
    assert projected > total


def test_only_one_llm_can_be_pinned_per_card(store):
    """Two llama-servers on one card would fight over its internal port."""
    assert store.resident_llm() == ("llm", "gemma-4-12b")
    assert store.resident_llm(exclude=("llm", "gemma-4-12b")) is None
    # Scoped to the card gemma actually lands on...
    where = store.effective_device("llm", "gemma-4-12b")
    assert store.resident_llm(device=where) == ("llm", "gemma-4-12b")
    # ...and silent about any other card, which is what lets a second LLM be
    # pinned elsewhere.
    assert store.resident_llm(device="GPU-nothing-here") is None


# --- enforcement: submission ------------------------------------------------


@pytest.mark.asyncio
async def test_submit_is_refused_for_a_disabled_model(store, monkeypatch):
    from giq.services.orchestration import Orchestrator

    store.set("llm", "gemma-4-12b", OFF, reason="freeing the card")
    orch = Orchestrator()
    request = JobRequest(worker=WorkerType.llm, model="gemma-4-12b", tasks=[{"id": "t1"}])
    with pytest.raises(HTTPException) as excinfo:
        await orch.submit_job(request)
    assert excinfo.value.status_code == 503
    assert "switched off" in excinfo.value.detail
    assert "freeing the card" in excinfo.value.detail
    assert excinfo.value.headers["X-Giq-Model-Policy"] == "off"


@pytest.mark.asyncio
async def test_submit_is_allowed_once_re_enabled(store):
    from giq.services.orchestration import Orchestrator

    store.set("text2image", "flux_klein", OFF)
    store.set("text2image", "flux_klein", AUTO)
    orch = Orchestrator()
    job_id, _pos = await orch.submit_job(
        JobRequest(worker=WorkerType.text2image, model="flux_klein", tasks=[{"id": "t1"}])
    )
    assert job_id
    await orch.queue.remove(job_id)


# --- enforcement: the load paths -------------------------------------------


@pytest.mark.asyncio
async def test_disabled_model_cannot_load_via_the_batch_path(store, queue):
    """Submission is the usual gate, but `off` must block loading outright."""
    runner = Runner(queue, use_policy=True)
    store.set("text2image", "flux_klein", OFF)
    with pytest.raises(RuntimeError, match="disabled"):
        await runner._ensure_worker(WorkerType.text2image, "flux_klein")


@pytest.mark.asyncio
async def test_disabled_resident_is_not_reloaded(store, queue):
    runner = Runner(queue, use_policy=True)
    store.set("llm", "gemma-4-12b", OFF)
    await runner._load_resident((WorkerType.llm, "gemma-4-12b"))
    assert (WorkerType.llm, "gemma-4-12b") not in runner._residents


@pytest.mark.asyncio
async def test_runner_resident_set_follows_policy_live(store, queue):
    runner = Runner(queue, use_policy=True)
    assert (WorkerType.audio, "whisper-large-v3") in runner._resident_keys
    store.set("audio", "whisper-large-v3", AUTO)
    assert (WorkerType.audio, "whisper-large-v3") not in runner._resident_keys


@pytest.mark.asyncio
async def test_static_residents_ignore_pinning_but_not_off(store, queue):
    """use_policy governs the resident set only.

    `off` is a hard statement that a model must not load; it would be a trap
    for that to depend on how the runner was constructed. Caught in live
    verification: /llm/endpoint reported "loading" for a switched-off model
    because that runner had use_policy=False.
    """
    runner = Runner(queue, residents=RESIDENTS)
    store.set("audio", "whisper-large-v3", OFF)
    # the static list still drives residency...
    assert (WorkerType.audio, "whisper-large-v3") in runner._resident_keys
    # ...but off is honoured everywhere
    assert runner.is_disabled(WorkerType.audio, "whisper-large-v3")
    with pytest.raises(RuntimeError, match="disabled"):
        await runner._ensure_worker(WorkerType.audio, "whisper-large-v3")


# --- unpinning actually unloads ---------------------------------------------


@pytest.mark.asyncio
async def test_unpinning_unloads_the_resident(store, queue):
    """The point of the whole design: the loop must not reload it right back."""
    runner = Runner(queue, use_policy=True)
    key = (WorkerType.audio, "whisper-large-v3")
    res = _prime_resident(runner, key)

    store.set("audio", "whisper-large-v3", AUTO)
    await runner._release_demoted_residents()

    res.worker.stop.assert_awaited()
    assert key not in runner._residents


@pytest.mark.asyncio
async def test_pinned_residents_are_left_alone(store, queue):
    runner = Runner(queue, use_policy=True)
    key = (WorkerType.audio, "whisper-large-v3")
    res = _prime_resident(runner, key)

    await runner._release_demoted_residents()

    res.worker.stop.assert_not_awaited()
    assert key in runner._residents


@pytest.mark.asyncio
async def test_unload_waits_for_in_flight_lane_jobs(store, queue):
    """Teardown drains the lane, so nothing dies mid-generation."""
    runner = Runner(queue, use_policy=True)
    key = (WorkerType.audio, "whisper-large-v3")
    res = _prime_resident(runner, key)
    await res.lane.acquire()  # simulate a job in flight
    res.active_count = 1

    store.set("audio", "whisper-large-v3", AUTO)
    task = asyncio.create_task(runner._release_demoted_residents())
    await asyncio.sleep(0.05)
    assert key in runner._residents  # still waiting on the lane
    res.worker.stop.assert_not_awaited()

    res.active_count = 0
    res.lane.release()
    await asyncio.wait_for(task, timeout=2)
    assert key not in runner._residents


# --- a lane job whose model is unpinned mid-flight --------------------------


@pytest.mark.asyncio
async def test_lane_job_fails_fast_when_unpinned(store, queue):
    """Without this it would wait out RESIDENT_WAIT_TIMEOUT_SECONDS (840s)."""
    runner = Runner(queue, use_policy=True)
    store.set("audio", "whisper-large-v3", AUTO)
    with pytest.raises(ResidentDemoted):
        await runner._wait_resident_ready((WorkerType.audio, "whisper-large-v3"))


@pytest.mark.asyncio
async def test_demoted_lane_job_is_requeued_not_failed(store, queue):
    runner = Runner(queue, use_policy=True)
    key = (WorkerType.audio, "whisper-large-v3")
    job = Job(
        job_id="j1",
        request=JobRequest(worker=WorkerType.audio, model="whisper-large-v3", tasks=[{"id": "t"}]),
    )
    job.status = JobStatus.running
    await queue.add(job)
    store.set("audio", "whisper-large-v3", AUTO)

    await runner._process_resident_job(job, key)

    assert job.status == JobStatus.pending  # picked up again by the batch path
    assert job.error is None
    assert job.completed_at is None


# --- the control endpoints --------------------------------------------------


@pytest.fixture
async def client(store, queue):
    from httpx import ASGITransport, AsyncClient

    import giq.queue
    import giq.runner
    from giq.main import app

    giq.queue._queue = queue
    giq.runner._runner = Runner(queue, use_policy=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as ac:
        yield ac


@pytest.mark.asyncio
async def test_policy_round_trip_over_http(client, store):
    # kokoro is 0.5GB, so it fits alongside the default resident set; pinning
    # a 9GB image model on top of it would (correctly) be refused as overcommit.
    r = await client.post(
        "/control/models/tts/kokoro", json={"policy": "pinned", "reason": "demo day"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"]["policy"] == "pinned"
    assert body["state"]["source"] == "override"
    assert body["state"]["reason"] == "demo day"
    assert "tts/kokoro" in body["pinned"]
    assert body["pinned_vram_gb"] <= body["vram_total_gb"]

    r = await client.delete("/control/models/tts/kokoro")
    assert r.status_code == 200
    assert r.json()["state"]["policy"] == "auto"
    assert r.json()["state"]["source"] == "default"
    assert "tts/kokoro" not in r.json()["pinned"]


@pytest.mark.asyncio
async def test_pinning_an_image_model_overcommits_a_small_card(client, store, monkeypatch):
    """A pinned set that cannot coexist is refused, not retried forever.

    The card size is forced rather than read from the host. This test used to
    assert "on this machine", and stopped meaning anything the day a second,
    bigger card went in — the same ambiguity that made every VRAM figure in
    the service need a device attached to it.
    """
    from giq.vram import VRAMStatus

    monkeypatch.setattr(
        "giq.vram.get_vram_status",
        lambda *args, **kwargs: VRAMStatus(used_gb=0.0, total_gb=16.0, free_gb=16.0),
    )
    r = await client.post("/control/models/text2image/flux_klein", json={"policy": "pinned"})
    assert r.status_code == 409
    # gemma 9.5 + whisper 4.0 + ecapa 0.6 + klein 8.0 + 0.5 headroom = 22.6
    assert "22.6GB of 16.0GB" in r.json()["detail"]


@pytest.mark.asyncio
async def test_listing_policies_covers_every_model(client):
    r = await client.get("/control/models")
    assert r.status_code == 200
    from giq.registry import all_specs

    assert len(r.json()) == len(all_specs())


@pytest.mark.asyncio
async def test_unknown_model_is_404(client):
    r = await client.post("/control/models/llm/nope", json={"policy": "pinned"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_policy_is_400(client):
    r = await client.post("/control/models/tts/kokoro", json={"policy": "sometimes"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_overcommitting_the_card_is_refused(client, store, sixteen_gb_card):
    """The footgun guard: an unsatisfiable pinned set thrashes reloads forever."""
    r = await client.post("/control/models/text2image/zimage", json={"policy": "pinned"})
    assert r.status_code == 409
    assert "force=true" in r.json()["detail"]
    assert store.policy_for("text2image", "zimage") == AUTO  # nothing was written


@pytest.mark.asyncio
async def test_overcommit_can_be_forced_but_warns(client, store, sixteen_gb_card):
    r = await client.post(
        "/control/models/text2image/zimage", json={"policy": "pinned", "force": True}
    )
    assert r.status_code == 200
    assert any("cannot all load" in w for w in r.json()["warnings"])
    assert store.policy_for("text2image", "zimage") == PINNED


@pytest.mark.asyncio
async def test_pinning_a_second_llm_is_refused(client, store):
    r = await client.post("/control/models/llm/llama-3.2-3b", json={"policy": "pinned"})
    assert r.status_code == 409
    assert "One resident LLM per card" in r.json()["detail"]
    assert store.policy_for("llm", "llama-3.2-3b") == AUTO


@pytest.mark.asyncio
async def test_swapping_the_pinned_llm_works(client, store):
    """Unpin then pin: the natural way to change which LLM is resident."""
    assert (
        await client.post("/control/models/llm/gemma-4-12b", json={"policy": "auto"})
    ).status_code == 200
    r = await client.post("/control/models/llm/llama-3.2-3b", json={"policy": "pinned"})
    assert r.status_code == 200
    assert store.resident_llm() == ("llm", "llama-3.2-3b")


@pytest.mark.asyncio
async def test_catalog_reports_policy(client, store):
    store.set("tts", "kokoro", OFF, reason="noisy")
    r = await client.get("/stats/models")
    assert r.status_code == 200
    body = r.json()
    entry = next(m for m in body["models"] if m["worker"] == "tts" and m["model"] == "kokoro")
    assert entry["policy"] == "off"
    assert entry["policy_reason"] == "noisy"
    assert body["pinned_fits"] is True


@pytest.mark.asyncio
async def test_llm_endpoint_reports_disabled(client, store):
    store.set("llm", "gemma-4-12b", OFF)
    r = await client.get("/llm/endpoint")
    assert r.status_code == 503
    assert r.json()["detail"]["state"] == "disabled"


# --- the loop has to be there before the first pin ---------------------------


@pytest.mark.asyncio
async def test_residents_loop_runs_when_nothing_is_pinned_at_boot(store, queue, monkeypatch):
    """A pin is useless if the loop that acts on it was never started.

    The loop used to be started only for a non-empty resident set. On a host
    where every registry resident had been set to on-demand, giq booted
    without it: pinning a model afterwards showed it in the resident lanes
    and sent its jobs down the resident lane, where they waited out a load
    nothing would ever do.
    """
    import giq.runner

    for worker, model in RESIDENTS:
        store.set(str(worker), model, AUTO)
    runner = Runner(queue, use_policy=True)
    assert runner._resident_keys == []

    loaded: list[tuple[WorkerType, str]] = []
    monkeypatch.setattr(giq.runner, "RESIDENT_TICK_SECONDS", 0.01)
    monkeypatch.setattr(giq.runner, "RESIDENT_RELOAD_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(runner, "_load_resident", AsyncMock(side_effect=loaded.append))

    await runner.start()
    try:
        assert runner._resident_task is not None
        store.set("audio", "whisper-large-v3", PINNED)
        for _ in range(100):
            await asyncio.sleep(0.02)
            if loaded:
                break
        assert (WorkerType.audio, "whisper-large-v3") in loaded
    finally:
        await runner.stop()
