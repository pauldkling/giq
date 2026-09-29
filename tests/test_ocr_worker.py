# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""OCRWorker: child results become documents in the parent.

The child is replaced by an inline script that answers every task with a
canned tagged text, so this exercises hydration, the per-task flags and the
error envelope without a GPU or a model.
"""

import json
import sys

import pytest

from giq.models import OCRResult
from giq.workers.ocr import OCRWorker, OCRWorkerConfig, hydrate

RAW = (
    "<PAGE>\n<|det|>header [100, 36, 400, 70]<|/det|>Example AG\n"
    "<|det|>text [100, 100, 900, 200]<|/det|>Body text.\n"
    "<|det|>page_number [900, 940, 950, 970]<|/det|>1\n"
)

# Answers each task with RAW, or an error when the task id says so.
CHILD_SCRIPT = f"""
import sys, json
RAW = {RAW!r}
sys.stdout.write(json.dumps({{"type": "ready"}}) + "\\n"); sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("type") == "shutdown":
        break
    results = []
    for t in msg["tasks"]:
        if t["id"].startswith("bad"):
            results.append({{"id": t["id"], "error": "no pages to parse"}})
        else:
            results.append(
                {{"id": t["id"], "raw": RAW, "pages": 1, "tokens_in": 260, "tokens_out": 12}}
            )
    sys.stdout.write(json.dumps({{"type": "results", "results": results}}) + "\\n")
    sys.stdout.flush()
"""


class _StubOCRWorker(OCRWorker):
    def _command(self) -> list[str]:
        return [sys.executable, "-u", "-c", CHILD_SCRIPT]

    def _spawn_env(self) -> dict[str, str]:
        import os

        return dict(os.environ)


@pytest.mark.asyncio
async def test_run_batch_returns_documents_not_pages():
    worker = _StubOCRWorker(OCRWorkerConfig())
    await worker.start()
    try:
        results = await worker.run_batch(
            [{"id": "a", "pdf_b64": "x"}, {"id": "b", "pdf_b64": "x", "raw": True}, {"id": "bad-1"}]
        )
    finally:
        await worker.stop()

    assert all(isinstance(r, OCRResult) for r in results)
    a, b, bad = results
    assert a.html == '<p class="text" data-page="1" data-bbox="100,100,900,200">Body text.</p>'
    assert a.pages == 1 and a.tokens_in == 260 and a.tokens_out == 12 and a.error is None
    assert "Example AG" not in a.html  # header stripped
    assert a.raw is None  # only on request
    assert b.raw == RAW
    assert bad.error == "no pages to parse" and bad.html == ""
    # The runner stores results via model_dump(); make sure that round-trips.
    dumped = json.loads(json.dumps([r.model_dump() for r in results]))
    assert dumped[0]["blocks"][0]["label"] == "text"


def test_hydrate_honours_strip_and_merge_flags():
    result = {"id": "t", "raw": RAW, "pages": 1}
    kept = hydrate(result, {"strip": False})
    assert "Example AG" in kept.html
    assert [b["label"] for b in kept.blocks] == ["header", "text", "page_number"]
    default = hydrate(result, {})
    assert [b["label"] for b in default.blocks] == ["text"]


def test_hydrate_counts_pages_when_the_child_did_not():
    assert hydrate({"id": "t", "raw": RAW}, {}).pages == 1


def test_estimated_vram_comes_from_the_registry():
    assert OCRWorker(OCRWorkerConfig()).estimated_vram_gb == 9.0


def test_the_engine_picks_the_child():
    assert (
        OCRWorker(OCRWorkerConfig(model="unlimited-ocr")).child_module == "giq.workers._ocr_child"
    )
    assert OCRWorker(OCRWorkerConfig(model="glm-ocr")).child_module == "giq.workers._glm_ocr_child"
    with pytest.raises(ValueError):
        OCRWorker(OCRWorkerConfig(model="no-such-ocr"))


def test_glm_vram_comes_from_the_registry():
    assert OCRWorker(OCRWorkerConfig(model="glm-ocr")).estimated_vram_gb == 4.0


def test_unlimited_ocr_runs_on_its_own_interpreter(monkeypatch):
    """Its remote code needs transformers 4.57; giq's venv is on 5. The child
    is spawned with the declared engine's python and can import giq from src."""
    import os
    import sys

    from giq.engines import binary_for

    w = OCRWorker(OCRWorkerConfig(model="unlimited-ocr"))
    monkeypatch.setattr("giq.engines.require_binary", lambda name: binary_for(name))
    cmd = w._command()
    assert cmd[0] == binary_for("transformers-4.57") and cmd[0] != sys.executable
    assert cmd[1:4] == ["-u", "-m", "giq.workers._ocr_child"]
    env = w._spawn_env()
    assert env["PYTHONPATH"].split(os.pathsep)[0].endswith("/src")

    assert cmd[4] == "--weights" and cmd[5].endswith("/baidu-Unlimited-OCR")

    g = OCRWorker(OCRWorkerConfig(model="glm-ocr"))
    assert g._command()[0] == sys.executable
    args = g._command()[4:]
    assert args[0] == "--weights" and args[1].endswith("/zai-GLM-OCR")
    assert args[2] == "--layout" and args[3].endswith("/PaddlePaddle-PP-DocLayoutV3")
    assert "PYTHONPATH" not in g._spawn_env() or not g._spawn_env()["PYTHONPATH"].endswith("/src")
