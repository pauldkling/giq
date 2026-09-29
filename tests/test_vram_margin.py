# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Regression: resident reload must not wedge inside the safety margin.

Observed: after a flux render (minimal-victim eviction → gemma only),
free VRAM was 11.43GB and gemma needed 9.5 + 2.0 margin = 11.5GB — the
resident loop retried every 15s for over an hour with nothing evictable.
Residents pass a reduced margin because the set is validated to coexist.
"""

import pytest

from giq import vram
from giq.vram import VRAMStatus, wait_for_vram


@pytest.fixture
def wedged_gpu(monkeypatch):
    """Free VRAM sits just inside the full margin window for gemma-4-12b."""
    status = VRAMStatus(used_gb=4.5, total_gb=15.93, free_gb=11.43)
    monkeypatch.setattr(vram, "get_vram_status", lambda *a, **kw: status)
    monkeypatch.setattr(vram, "get_free_vram", lambda *a, **kw: status.free_gb)


async def test_full_margin_wedges(wedged_gpu):
    ok = await wait_for_vram("llm", "gemma-4-12b", timeout=0.05, poll_interval=0.01)
    assert not ok


async def test_resident_margin_unwedges(wedged_gpu):
    ok = await wait_for_vram("llm", "gemma-4-12b", timeout=0.05, poll_interval=0.01, margin_gb=0.5)
    assert ok
