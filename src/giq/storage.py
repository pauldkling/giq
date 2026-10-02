# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Disk storage accounting and deletion for model weights.

Resolves every model in the VRAM registry to its on-disk files (GGUF files,
safetensors components, HF-cache snapshot dirs), detects files shared between
models (text2image and image_edit flux_klein share every file; stt large-v3 and the audio resident
share the faster-whisper snapshot), and aggregates per-mount disk usage.
Where a model's files are is its recipe's to say (``giq.weights``).
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from giq.paths import hf_home
from giq.registry import all_recipes, get_recipe
from giq.weights import Location, locations

# GGUF shard names: model-00001-of-00004.gguf → glob the whole set.
_SHARD_RE = re.compile(r"^(.*)-\d{5}-of-(\d{5})$")


class StorageError(Exception):
    """Deletion refused or failed; .status carries the HTTP code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def hf_cache_dir() -> Path:
    """HF hub cache root, honoring the usual env overrides.

    ``paths.hf_home`` is also what giq exports to its children, so the
    catalog looks where they download.
    """
    if explicit := os.environ.get("HUGGINGFACE_HUB_CACHE"):
        return Path(explicit)
    return hf_home() / "hub"


def _on_disk(loc: Location, hub: Path) -> Path:
    """A path as it is, a repository as its HF-cache directory."""
    if loc.path:
        return Path(loc.path)
    return hub / f"models--{str(loc.repo).replace('/', '--')}"


def _expand_gguf(path: Path) -> list[Path]:
    """A sharded GGUF's siblings count as part of the model; anything else is itself.

    A checkpoint directory is counted whole already, and its own
    ``model-00001-of-00003.safetensors`` shards are not the GGUF set this
    globs for.
    """
    if path.suffix != ".gguf":
        return [path]
    m = _SHARD_RE.match(path.stem)
    if not m:
        return [path]
    siblings = sorted(path.parent.glob(f"{m.group(1)}-*-of-{m.group(2)}{path.suffix}"))
    return siblings or [path]


def resolve_model_paths() -> dict[str, list[Path]]:
    """recipe → on-disk paths (files or snapshot dirs), resolved.

    Every recipe gets an entry; unresolvable ones map to an empty list rather
    than being dropped.
    """
    hub = hf_cache_dir()
    out: dict[str, list[Path]] = {}
    for name in (r.name for r in all_recipes()):
        paths: list[Path] = []
        if found := locations(name):
            # What the recipe names (with the adapters' env overrides): local
            # files and snapshot directories for the models loaded by path —
            # the hub is never consulted for those — and HF-cache repos for
            # the models loaded by repository. faster-whisper large-v3 appears
            # twice on purpose: the stt recipe large-v3 and the audio resident
            # whisper-large-v3 load one snapshot. LLMs come through here too,
            # whatever their format: a llama.cpp GGUF (its shards expanded) and
            # a vllm checkpoint directory are both just the recipe's
            # weights.path.
            paths = [p for loc in found for p in _expand_gguf(_on_disk(loc, hub))]
        # resolve() unifies symlinked routes (e.g. a symlinked home dir) so
        # sharing detection compares real locations.
        out[name] = [p.expanduser().resolve() for p in paths]
    return out


def _path_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return 0


def _mount_point(p: Path) -> Path:
    while not os.path.ismount(p):
        p = p.parent
    return p


@dataclass
class ModelStorage:
    # The recipe's first modality, as the dashboard groups it; the recipe is
    # `model`. GET /weights replaces this per-recipe view (ADR-003 step 4).
    worker: str
    model: str
    paths: list[Path]
    on_disk: bool
    size_bytes: int  # 0 when not on disk
    shared_with: list[str] = field(default_factory=list)  # other recipes


def storage_report() -> tuple[list[ModelStorage], list[dict]]:
    """Per-model storage plus per-mount disk breakdown.

    Disk breakdown counts each physical file once even when two models
    reference it.
    """
    resolved = resolve_model_paths()
    owners: dict[Path, list[str]] = {}
    for name, paths in resolved.items():
        for p in paths:
            owners.setdefault(p, []).append(name)

    sizes = {p: _path_size(p) for p in owners}
    models: list[ModelStorage] = []
    for name, paths in sorted(resolved.items()):
        recipe = get_recipe(name)
        existing = [p for p in paths if p.exists()]
        shared = sorted({o for p in paths for o in owners[p] if o != name})
        models.append(
            ModelStorage(
                worker=recipe.modality if recipe is not None else "",
                model=name,
                paths=paths,
                on_disk=bool(paths) and len(existing) == len(paths),
                size_bytes=sum(sizes[p] for p in existing),
                shared_with=shared,
            )
        )

    disks: dict[Path, dict] = {}
    for p, size in sizes.items():
        if not p.exists():
            continue
        mount = _mount_point(p)
        if mount not in disks:
            st = os.statvfs(mount)
            disks[mount] = {
                "mount": str(mount),
                "total_bytes": st.f_blocks * st.f_frsize,
                "free_bytes": st.f_bavail * st.f_frsize,
                "models_bytes": 0,
            }
        disks[mount]["models_bytes"] += size
    for d in disks.values():
        d["other_bytes"] = max(0, d["total_bytes"] - d["free_bytes"] - d["models_bytes"])
    return models, sorted(disks.values(), key=lambda d: d["mount"])


def delete_model(
    model: str,
    *,
    resident_keys: set[str],
    loaded: set[str] | None = None,
) -> dict:
    """Delete a recipe's weights from disk; returns what happened per path.

    Refuses residents (evicting them is scheduler policy, not a disk
    operation) and loaded recipes. Paths another recipe also uses are left
    alone and reported as skipped.
    """
    recipe = get_recipe(model)
    if recipe is None:
        raise StorageError(f"unknown recipe {model}", status=404)
    model = recipe.name
    if model in resident_keys:
        raise StorageError(
            f"{model} is a configured resident — it would reload on the "
            "next idle cycle; remove it from residents first",
            status=409,
        )
    if model in (loaded or set()):
        raise StorageError(f"{model} is currently loaded", status=409)

    resolved = resolve_model_paths()
    owners: dict[Path, list[str]] = {}
    for name, paths in resolved.items():
        for p in paths:
            owners.setdefault(p, []).append(name)

    deleted, skipped_shared, missing = [], [], []
    freed = 0
    for p in resolved[model]:
        if others := [o for o in owners[p] if o != model]:
            skipped_shared.append({"path": str(p), "shared_with": others})
            continue
        if not p.exists():
            missing.append(str(p))
            continue
        size = _path_size(p)
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as e:
            # A hardened service mounts the model store read-only (the systemd
            # unit's ProtectSystem=strict); weights are the operator's to
            # delete, and a 500 would read like a giq bug.
            raise StorageError(
                f"cannot delete {p}: {e.strerror or e}. The model store is read-only "
                "for the service; delete the files as the operator"
                + (f" (already deleted: {', '.join(deleted)})" if deleted else ""),
                status=409,
            ) from e
        freed += size
        deleted.append(str(p))
    return {
        "model": model,
        "deleted": deleted,
        "skipped_shared": skipped_shared,
        "missing": missing,
        "freed_bytes": freed,
    }
