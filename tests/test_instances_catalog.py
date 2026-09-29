# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""The built-in instance files reproduce the catalog they replaced.

`_catalog_baseline` is the registry and the per-model llm tables exactly as
the hand-written code defined them. Every ModelSpec field and every table
entry — including which models are *absent* from a table, since absence
means "take the default" — must come out of the YAML unchanged.
"""

from dataclasses import asdict

import pytest

from giq import instances
from giq.registry import spec_of
from giq.workers import llm
from tests._catalog_baseline import BUILTIN_SPECS, LLM_DEFAULTS, LLM_TABLES


def _builtin_instances():
    return [inst for inst, _ in instances.builtin().values()]


def _builtin_specs() -> dict[tuple[str, str], dict]:
    return {(s.worker, s.model): asdict(s) for s in map(spec_of, _builtin_instances())}


def test_every_builtin_file_is_valid():
    """A broken built-in raises here rather than at a customer's startup."""
    assert instances.builtin()


def test_the_same_models_exist():
    assert set(_builtin_specs()) == {(d["worker"], d["model"]) for d in BUILTIN_SPECS}


@pytest.mark.parametrize("expected", BUILTIN_SPECS, ids=lambda d: f"{d['worker']}/{d['model']}")
def test_every_spec_field_is_reproduced(expected):
    actual = _builtin_specs()[(expected["worker"], expected["model"])]
    assert actual == expected


@pytest.mark.parametrize("table", sorted(LLM_TABLES))
def test_every_llm_table_is_reproduced(table):
    assert llm.tables_of(_builtin_instances())[table] == LLM_TABLES[table]


@pytest.mark.parametrize("name", sorted(LLM_DEFAULTS))
def test_the_engine_defaults_did_not_move(name):
    """The tables are sparse over these; a changed default would change every
    model that does not set the parameter, without touching a single file."""
    assert getattr(llm, name) == LLM_DEFAULTS[name]


# --- operator instances reach the consumers -----------------------------------


@pytest.fixture
def operator_dir(tmp_path, monkeypatch):
    """An operator instances directory, with the catalog rebuilt around it."""
    from giq.registry import reload_registry

    monkeypatch.setenv("GIQ_INSTANCES_DIR", str(tmp_path))
    yield tmp_path
    monkeypatch.undo()
    reload_registry()


def test_an_operator_instance_is_served_like_a_builtin(operator_dir):
    from giq.registry import get_spec, reload_registry
    from giq.workers.llm import LLMWorker, LLMWorkerConfig

    (operator_dir / "private.yaml").write_text(
        "name: private-ft\nworker: llm\nengine: llama.cpp\n"
        "weights: {path: /srv/models/private-ft.gguf}\n"
        "params: {ctx_size: 32768, reasoning: 'on'}\n"
        "vram: {gb: 12.0}\n"
    )
    reload_registry()

    assert get_spec("llm", "private-ft").vram_gb == 12.0
    cmd = LLMWorker(LLMWorkerConfig(model="private-ft")).build_command()
    assert cmd[cmd.index("-m") + 1] == "/srv/models/private-ft.gguf"
    assert cmd[cmd.index("-c") + 1] == "32768"


def test_an_operator_override_replaces_the_builtin_everywhere(operator_dir):
    """Parameters the override leaves out fall back to the engine defaults —
    they are not inherited from the built-in it replaces."""
    from giq.registry import get_spec, reload_registry

    (operator_dir / "gemma.yaml").write_text(
        "name: gemma-4-12b\nworker: llm\nengine: llama.cpp\n"
        "weights: {path: elsewhere/gemma.gguf}\nvram: {gb: 7.5, measured: true}\n"
    )
    reload_registry()

    assert get_spec("llm", "gemma-4-12b").vram_gb == 7.5
    assert get_spec("llm", "gemma-4-12b").resident_priority is None
    assert llm.MODEL_PATHS["gemma-4-12b"] == "elsewhere/gemma.gguf"
    assert "gemma-4-12b" not in llm.MODEL_PARALLEL
    assert "gemma-4-12b" not in llm.MODEL_CTX_SIZE


def test_the_tables_return_to_the_builtins_when_the_override_goes(operator_dir):
    from giq.registry import reload_registry

    path = operator_dir / "gemma.yaml"
    path.write_text(
        "name: gemma-4-12b\nworker: llm\nengine: llama.cpp\n"
        "weights: {path: elsewhere/gemma.gguf}\nvram: {gb: 7.5}\n"
    )
    reload_registry()
    path.unlink()
    reload_registry()

    for table, expected in LLM_TABLES.items():
        assert getattr(llm, table) == expected


def test_a_broken_operator_file_leaves_the_catalog_serving(operator_dir):
    from giq.registry import get_spec, reload_registry

    (operator_dir / "gemma.yaml").write_text("name: gemma-4-12b\nworker: llm\nctx: 1\n")
    reload_registry()

    assert get_spec("llm", "gemma-4-12b").vram_gb == 9.5
    assert llm.MODEL_PARALLEL["gemma-4-12b"] == 4


async def test_storage_reports_the_operator_files_and_what_was_left_out(operator_dir, monkeypatch):
    """A broken file is logged and left out; /storage is where the dashboard
    learns of it, so an operator does not have to read the journal."""
    from httpx import ASGITransport, AsyncClient

    from giq.api import stats_api
    from giq.main import app
    from giq.registry import reload_registry

    (operator_dir / "gemma.yaml").write_text(
        "name: gemma-4-12b\nworker: llm\nengine: llama.cpp\n"
        "weights: {path: elsewhere/gemma.gguf}\nvram: {gb: 7.5}\n"
    )
    (operator_dir / "private.yaml").write_text(
        "name: private-ft\nworker: llm\nengine: llama.cpp\n"
        "weights: {path: private.gguf}\nvram: {gb: 12.0}\n"
    )
    (operator_dir / "broken.yaml").write_text("name: broken\nworker: llm\nctx: 1\n")
    reload_registry()
    monkeypatch.setattr(stats_api, "storage_report", lambda: ([], []))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        block = (await c.get("/storage")).json()["instances"]

    assert block["dir"] == str(operator_dir)
    assert [(f["name"], f["replaces_builtin"]) for f in block["files"]] == [
        ("gemma-4-12b", True),
        ("private-ft", False),
    ]
    assert block["overrides"] == ["llm/gemma-4-12b"]
    (error,) = block["errors"]
    assert error["file"] == str(operator_dir / "broken.yaml")
    assert "ctx" in error["message"] and str(operator_dir) not in error["message"]
