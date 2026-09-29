# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import logging
from contextlib import asynccontextmanager

from giq.api.dependencies import get_audio_cache
from giq.runner import get_runner
from giq.workers.llm import INTERNAL_LLM_PORT

logger = logging.getLogger(__name__)

# Reaps expired entries from the AudioCache singleton. ESP32 streaming puts
# rendered audio in this cache with a per-file TTL; without a sweeper the dict
# would grow forever since get() only evicts on access.
AUDIO_CACHE_CLEANUP_INTERVAL = 60


async def _audio_cache_cleanup_loop():
    cache = get_audio_cache()
    while True:
        try:
            await asyncio.sleep(AUDIO_CACHE_CLEANUP_INTERVAL)
            await cache.cleanup()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"audio cache cleanup tick failed: {e}")


async def _vram_sampler_loop(runner):
    """Periodic VRAM + per-GPU telemetry samples for the dashboard timelines."""
    from giq.gpus import get_gpus
    from giq.stats import VRAM_SAMPLE_INTERVAL_SECONDS, get_stats
    from giq.vram import get_vram_status

    stats = get_stats()
    while True:
        try:
            await asyncio.sleep(VRAM_SAMPLE_INTERVAL_SECONDS)
            vram = await asyncio.to_thread(get_vram_status)
            ready = sum(1 for ok in runner.resident_models.values() if ok)
            active = runner.active_worker.value if runner.active_worker else None
            await stats.sample_vram(vram.used_gb, vram.free_gb, active, ready)
            gpus = await asyncio.to_thread(get_gpus)
            await stats.note_gpus(gpus)  # catches a card swapped in mid-run
            await stats.sample_gpus(gpus)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"vram sampler tick failed: {e}")


async def _kill_stale_servers(port: int = INTERNAL_LLM_PORT):
    """Kill any llama-server processes lingering from a prior run.

    fuser only catches processes already bound to the port; pkill also catches
    processes still mid-model-load that haven't called bind() yet (but are
    already holding VRAM).

    Every pattern is qualified by one of giq's own internal ports, so the sweep
    can only reach servers giq is responsible for. There used to be a bare
    ``^llama-server `` pattern as well, for bare-invoked servers — but giq
    passes --port to every server it starts, so the port-qualified patterns
    already cover all of them, and the bare one only added reach over other
    people's processes: a hand-started llama-server, or another tool's, killed
    for the crime of sharing a program name.

    One port per card since bindings landed: a run that ended with servers on
    both cards leaves two of each, and sweeping only the first card's port
    would leave the second holding VRAM with nothing tracking it.
    """
    from giq.gpus import device_port, get_gpus
    from giq.workers.sdcpp import INTERNAL_SD_PORT
    from giq.workers.vllm import INTERNAL_VLLM_PORT, scope_unit, stop_scope

    ports = {port} | {device_port(INTERNAL_LLM_PORT, gpu) for gpu in get_gpus()}
    sd_ports = {INTERNAL_SD_PORT} | {device_port(INTERNAL_SD_PORT, gpu) for gpu in get_gpus()}
    vllm_ports = {INTERNAL_VLLM_PORT} | {device_port(INTERNAL_VLLM_PORT, gpu) for gpu in get_gpus()}
    # A vllm server runs in a transient systemd scope, which outlives a giq
    # that died without stopping it; the scope takes its engine core down
    # with it, which a pattern on the API server's command line would miss.
    for p in sorted(vllm_ports):
        await asyncio.to_thread(stop_scope, scope_unit(p))
    patterns = [rf"llama-server .*--port {p}" for p in sorted(ports)]
    patterns += [rf"sd-server .*--listen-port {p}" for p in sorted(sd_ports)]
    patterns += [rf"vllm serve .*--port {p}" for p in sorted(vllm_ports)]
    # SIGTERM everything matching llama-server
    for pattern in patterns:
        proc = await asyncio.create_subprocess_exec(
            "pkill",
            "-TERM",
            "-f",
            pattern,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    # Grace period for clean shutdown before SIGKILL
    await asyncio.sleep(2.0)

    for pattern in patterns:
        proc = await asyncio.create_subprocess_exec(
            "pkill",
            "-KILL",
            "-f",
            pattern,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    # Belt-and-braces: free the ports too (catches anything else holding them)
    for p in sorted(ports):
        proc = await asyncio.create_subprocess_exec(
            "fuser",
            "-k",
            f"{p}/tcp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()


@asynccontextmanager
async def lifespan(app):
    """Manage runner lifecycle."""
    # Before any worker imports huggingface_hub, which reads HF_HOME once at
    # import: in-process workers, children and the storage catalog must all
    # agree on one cache (see paths.cache_env).
    from giq.paths import apply_cache_env

    if exported := apply_cache_env():
        logger.info("cache locations: %s", ", ".join(f"{k}={v}" for k, v in exported.items()))
    await _kill_stale_servers()
    from giq.stats import get_stats

    stats = get_stats()
    # Record the installed cards before init(): the era backfill attributes
    # post-swap jobs to the current card, which it can only do once that card
    # is in gpu_eras. This also arms the per-job GPU stamp before the first job,
    # rather than waiting a full sampler interval.
    from giq.gpus import get_gpus

    await stats.note_gpus(await asyncio.to_thread(get_gpus))
    await stats.init()  # creates schema; backfills from inflight log on first run
    await stats.record_event("start")
    # Policy overrides must load before the runner starts, or the residents
    # loop would spend its first ticks loading models the operator unpinned.
    from giq.policy import get_policy_store

    await asyncio.to_thread(get_policy_store().load)
    runner = get_runner(use_policy=True)
    await runner.start()
    cleanup_task = asyncio.create_task(_audio_cache_cleanup_loop())
    sampler_task = asyncio.create_task(_vram_sampler_loop(runner))
    logger.info("giq started")
    try:
        yield
    finally:
        for task in (cleanup_task, sampler_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await runner.stop()
        await stats.record_event("stop")
        await asyncio.to_thread(stats.close)
        logger.info("giq stopped")
