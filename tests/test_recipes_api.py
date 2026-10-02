# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""GET /recipes and the residency and card writes, by recipe name (ADR-003)."""

import pytest
from httpx import ASGITransport, AsyncClient

from giq.main import app
from giq.policy import reset_policy_store
from giq.registry import all_recipes


@pytest.fixture
def clean_policy():
    from giq.stats import get_stats

    stats = get_stats()

    def wipe():
        for name in list(stats.load_policies()):
            stats.delete_policy(name)
        for name in list(stats.load_devices()):
            stats.save_device(name, None)

    wipe()
    reset_policy_store().load()
    yield
    wipe()
    reset_policy_store()


@pytest.fixture
async def client(clean_policy):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


async def test_every_recipe_is_listed_once_in_its_own_terms(client):
    body = (await client.get("/recipes")).json()
    names = [r["name"] for r in body["recipes"]]
    assert sorted(names) == sorted(r.name for r in all_recipes())
    flux = next(r for r in body["recipes"] if r["name"] == "flux_klein")
    assert flux["modalities"] == ["text2image", "image_edit"]
    assert flux["max_batch"] == {"text2image": 8, "image_edit": 4}
    assert flux["engine"] == "sd.cpp" and len(flux["weights"]) == 3
    gemma = next(r for r in body["recipes"] if r["name"] == "gemma-4-12b")
    assert gemma["residency"] == {
        "policy": "pinned",
        "source": "default",
        "reason": None,
        "default_resident": True,
    }
    assert body["pinned"][0] == "gemma-4-12b"
    assert {"fit", "card", "installed", "instance"} <= set(gemma)


async def test_residency_is_set_and_cleared_by_name_or_alias(client):
    r = await client.put("/recipes/kokoro-82m/residency", json={"policy": "off", "reason": "test"})
    assert r.status_code == 200
    assert r.json()["recipe"]["name"] == "kokoro"
    assert r.json()["recipe"]["residency"]["policy"] == "off"
    one = (await client.get("/recipes/kokoro")).json()
    assert (one["residency"]["policy"], one["residency"]["reason"]) == ("off", "test")

    cleared = (await client.delete("/recipes/kokoro/residency")).json()["recipe"]
    assert (cleared["residency"]["policy"], cleared["residency"]["source"]) == ("auto", "default")


async def test_an_unknown_recipe_is_404(client):
    assert (await client.put("/recipes/nope/residency", json={"policy": "off"})).status_code == 404
    assert (await client.get("/recipes/nope")).status_code == 404
    assert (await client.put("/recipes/nope/card", json={"device": None})).status_code == 404


async def test_a_bad_policy_is_a_client_error(client):
    r = await client.put("/recipes/kokoro/residency", json={"policy": "sometimes"})
    assert r.status_code == 400 and "unknown policy" in r.json()["detail"]
