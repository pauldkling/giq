# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""GIQ_HOME and path resolution: env > config.yaml `paths:` > GIQ_HOME > legacy."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from giq import config as giq_config
from giq import engines, paths
from giq.cli import init_home, main, template_text
from giq.gpus import device_env
from giq.main import build_parser

_VARS = (
    "GIQ_HOME",
    "GIQ_CONFIG",
    "GIQ_MODELS_DIR",
    "GIQ_RECIPES_DIR",
    "GIQ_ENGINES_DIR",
    "GIQ_DATA_DIR",
    "GIQ_CACHE_DIR",
    "GIQ_STATS_DB",
    "GIQ_INFLIGHT_LOG",
    "GIQ_LLAMA_BINARY",
    "GIQ_SDCPP_BINARY",
    "STATE_DIRECTORY",
    "CACHE_DIRECTORY",
    "HF_HOME",
    "HUGGINGFACE_HUB_CACHE",
    "XDG_CACHE_HOME",
    "TRITON_CACHE_DIR",
    "CUDA_CACHE_PATH",
    "MPLCONFIGDIR",
    "GIQ_HOST",
    "GIQ_PORT",
    "GIQ_INSTANCES_DIR",
)


@pytest.fixture
def clean(monkeypatch, tmp_path):
    """No path variables, a working directory without config.yaml, and a
    config cache that is rebuilt on demand and forgotten afterwards."""
    for var in _VARS:
        # Set first so monkeypatch records the variable and restores it —
        # absent included — even when the code under test exports it.
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(giq_config, "_config", None)
    monkeypatch.setattr(engines, "_engines", None)
    monkeypatch.setattr(engines, "_versions", {})
    # device_env asks nvidia-smi which card a name means; no card is needed
    # to test what it adds to the environment.
    monkeypatch.setattr("giq.gpus.resolve_device", lambda device: None)
    monkeypatch.setattr("giq.gpus.selected_device", lambda: None)
    return monkeypatch


def _config(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "cfg" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(body)
    return cfg


def _reload():
    giq_config._config = None


# --- legacy: without GIQ_HOME nothing moves ------------------------------------


def test_legacy_defaults_without_home(clean):
    assert paths.home() is None
    assert paths.config_file() == Path("config.yaml")
    assert paths.models_dir() == Path("~/models").expanduser()
    assert paths.recipes_dir() == Path("~/.config/giq/recipes").expanduser()
    assert paths.engines_dir() is None
    assert paths.state_dir() == paths.repo_root() / "data"
    assert paths.stats_db() == paths.repo_root() / "data" / "stats.db"
    assert paths.inflight_log() == paths.repo_root() / "data" / "inflight.log"
    assert paths.cache_dir() is None
    assert paths.hf_home() == Path("~/.cache/huggingface").expanduser()
    assert paths.cache_env() == {}


def test_legacy_child_env_is_untouched(clean):
    env = device_env("no-such-card")
    assert env == dict(os.environ)


# --- ADR-003: instance files became recipes; old setups keep their files --------


def test_the_old_variable_still_finds_the_recipes(clean, tmp_path):
    clean.setenv("GIQ_INSTANCES_DIR", str(tmp_path / "old"))
    assert paths.recipes_dir() == tmp_path / "old"
    clean.setenv("GIQ_RECIPES_DIR", str(tmp_path / "new"))
    assert paths.recipes_dir() == tmp_path / "new"


def test_an_old_directory_is_used_until_the_new_one_has_recipes(clean, tmp_path):
    old = tmp_path / ".config" / "giq" / "instances"
    old.mkdir(parents=True)
    (old / "mine.yaml").write_text("name: mine\n")
    clean.setenv("HOME", str(tmp_path))
    assert paths.recipes_dir() == old
    # An empty new directory does not hide the operator's files.
    new = tmp_path / ".config" / "giq" / "recipes"
    new.mkdir()
    assert paths.recipes_dir() == old
    (new / "mine.yaml").write_text("name: mine\n")
    assert paths.recipes_dir() == new


def test_init_moves_the_old_directory_so_the_unit_can_start(clean, tmp_path):
    home = tmp_path / "home"
    (home / "instances").mkdir(parents=True)
    (home / "instances" / "mine.yaml").write_text("name: mine\n")
    init_home(home)
    assert (home / "recipes" / "mine.yaml").is_file()
    assert not (home / "instances").exists()
    assert paths.recipes_dir() == home / "recipes"


def test_the_old_config_key_still_finds_the_recipes(clean, tmp_path):
    cfg = _config(tmp_path, "paths:\n  instances: /srv/giq/instances\n")
    clean.setenv("GIQ_CONFIG", str(cfg))
    _reload()
    assert paths.recipes_dir() == Path("/srv/giq/instances")


# --- the GIQ_HOME layout ----------------------------------------------------------


def test_home_layout(clean, tmp_path):
    home = tmp_path / "home"
    clean.setenv("GIQ_HOME", str(home))
    assert paths.config_file() == home / "config.yaml"
    assert paths.models_dir() == home / "models"
    assert paths.recipes_dir() == home / "recipes"
    assert paths.engines_dir() == home / "engines"
    assert paths.state_dir() == home / "state"
    assert paths.stats_db() == home / "state" / "stats.db"
    assert paths.inflight_log() == home / "state" / "inflight.log"
    assert paths.cache_dir() == home / "cache"
    assert paths.hf_home() == home / "cache" / "huggingface"
    assert paths.model_path("gguf/x.gguf") == str(home / "models" / "gguf" / "x.gguf")


def test_home_expands_tilde(clean):
    clean.setenv("GIQ_HOME", "~/giq-home")
    assert paths.home() == Path("~/giq-home").expanduser()


def test_config_file_env_beats_home(clean, tmp_path):
    clean.setenv("GIQ_HOME", str(tmp_path / "home"))
    clean.setenv("GIQ_CONFIG", str(tmp_path / "elsewhere.yaml"))
    assert paths.config_file() == tmp_path / "elsewhere.yaml"


# --- precedence: env > config > home > legacy -------------------------------------


@pytest.mark.parametrize(
    ("func", "env", "key"),
    [
        (paths.models_dir, "GIQ_MODELS_DIR", "models"),
        (paths.recipes_dir, "GIQ_RECIPES_DIR", "recipes"),
        (paths.engines_dir, "GIQ_ENGINES_DIR", "engines"),
        (paths.state_dir, "GIQ_DATA_DIR", "state"),
        (paths.cache_dir, "GIQ_CACHE_DIR", "cache"),
    ],
)
def test_precedence(clean, tmp_path, func, env, key):
    home = tmp_path / "home"
    clean.setenv("GIQ_HOME", str(home))
    assert func() == home / key

    cfg = _config(tmp_path, f"paths:\n  {key}: /from/config/{key}\n")
    clean.setenv("GIQ_CONFIG", str(cfg))
    _reload()
    assert func() == Path(f"/from/config/{key}")

    clean.setenv(env, str(tmp_path / "from-env"))
    assert func() == tmp_path / "from-env"


def test_config_relative_paths_follow_home(clean, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("paths:\n  models: weights\n  state: ~/giq-state\n")
    clean.setenv("GIQ_HOME", str(home))
    assert paths.models_dir() == home / "weights"
    assert paths.state_dir() == Path("~/giq-state").expanduser()


def test_config_relative_paths_without_home_follow_the_config_file(clean, tmp_path):
    cfg = _config(tmp_path, "paths:\n  models: weights\n")
    clean.setenv("GIQ_CONFIG", str(cfg))
    assert paths.models_dir() == cfg.parent / "weights"


def test_unknown_paths_keys_are_ignored(clean, tmp_path):
    cfg = _config(tmp_path, "paths:\n  modles: /typo\n  models: /m\n")
    clean.setenv("GIQ_CONFIG", str(cfg))
    assert giq_config.get_config().paths == {"models": "/m"}


def test_specific_file_vars_beat_the_state_dir(clean, tmp_path):
    clean.setenv("GIQ_HOME", str(tmp_path / "home"))
    clean.setenv("GIQ_STATS_DB", str(tmp_path / "s.db"))
    clean.setenv("GIQ_INFLIGHT_LOG", str(tmp_path / "i.log"))
    assert paths.stats_db() == tmp_path / "s.db"
    assert paths.inflight_log() == tmp_path / "i.log"


def test_systemd_directories_are_a_fallback_only(clean, tmp_path):
    clean.setenv("STATE_DIRECTORY", f"{tmp_path}/st:{tmp_path}/other")
    clean.setenv("CACHE_DIRECTORY", str(tmp_path / "ca"))
    assert paths.state_dir() == tmp_path / "st"
    assert paths.cache_dir() == tmp_path / "ca"
    clean.setenv("GIQ_HOME", str(tmp_path / "home"))
    assert paths.state_dir() == tmp_path / "home" / "state"
    assert paths.cache_dir() == tmp_path / "home" / "cache"


# --- caches handed to children ----------------------------------------------------


def test_cache_env_under_home(clean, tmp_path):
    clean.setenv("GIQ_HOME", str(tmp_path))
    env = paths.cache_env()
    assert env["HF_HOME"] == str(tmp_path / "cache" / "huggingface")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "cache")
    assert env["TRITON_CACHE_DIR"] == str(tmp_path / "cache" / "triton")
    assert env["CUDA_CACHE_PATH"] == str(tmp_path / "cache" / "nv" / "ComputeCache")


def test_operator_cache_vars_win(clean, tmp_path):
    clean.setenv("GIQ_HOME", str(tmp_path))
    clean.setenv("HF_HOME", "/operator/hf")
    clean.setenv("XDG_CACHE_HOME", "/operator/xdg")
    env = paths.cache_env()
    assert "HF_HOME" not in env and "XDG_CACHE_HOME" not in env
    assert paths.hf_home() == Path("/operator/hf")


def test_children_and_catalog_agree_on_hf_home(clean, tmp_path):
    from giq.storage import hf_cache_dir

    clean.setenv("GIQ_HOME", str(tmp_path))
    env = device_env("no-such-card")
    assert Path(env["HF_HOME"]) / "hub" == hf_cache_dir()
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "cache")


def test_subprocess_worker_spawn_env_carries_caches(clean, tmp_path):
    from giq.adapters._subprocess import SubprocessAdapter

    clean.setenv("GIQ_HOME", str(tmp_path))
    worker = SubprocessAdapter(config=None, device="no-such-card")
    env = worker._spawn_env()
    assert env["HF_HOME"] == str(tmp_path / "cache" / "huggingface")


def test_apply_cache_env_exports_once(clean, tmp_path):
    clean.setenv("GIQ_HOME", str(tmp_path))
    added = paths.apply_cache_env()
    assert os.environ["HF_HOME"] == added["HF_HOME"]
    assert paths.apply_cache_env() == {}


# --- engines ----------------------------------------------------------------------


def _fake_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_engine_found_in_home(clean, tmp_path):
    clean.setenv("GIQ_HOME", str(tmp_path))
    llama = _fake_binary(tmp_path / "engines" / "llama.cpp" / "bin" / "llama-server")
    engines.reload_engines()
    assert engines.binary_for("llama.cpp") == str(llama)


def test_engine_home_build_loses_to_config_and_env(clean, tmp_path):
    clean.setenv("GIQ_HOME", str(tmp_path))
    _fake_binary(tmp_path / "engines" / "sd.cpp" / "bin" / "sd-server")
    (tmp_path / "config.yaml").write_text("engines:\n  sd.cpp:\n    binary: /cfg/sd-server\n")
    engines.reload_engines()
    assert engines.binary_for("sd.cpp") == "/cfg/sd-server"
    clean.setenv("GIQ_SDCPP_BINARY", "/env/sd-server")
    engines.reload_engines()
    assert engines.binary_for("sd.cpp") == "/env/sd-server"


def test_engine_falls_back_to_path_without_a_home_build(clean, tmp_path):
    bindir = tmp_path / "bin"
    on_path = _fake_binary(bindir / "llama-server")
    clean.setenv("PATH", str(bindir))
    clean.setenv("GIQ_HOME", str(tmp_path / "home"))
    engines.reload_engines()
    assert engines.binary_for("llama.cpp") == str(on_path)


# --- giq init ---------------------------------------------------------------------


def test_init_creates_the_tree_and_is_idempotent(clean, tmp_path):
    home = tmp_path / "giq"
    created = init_home(home)
    for sub in ("models", "recipes", "engines", "state", "cache", "cache/huggingface"):
        assert (home / sub).is_dir()
    assert (home / "config.yaml").read_text() == template_text()
    assert f"{home / 'config.yaml'}" in created

    (home / "config.yaml").write_text("gpu:\n  device: 1\n")
    assert init_home(home) == []
    assert (home / "config.yaml").read_text() == "gpu:\n  device: 1\n"


def test_init_honours_an_existing_paths_block(clean, tmp_path):
    home = tmp_path / "giq"
    home.mkdir()
    (home / "config.yaml").write_text(f"paths:\n  models: {tmp_path / 'big-disk'}\n")
    init_home(home)
    assert (tmp_path / "big-disk").is_dir()
    assert not (home / "models").exists()


def test_init_cli_needs_a_home(clean, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["init"])
    assert exc.value.code == 2
    assert "GIQ_HOME" in capsys.readouterr().err


def test_init_cli(clean, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["init", "--home", str(tmp_path / "g")])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "created" in out and str(tmp_path / "g" / "state") in out


def test_template_is_the_checkout_config():
    assert (paths.repo_root() / "config.yaml").read_text() == template_text()


def test_template_parses_to_defaults_for_paths_and_access(clean, tmp_path):
    cfg = _config(tmp_path, template_text())
    loaded = giq_config.GiqConfig.load(cfg)
    assert loaded.paths == {}
    assert loaded.access.token == ""


# --- serve options ----------------------------------------------------------------


def test_host_and_port_from_env(clean):
    args = build_parser().parse_args([])
    assert (args.host, args.port) == ("127.0.0.1", 8084)
    clean.setenv("GIQ_HOST", "0.0.0.0")
    clean.setenv("GIQ_PORT", "9000")
    args = build_parser().parse_args([])
    assert (args.host, args.port) == ("0.0.0.0", 9000)
    args = build_parser().parse_args(["--port", "1234"])
    assert args.port == 1234


def test_serve_dispatch(clean, monkeypatch):
    seen = []
    import giq.main

    monkeypatch.setattr(giq.main, "cli", lambda argv: seen.append(argv))
    main(["serve", "--port", "1"])
    main(["--port", "2"])
    assert seen == [["--port", "1"], ["--port", "2"]]


# --- /storage reports the resolved directories -------------------------------------


async def test_storage_endpoint_reports_paths(clean, tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from giq.api import stats_api
    from giq.main import app

    monkeypatch.setattr(stats_api, "disk_report", lambda: [])
    clean.setenv("GIQ_HOME", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        body = (await c.get("/storage")).json()
    assert body["paths"]["home"] == str(tmp_path)
    assert body["paths"]["state"] == str(tmp_path / "state")
    assert body["paths"]["config"] == str(tmp_path / "config.yaml")
