# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""PNG provenance stamping."""

import base64
import io
import struct

import pytest
from PIL import Image

from giq.models import ImageResult
from giq.provenance import stamp_png, stamp_results


def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    out, pos = [], 8
    while pos < len(png):
        length = struct.unpack(">I", png[pos : pos + 4])[0]
        ctype = png[pos + 4 : pos + 8]
        out.append((ctype, png[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return out


def test_stamp_inserts_valid_chunks():
    stamped = stamp_png(_tiny_png(), "flux_klein")
    chunks = _chunks(stamped)
    assert chunks[0][0] == b"IHDR"
    assert chunks[1][0] == b"iTXt"
    assert b"trainedAlgorithmicMedia" in chunks[1][1]
    assert b"flux_klein" in chunks[1][1]
    assert chunks[2][0] == b"tEXt"
    # CRCs valid → Pillow still opens it, pixels untouched
    img = Image.open(io.BytesIO(stamped))
    assert img.size == (4, 4)
    assert img.convert("RGB").getpixel((0, 0)) == (200, 30, 30)


def test_stamp_idempotent():
    once = stamp_png(_tiny_png(), "m")
    assert stamp_png(once, "m") == once


def test_stamp_rejects_non_png():
    with pytest.raises(ValueError):
        stamp_png(b"JFIF not a png", "m")


def test_stamp_results_respects_optout(monkeypatch):
    from giq import config as config_mod

    png_b64 = base64.b64encode(_tiny_png()).decode()

    monkeypatch.setattr(config_mod, "_config", None)
    monkeypatch.setenv("GIQ_CONFIG", "/nonexistent.yaml")  # defaults → on
    results = stamp_results([ImageResult(id="a", image_b64=png_b64)], "m")
    assert results[0].image_b64 != png_b64

    cfg = config_mod.get_config()
    cfg.provenance.mark_images = False
    results = stamp_results([ImageResult(id="a", image_b64=png_b64)], "m")
    assert results[0].image_b64 == png_b64
    monkeypatch.setattr(config_mod, "_config", None)


def test_stamp_results_survives_garbage():
    bad = ImageResult(id="a", image_b64=base64.b64encode(b"not png").decode())
    err = ImageResult(id="b", error="boom")
    out = stamp_results([bad, err], "m")
    assert out[0].image_b64 == bad.image_b64
    assert out[1].error == "boom"
