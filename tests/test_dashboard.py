# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Serving the built dashboard, and what /status tells it about the service.

The UI is a separate build (frontend/ → src/giq/static/ui/), absent from a
fresh checkout, so these tests point the routes at a fake build in a temp
directory rather than depending on whether `make ui` has run.
"""

import pytest
from httpx import ASGITransport, AsyncClient

import giq
from giq.api import stats_api
from giq.config import get_config
from giq.main import app

INDEX = '<!doctype html><script type="module" src="/dash/assets/index-abc.js"></script>'


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8084")


def _assets_app():
    for route in stats_api.router.routes:
        if getattr(route, "name", None) == "dash-assets":
            return route.app
    raise AssertionError("/dash/assets is not mounted")


@pytest.fixture
def built_ui(tmp_path, monkeypatch):
    """A fake `make ui` output: index.html plus one hashed asset."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "index-abc.js").write_text("console.log('giq')")
    monkeypatch.setattr(stats_api, "_UI_DIR", tmp_path)
    assets = _assets_app()
    monkeypatch.setattr(assets, "directory", tmp_path / "assets")
    monkeypatch.setattr(assets, "all_directories", [tmp_path / "assets"])
    monkeypatch.setattr(assets, "config_checked", False)
    return tmp_path


@pytest.fixture
def no_ui(tmp_path, monkeypatch):
    monkeypatch.setattr(stats_api, "_UI_DIR", tmp_path / "missing")
    assets = _assets_app()
    monkeypatch.setattr(assets, "directory", tmp_path / "missing" / "assets")
    monkeypatch.setattr(assets, "all_directories", [tmp_path / "missing" / "assets"])
    monkeypatch.setattr(assets, "config_checked", False)


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(get_config().access, "token", "s3cret", raising=False)
    return "s3cret"


@pytest.mark.asyncio
async def test_dash_serves_the_built_page_and_its_assets(built_ui):
    async with client() as c:
        page = await c.get("/dash")
        asset = await c.get("/dash/assets/index-abc.js")
        missing = await c.get("/dash/assets/nope.js")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.text == INDEX
    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_the_assets_mount_does_not_leave_its_directory(built_ui):
    (built_ui / "secret.txt").write_text("not an asset")
    async with client() as c:
        r = await c.get("/dash/assets/../secret.txt")
        r2 = await c.get("/dash/assets/%2e%2e/secret.txt")

    assert "not an asset" not in r.text
    assert "not an asset" not in r2.text


@pytest.mark.asyncio
async def test_an_unbuilt_ui_says_how_to_build_it(no_ui):
    async with client() as c:
        page = await c.get("/dash")
        asset = await c.get("/dash/assets/index-abc.js")

    assert page.status_code == 503
    assert "make ui" in page.text
    # Not a 500: a missing build is an expected state of a fresh checkout.
    assert asset.status_code == 404


@pytest.mark.asyncio
async def test_old_sandbox_links_still_land_in_the_dashboard():
    async with client() as c:
        r = await c.get("/sandbox")

    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/dash#/sandbox"


@pytest.mark.asyncio
async def test_the_page_loads_on_a_token_guarded_rig_but_the_api_does_not(built_ui, token):
    """A browser fetches <script src> itself and cannot attach the token, so
    the page and its build assets load without it. Everything with data
    behind it still needs it."""
    async with client() as c:
        page = await c.get("/dash")
        asset = await c.get("/dash/assets/index-abc.js")
        status = await c.get("/status")
        authed = await c.get("/status", headers={"x-giq-token": token})

    assert page.status_code == 200
    assert asset.status_code == 200
    assert status.status_code == 401
    assert authed.status_code == 200


@pytest.mark.asyncio
async def test_the_token_exemption_does_not_lift_the_host_rule(built_ui, token):
    async with client() as c:
        r = await c.get("/dash/assets/index-abc.js", headers={"host": "evil.example"})

    assert r.status_code == 403


def test_the_version_is_the_one_in_pyproject():
    """A release bumps pyproject.toml; /status must say the same, not an older copy."""
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert giq.__version__ == pyproject["project"]["version"]


@pytest.mark.asyncio
async def test_status_reports_version_and_uptime():
    async with client() as c:
        r = await c.get("/status")

    assert r.status_code == 200
    data = r.json()
    assert data["version"] == giq.__version__
    assert isinstance(data["uptime_s"], (int, float))
    assert data["uptime_s"] >= 0
