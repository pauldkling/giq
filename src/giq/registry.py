# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Canonical registry of every model giq can run.

Before this module the model list lived in six places that each knew a part
of it: ``vram.VRAM_REQUIREMENTS``, ``workers.llm.MODEL_VRAM_GB`` (a hand-kept
copy of the LLM half), ``config.yaml: image_models``, the hand-written
``Capabilities`` payload in the API, ``runner.RESIDENTS_DEFAULT`` +
``RESIDENT_LANE_WIDTH``, and ``LANE_LABEL`` in the dashboard. They drifted:
``/capabilities`` advertised ``tts/kokoro-82m``, a name absent from the VRAM
table, so it fell through to ``DEFAULT_VRAM_REQUIREMENT`` (22 GB) and
``wait_for_vram`` refused to load it at all on a 16 GB card. A client that
trusted the discovery endpoint got a hard failure.

So: one record per model, one place to add one, and everything else — VRAM
gating, the catalog, ``/capabilities``, the resident set, the dashboard —
reads from here. The records are recipe files (``giq.recipes``): the
built-ins shipped with giq and the operator's own, which add models or
replace a built-in by name. This module turns the current snapshot of them
into ModelSpecs and lays config.yaml's overlays on top.

Registration is not a whitelist. ``get_vram_requirement`` still falls back to
a default for unregistered pairs so an experimental model can be submitted
without a code change; it just won't be schedulable on a small card, which is
exactly the trap above. Give a model you intend to run a recipe file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from giq import recipes
from giq.engines import canonical_engine
from giq.recipes.schema import LlamaCppParams, Recipe, VllmParams

logger = logging.getLogger(__name__)

# Concurrent jobs allowed on a resident's lane, by worker type. llm matches
# llama-server's 4 slots, so a client fanning out a few chat calls at once
# gets them served in parallel; embed takes 2; audio is GPU-heavy and serial.
DEFAULT_LANE_WIDTH: dict[str, int] = {"llm": 4, "audio": 1, "embed": 2}

IMAGE_WORKERS = ("text2image", "image_edit")


@dataclass(frozen=True)
class ModelSpec:
    """Everything giq needs to know about one (worker, model) pair."""

    worker: str
    model: str
    vram_gb: float
    backend: str
    # Dashboard presentation. label defaults to the model name.
    label: str = ""
    detail: str = ""
    # Image models only: which runtime renders this ("sd.cpp"), the same name
    # as `backend`; kept because the dashboard shows the image runtime as an
    # engine of its own.
    engine: str | None = None
    # None = take DEFAULT_LANE_WIDTH for the worker type.
    lane_width: int | None = None
    # Position in the resident set, lowest first. None = not resident by
    # default (a "sleepy" model: loads on demand, evictable).
    resident_priority: int | None = None
    max_batch: int | None = None
    voices: tuple[str, ...] = ()
    # Alternative names clients may send. Kept so back-compat names keep
    # resolving to the same spec instead of silently missing the table.
    aliases: tuple[str, ...] = ()
    # True when vram_gb was measured on real hardware, False when estimated.
    # Surfaced in the catalog so an estimate is never mistaken for a fact.
    measured: bool = False
    # Vision: the model accepts images alongside text. A capability of an LLM,
    # not a worker type of its own — it still serves ordinary chat. `mmproj`
    # is llama.cpp's separate projector file, without which the weights are
    # text-only; its size counts toward vram_gb.
    vision: bool = False
    mmproj: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.worker, self.model)

    @property
    def name(self) -> str:
        return f"{self.worker}/{self.model}"

    @property
    def lanes(self) -> int:
        if self.lane_width is not None:
            return self.lane_width
        return DEFAULT_LANE_WIDTH.get(self.worker, 1)

    @property
    def display(self) -> str:
        return self.label or self.model


def spec_of(recipe: Recipe) -> ModelSpec:
    """The ModelSpec a recipe file declares."""
    params = recipe.params
    return ModelSpec(
        worker=recipe.worker,
        model=recipe.name,
        vram_gb=recipe.vram.gb,
        backend=recipe.engine,
        label=recipe.label,
        detail=recipe.detail,
        engine=recipe.engine if recipe.worker in IMAGE_WORKERS else None,
        # D8: vllm's max_num_seqs is how many requests it really runs at once;
        # llama.cpp keeps its separate lane width until its -np is aligned.
        lane_width=(params.max_num_seqs if isinstance(params, VllmParams) else recipe.lane_width),
        resident_priority=recipe.residency.priority,
        max_batch=recipe.max_batch,
        voices=recipe.voices,
        aliases=recipe.aliases,
        measured=recipe.vram.measured,
        vision="vision" in recipe.capabilities,
        mmproj=params.mmproj if isinstance(params, LlamaCppParams) else None,
    )


# --- Build + access ----------------------------------------------------------

_registry: dict[tuple[str, str], ModelSpec] | None = None
_alias_index: dict[tuple[str, str], tuple[str, str]] | None = None


def _apply_config(specs: dict[tuple[str, str], ModelSpec]) -> None:
    """Overlay config.yaml on the recipe specs.

    ``image_models`` (deprecated: an image model's files belong in its
    recipe file) is keyed by model name and applies to whichever image
    worker serves it (flux_klein is both a text2image and an image_edit
    model). Only keys the entry actually sets are overlaid, so one that omits
    vram_gb keeps the measured recipe figure rather than a default.
    """
    from giq.config import get_config, warn_image_model

    cfg = get_config()
    for name, model_cfg in cfg.image_models.items():
        for worker in ("text2image", "image_edit"):
            key = (worker, name)
            spec = specs.get(key)
            if spec is None:
                continue
            warn_image_model(name, model_cfg)
            engine = (
                canonical_engine(model_cfg.engine, f"config.yaml image_models.{name}")
                if model_cfg.engine
                else spec.engine
            )
            vram_gb = model_cfg.vram_gb if model_cfg.vram_gb is not None else spec.vram_gb
            specs[key] = replace(
                spec,
                vram_gb=vram_gb,
                engine=engine,
                backend=engine or spec.backend,
                # A config-supplied figure is a claim, not a measurement.
                measured=spec.measured and vram_gb == spec.vram_gb,
            )

    residents = getattr(cfg, "residents", None)
    if not residents:
        return
    # An explicit residents list replaces the built-in set entirely, in the
    # order given (that order is reload priority).
    for spec in list(specs.values()):
        if spec.resident_priority is not None:
            specs[spec.key] = replace(spec, resident_priority=None)
    for priority, entry in enumerate(residents):
        worker, _, model = entry.partition("/")
        key = (worker, model)
        spec = specs.get(key)
        if spec is None:
            logger.warning(f"config residents: unknown model {entry!r}, ignoring")
            continue
        specs[key] = replace(spec, resident_priority=priority)


def _build() -> dict[tuple[str, str], ModelSpec]:
    # VRAM figures are measured per-model peaks unless a recipe says
    # otherwise. They must be measured, not derived from weight size:
    # flux_klein and zimage run under identical --offload-to-cpu flags and
    # peak 8.5 vs 12.6 GB.
    specs = {recipe.key: spec_of(recipe) for recipe in recipes.current().recipes.values()}
    try:
        _apply_config(specs)
    except Exception as e:  # config problems must not take the service down
        logger.warning(f"registry: config overlay failed, using built-ins: {e}")
    return specs


def get_registry() -> dict[tuple[str, str], ModelSpec]:
    global _registry, _alias_index
    if _registry is None:
        _registry = _build()
        _alias_index = {
            (spec.worker, alias): spec.key for spec in _registry.values() for alias in spec.aliases
        }
    return _registry


def _invalidate(_snapshot: recipes.Snapshot | None = None) -> None:
    global _registry, _alias_index
    _registry = None
    _alias_index = None


def reload_registry() -> dict[tuple[str, str], ModelSpec]:
    """Re-read the recipe files and the config, and rebuild."""
    recipes.reload()  # notifies _invalidate
    _invalidate()
    return get_registry()


# A reload of the recipes, from wherever it comes, rebuilds on next use.
recipes.subscribe(_invalidate)


def get_spec(worker: str, model: str) -> ModelSpec | None:
    """Look up a spec, resolving aliases. None if not registered."""
    registry = get_registry()
    key = (str(worker), str(model))
    spec = registry.get(key)
    if spec is not None:
        return spec
    assert _alias_index is not None  # populated by get_registry
    aliased = _alias_index.get(key)
    return registry.get(aliased) if aliased else None


def all_specs() -> list[ModelSpec]:
    """Every registered model, sorted by worker then model."""
    return sorted(get_registry().values(), key=lambda s: (s.worker, s.model))


def resident_defaults() -> list[tuple[str, str]]:
    """The default resident set, in reload-priority order."""
    residents = [s for s in get_registry().values() if s.resident_priority is not None]
    residents.sort(key=lambda s: s.resident_priority or 0)
    return [s.key for s in residents]


def vram_for(model: str, *workers: str, default: float) -> float:
    """VRAM for ``model`` under the first of ``workers`` that registers it.

    Workers call this for their ``estimated_vram_gb``, which is what the
    eviction planner uses to size victims. Before the registry each worker
    kept its own MODEL_VRAM_GB, so the planner and the VRAM gate could read
    different numbers for the same model — sd.cpp had zimage at 9GB while the
    gate required 13GB.
    """
    for worker in workers:
        spec = get_spec(worker, model)
        if spec is not None:
            return spec.vram_gb
    return default


def lane_width_for(worker: str, model: str) -> int:
    """Concurrent jobs allowed on this model's resident lane."""
    spec = get_spec(worker, model)
    return spec.lanes if spec else DEFAULT_LANE_WIDTH.get(str(worker), 1)
