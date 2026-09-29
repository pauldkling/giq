# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Where a model's weights are, as its instance file says (ADR-002).

Workers used to find their weights through tables of their own — a snapshot
directory name per model, hard-coded next to the worker — so an instance
file could add a model to the catalog that its worker then refused to load.
Every worker now asks here, and the answer comes from the instance:
``weights.path`` for the main weights, ``weights.parts.<name>`` for the other
files a model needs (an image model's text encoder and VAE, OCR's layout
model). A relative path is taken under the models directory; ``~`` and
absolute paths are used as written.

The environment variables that located these snapshots before instance
files existed still work, and outrank the instance, as an environment
variable outranks a file everywhere else in giq:

- a directory for one model's weights (``DIR_OVERRIDES``), which applies to
  that model name only — an operator's second OCR instance is not redirected
  by a variable documented for the built-in;
- a root for one worker's relative paths (``ROOT_OVERRIDES``), in place of
  the models directory.

Models that load by Hugging Face repository rather than by path (the audio
and speech workers) record it as ``source: hf:org/repo``; :func:`hub_repo`
reads it, and the storage catalog finds the download in the HF cache by it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from giq import instances
from giq.instances.schema import Instance
from giq.paths import model_path

if TYPE_CHECKING:
    from giq.config import ImageModelConfig

# A directory that replaces one instance's weights: (worker, name, part) ->
# variable; part None is the main weights.
DIR_OVERRIDES: dict[tuple[str, str, str | None], str] = {
    ("ocr", "unlimited-ocr", None): "GIQ_OCR_MODEL_DIR",
    ("ocr", "glm-ocr", None): "GIQ_GLM_OCR_MODEL_DIR",
    ("ocr", "glm-ocr", "layout"): "GIQ_GLM_LAYOUT_DIR",
}

# A root that replaces the models directory for one worker's relative paths.
ROOT_OVERRIDES: dict[str, str] = {
    "depth": "GIQ_DEPTH_MODELS_DIR",
    "multiview": "GIQ_MULTIVIEW_MODELS_DIR",
}

HF_PREFIX = "hf:"


def instance_of(worker: str, model: str) -> Instance | None:
    """The current instance ``worker/model`` names, by name or alias."""
    snapshot = instances.current()
    inst = snapshot.get(str(worker), str(model))
    if inst is not None:
        return inst
    return next((i for i in snapshot.of_worker(str(worker)) if model in i.aliases), None)


def _env(var: str | None) -> str | None:
    return os.environ.get(var) if var else None


def resolve_path(worker: str, raw: str) -> str:
    """A path as an instance writes it, made absolute for ``worker``."""
    p = Path(raw).expanduser()
    if p.is_absolute():
        return str(p)
    if root := _env(ROOT_OVERRIDES.get(str(worker))):
        return str(Path(root).expanduser() / p)
    return model_path(p)


def path_of(worker: str, model: str, part: str | None = None) -> str | None:
    """Absolute path of a model's main weights (``part=None``) or of one part.

    None when neither an override nor the instance gives one — the model is
    unknown, has no such part, or loads by repository rather than by path.
    """
    if override := _env(DIR_OVERRIDES.get((str(worker), str(model), part))):
        return str(Path(override).expanduser())
    inst = instance_of(worker, model)
    if inst is None or inst.weights is None:
        return None
    if part is None:
        raw = inst.weights.path
    else:
        piece = inst.weights.parts.get(part)
        raw = piece.path if piece is not None else None
    return resolve_path(worker, raw) if raw else None


def require_path(worker: str, model: str, part: str | None = None) -> str:
    """:func:`path_of`, raising when there is none — at construction, not at spawn."""
    path = path_of(worker, model, part)
    if path is None:
        what = "weights.path" if part is None else f"weights.parts.{part}"
        if instance_of(worker, model) is None:
            raise ValueError(f"unknown {worker} model {model!r}: no instance file defines it")
        raise ValueError(f"{worker}/{model} has no {what} in its instance file")
    return path


def hub_repo(source: str | None) -> str | None:
    """``org/repo`` of an ``hf:org/repo`` source, else None."""
    if source and source.startswith(HF_PREFIX):
        return source[len(HF_PREFIX) :] or None
    return None


def load_ref(worker: str, model: str, part: str | None = None) -> str | None:
    """What a library that takes "a path or a repo id" should load.

    The path when the instance gives one (or an override does), else the
    repository of its ``hf:`` source, else None.
    """
    if path := path_of(worker, model, part):
        return path
    inst = instance_of(worker, model)
    if inst is None or inst.weights is None:
        return None
    if part is None:
        return hub_repo(inst.weights.source)
    piece = inst.weights.parts.get(part)
    return hub_repo(piece.source) if piece is not None else None


IMAGE_PARTS = ("diffusion", "text_encoder", "vae", "lora")
_REQUIRED_IMAGE_PARTS = ("diffusion", "text_encoder", "vae")


def image_files(worker: str, model: str) -> ImageModelConfig:
    """An image model's files and runtime, as the image workers take them.

    A ``config.yaml`` ``image_models`` entry of that name still wins, with a
    deprecation warning; otherwise the instance's ``weights.parts`` (paths
    resolved like any weights) and its engine and VRAM figure.
    """
    from giq.config import ImageModelConfig, get_config, warn_image_model

    legacy = get_config().image_models.get(str(model))
    if legacy is not None:
        warn_image_model(str(model), legacy)
        return legacy
    inst = instance_of(worker, model)
    if inst is None:
        raise ValueError(f"unknown {worker} model {model!r}: no instance file defines it")
    files = {part: path_of(worker, inst.name, part) for part in IMAGE_PARTS}
    if missing := [p for p in _REQUIRED_IMAGE_PARTS if not files[p]]:
        raise ValueError(
            f"{worker}/{model} names no {', '.join(f'weights.parts.{p}' for p in missing)} "
            "in its instance file"
        )
    return ImageModelConfig(
        diffusion=str(files["diffusion"]),
        text_encoder=str(files["text_encoder"]),
        vae=str(files["vae"]),
        lora=files["lora"],
        vram_gb=inst.vram.gb,
        engine=inst.engine,
    )


@dataclass(frozen=True)
class Location:
    """One thing on disk a model needs: a path, or an HF repository whose
    download lives in the HF cache."""

    part: str | None
    path: str | None = None
    repo: str | None = None


def locations(worker: str, model: str) -> list[Location]:
    """Every file, snapshot or repository ``worker/model`` loads, main weights first."""
    inst = instance_of(worker, model)
    weights = inst.weights if inst is not None else None
    parts: list[tuple[str | None, str | None]] = [
        (None, weights.source if weights else None),
        *((name, p.source) for name, p in (weights.parts.items() if weights else ())),
    ]
    out = []
    for part, source in parts:
        if path := path_of(worker, model, part):
            out.append(Location(part, path=path))
        elif repo := hub_repo(source):
            out.append(Location(part, repo=repo))
    return out
