# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for VRAM utilities.

The gate reads ONE card. Which one is ``gpus.selected_device()``'s answer —
these tests exist because it used to be "whichever row nvidia-smi printed
first", a distinction with no difference until a second card arrived.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from giq import gpus
from giq.vram import VRAMStatus, can_load, get_free_vram, get_vram_status

# GPU 0 is the small card (and the one the old first-row read would have
# reported); GPU 1 is the big one giq should actually pick.
SMALL_FIRST_OUTPUT = (
    "GPU-8f6adead-beef-0000-0000-c0ffee000002, 0, NVIDIA GeForce RTX 5060 Ti, "
    "16311, 811, 36, 9.00, 180.00, 3, 0, 0x0000000000000000\n"
    "GPU-8f6adead-beef-0000-0000-c0ffee000001, 1, NVIDIA GeForce RTX 5090, "
    "32607, 4921, 30, 9.00, 500.00, 0, 0, 0x0000000000000000\n"
)


class FakeResult:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


@pytest.fixture(autouse=True)
def _reset_gpu_state():
    gpus._cache = None
    gpus.reset_selected_device()
    yield
    gpus._cache = None
    gpus.reset_selected_device()


@pytest.fixture
def two_cards(monkeypatch):
    """Two visible cards, with ``gpu.device`` set to whatever the test wants."""

    def configure(device=None):
        monkeypatch.setattr(
            "giq.config.get_config",
            lambda: SimpleNamespace(gpu=SimpleNamespace(device=device)),
        )
        return patch("giq.gpus.subprocess.run", return_value=FakeResult(SMALL_FIRST_OUTPUT))

    return configure


def test_vram_status_utilization():
    status = VRAMStatus(used_gb=16.0, total_gb=32.0, free_gb=16.0)
    assert status.utilization == 50.0


def test_vram_status_utilization_zero_total():
    status = VRAMStatus(used_gb=0.0, total_gb=0.0, free_gb=0.0)
    assert status.utilization == 0


def test_status_describes_the_selected_card_not_the_first_row(two_cards):
    """The regression: 'the GPU' meant nvidia-smi's first line."""
    with two_cards(None):
        status = get_vram_status()
    assert round(status.total_gb, 1) == 31.8  # the 5090, which is index 1 here
    assert round(status.used_gb, 1) == 4.8
    assert round(status.free_gb, 1) == 27.0


def test_status_follows_the_configured_device(two_cards):
    with two_cards("0"):
        status = get_vram_status()
        free = get_free_vram()
    assert round(status.total_gb, 1) == 15.9  # the 5060 Ti
    assert round(free, 1) == 15.1


def test_status_can_be_asked_about_a_named_card(two_cards):
    """Per-model binding will need this; the plumbing is here now."""
    with two_cards(None):
        big = get_vram_status("1")
        small = get_vram_status("GPU-8f6adead-beef-0000-0000-c0ffee000002")
    assert round(big.total_gb, 1) == 31.8
    assert round(small.total_gb, 1) == 15.9


def test_falls_back_to_a_conservative_card_when_no_gpu_visible(monkeypatch):
    monkeypatch.setattr(
        "giq.config.get_config", lambda: SimpleNamespace(gpu=SimpleNamespace(device=None))
    )
    with patch("giq.gpus.subprocess.run", side_effect=FileNotFoundError("no nvidia-smi")):
        status = get_vram_status()
    assert status.total_gb == 16.0
    assert status.free_gb == 16.0


def test_can_load_model_is_judged_against_the_selected_card(two_cards):
    """A model that fits the 5090 and not the 5060 Ti answers differently."""
    with two_cards("1"):  # 5090, 27GB free
        ok_big, _ = can_load("qwen3.8-27b")  # 26.5GB declared
        ok_klein_big, _ = can_load("flux_klein")  # 8GB
    gpus.reset_selected_device()
    gpus._cache = None
    with two_cards("0"):  # 5060 Ti, 15.1GB free
        ok_small, reason_small = can_load("qwen3.8-27b")
    assert ok_klein_big is True
    assert ok_big is False  # 26.5GB + margin overruns the 27GB free
    assert ok_small is False
    assert "can never fit" in reason_small  # 26.5GB exceeds a 16GB card entirely
