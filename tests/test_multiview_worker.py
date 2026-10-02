# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""MultiviewAdapter: child results become MultiviewResults in the parent.

The child is replaced by an inline script that answers every task with two
canned views, so this exercises hydration, the error envelope and the
interpreter selection without a GPU, a model or the da3 env.
"""

import json
import os
import sys

import pytest

from giq.adapters.multiview import MultiviewAdapter, MultiviewConfig, hydrate
from giq.models import MultiviewResult

VIEW = {
    "index": 0,
    "width": 504,
    "height": 378,
    "depth_b64": "iVBORw0=",
    "depth_min": 0.5,
    "depth_max": 9.0,
    "conf_b64": "iVBORw0=",
    "conf_min": 1.0,
    "conf_max": 3.0,
    "extrinsics": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
    "intrinsics": [[400, 0, 252], [0, 400, 189], [0, 0, 1]],
}

CHILD_SCRIPT = f"""
import sys, json
VIEW = {VIEW!r}
sys.stdout.write(json.dumps({{"type": "ready"}}) + "\\n"); sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("type") == "shutdown":
        break
    results = []
    for t in msg["tasks"]:
        if not t.get("images_b64"):
            results.append({{"id": t["id"], "error": "task needs images_b64"}})
            continue
        r = {{"id": t["id"], "views": [VIEW, {{**VIEW, "index": 1}}], "metric": False,
             "process_res": t.get("process_res") or 504}}
        if t.get("glb"):
            r["glb_b64"] = "Z2xURg=="
        results.append(r)
    sys.stdout.write(json.dumps({{"type": "results", "results": results}}) + "\\n")
    sys.stdout.flush()
"""


class _StubMultiviewWorker(MultiviewAdapter):
    def _command(self) -> list[str]:
        return [sys.executable, "-u", "-c", CHILD_SCRIPT]

    def _spawn_env(self) -> dict[str, str]:
        return dict(os.environ)


@pytest.mark.asyncio
async def test_run_batch_returns_multiview_results():
    worker = _StubMultiviewWorker(MultiviewConfig())
    await worker.start()
    try:
        results = await worker.run_batch(
            [
                {"id": "a", "images_b64": ["x", "y"]},
                {"id": "b", "images_b64": ["x", "y"], "glb": True, "process_res": 756},
                {"id": "bad"},
            ]
        )
    finally:
        await worker.stop()

    assert all(isinstance(r, MultiviewResult) for r in results)
    a, b, bad = results
    assert [v.index for v in a.views] == [0, 1] and a.views[0].width == 504
    assert a.views[0].extrinsics[0] == [1, 0, 0, 0] and a.views[0].intrinsics[2] == [0, 0, 1]
    assert a.views[0].conf_min == 1.0 and a.metric is False and a.glb_b64 is None
    assert b.glb_b64 == "Z2xURg==" and b.process_res == 756
    assert bad.error == "task needs images_b64" and bad.views == []
    dumped = json.loads(json.dumps([r.model_dump() for r in results]))
    assert dumped[0]["views"][1]["index"] == 1


def test_hydrate_keeps_the_error_envelope():
    assert hydrate({"id": "t", "error": "boom"}).error == "boom"
    assert hydrate({"error": "boom"}).id == "unknown"


def test_estimated_vram_comes_from_the_registry():
    from giq.registry import get_recipe

    recipe = get_recipe(MultiviewConfig().model)
    assert recipe is not None and recipe.name == "da3-base"
    assert MultiviewAdapter(MultiviewConfig()).estimated_vram_gb == recipe.vram_gb


def test_unknown_model_fails_at_construction():
    with pytest.raises(ValueError):
        MultiviewAdapter(MultiviewConfig(model="vggt"))


def test_the_child_runs_on_the_da3_interpreter(monkeypatch):
    """Depth Anything 3 lives in envs/da3; the child is spawned with that
    python and can import giq from this checkout's src."""
    from giq.engines import binary_for

    monkeypatch.setattr("giq.engines.require_binary", lambda name: binary_for(name))
    w = MultiviewAdapter(MultiviewConfig(model="da3-base"))
    cmd = w._command()
    assert cmd[0] == binary_for("da3") and cmd[0] != sys.executable
    assert cmd[1:6] == ["-u", "-m", "giq.adapters._multiview_child", "--model", "da3-base"]
    assert cmd[6] == "--weights" and cmd[7].endswith("/depth-anything-DA3-BASE")
    env = w._spawn_env()
    assert env["PYTHONPATH"].split(os.pathsep)[0].endswith("/src")


def test_snapshot_root_is_overridable(monkeypatch):
    monkeypatch.setenv("GIQ_MULTIVIEW_MODELS_DIR", "/elsewhere")
    w = MultiviewAdapter(MultiviewConfig(model="da3-base"))
    assert w.weights == "/elsewhere/depth-anything-DA3-BASE"
