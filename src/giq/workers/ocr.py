# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""OCR worker: PDF or page images → layout-tagged text → HTML.

The child — ``_ocr_child`` for baidu/Unlimited-OCR, ``_glm_ocr_child`` for
GLM-OCR — returns the model's raw tagged text, loading the weights the
instance file names (``giq.weights``), which the parent passes on its
command line. Everything that turns that into a document — dropping
headers, footers and page numbers, re-joining a table or paragraph the page
break cut in two, and rendering HTML — happens here in the parent through
``giq.ocrdoc``, on plain strings, so it is testable without a GPU and without
a real document.

Sleepy model: loads on demand, evictable. A pass over a dozen pages runs a
few minutes at ~80 tok/s, so the batch timeout is generous.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from giq import ocrdoc
from giq.models import OCRResult
from giq.registry import vram_for
from giq.weights import instance_of, require_path
from giq.workers._subprocess import SubprocessWorker

# 8266 MiB per-process peak measured on an RTX 5090 (4-page pass at 1024px);
# 6.3 GiB idle after load. Declared above the peak, as a gate figure
# should be.
OCR_VRAM_GB = 9.0

# Which child runs an OCR instance, by its engine. giq has two OCR pipelines
# and each child is written for one architecture: `transformers-4.57` runs
# Unlimited-OCR's remote code (it needs that transformers, see engines.py),
# `transformers` runs GLM-OCR behind a PP-DocLayoutV3 layout stage, which it
# reads from weights.parts.layout. An operator's OCR instance is another
# checkpoint of one of the two, served under a name of its own.
CHILD_OF_ENGINE: dict[str, str] = {
    "transformers-4.57": "giq.workers._ocr_child",
    "transformers": "giq.workers._glm_ocr_child",
}
# The parts each child loads besides the main weights.
PARTS_OF_CHILD: dict[str, tuple[str, ...]] = {"giq.workers._glm_ocr_child": ("layout",)}
# `giq` must be importable in the other interpreter: its venv does not
# install giq, so the child gets this checkout's src on PYTHONPATH.
_GIQ_SRC = str(Path(__file__).resolve().parents[2])


def _instance(model: str):
    inst = instance_of("ocr", model)
    if inst is None:
        raise ValueError(f"unknown OCR model {model!r}: no instance file defines it")
    return inst


@dataclass
class OCRWorkerConfig:
    model: str = "unlimited-ocr"


class OCRWorker(SubprocessWorker):
    """An OCR model in a child process; documents assembled in the parent."""

    child_module: ClassVar[str] = "giq.workers._ocr_child"  # per engine; see CHILD_OF_ENGINE
    worker_type: ClassVar[str] = "ocr"
    # A long document is several passes of a few minutes each.
    run_batch_timeout: ClassVar[float] = 3600.0

    def __init__(self, config: OCRWorkerConfig, device: str | None = None):
        super().__init__(config, device)
        # Unknown model, foreign engine or missing weights: fail here, not at spawn.
        self.engine = _instance(config.model).engine
        try:
            # Instance attribute shadows the ClassVar: _command() reads self.child_module.
            self.child_module = CHILD_OF_ENGINE[self.engine]
        except KeyError:
            raise ValueError(
                f"ocr/{config.model}: no OCR child runs engine {self.engine!r} "
                f"(one of {', '.join(sorted(CHILD_OF_ENGINE))})"
            ) from None
        self.weights = require_path("ocr", config.model)
        self.parts = {
            part: require_path("ocr", config.model, part)
            for part in PARTS_OF_CHILD.get(self.child_module, ())
        }

    def child_args(self) -> list[str]:
        args = ["--weights", self.weights]
        for part, path in self.parts.items():
            args += [f"--{part}", path]
        return args

    @property
    def estimated_vram_gb(self) -> float:
        return vram_for(self.config.model, "ocr", default=OCR_VRAM_GB)

    def _own_interpreter(self) -> bool:
        # giq's own interpreter runs the engines ENGINE_OF_BACKEND maps to it.
        from giq.engines import ENGINE_OF_BACKEND, SELF

        return ENGINE_OF_BACKEND.get(self.engine, SELF) == SELF

    def _interpreter(self) -> str:
        if self._own_interpreter():
            return sys.executable
        from giq.engines import ENGINE_OF_BACKEND, require_binary

        return require_binary(ENGINE_OF_BACKEND[self.engine])

    def _command(self) -> list[str]:
        return [self._interpreter(), "-u", "-m", self.child_module, *self.child_args()]

    def _spawn_env(self) -> dict[str, str]:
        env = super()._spawn_env()
        if not self._own_interpreter():
            extra = env.get("PYTHONPATH")
            env["PYTHONPATH"] = _GIQ_SRC + (os.pathsep + extra if extra else "")
        return env

    async def run_batch(
        self, tasks: list[dict[str, Any]], params: dict[str, Any] | None = None
    ) -> list[OCRResult]:
        raw_results = await super().run_batch(tasks, params)
        options = {t.get("id"): t for t in tasks}
        return [hydrate(r, options.get(r.get("id"), {})) for r in raw_results]


def hydrate(result: dict[str, Any], task: dict[str, Any]) -> OCRResult:
    """Child result dict → OCRResult, applying the task's post-processing flags."""
    rid = str(result.get("id", "unknown"))
    if result.get("error"):
        return OCRResult(id=rid, error=str(result["error"]))
    raw = result.get("raw") or ""
    html, blocks = ocrdoc.render(
        raw, strip=task.get("strip", True) is not False, merge=task.get("merge", True) is not False
    )
    return OCRResult(
        id=rid,
        html=html,
        pages=int(result.get("pages") or ocrdoc.page_count(raw)),
        blocks=blocks,
        raw=raw if task.get("raw") else None,
        tokens_in=result.get("tokens_in"),
        tokens_out=result.get("tokens_out"),
        truncated=bool(result.get("truncated", False)),
    )
