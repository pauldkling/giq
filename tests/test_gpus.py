# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for per-GPU telemetry parsing and device selection (gpus.py)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from giq import gpus
from giq.gpus import GpuTelemetry, decode_throttle, get_gpus


class FakeResult:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


TWO_GPU_OUTPUT = (
    "GPU-8f6adead-beef-0000-0000-c0ffee000001, 0, NVIDIA GeForce RTX 5090, "
    "32607, 12034, 62, 287.45, 575.00, 93, 41, 0x0000000000000000\n"
    "GPU-8f6adead-beef-0000-0000-c0ffee000002, 1, NVIDIA GeForce RTX 5060 Ti, "
    "16311, 13800, 78, 154.10, 180.00, 34, [N/A], 0x0000000000000004\n"
)


def _fresh_cache():
    gpus._cache = None


def test_parses_multiple_gpus():
    _fresh_cache()
    with patch("giq.gpus.subprocess.run", return_value=FakeResult(TWO_GPU_OUTPUT)):
        result = get_gpus(max_age=0)
    assert len(result) == 2
    big, small = result
    assert big.uuid.endswith("000001")
    assert big.index == 0
    assert big.name == "NVIDIA GeForce RTX 5090"
    assert round(big.vram_total_gb, 1) == 31.8
    assert big.temperature_c == 62
    assert big.power_draw_w == 287.45
    assert big.power_limit_w == 575.0
    assert big.throttle == []
    # [N/A] fan on the second card parses to None, not a crash
    assert small.fan_pct is None
    assert small.throttle == [{"reason": "sw power cap", "severity": "info"}]


def test_throttle_decode_multiple_bits():
    reasons = decode_throttle("0x0000000000000044")
    # Holding a configured power limit is normal operation, so it decodes as
    # info and the dashboard's chips (warning + critical only) stay quiet.
    assert {"reason": "sw power cap", "severity": "info"} in reasons
    assert {"reason": "hw thermal", "severity": "critical"} in reasons


def test_power_brake_is_still_loud():
    """The hardware brake is a different animal: the board is being forced
    down — the signature of a PSU that cannot hold the load."""
    assert decode_throttle("0x80") == [{"reason": "power brake", "severity": "critical"}]


def test_failed_query_returns_empty_not_raise():
    _fresh_cache()
    with patch("giq.gpus.subprocess.run", side_effect=FileNotFoundError("no nvidia-smi")):
        assert get_gpus(max_age=0) == []


def test_falls_back_to_minimal_query():
    _fresh_cache()
    minimal = "GPU-abc, 0, NVIDIA GeForce RTX 5060 Ti, 16311, 13800\n"

    def fake_run(cmd, **kwargs):
        if "temperature.gpu" in cmd[1]:
            return FakeResult("", returncode=6)  # old driver rejects a column
        return FakeResult(minimal)

    with patch("giq.gpus.subprocess.run", side_effect=fake_run):
        result = get_gpus(max_age=0)
    assert len(result) == 1
    assert result[0].temperature_c is None
    assert round(result[0].vram_used_gb, 1) == 13.5


def test_free_vram_property():
    g = GpuTelemetry(uuid="GPU-x", index=0, name="card", vram_total_gb=32.0, vram_used_gb=12.5)
    assert g.vram_free_gb == 19.5
    d = g.to_dict()
    assert d["vram_free_gb"] == 19.5
    assert d["throttle"] == []


# --- Device selection --------------------------------------------------------
# Two cards make every VRAM figure ambiguous until something names one. These
# cover the naming: which card giq picks, how an operator overrides it, and
# that the pick survives the indices moving under it.

BIG_SECOND_OUTPUT = (
    "GPU-8f6adead-beef-0000-0000-c0ffee000002, 0, NVIDIA GeForce RTX 5060 Ti, "
    "16311, 811, 36, 9.00, 180.00, 3, 0, 0x0000000000000000\n"
    "GPU-8f6adead-beef-0000-0000-c0ffee000001, 1, NVIDIA GeForce RTX 5090, "
    "32607, 4921, 30, 9.00, 500.00, 0, 0, 0x0000000000000000\n"
)

COMPUTE_APPS_OUTPUT = (
    "GPU-8f6adead-beef-0000-0000-c0ffee000001, 3702, 9100\n"
    "GPU-8f6adead-beef-0000-0000-c0ffee000002, 4050, 242\n"
    "GPU-8f6adead-beef-0000-0000-c0ffee000001, 3747, 602\n"
)


@pytest.fixture(autouse=True)
def _reset_gpu_state():
    """Cache and device pin are process-global; don't leak them between tests."""
    gpus._cache = None
    gpus.reset_selected_device()
    yield
    gpus._cache = None
    gpus.reset_selected_device()


def _fake_nvidia_smi(gpu_output: str = TWO_GPU_OUTPUT, apps: str = COMPUTE_APPS_OUTPUT):
    def fake_run(cmd, **kwargs):
        if cmd[1].startswith("--query-compute-apps"):
            return FakeResult(apps)
        return FakeResult(gpu_output)

    return fake_run


def _use_config(monkeypatch, device):
    monkeypatch.setattr(
        "giq.config.get_config", lambda: SimpleNamespace(gpu=SimpleNamespace(device=device))
    )


def test_default_device_is_the_biggest_card_not_index_zero(monkeypatch):
    """Index 0 is whatever the PCIe tree says; VRAM is what models need."""
    _use_config(monkeypatch, None)
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi(BIG_SECOND_OUTPUT)):
        chosen = gpus.selected_device()
    assert chosen is not None
    assert chosen.index == 1
    assert chosen.name == "NVIDIA GeForce RTX 5090"


def test_resolve_device_by_index_and_by_uuid(monkeypatch):
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
        by_index = gpus.resolve_device("1")
        by_uuid = gpus.resolve_device("GPU-8F6ADEAD-BEEF-0000-0000-C0FFEE000002")  # case-blind
        missing = gpus.resolve_device("GPU-nope")
    assert by_index is not None and by_index.index == 1
    assert by_uuid is not None and by_uuid.index == 1
    assert missing is None


def test_configured_device_overrides_the_default(monkeypatch):
    _use_config(monkeypatch, "1")
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
        chosen = gpus.selected_device()
    assert chosen is not None
    assert chosen.name == "NVIDIA GeForce RTX 5060 Ti"


def test_unknown_configured_device_falls_back_loudly(monkeypatch, caplog):
    """A typo'd device must not blind the VRAM gate — pick a card and shout."""
    _use_config(monkeypatch, "GPU-does-not-exist")
    with caplog.at_level("ERROR"):
        with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
            chosen = gpus.selected_device()
    assert chosen is not None and chosen.index == 0  # the 5090, by size
    assert "matches no card" in caplog.text


def test_selection_pins_by_uuid_across_reenumeration(monkeypatch):
    """A card's index can move under a running scheduler; the choice must not."""
    _use_config(monkeypatch, "0")
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi(TWO_GPU_OUTPUT)):
        first = gpus.selected_device()
    assert first is not None and first.uuid.endswith("000001")

    gpus._cache = None  # cards re-enumerate: same UUIDs, swapped indices
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi(BIG_SECOND_OUTPUT)):
        again = gpus.selected_device()
    assert again is not None
    assert again.uuid == first.uuid  # same card...
    assert again.index == 1  # ...even though config said "0"


def test_device_env_pins_children_to_one_card(monkeypatch):
    _use_config(monkeypatch, "1")
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
        env = gpus.device_env()
    assert env["CUDA_VISIBLE_DEVICES"].endswith("000002")


def test_device_env_leaves_environment_alone_without_a_gpu(monkeypatch):
    _use_config(monkeypatch, None)
    with patch("giq.gpus.subprocess.run", side_effect=FileNotFoundError("no nvidia-smi")):
        env = gpus.device_env()
    # An empty CUDA_VISIBLE_DEVICES means "no GPUs" — worse than not setting it.
    assert "CUDA_VISIBLE_DEVICES" not in env


def test_compute_app_memory_counts_only_the_selected_card(monkeypatch):
    """The bug: this table was machine-wide while the gate read one card.

    Sizing eviction victims from processes on a card giq isn't loading onto
    means planning to free VRAM that was never going to come back.
    """
    _use_config(monkeypatch, "0")  # the 5090
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
        mine = gpus.compute_app_memory()
        everything = gpus.compute_app_memory("all")
        other = gpus.compute_app_memory("1")
    assert set(mine) == {3702, 3747}  # gnome-shell on the other card is not ours
    assert set(everything) == {3702, 3747, 4050}
    assert set(other) == {4050}
    assert round(mine[3702], 2) == 8.89


# --- VRAM attribution --------------------------------------------------------
# "Is this card full?" and "is it full because of giq?" are different questions.
# Only the second one tells an operator whether unloading something would help.


def test_attribution_splits_used_into_ours_and_theirs(monkeypatch):
    _use_config(monkeypatch, "0")
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
        split = gpus.attribute_vram({3702: "llm/gemma-4-12b", 3747: "embed/ecapa-tdnn"})
    big = split["GPU-8f6adead-beef-0000-0000-c0ffee000001"]
    # 9100 + 602 MiB of ours on a card reporting 12034 MiB used.
    assert big["giq_gb"] == pytest.approx(9.47, abs=0.01)
    assert big["other_gb"] == pytest.approx(2.28, abs=0.01)
    assert big["giq_gb"] + big["other_gb"] == pytest.approx(
        big["total_gb"] - big["free_gb"], abs=0.02
    )
    assert [b["label"] for b in big["giq"]] == ["llm/gemma-4-12b", "embed/ecapa-tdnn"]


def test_processes_we_do_not_own_count_as_theirs(monkeypatch):
    """Someone else's CUDA job is occupancy giq cannot schedule around."""
    _use_config(monkeypatch, "0")
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
        split = gpus.attribute_vram({})  # giq owns nothing
    big = split["GPU-8f6adead-beef-0000-0000-c0ffee000001"]
    assert big["giq_gb"] == 0.0
    assert big["other_gb"] == pytest.approx(11.75, abs=0.01)  # the whole used figure


def test_theirs_is_a_remainder_not_a_sum_of_visible_processes(monkeypatch):
    """The desktop holds VRAM through graphics contexts nvidia-smi's
    compute-apps query never lists. Summing what we can see would report the
    desktop as free."""
    _use_config(monkeypatch, "1")
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi()):
        split = gpus.attribute_vram({})
        visible = sum(gpus.compute_app_memory("1").values())
    small = split["GPU-8f6adead-beef-0000-0000-c0ffee000002"]
    # The card reports 13800 MiB used; the only compute process on it holds
    # 242. The other 13.2 GB is graphics memory — real occupancy, invisible
    # to this query, and it must not come out as free.
    assert visible == pytest.approx(0.24, abs=0.01)
    assert small["other_gb"] == pytest.approx(13.48, abs=0.01)


def test_our_share_is_clamped_to_the_cards_used_total(monkeypatch):
    """Observed live: 4.78GB of processes on a card reporting 4.21GB used.

    The two figures are separate nvidia-smi queries a moment apart. A caller
    drawing a bar from them needs the parts to sum to the whole, so ours is
    clamped — as a bar, 4.78 of 4.21 simply overflows.
    """
    _use_config(monkeypatch, "0")
    skewed = (
        "GPU-8f6adead-beef-0000-0000-c0ffee000001, 0, NVIDIA GeForce RTX 5090, "
        "32607, 4311, 30, 9.00, 500.00, 0, 0, 0x0\n"
    )
    apps = "GPU-8f6adead-beef-0000-0000-c0ffee000001, 3702, 4894\n"
    with patch("giq.gpus.subprocess.run", side_effect=_fake_nvidia_smi(skewed, apps)):
        split = gpus.attribute_vram({3702: "audio/whisper-large-v3"})
    card = split["GPU-8f6adead-beef-0000-0000-c0ffee000001"]
    assert card["giq_gb"] == pytest.approx(4.21, abs=0.01)  # clamped, not 4.78
    assert card["other_gb"] == 0.0
    # The unclamped per-process truth is still there for the tooltip.
    assert card["giq"][0]["gb"] == pytest.approx(4.78, abs=0.01)
