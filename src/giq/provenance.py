# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""AI-provenance marking for generated images.

Inserts an XMP packet (IPTC digitalSourceType = trainedAlgorithmicMedia — the
signal platforms actually parse) as a PNG iTXt chunk, plus a Software tEXt
chunk. Pure chunk surgery: pixel data is never re-encoded, so stamping is
byte-exact on the image itself and costs microseconds.

Limitation worth knowing: metadata survives the file giq serves, but most
social platforms re-encode uploads and strip it.
"""

from __future__ import annotations

import base64
import logging
import struct
import zlib

logger = logging.getLogger(__name__)

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_XMP_KEYWORD = b"XML:com.adobe.xmp"

_XMP_TEMPLATE = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
    xmp:CreatorTool="giq · {model}"
    Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="r"?>"""


def _chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def stamp_png(png: bytes, model: str) -> bytes:
    """Insert provenance chunks after IHDR; no-op if already stamped."""
    if not png.startswith(_PNG_SIG):
        raise ValueError("not a PNG")
    if _XMP_KEYWORD in png:
        return png
    # IHDR is mandatory-first: signature(8) + length(4) + type(4) + data + crc(4)
    ihdr_len = struct.unpack(">I", png[8:12])[0]
    cut = 8 + 12 + ihdr_len
    xmp = _XMP_TEMPLATE.format(model=model).encode()
    itxt = _chunk(b"iTXt", _XMP_KEYWORD + b"\x00\x00\x00\x00\x00" + xmp)
    text = _chunk(b"tEXt", b"Software\x00giq (AI-generated, model=" + model.encode() + b")")
    return png[:cut] + itxt + text + png[cut:]


def stamp_results(results: list, model: str) -> list:
    """Stamp every ImageResult.image_b64 in place; never fails the job."""
    from giq.config import get_config

    if not get_config().provenance.mark_images:
        return results
    for r in results:
        if not getattr(r, "image_b64", None):
            continue
        try:
            raw = base64.b64decode(r.image_b64)
            r.image_b64 = base64.b64encode(stamp_png(raw, model)).decode()
        except Exception as e:  # noqa: BLE001 — marking must never kill a render
            logger.warning("provenance stamp failed for %s: %s", r.id, e)
    return results
