# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Test helpers for the recipe catalog."""

import dataclasses
from types import MappingProxyType

from giq import recipes
from giq.recipes.schema import Recipe


def with_recipes(monkeypatch, *extra: Recipe) -> None:
    """The current catalog plus ``extra``, for the length of one test.

    Every reader goes through ``recipes.current()``, so replacing it is all a
    test needs to make a recipe exist — or to replace a built-in of the same
    name.
    """
    snapshot = recipes.current()
    patched = dataclasses.replace(
        snapshot,
        recipes=MappingProxyType({**snapshot.recipes, **{r.name: r for r in extra}}),
    )
    monkeypatch.setattr(recipes, "current", lambda: patched)
