# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Multiview worker: N images of one scene → consistent depth, poses, intrinsics.

Depth Anything 3 (ByteDance-Seed, arXiv 2511.10647) is the any-view model:
one plain transformer over every view's tokens at once predicts a depth map
per view plus each camera's extrinsics and intrinsics, so the views
unproject into one world frame without structure-from-motion. That is what
a scan of an object from many angles needs and what the single-image
``depth`` worker cannot give (its maps have an unknown scale and shift per
frame).

The child (``_multiview_child``) runs on its own interpreter, declared as
engine ``da3`` in ``engines.py``: the package is not on PyPI, pins numpy
below 2, and drags a research toolkit (open3d, pycolmap, evo, e3nn, moviepy)
that has no place in giq's venv. ``envs/da3`` is that interpreter, synced by
``make sync``. The child gets this checkout's ``src`` on ``PYTHONPATH`` so
``giq`` imports there, as the unlimited-ocr child does.

Sleepy: loads on demand, evictable. VRAM grows with the number of views
(every view's tokens attend to every other's), so the child caps views and
the registry figure is for that cap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from giq.models import MultiviewResult
from giq.registry import vram_for
from giq.weights import require_path
from giq.workers._subprocess import SubprocessWorker

# Which declared engine runs the child.
ENGINE = "da3"
# `giq` must be importable in the other interpreter: its venv does not
# install giq, so the child gets this checkout's src on PYTHONPATH.
_GIQ_SRC = str(Path(__file__).resolve().parents[2])

# Upper bound for an unregistered model; the registry has the measured ones.
MULTIVIEW_VRAM_GB = 8.0


@dataclass
class MultiviewWorkerConfig:
    model: str = "da3-base"


class MultiviewWorker(SubprocessWorker):
    """Depth Anything 3 in a child process on the ``da3`` interpreter."""

    child_module: ClassVar[str] = "giq.workers._multiview_child"
    modality: ClassVar[str] = "multiview"

    def __init__(self, config: MultiviewWorkerConfig, device: str | None = None):
        super().__init__(config, device)
        # The recipe's weights.path, under GIQ_MULTIVIEW_MODELS_DIR when
        # that is set. Unknown model or no weights: fail here, not at spawn.
        self.weights = require_path(config.model)

    def child_args(self) -> list[str]:
        return ["--model", self.config.model, "--weights", self.weights]

    @property
    def estimated_vram_gb(self) -> float:
        return vram_for(self.config.model, default=MULTIVIEW_VRAM_GB)

    def _interpreter(self) -> str:
        from giq.engines import require_binary

        return require_binary(ENGINE)

    def _command(self) -> list[str]:
        return [self._interpreter(), "-u", "-m", self.child_module, *self.child_args()]

    def _spawn_env(self) -> dict[str, str]:
        env = super()._spawn_env()
        extra = env.get("PYTHONPATH")
        env["PYTHONPATH"] = _GIQ_SRC + (os.pathsep + extra if extra else "")
        return env

    async def run_batch(
        self, tasks: list[dict[str, Any]], params: dict[str, Any] | None = None
    ) -> list[MultiviewResult]:
        raw_results = await super().run_batch(tasks, params)
        return [hydrate(r) for r in raw_results]


def hydrate(result: dict[str, Any]) -> MultiviewResult:
    """Child result dict → MultiviewResult; an error envelope stays an error."""
    rid = str(result.get("id", "unknown"))
    if result.get("error"):
        return MultiviewResult(id=rid, error=str(result["error"]))
    return MultiviewResult.model_validate({**result, "id": rid})
