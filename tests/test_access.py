# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""A local service still has to survive the browser.

giq binds a socket on a machine somebody else's web page can also reach. Not
over the network — through the owner's own browser, which will happily send a
request to 127.0.0.1 on behalf of any site they happen to be reading. The
service cannot tell that request from a real one by looking at the socket, so
these tests pin the two things it *can* look at: the Host it was asked for and
the Origin that asked.

The bar is deliberately not "authenticated". It is "an honest client never
notices, and a page on another site never gets through" — because anything
stricter gets switched off on a rig whose operator is also its only user.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from giq.api import access
from giq.config import get_config
from giq.main import app


@pytest.fixture
def token(monkeypatch):
    """Turn the optional shared secret on for one test."""
    monkeypatch.setattr(get_config().access, "token", "s3cret", raising=False)
    yield "s3cret"


def client(**kwargs) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8084", **kwargs)


# --- Host: the rebinding defence ------------------------------------------


@pytest.mark.asyncio
async def test_a_rebound_hostname_is_refused():
    """The shape of a DNS-rebinding attack: a name the attacker controls,
    pointed at a local address. The request is otherwise perfectly ordinary."""
    async with client() as c:
        r = await c.get("/status", headers={"host": "evil.example"})

    assert r.status_code == 403
    assert "does not name this server" in r.json()["detail"]


@pytest.mark.asyncio
async def test_the_addresses_a_real_client_dials_are_accepted():
    """Loopback by name, loopback by number, and the LAN IP an ESP32 would
    use. An IP literal is safe to accept: rebinding needs a *name* to move."""
    for host in ("localhost:8084", "127.0.0.1:8084", "[::1]:8084", "192.168.1.50:8084"):
        async with client() as c:
            r = await c.get("/status", headers={"host": host})

        assert r.status_code == 200, f"{host} should be allowed"


@pytest.mark.asyncio
async def test_a_proxy_name_can_be_allowed_by_config(monkeypatch):
    """Reverse proxies rewrite Host; the operator gets to say which names."""
    monkeypatch.setattr(get_config().access, "allow_hosts", ["giq.lan"], raising=False)

    async with client() as c:
        r = await c.get("/status", headers={"host": "giq.lan"})

    assert r.status_code == 200


# --- Origin: the CSRF defence ---------------------------------------------


@pytest.mark.asyncio
async def test_a_foreign_page_cannot_drive_the_gpu():
    """The whole point. Pausing giq is a side effect a page gets for free if
    nothing checks who is asking — no reply needed, the damage is the request."""
    async with client() as c:
        r = await c.post(
            "/control/pause",
            json={"reason": "drive-by"},
            headers={"origin": "http://evil.example"},
        )

    assert r.status_code == 403
    assert "another site" in r.json()["detail"]


@pytest.mark.asyncio
async def test_a_foreign_page_cannot_read_past_results_either():
    """Rebinding aside, a GET carrying a foreign Origin is still a page
    asking. Past jobs hold prompts and answers; they are not a public read."""
    async with client() as c:
        r = await c.get("/jobs/whatever", headers={"origin": "http://evil.example"})

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_the_dashboard_calling_its_own_api_is_not_a_foreign_page():
    """Same-origin is judged against the Host the request arrived on, so it
    holds however the owner reached giq rather than needing to be configured."""
    async with client() as c:
        r = await c.get(
            "/status", headers={"host": "localhost:8084", "origin": "http://localhost:8084"}
        )

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_a_client_that_sends_no_origin_is_untouched():
    """curl, scripts and embedded firmware send no Origin at all. The check
    has to cost them nothing or it will not survive contact with real clients."""
    async with client() as c:
        r = await c.get("/status")

    assert r.status_code == 200


# --- the optional shared secret -------------------------------------------


@pytest.mark.asyncio
async def test_no_token_is_required_by_default():
    """Default posture: a single-user machine where asking the owner to authenticate to
    their own GPU buys nothing."""
    assert get_config().access.token == ""

    async with client() as c:
        r = await c.get("/status")

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_a_configured_token_is_demanded(token):
    async with client() as c:
        r = await c.get("/status")

    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_the_token_may_arrive_however_the_client_can_send_it(token):
    """A header for scripts; a query parameter for firmware that cannot set
    one. A token no one can send is a token that gets turned back off."""
    for kwargs in (
        {"headers": {"authorization": f"Bearer {token}"}},
        {"headers": {"x-giq-token": token}},
        {"params": {"token": token}},
    ):
        async with client() as c:
            r = await c.get("/status", **kwargs)

        assert r.status_code == 200, f"{kwargs} should authenticate"


@pytest.mark.asyncio
async def test_a_wrong_token_is_not_close_enough(token):
    async with client() as c:
        r = await c.get("/status", headers={"authorization": "Bearer s3cre"})

    assert r.status_code == 401


# --- saying so out loud ---------------------------------------------------


def test_the_posture_names_the_exposed_case():
    """Being open on a home network is a legitimate choice. Being open without
    having made it is not, and the difference is whether anyone said so."""
    assert access.posture("127.0.0.1")["exposed"] is False
    assert access.posture("0.0.0.0")["exposed"] is True


def test_a_token_takes_the_lan_bind_out_of_the_exposed_state(token):
    p = access.posture("0.0.0.0")

    assert p["loopback_only"] is False
    assert p["exposed"] is False
