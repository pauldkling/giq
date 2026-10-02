# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Instances: a recipe running on a card is a thing of its own (ADR-003)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from giq.queue import JobQueue
from giq.runner import ON_DEMAND, RESIDENT, Instance, Runner


def _adapter(*, ready=True, running=True, port=None, pid=None, vram=4.0):
    adapter = AsyncMock()
    adapter.is_ready = ready
    adapter.is_running = running
    adapter.pid = pid
    adapter.estimated_vram_gb = vram
    adapter.config = SimpleNamespace(port=port)
    return adapter


def test_an_instance_is_named_recipe_at_card_and_reports_its_state():
    inst = Instance(_adapter(port=8088), "gemma-4-12b", "GPU-a", residency=RESIDENT, width=4)
    assert inst.id == "gemma-4-12b@GPU-a"
    assert (inst.state, inst.port, inst.width) == ("ready", 8088, 4)
    assert Instance(_adapter(ready=False), "x").state == "starting"
    assert Instance(_adapter(ready=False, running=False), "x").state == "stopped"
    assert Instance(_adapter(), "x").id == "x@default"


def test_the_runner_lists_residents_and_on_demand_instances_together():
    runner = Runner(JobQueue())
    runner._residents["gemma-4-12b"] = Instance(
        _adapter(), "gemma-4-12b", "GPU-a", residency=RESIDENT, width=4
    )
    runner._slots["GPU-b"] = Instance(_adapter(), "zimage", "GPU-b", residency=ON_DEMAND)
    assert [(i.id, i.residency) for i in runner.instances()] == [
        ("gemma-4-12b@GPU-a", "resident"),
        ("zimage@GPU-b", "on_demand"),
    ]


@pytest.mark.asyncio
async def test_get_instances(monkeypatch):
    from giq.api import router as api
    from giq.main import app

    runner = Runner(JobQueue())
    runner._residents["gemma-4-12b"] = Instance(
        _adapter(port=8086, pid=111, vram=7.0),
        "gemma-4-12b",
        "GPU-a",
        residency=RESIDENT,
        width=4,
    )
    runner._slots["GPU-a"] = Instance(
        _adapter(pid=222, vram=1.5), "depth-anything-v2-small", "GPU-a"
    )
    monkeypatch.setattr(api, "get_runner", lambda: runner)
    monkeypatch.setattr(api, "resolve_device", lambda uuid: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        body = (await c.get("/instances")).json()

    by_recipe = {i["recipe"]: i for i in body["instances"]}
    gemma, depth = by_recipe["gemma-4-12b"], by_recipe["depth-anything-v2-small"]
    assert gemma["recipe"] == "gemma-4-12b" and gemma["modalities"] == ["llm"]
    assert (gemma["residency"], gemma["state"], gemma["port"], gemma["lanes"]) == (
        "resident",
        "ready",
        8086,
        4,
    )
    assert gemma["engine"] == "llama.cpp" and gemma["vram_gb"] == 7.0 and gemma["pid"] == 111
    assert depth["residency"] == "on_demand" and depth["port"] is None
