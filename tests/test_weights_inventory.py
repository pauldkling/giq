# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Weights are a thing of their own (ADR-003): one checkpoint, however many
recipes use it — listed once, sized once, deleted once."""

import pytest

from giq import recipes, storage
from giq.recipes import load_file
from giq.registry import reload_registry
from giq.storage import StorageError, delete_weights, weights_report
from giq.weights import inventory, provenance_conflicts


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Operator recipes over files in a temporary models directory."""
    models = tmp_path / "models"
    (models / "shared").mkdir(parents=True)
    (models / "shared" / "model.gguf").write_bytes(b"w" * 1000)
    (models / "solo.gguf").write_bytes(b"s" * 300)
    operator = tmp_path / "recipes"
    operator.mkdir()
    for name, path in (("a", "shared/model.gguf"), ("b", "shared/model.gguf"), ("c", "solo.gguf")):
        (operator / f"{name}.yaml").write_text(
            f"name: {name}\nmodalities: [llm]\nengine: llama.cpp\n"
            f"weights: {{path: {path}, licence: mit}}\nvram: {{gb: 1.0}}\n"
        )
    monkeypatch.setenv("GIQ_MODELS_DIR", str(models))
    monkeypatch.setenv("GIQ_RECIPES_DIR", str(operator))
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    reload_registry()
    yield models
    monkeypatch.undo()
    reload_registry()


def _by_recipe(report: list[dict], name: str) -> dict:
    return next(w for w in report if name in w["recipes"])


# --- the built-ins --------------------------------------------------------------


def test_a_checkpoint_two_recipes_load_is_one_item():
    """The stt recipe and the audio stack's ASR part load one faster-whisper
    snapshot; the two NVFP4 recipes one checkpoint directory."""
    items = {i.repo or i.path: i for i in inventory()}
    whisper = items["Systran/faster-whisper-large-v3"]
    assert whisper.used_by == ("faster-whisper-large-v3", "whisper-large-v3:asr")
    nvfp4 = next(i for i in items.values() if i.path and i.path.endswith("Qwen3.8-27B-NVFP4"))
    assert nvfp4.recipes == ("qwen3.8-27b-nvfp4", "qwen3.8-27b-nvfp4-chat")


def test_a_part_is_under_the_recipes_licence_unless_it_names_its_own():
    flux = [i for i in inventory() if any(u.startswith("flux_klein:") for u in i.used_by)]
    assert len(flux) == 3
    assert {i.licence for i in flux} == {"apache-2.0"}


def test_ids_are_stable_and_url_safe():
    first = {i.id for i in inventory()}
    assert first == {i.id for i in inventory()}
    assert all(i.isalnum() and len(i) == 12 for i in first)


# --- provenance -------------------------------------------------------------------


def _recipe(tmp_path, name: str, path: str, licence: str):
    file = tmp_path / f"{name}.yaml"
    file.write_text(
        f"name: {name}\nmodalities: [llm]\nengine: llama.cpp\n"
        f"weights: {{path: {path}, licence: {licence}}}\nvram: {{gb: 1.0}}\n"
    )
    return load_file(file)


def test_two_recipes_may_not_disagree_on_what_one_checkpoint_is(tmp_path):
    a = _recipe(tmp_path, "a", "/w/model.gguf", "mit")
    b = _recipe(tmp_path, "b", "/w/model.gguf", "cc-by-nc-4.0")
    (problem,) = provenance_conflicts([a, b])
    assert "disagree on licence" in problem and "mit" in problem
    assert provenance_conflicts([a, _recipe(tmp_path, "c", "/w/model.gguf", "mit")]) == []


def test_an_operator_file_that_contradicts_a_builtin_is_left_out(tmp_path):
    """The built-in's word stands; the operator learns why their file did nothing."""
    builtin = next(r for r, _ in recipes.builtin().values() if r.name == "qwen3.8-27b-nvfp4")
    (tmp_path / "mine.yaml").write_text(
        "name: mine\nmodalities: [llm]\nengine: llama.cpp\n"
        f"weights: {{path: {builtin.weights.path}, licence: proprietary}}\nvram: {{gb: 1.0}}\n"
    )
    snap = recipes.load(tmp_path)
    assert snap.get("mine") is None
    assert "disagree on licence" in snap.errors[0]


# --- disk -------------------------------------------------------------------------


def test_the_report_counts_a_shared_checkpoint_once(store):
    report = weights_report()
    shared = _by_recipe(report, "a")
    assert shared["recipes"] == ["a", "b"]
    assert shared["on_disk"] and shared["size_bytes"] == 1000
    assert shared["licence"] == "mit"
    assert sum(1 for w in report if "a" in w["recipes"]) == 1


def test_deleting_weights_removes_the_files_and_keeps_the_recipes(store):
    shared = _by_recipe(weights_report(), "a")
    result = delete_weights(shared["id"], busy=set())
    assert result["freed_bytes"] == 1000 and result["recipes"] == ["a", "b"]
    assert not (store / "shared" / "model.gguf").exists()
    after = _by_recipe(weights_report(), "a")
    assert not after["on_disk"], "the recipes stay, uninstalled"


def test_weights_a_busy_recipe_uses_are_not_deleted(store):
    shared = _by_recipe(weights_report(), "a")
    with pytest.raises(StorageError) as exc:
        delete_weights(shared["id"], busy={"b"})
    assert exc.value.status == 409 and "b uses these weights" in str(exc.value)
    assert (store / "shared" / "model.gguf").exists()


def test_unknown_weights_are_404(store):
    with pytest.raises(StorageError) as exc:
        delete_weights("000000000000", busy=set())
    assert exc.value.status == 404


async def test_the_routes(store, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from giq.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        listed = (await c.get("/weights")).json()["weights"]
        solo = _by_recipe(listed, "c")
        r = await c.delete(f"/weights/{solo['id']}")
    assert r.status_code == 200 and r.json()["freed_bytes"] == 300
    assert not (store / "solo.gguf").exists()
    assert storage.hf_cache_dir() is not None
