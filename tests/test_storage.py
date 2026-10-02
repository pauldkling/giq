# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Storage accounting and model deletion."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from giq import storage
from giq.storage import StorageError, delete_model, resolve_model_paths, storage_report
from giq.weights import Location


@pytest.fixture
def fake_layout(tmp_path, monkeypatch):
    """Two GGUFs, an image model sharing its encoder with another, HF cache."""
    gguf_a = tmp_path / "ggufs" / "model-a.gguf"
    gguf_a.parent.mkdir()
    gguf_a.write_bytes(b"a" * 1000)
    gguf_b = tmp_path / "ggufs" / "model-b.gguf"
    gguf_b.write_bytes(b"b" * 2000)

    shared_enc = tmp_path / "enc.safetensors"
    shared_enc.write_bytes(b"e" * 500)
    diff1 = tmp_path / "diff1.safetensors"
    diff1.write_bytes(b"d" * 300)
    diff2 = tmp_path / "diff2.safetensors"
    diff2.write_bytes(b"d" * 400)
    vae = tmp_path / "vae.safetensors"
    vae.write_bytes(b"v" * 100)

    hub = tmp_path / "hub"
    whisper = hub / "models--Systran--faster-whisper-large-v3"
    (whisper / "snapshots").mkdir(parents=True)
    (whisper / "snapshots" / "w.bin").write_bytes(b"w" * 700)
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(hub))

    # A vllm checkpoint is a directory, served by two recipes; its own
    # safetensors shards are not a GGUF shard set.
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "config.json").write_bytes(b"{}")
    (ckpt / "model-00001-of-00002.safetensors").write_bytes(b"s" * 3000)
    (ckpt / "model-00002-of-00002.safetensors").write_bytes(b"s" * 1000)
    # A GGUF split in two: the recipe names the first shard.
    for i in (1, 2):
        (tmp_path / "ggufs" / f"big-0000{i}-of-00002.gguf").write_bytes(b"g" * 600)

    llm_paths = {
        "model-a": gguf_a,
        "model-b": gguf_b,
        "model-big": tmp_path / "ggufs" / "big-00001-of-00002.gguf",
        "model-vllm": ckpt,
        "model-vllm-chat": ckpt,
    }
    image_parts = {
        name: [
            Location("diffusion", path=str(diffusion)),
            Location("text_encoder", path=str(shared_enc)),
            Location("vae", path=str(vae)),
        ]
        for name, diffusion in (("img1", diff1), ("img2", diff2))
    }
    real_locations = storage.locations

    def locations(name):
        if name in llm_paths:
            return [Location(None, path=str(llm_paths[name]))]
        if name in image_parts:
            return image_parts[name]
        if name in ("large-v3", "whisper-large-v3"):
            return real_locations(name)
        return []

    monkeypatch.setattr(storage, "locations", locations)
    # Storage reads a recipe's name and first modality; nothing else.
    catalog = {
        name: SimpleNamespace(name=name, modality=modality)
        for name, modality in [
            ("model-a", "llm"),
            ("model-b", "llm"),
            ("model-missing", "llm"),
            ("model-big", "llm"),
            ("model-vllm", "llm"),
            ("model-vllm-chat", "llm"),
            ("img1", "text2image"),
            ("img2", "text2image"),
            ("large-v3", "stt"),
            ("whisper-large-v3", "audio"),
        ]
    }
    monkeypatch.setattr(storage, "all_recipes", lambda: list(catalog.values()))
    monkeypatch.setattr(storage, "get_recipe", catalog.get)
    return tmp_path


def test_resolution_and_sizes(fake_layout):
    models, disks = storage_report()
    by_key = {m.model: m for m in models}
    assert by_key["model-a"].size_bytes == 1000
    assert by_key["model-a"].on_disk
    # img1 = diffusion 300 + shared enc 500 + vae 100
    assert by_key["img1"].size_bytes == 900
    assert not by_key["model-missing"].on_disk
    # HF-cache dir sized recursively
    assert by_key["large-v3"].size_bytes == 700
    # disk totals count the shared encoder and vae once
    assert len(disks) == 1
    expected = 1000 + 2000 + 500 + 300 + 400 + 100 + 700 + 1200 + 4002
    assert disks[0]["models_bytes"] == expected
    assert disks[0]["other_bytes"] >= 0


def test_llm_weights_of_every_format_are_found(fake_layout):
    """An LLM's weights are whatever its recipe names: a GGUF (every shard
    of a split one) for llama.cpp, a checkpoint directory for vllm."""
    models, _ = storage_report()
    by_key = {m.model: m for m in models}
    assert by_key["model-big"].size_bytes == 1200
    vllm = by_key["model-vllm"]
    assert vllm.on_disk and vllm.size_bytes == 4002
    assert vllm.shared_with == ["model-vllm-chat"]
    assert resolve_model_paths()["model-vllm"] == [(fake_layout / "ckpt").resolve()]


def test_shared_detection(fake_layout):
    models, _ = storage_report()
    by_key = {m.model: m for m in models}
    assert by_key["img1"].shared_with == ["img2"]
    # stt large-v3 snapshot doubles as the audio resident's whisper
    assert by_key["large-v3"].shared_with == ["whisper-large-v3"]
    assert by_key["model-a"].shared_with == []


def test_delete_plain_model(fake_layout):
    gguf = fake_layout / "ggufs" / "model-a.gguf"
    result = delete_model("model-a", resident_keys=set())
    assert not gguf.exists()
    assert result["freed_bytes"] == 1000
    assert result["deleted"] == [str(gguf)]


def test_delete_on_a_read_only_store_is_a_refusal(fake_layout, monkeypatch):
    def refuse(self):
        raise PermissionError(30, "Read-only file system")

    monkeypatch.setattr(Path, "unlink", refuse)
    with pytest.raises(StorageError) as exc:
        delete_model("model-a", resident_keys=set())
    assert exc.value.status == 409
    assert "read-only" in str(exc.value)
    assert (fake_layout / "ggufs" / "model-a.gguf").exists()


def test_delete_skips_shared_files(fake_layout):
    result = delete_model("img1", resident_keys=set())
    assert not (fake_layout / "diff1.safetensors").exists()
    # shared encoder and vae survive for img2
    assert (fake_layout / "enc.safetensors").exists()
    assert (fake_layout / "vae.safetensors").exists()
    assert result["freed_bytes"] == 300
    assert len(result["skipped_shared"]) == 2


def test_delete_refuses_resident(fake_layout):
    with pytest.raises(StorageError) as e:
        delete_model("model-a", resident_keys={"model-a"})
    assert e.value.status == 409


def test_delete_refuses_loaded(fake_layout):
    with pytest.raises(StorageError) as e:
        delete_model("model-a", resident_keys=set(), loaded={"model-a"})
    assert e.value.status == 409


def test_delete_unknown_model(fake_layout):
    with pytest.raises(StorageError) as e:
        delete_model("nope", resident_keys=set())
    assert e.value.status == 404


def test_delete_hf_dir(fake_layout):
    hub = fake_layout / "hub"
    result = delete_model("whisper-large-v3", resident_keys=set())
    # whisper snapshot shared with stt/large-v3 → skipped; pyannote dir absent
    assert (hub / "models--Systran--faster-whisper-large-v3").exists()
    assert result["deleted"] == []
    assert len(result["skipped_shared"]) == 1
    assert len(result["missing"]) == 1


def test_gguf_shard_expansion(tmp_path):
    shard1 = tmp_path / "big-00001-of-00002.gguf"
    shard2 = tmp_path / "big-00002-of-00002.gguf"
    shard1.write_bytes(b"x")
    shard2.write_bytes(b"y")
    assert storage._expand_gguf(shard1) == [shard1, shard2]


def _only(monkeypatch, name: str) -> None:
    """The real recipe ``name``, alone in the catalog storage reads."""
    from giq.registry import get_recipe

    recipe = get_recipe(name)
    assert recipe is not None
    monkeypatch.setattr(storage, "all_recipes", lambda: [recipe])


def test_real_registry_resolves():
    """Against the real config: every registered model resolves without raising."""
    from giq.registry import all_recipes

    resolved = resolve_model_paths()
    assert set(resolved) == {r.name for r in all_recipes()}


def test_ocr_snapshot_resolves_by_directory(tmp_path, monkeypatch):
    """The OCR model is a local snapshot loaded by path, not an HF-cache repo:
    the catalog must find it where GIQ_OCR_MODEL_DIR says, or the dashboard
    reports a working model as absent."""
    snap = tmp_path / "baidu-Unlimited-OCR"
    snap.mkdir()
    (snap / "model.safetensors").write_bytes(b"o" * 1234)
    monkeypatch.setenv("GIQ_OCR_MODEL_DIR", str(snap))
    _only(monkeypatch, "unlimited-ocr")
    (model,), _ = storage_report()
    assert model.on_disk and model.size_bytes == 1234 and model.paths == [snap.resolve()]

    monkeypatch.setenv("GIQ_OCR_MODEL_DIR", str(tmp_path / "missing"))
    (model,), _ = storage_report()
    assert not model.on_disk


def test_glm_ocr_needs_both_of_its_directories(tmp_path, monkeypatch):
    glm = tmp_path / "glm"
    layout = tmp_path / "layout"
    glm.mkdir()
    (glm / "model.safetensors").write_bytes(b"g" * 100)
    monkeypatch.setenv("GIQ_GLM_OCR_MODEL_DIR", str(glm))
    monkeypatch.setenv("GIQ_GLM_LAYOUT_DIR", str(layout))
    _only(monkeypatch, "glm-ocr")
    (model,), _ = storage_report()
    # The recognizer alone is not the model: without the layout stage it is not on disk.
    assert not model.on_disk and len(model.paths) == 2
    layout.mkdir()
    (layout / "model.safetensors").write_bytes(b"l" * 50)
    (model,), _ = storage_report()
    assert model.on_disk and model.size_bytes == 150


def test_depth_snapshot_resolves_by_directory(tmp_path, monkeypatch):
    """Depth models are local snapshots under one root, loaded by path."""
    root = tmp_path / "models"
    snap = root / "depth-anything-Depth-Anything-V2-Small-hf"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"d" * 99)
    monkeypatch.setenv("GIQ_DEPTH_MODELS_DIR", str(root))
    _only(monkeypatch, "depth-anything-v2-small")
    (model,), _ = storage_report()
    assert model.on_disk and model.size_bytes == 99 and model.paths == [snap.resolve()]


def test_multiview_snapshot_resolves_by_directory(tmp_path, monkeypatch):
    root = tmp_path / "models"
    snap = root / "depth-anything-DA3-BASE"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"m" * 42)
    monkeypatch.setenv("GIQ_MULTIVIEW_MODELS_DIR", str(root))
    _only(monkeypatch, "da3-base")
    (model,), _ = storage_report()
    assert model.on_disk and model.size_bytes == 42 and model.paths == [snap.resolve()]
