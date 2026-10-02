# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""The registry is the single source of truth for what models exist.

These tests exist because the list used to live in six places and drifted:
/capabilities advertised tts/kokoro-82m, a name absent from the VRAM table,
so it inherited the 22GB default and could never load on a 16GB card.
"""

import asyncio

import pytest

from giq.models import Modality
from giq.registry import (
    DEFAULT_LANE_WIDTH,
    ModelSpec,
    all_specs,
    get_spec,
    lane_width_for,
    reload_registry,
    resident_defaults,
    vram_for,
)
from giq.vram import DEFAULT_VRAM_REQUIREMENT, get_vram_requirement, get_vram_status, margin_for


@pytest.fixture(autouse=True)
def _fresh_registry():
    reload_registry()
    yield
    reload_registry()


def test_every_spec_is_uniquely_keyed():
    keys = [spec.key for spec in all_specs()]
    assert len(keys) == len(set(keys))


def test_worker_names_are_real_worker_types():
    """A typo'd worker name would silently create an unreachable entry."""
    for spec in all_specs():
        Modality(spec.worker)  # raises on an unknown worker


def test_vram_lookup_goes_through_the_registry():
    for spec in all_specs():
        assert get_vram_requirement(spec.worker, spec.model) == spec.vram_gb


def test_unregistered_model_falls_back_to_the_default():
    assert get_vram_requirement("llm", "no-such-model") == DEFAULT_VRAM_REQUIREMENT


def test_aliases_resolve_to_the_same_spec():
    for spec in all_specs():
        for alias in spec.aliases:
            assert get_spec(spec.worker, alias) is spec


def test_kokoro_82m_alias_is_loadable():
    """The regression: the advertised name must resolve to the real footprint.

    Unaliased it fell through to the 22GB default, and wait_for_vram refuses
    anything larger than the card outright — so /v1/audio/speech failed with
    "VRAM never became available" rather than loading a 0.5GB model.
    """
    total = get_vram_status().total_gb
    req = get_vram_requirement("tts", "kokoro-82m")
    assert req == get_vram_requirement("tts", "kokoro")
    assert req + margin_for(req) <= total


def test_advertised_models_are_all_registered():
    """Anything /capabilities lists must be schedulable, not just nameable."""
    from giq.api.router import get_capabilities

    caps = asyncio.run(get_capabilities())
    for worker, cap in caps.workers.items():
        for model in cap.models:
            assert get_spec(str(worker), model) is not None, f"{worker}/{model} unregistered"


def test_capabilities_covers_every_registered_worker():
    from giq.api.router import get_capabilities

    caps = asyncio.run(get_capabilities())
    assert {str(w) for w in caps.workers} == {spec.worker for spec in all_specs()}


def test_resident_defaults_are_ordered_and_registered():
    residents = resident_defaults()
    assert residents  # a giq with no resident set is a misconfiguration
    for key in residents:
        assert get_spec(*key) is not None
    priorities = [get_spec(*key).resident_priority for key in residents]
    assert priorities == sorted(priorities)


def test_runner_residents_match_the_registry():
    from giq.runner import RESIDENTS_DEFAULT

    assert [(str(w), m) for w, m in RESIDENTS_DEFAULT] == resident_defaults()


def test_lane_width_falls_back_to_the_worker_default():
    assert lane_width_for("llm", "gemma-4-12b") == DEFAULT_LANE_WIDTH["llm"]
    assert lane_width_for("llm", "unregistered") == DEFAULT_LANE_WIDTH["llm"]
    assert lane_width_for("stt", "tiny") == 1


def test_vram_for_tries_workers_in_order():
    """sd.cpp serves both image workers; zimage exists only under text2image."""
    assert vram_for("zimage", "text2image", "image_edit", default=99.0) == 13.0
    assert vram_for("nothing", "text2image", default=99.0) == 99.0


def test_lane_width_override_beats_the_worker_default():
    spec = ModelSpec("llm", "x", 1.0, "llama.cpp", lane_width=2)
    assert spec.lanes == 2
    assert ModelSpec("llm", "y", 1.0, "llama.cpp").lanes == DEFAULT_LANE_WIDTH["llm"]


def test_config_residents_override_the_builtin_set(monkeypatch):
    class _Cfg:
        image_models: dict = {}
        residents = ["embed/ecapa-tdnn", "llm/gemma-4-12b"]

    monkeypatch.setattr("giq.config.get_config", lambda: _Cfg())
    reload_registry()
    assert resident_defaults() == [("embed", "ecapa-tdnn"), ("llm", "gemma-4-12b")]


def test_unknown_config_resident_is_ignored_not_fatal(monkeypatch):
    class _Cfg:
        image_models: dict = {}
        residents = ["llm/does-not-exist", "llm/gemma-4-12b"]

    monkeypatch.setattr("giq.config.get_config", lambda: _Cfg())
    reload_registry()
    assert resident_defaults() == [("llm", "gemma-4-12b")]


def test_estimated_vram_matches_the_gate():
    """The eviction planner and the VRAM gate must read the same number.

    They used to disagree: sd.cpp put zimage at 9GB while the gate wanted 13,
    so a victim's freed VRAM was mis-sized.
    """
    from giq.workers.llm import LLMWorker, LLMWorkerConfig
    from giq.workers.sdcpp import SdCppWorker, SdCppWorkerConfig

    llm = LLMWorker(config=LLMWorkerConfig(model="gemma-4-12b"))
    assert llm.estimated_vram_gb == get_vram_requirement("llm", "gemma-4-12b")

    for model in ("flux_klein", "zimage"):
        worker = SdCppWorker(config=SdCppWorkerConfig(model=model))
        assert worker.estimated_vram_gb == get_vram_requirement("text2image", model)
