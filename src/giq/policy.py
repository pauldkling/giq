# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Per-recipe residency policy: pinned, auto, or off.

giq always had two implicit behaviours per model — *resident* (the residents
loop keeps it loaded, reloads it after eviction and on boot) and *sleepy*
(loads on demand, evictable, unloaded on the warm timeout). This makes that
choice explicit, per model, changeable at runtime and persistent:

  pinned   resident. Kept loaded whenever VRAM allows; comes back on boot.
  auto     on demand. Loads when a job arrives, evictable. The default.
  off      disabled. Refuses jobs and cannot load by any path.

There is deliberately no "unload" verb. The residents loop is the single
reload path and it ticks every few seconds, so an unload button on a pinned
model would be undone before the operator's hand left the mouse. Demoting to
`auto` (or `off`) *is* the unload, and it cannot be silently reverted by the
scheduler.

Overrides persist in stats.db and outrank config.yaml, which outranks the
recipes' own residency. So "mark this persistent" needs no separate flag:
what you set is what comes back after a restart.

The same store answers the second per-model question a multi-card rig raises:
*which card*. A binding is a GPU UUID recorded beside the policy, with the
same precedence (override > config `gpu.bind` > unbound, meaning the default
card). The two are deliberately independent — pinning a model says it stays
loaded, binding says where — and clearing one must not clear the other.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from giq.gpus import GpuTelemetry, resolve_device, selected_device
from giq.registry import all_recipes, get_recipe, resident_defaults

logger = logging.getLogger(__name__)

PINNED = "pinned"
AUTO = "auto"
OFF = "off"
POLICIES = (PINNED, AUTO, OFF)

# Free VRAM the pinned set must leave on the card. Matches the reduced margin
# _load_resident uses per resident: the set is validated to coexist, so
# demanding a full per-model spike margin would reject the working default set
# (9.5 + 4.0 + 0.6 = 14.1 GB of a 16 GB card's 15.93), which runs fine.
RESIDENT_SET_HEADROOM_GB = 0.5


@dataclass(frozen=True)
class PolicyRecord:
    """A recipe's residency: its policy, and the card it is bound to."""

    recipe: str
    policy: str
    source: str  # "override" (operator set it) | "default" (recipe/config)
    reason: str | None = None
    updated_at: float | None = None
    # GPU UUID this recipe is bound to, and where that came from:
    # "override" (operator), "config" (gpu.bind), "default" (unbound — the
    # recipe runs on whatever card giq selected).
    device: str | None = None
    device_source: str = "default"


def _canonical(name: str) -> str | None:
    """The recipe name ``name`` means (an alias resolved), or None if unknown."""
    recipe = get_recipe(name)
    return recipe.name if recipe is not None else None


class PolicyStore:
    """In-memory policy map, write-through to stats.db.

    Held in memory because the residents loop consults it on every tick and
    the dispatch path consults it per job; neither should touch SQLite.
    Keyed by recipe name (ADR-003).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overrides: dict[str, tuple[str, str | None, float]] = {}
        self._devices: dict[str, str] = {}
        self._loaded = False

    def load(self) -> None:
        """Read persisted overrides and bindings. Safe to call more than once."""
        from giq.stats import get_stats

        try:
            stats = get_stats()
            overrides = stats.load_policies()
            devices = stats.load_devices()
        except Exception as e:
            # A policy store that can't read must not take the service down;
            # falling back to the recipes' defaults is the safe direction (it
            # can only load models the operator had already allowed).
            logger.error(f"policy: could not load overrides, using defaults: {e}")
            overrides, devices = {}, {}
        for table, label in ((overrides, "override"), (devices, "binding")):
            for name in [n for n in table if get_recipe(n) is None]:
                logger.warning(f"policy: no recipe {name!r} any more, ignoring its {label}")
                table.pop(name)
        # A row can exist purely to carry a binding, with the policy column
        # holding the default. That is not an override — reporting it as one
        # would freeze the recipe against a later default change.
        for name in [n for n, v in overrides.items() if v[0] == self.default_for(n)]:
            overrides.pop(name)
        with self._lock:
            self._overrides = overrides
            self._devices = devices
            self._loaded = True
        if overrides or devices:
            logger.info(f"policy: {len(overrides)} override(s), {len(devices)} binding(s) loaded")

    # --- reads ---------------------------------------------------------------

    @staticmethod
    def default_for(name: str) -> str:
        """PINNED for the default resident set (the recipes', or config.yaml's), else AUTO."""
        return PINNED if _canonical(name) in resident_defaults() else AUTO

    def policy_for(self, name: str) -> str:
        key = _canonical(name) or str(name)
        with self._lock:
            override = self._overrides.get(key)
        if override is not None:
            return override[0]
        return self.default_for(key)

    def record_for(self, name: str) -> PolicyRecord:
        key = _canonical(name) or str(name)
        with self._lock:
            override = self._overrides.get(key)
        device, device_source = self.device_record(key)
        if override is not None:
            policy, reason, ts = override
            return PolicyRecord(key, policy, "override", reason, ts, device, device_source)
        return PolicyRecord(
            key, self.default_for(key), "default", device=device, device_source=device_source
        )

    # --- device bindings -----------------------------------------------------

    def device_record(self, name: str) -> tuple[str | None, str]:
        """(GPU UUID, source) this recipe is bound to. (None, "default") = unbound.

        Precedence mirrors residency: an operator override outranks
        config.yaml's ``gpu.bind``, which outranks being unbound. A binding
        that no longer resolves to a present card is dropped with a warning
        rather than honoured — refusing to load at all would be a worse
        failure than falling back to the default card.
        """
        key = _canonical(name) or str(name)
        with self._lock:
            override = self._devices.get(key)
        if override is not None:
            gpu = resolve_device(override)
            if gpu is not None:
                return gpu.uuid, "override"
            logger.warning(
                f"policy: {key} is bound to {override}, which is not present "
                "— falling back to the default card"
            )
            return None, "default"

        configured = _configured_binding(key)
        if configured is not None:
            gpu = resolve_device(configured)
            if gpu is not None:
                return gpu.uuid, "config"
            logger.error(
                f"policy: gpu.bind has {key} on {configured!r}, which matches no "
                "card — using the default card"
            )
        return None, "default"

    def device_for(self, name: str) -> str | None:
        """The GPU UUID this recipe is bound to, or None when unbound."""
        return self.device_record(name)[0]

    def is_off(self, name: str) -> bool:
        return self.policy_for(name) == OFF

    def all_records(self) -> list[PolicyRecord]:
        return [self.record_for(r.name) for r in all_recipes()]

    def residents(self) -> list[str]:
        """Pinned recipes in reload-priority order.

        The default residents keep their declared order (it encodes which
        model matters most when VRAM is tight); recipes pinned by an operator
        follow, oldest pin first, so the order is stable across restarts.
        """
        defaults = resident_defaults()
        pinned: list[tuple[tuple[int, float], str]] = []
        for recipe in all_recipes():
            record = self.record_for(recipe.name)
            if record.policy != PINNED:
                continue
            if record.source == "default":
                rank = (0, float(defaults.index(recipe.name)))
            else:
                rank = (1, record.updated_at or 0.0)
            pinned.append((rank, recipe.name))
        pinned.sort(key=lambda item: item[0])
        return [name for _rank, name in pinned]

    def effective_device(self, name: str) -> str | None:
        """The UUID of the card this recipe will actually load on.

        The binding when there is one, the service's selected card otherwise.
        None only when no GPU is visible at all.
        """
        bound = self.device_for(name)
        if bound is not None:
            return bound
        gpu = selected_device()
        return gpu.uuid if gpu else None

    def residents_on(self, device: str | None) -> list[str]:
        """Pinned recipes that will load on ``device``, in reload-priority order."""
        return [name for name in self.residents() if self.effective_device(name) == device]

    def pinned_by_device(self) -> dict[str | None, list[str]]:
        """Pinned recipes grouped by the card they land on."""
        grouped: dict[str | None, list[str]] = {}
        for name in self.residents():
            grouped.setdefault(self.effective_device(name), []).append(name)
        return grouped

    def pinned_vram_gb(self, extra: str | None = None, device: str | None = None) -> float:
        """VRAM the pinned set claims on one card, optionally with one more recipe.

        ``device`` is a UUID; None means "wherever ``extra`` lands", which is
        what a caller checking a pin actually wants to know. Before bindings
        this summed every pinned model regardless of card — on a two-card rig
        that answers a question nobody asked, and refuses pins that fit fine.
        """
        if device is None and extra is not None:
            device = self.effective_device(extra)
        names = set(self.residents_on(device))
        if extra is not None and self.effective_device(extra) == device:
            names.add(_canonical(extra) or str(extra))
        total = 0.0
        for name in names:
            recipe = get_recipe(name)
            if recipe is not None:
                total += recipe.vram_gb
        return total

    def pinned_fit(self, extra: str | None = None) -> tuple[bool, float, float, str | None]:
        """(fits, projected_gb, total_gb, device) for one card's pinned set.

        The card is the one ``extra`` would land on; with no ``extra``, the
        most over-committed card, so a caller asking "is the current set OK?"
        hears about the card that isn't.

        Over-pinning is the sharp edge of this feature on a small card: the
        residents loop would try forever to load a set that cannot coexist,
        thrashing reloads and never converging. Callers check before writing.
        """
        from giq.vram import get_vram_status, reserve_for

        def judge(device: str | None) -> tuple[bool, float, float, str | None]:
            total = get_vram_status(device).total_gb
            projected = (
                self.pinned_vram_gb(extra, device) + RESIDENT_SET_HEADROOM_GB + reserve_for(device)
            )
            return projected <= total, round(projected, 2), round(total, 2), device

        if extra is not None:
            return judge(self.effective_device(extra))
        devices = set(self.pinned_by_device()) or {None}
        return min((judge(d) for d in devices), key=lambda r: r[2] - r[1])

    def resident_llm(self, exclude: str | None = None, device: str | None = None) -> str | None:
        """The pinned LLM recipe on one card, if any. At most one may be pinned there.

        The rule dates from when every LLM server on a card bound that card's
        one port, so two pinned there collided. Servers now take a free port
        of their card's block (``giq.gpus.server_port``) and an on-demand LLM
        can share a card with the pinned one; two *pinned* LLMs on one card
        stay refused until that pairing is exercised under the residents
        loop. On different cards they coexist, which is the point of binding.
        """
        exclude = _canonical(exclude) if exclude is not None else None
        for name in self.residents():
            recipe = get_recipe(name)
            if recipe is None or not recipe.serves("llm") or name == exclude:
                continue
            if device is None or self.effective_device(name) == device:
                return name
        return None

    # --- writes --------------------------------------------------------------

    def set(self, name: str, policy: str, reason: str | None = None) -> PolicyRecord:
        if policy not in POLICIES:
            raise ValueError(f"unknown policy {policy!r} (expected one of {', '.join(POLICIES)})")
        key = _canonical(name)
        if key is None:
            raise ValueError(f"{name} is not a recipe")

        from giq.stats import get_stats

        # Setting a recipe back to its default clears the override rather than
        # persisting a row that says "same as default" — otherwise a later
        # change to the default would be silently pinned in place.
        if policy == self.default_for(key):
            get_stats().delete_policy(key)
            with self._lock:
                self._overrides.pop(key, None)
            return PolicyRecord(key, policy, "default")

        ts = get_stats().save_policy(key, policy, reason)
        with self._lock:
            self._overrides[key] = (policy, reason, ts)
        logger.info(f"policy: {key} -> {policy}" + (f" ({reason})" if reason else ""))
        return PolicyRecord(key, policy, "override", reason, ts)

    def set_device(self, name: str, device: str | int | None) -> PolicyRecord:
        """Bind a recipe to a card (index or UUID), or unbind it with None.

        Stores the UUID, never the index: an index is a position in whatever
        order the driver enumerated the cards this boot, and a binding has to
        outlive that.
        """
        key = _canonical(name)
        if key is None:
            raise ValueError(f"{name} is not a recipe")

        uuid: str | None = None
        if device is not None and str(device).strip() != "":
            gpu = resolve_device(device)
            if gpu is None:
                raise ValueError(f"{device!r} matches no GPU on this machine")
            uuid = gpu.uuid

        from giq.stats import get_stats

        get_stats().save_device(key, uuid)
        with self._lock:
            if uuid is None:
                self._devices.pop(key, None)
            else:
                self._devices[key] = uuid
        logger.info(f"policy: {key} bound to {uuid or 'the default card'}")
        return self.record_for(key)

    def clear(self, name: str) -> PolicyRecord:
        """Revert residency to the recipe/config default. Keeps the binding."""
        from giq.stats import get_stats

        key = _canonical(name) or str(name)
        get_stats().delete_policy(key)
        with self._lock:
            self._overrides.pop(key, None)
        return self.record_for(key)


def _configured_binding(name: str) -> str | None:
    """config.yaml's ``gpu.bind`` entry for a recipe.

    Keyed by recipe name; the ``worker/name`` keys written before ADR-003
    still count.
    """
    try:
        from giq.config import get_config

        bind = get_config().gpu.bind
    except Exception as e:
        logger.warning(f"policy: gpu.bind unreadable: {e}")
        return None
    if name in bind:
        return bind[name]
    return next((v for k, v in bind.items() if str(k).rpartition("/")[2] == name), None)


_store: PolicyStore | None = None


def get_policy_store() -> PolicyStore:
    global _store
    if _store is None:
        _store = PolicyStore()
    return _store


def reset_policy_store() -> PolicyStore:
    """Drop the in-memory store (tests; and after a recipe reload)."""
    global _store
    _store = None
    return get_policy_store()


def device_of(name: str) -> GpuTelemetry | None:
    """The card recipe ``name`` loads on, as live telemetry.

    The one call the scheduler, the VRAM gate and the adapters all make: it
    folds "is this recipe bound?" and "what did giq select?" into a single
    answer, so no caller has to remember the fallback. None when no GPU is
    visible.
    """
    uuid = get_policy_store().effective_device(name)
    return resolve_device(uuid) if uuid else selected_device()
