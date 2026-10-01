# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Recipe files: the schema, the loader and the operator override rules.

The failure these guard against is a setting that is written down and then
not applied — a typo'd key taking a default, a second file silently winning,
a broken operator file taking the whole catalog down with it.
"""

import logging
from pathlib import Path

import pytest

from giq import recipes
from giq.recipes import RecipeError, load, load_file
from giq.recipes.schema import LlamaCppParams, Recipe

LLM = """\
name: {name}
worker: llm
engine: llama.cpp
weights:
  path: some-GGUF/model-Q4_K_M.gguf
vram:
  gb: 9.5
  measured: true
"""


def _write(directory: Path, filename: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(text)
    return path


@pytest.fixture
def builtin_dir(tmp_path, monkeypatch):
    """A stand-in for the shipped recipes, so override rules can be tested."""
    directory = tmp_path / "builtin"
    directory.mkdir()
    monkeypatch.setattr(recipes, "BUILTIN_DIR", directory)
    recipes.builtin.cache_clear()
    yield directory
    recipes.builtin.cache_clear()


@pytest.fixture
def operator_dir(tmp_path):
    directory = tmp_path / "operator"
    directory.mkdir()
    return directory


# --- the schema ---------------------------------------------------------------


def test_a_minimal_instance_loads(tmp_path):
    recipe = load_file(_write(tmp_path, "a.yaml", LLM.format(name="m")))
    assert recipe.key == ("llm", "m")
    assert isinstance(recipe.params, LlamaCppParams)
    assert recipe.params.given() == {}, "nothing set means every engine default applies"


def test_only_the_parameters_written_count_as_given(tmp_path):
    text = LLM.format(name="m") + "params:\n  ctx_size: 131072\n  parallel: 4\n"
    recipe = load_file(_write(tmp_path, "a.yaml", text))
    assert recipe.params.given() == {"ctx_size": 131072, "parallel": 4}


@pytest.mark.parametrize(
    "extra, complaint",
    [
        ("colour: red\n", "colour"),
        ("params:\n  ctx_sise: 8192\n", "ctx_sise"),
        ("vram:\n  gb: 1.0\n", "duplicate key"),
        ("params:\n  cache_type_k: q8_0\n  cache_type_v: q4_0\n", "must match"),
        ("params:\n  cache_type_k: q8_0\n", "set together"),
        ("params:\n  cache_type_k: q7\n  cache_type_v: q7\n", "cache_type_k"),
        ("params:\n  spec_type: --model-draft\n", "spec_type"),
        ("capabilities: [vision]\n", "mmproj"),
        ("params:\n  mmproj: proj.gguf\n", "vision"),
        ("profile: interactive\n", "profile"),
        ("residency:\n  gpu: '1'\n", "gpu.bind"),
        ("residency:\n  default_policy: pinned\n", "disagrees"),
        ("residency:\n  default_policy: 'off'\n", "not supported"),
        ("aliases: [m]\n", "repeats"),
        ("lane_width: 0\n", "lane_width"),
    ],
)
def test_what_is_not_understood_is_refused(tmp_path, extra, complaint):
    """Unknown keys, conflicting parameters and not-yet-honoured settings are
    all errors — never a value quietly dropped."""
    with pytest.raises(RecipeError, match=complaint):
        load_file(_write(tmp_path, "a.yaml", LLM.format(name="m") + extra))


@pytest.mark.parametrize(
    "text, complaint",
    [
        ("name: m\nworker: painter\nengine: sd.cpp\nvram: {gb: 1}\n", "unknown worker"),
        ("name: m\nworker: tts\nengine: tensorrt-llm\nvram: {gb: 1}\n", "unknown engine"),
        ("name: m\nworker: tts\nengine: llama.cpp\nvram: {gb: 1}\n", "cannot serve"),
        ("name: m\nworker: llm\nengine: llama.cpp\nvram: {gb: 1}\n", "weights.path"),
        ("name: ../m\nworker: stt\nengine: faster-whisper\nvram: {gb: 1}\n", "name"),
        ("name: m\nworker: stt\nengine: faster-whisper\nvram: {gb: 0}\n", "vram.gb"),
        ("name: m\nworker: stt\nengine: faster-whisper\n", "vram"),
        ("name: m\nworker: stt\nengine: faster-whisper\nvram: {gb: 1}\nparams: {x: 1}\n", "x"),
        ("- not a mapping\n", "mapping"),
    ],
)
def test_invalid_files_are_refused(tmp_path, text, complaint):
    with pytest.raises(RecipeError, match=complaint):
        load_file(_write(tmp_path, "a.yaml", text))


def test_the_policy_may_be_spelled_out_when_it_agrees(tmp_path):
    text = LLM.format(name="m") + "residency:\n  priority: 0\n  default_policy: pinned\n"
    assert load_file(_write(tmp_path, "a.yaml", text)).residency.priority == 0


def test_an_instance_cannot_be_changed_once_loaded(tmp_path):
    recipe = load_file(_write(tmp_path, "a.yaml", LLM.format(name="m")))
    with pytest.raises(Exception, match="frozen"):
        recipe.name = "other"  # ty: ignore[invalid-assignment]


# --- the loader and the override rules ----------------------------------------


def test_builtins_must_be_named_after_what_they_define(builtin_dir):
    _write(builtin_dir, "llm.other.yaml", LLM.format(name="m"))
    with pytest.raises(RecipeError, match="<worker>.<name>.yaml"):
        recipes.builtin()


def test_a_broken_builtin_raises(builtin_dir):
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m") + "colour: red\n")
    with pytest.raises(RecipeError):
        recipes.builtin()


def test_builtin_aliases_may_not_shadow_another_instance(builtin_dir):
    _write(builtin_dir, "llm.a.yaml", LLM.format(name="a") + "aliases: [b]\n")
    _write(builtin_dir, "llm.b.yaml", LLM.format(name="b"))
    with pytest.raises(RecipeError, match="names both"):
        recipes.builtin()


def test_one_name_may_serve_two_workers(builtin_dir, operator_dir):
    """flux_klein is both a text2image and an image_edit model."""
    for worker in ("text2image", "image_edit"):
        _write(
            builtin_dir,
            f"{worker}.klein.yaml",
            f"name: klein\nworker: {worker}\nengine: sd.cpp\nvram: {{gb: 8}}\n",
        )
    assert set(load(operator_dir).recipes) == {("text2image", "klein"), ("image_edit", "klein")}


def test_no_operator_directory_means_the_builtins(builtin_dir, tmp_path):
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    snap = load(tmp_path / "does-not-exist")
    assert list(snap.recipes) == [("llm", "m")]
    assert snap.errors == ()


def test_an_operator_file_adds_an_instance(builtin_dir, operator_dir):
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    path = _write(operator_dir, "private.yaml", LLM.format(name="private-finetune"))
    snap = load(operator_dir)
    assert snap.get("llm", "private-finetune") is not None
    assert snap.sources[("llm", "private-finetune")] == path


def test_an_operator_file_replaces_the_builtin_of_its_name(builtin_dir, operator_dir, caplog):
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    path = _write(operator_dir, "m.yml", LLM.format(name="m").replace("9.5", "11.0"))
    with caplog.at_level(logging.INFO, logger="giq.recipes"):
        snap = load(operator_dir)
    assert snap.recipes[("llm", "m")].vram.gb == 11.0
    assert snap.sources[("llm", "m")] == path
    messages = [r.message for r in caplog.records]
    assert any("replaces the built-in" in m and str(path) in m for m in messages)


def test_a_broken_operator_file_falls_back_to_the_builtin(builtin_dir, operator_dir, caplog):
    """An operator typo must not take the service down, nor the model with it."""
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    _write(operator_dir, "m.yaml", LLM.format(name="m") + "ctx_size: 8192\n")
    with caplog.at_level(logging.ERROR, logger="giq.recipes"):
        snap = load(operator_dir)
    assert snap.recipes[("llm", "m")].vram.gb == 9.5
    assert len(snap.errors) == 1 and "ctx_size" in snap.errors[0]
    assert any("m.yaml" in r.message for r in caplog.records if r.levelno == logging.ERROR)


def test_two_operator_files_with_one_name_are_both_refused(builtin_dir, operator_dir):
    """Which would win is an accident of sorting, so neither does."""
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    _write(operator_dir, "a.yaml", LLM.format(name="m").replace("9.5", "1.0"))
    _write(operator_dir, "b.yaml", LLM.format(name="m").replace("9.5", "2.0"))
    snap = load(operator_dir)
    assert snap.recipes[("llm", "m")].vram.gb == 9.5
    assert "more than once" in snap.errors[0]


def test_an_operator_alias_may_not_capture_a_builtin_name(builtin_dir, operator_dir):
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    _write(operator_dir, "x.yaml", LLM.format(name="x") + "aliases: [m]\n")
    snap = load(operator_dir)
    assert snap.get("llm", "x") is None
    assert "names both" in snap.errors[0]


def test_other_files_in_the_operator_directory_are_not_read(builtin_dir, operator_dir):
    _write(operator_dir, "README.md", "not a recipe")
    _write(operator_dir, "m.yaml.bak", "colour: red\n")
    assert load(operator_dir).errors == ()


def test_the_snapshot_cannot_be_edited(builtin_dir, operator_dir):
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    snap = load(operator_dir)
    with pytest.raises(TypeError):
        snap.recipes[("llm", "n")] = snap.get("llm", "m")  # ty: ignore[invalid-assignment]


def test_reload_swaps_the_snapshot_and_tells_subscribers(builtin_dir, operator_dir, monkeypatch):
    monkeypatch.setattr(recipes, "_current", None)
    monkeypatch.setattr(recipes, "_subscribers", [])
    monkeypatch.setenv("GIQ_RECIPES_DIR", str(operator_dir))
    _write(builtin_dir, "llm.m.yaml", LLM.format(name="m"))
    seen: list[set] = []
    recipes.subscribe(lambda snap: seen.append(set(snap.recipes)))

    _write(operator_dir, "n.yaml", LLM.format(name="n"))
    recipes.reload()

    assert seen == [{("llm", "m")}, {("llm", "m"), ("llm", "n")}]
    assert recipes.current().get("llm", "n") is not None


def test_a_validated_instance_round_trips(tmp_path):
    text = LLM.format(name="m") + "params: {ctx_size: 8192}\n"
    recipe = load_file(_write(tmp_path, "a.yaml", text))
    again = Recipe.model_validate(recipe.model_dump(exclude_unset=True))
    assert again == recipe
