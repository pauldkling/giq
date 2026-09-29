# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Per-model residency policy: pinned, auto, or off.

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
registry's built-in set. So "mark this persistent" needs no separate flag:
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
from giq.registry import all_specs, get_spec

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
    worker: str
    model: str
    policy: str
    source: str  # "override" (operator set it) | "default" (registry/config)
    reason: str | None = None
    updated_at: float | None = None
    # GPU UUID this model is bound to, and where that came from:
    # "override" (operator), "config" (gpu.bind), "default" (unbound — the
    # model runs on whatever card giq selected).
    device: str | None = None
    device_source: str = "default"

    @property
    def key(self) -> tuple[str, str]:
        return (self.worker, self.model)

    @property
    def name(self) -> str:
        return f"{self.worker}/{self.model}"


class PolicyStore:
    """In-memory policy map, write-through to stats.db.

    Held in memory because the residents loop consults it on every tick and
    the dispatch path consults it per job; neither should touch SQLite.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overrides: dict[tuple[str, str], tuple[str, str | None, float]] = {}
        self._devices: dict[tuple[str, str], str] = {}
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
            # falling back to registry defaults is the safe direction (it can
            # only load models the operator had already allowed).
            logger.error(f"policy: could not load overrides, using defaults: {e}")
            overrides, devices = {}, {}
        for table, label in ((overrides, "override"), (devices, "binding")):
            for key in [k for k in table if get_spec(*k) is None]:
                logger.warning(
                    f"policy: {key[0]}/{key[1]} is no longer registered, ignoring {label}"
                )
                table.pop(key)
        # A row can exist purely to carry a binding, with the policy column
        # holding the registry default. That is not an override — reporting it
        # as one would freeze the model against a later default change.
        for key in [k for k, v in overrides.items() if v[0] == self.default_for(*k)]:
            overrides.pop(key)
        with self._lock:
            self._overrides = overrides
            self._devices = devices
            self._loaded = True
        if overrides or devices:
            logger.info(f"policy: {len(overrides)} override(s), {len(devices)} binding(s) loaded")

    # --- reads ---------------------------------------------------------------

    @staticmethod
    def default_for(worker: str, model: str) -> str:
        spec = get_spec(worker, model)
        if spec is None:
            return AUTO
        return PINNED if spec.resident_priority is not None else AUTO

    def policy_for(self, worker: str, model: str) -> str:
        key = (str(worker), str(model))
        with self._lock:
            override = self._overrides.get(key)
        if override is not None:
            return override[0]
        return self.default_for(*key)

    def record_for(self, worker: str, model: str) -> PolicyRecord:
        key = (str(worker), str(model))
        with self._lock:
            override = self._overrides.get(key)
        device, device_source = self.device_record(*key)
        if override is not None:
            policy, reason, ts = override
            return PolicyRecord(
                key[0], key[1], policy, "override", reason, ts, device, device_source
            )
        return PolicyRecord(
            key[0],
            key[1],
            self.default_for(*key),
            "default",
            device=device,
            device_source=device_source,
        )

    # --- device bindings -----------------------------------------------------

    def device_record(self, worker: str, model: str) -> tuple[str | None, str]:
        """(GPU UUID, source) this model is bound to. (None, "default") = unbound.

        Precedence mirrors residency: an operator override outranks
        config.yaml's ``gpu.bind``, which outranks being unbound. A binding
        that no longer resolves to a present card is dropped with a warning
        rather than honoured — refusing to load at all would be a worse
        failure than falling back to the default card.
        """
        key = (str(worker), str(model))
        with self._lock:
            override = self._devices.get(key)
        if override is not None:
            gpu = resolve_device(override)
            if gpu is not None:
                return gpu.uuid, "override"
            logger.warning(
                f"policy: {key[0]}/{key[1]} is bound to {override}, which is not present "
                "— falling back to the default card"
            )
            return None, "default"

        try:
            from giq.config import get_config

            configured = get_config().gpu.bind.get(f"{key[0]}/{key[1]}")
        except Exception as e:
            logger.warning(f"policy: gpu.bind unreadable: {e}")
            configured = None
        if configured is not None:
            gpu = resolve_device(configured)
            if gpu is not None:
                return gpu.uuid, "config"
            logger.error(
                f"policy: gpu.bind has {key[0]}/{key[1]} on {configured!r}, which matches no "
                "card — using the default card"
            )
        return None, "default"

    def device_for(self, worker: str, model: str) -> str | None:
        """The GPU UUID this model is bound to, or None when unbound."""
        return self.device_record(worker, model)[0]

    def is_off(self, worker: str, model: str) -> bool:
        return self.policy_for(worker, model) == OFF

    def all_records(self) -> list[PolicyRecord]:
        return [self.record_for(spec.worker, spec.model) for spec in all_specs()]

    def residents(self) -> list[tuple[str, str]]:
        """Pinned models in reload-priority order.

        Registry residents keep their declared order (it encodes which model
        matters most when VRAM is tight); models pinned by an operator follow,
        oldest pin first, so the order is stable across restarts.
        """
        pinned: list[tuple[tuple[int, float], tuple[str, str]]] = []
        for spec in all_specs():
            record = self.record_for(spec.worker, spec.model)
            if record.policy != PINNED:
                continue
            if record.source == "default":
                rank = (0, float(spec.resident_priority or 0))
            else:
                rank = (1, record.updated_at or 0.0)
            pinned.append((rank, spec.key))
        pinned.sort(key=lambda item: item[0])
        return [key for _rank, key in pinned]

    def effective_device(self, worker: str, model: str) -> str | None:
        """The UUID of the card this model will actually load on.

        The binding when there is one, the service's selected card otherwise.
        None only when no GPU is visible at all.
        """
        bound = self.device_for(worker, model)
        if bound is not None:
            return bound
        gpu = selected_device()
        return gpu.uuid if gpu else None

    def residents_on(self, device: str | None) -> list[tuple[str, str]]:
        """Pinned models that will load on ``device``, in reload-priority order."""
        return [key for key in self.residents() if self.effective_device(*key) == device]

    def pinned_by_device(self) -> dict[str | None, list[tuple[str, str]]]:
        """Pinned models grouped by the card they land on."""
        grouped: dict[str | None, list[tuple[str, str]]] = {}
        for key in self.residents():
            grouped.setdefault(self.effective_device(*key), []).append(key)
        return grouped

    def pinned_vram_gb(
        self, extra: tuple[str, str] | None = None, device: str | None = None
    ) -> float:
        """VRAM the pinned set claims on one card, optionally with one more.

        ``device`` is a UUID; None means "wherever ``extra`` lands", which is
        what a caller checking a pin actually wants to know. Before bindings
        this summed every pinned model regardless of card — on a two-card rig
        that answers a question nobody asked, and refuses pins that fit fine.
        """
        if device is None and extra is not None:
            device = self.effective_device(*extra)
        keys = set(self.residents_on(device))
        if extra is not None and self.effective_device(*extra) == device:
            keys.add((str(extra[0]), str(extra[1])))
        total = 0.0
        for key in keys:
            spec = get_spec(*key)
            if spec is not None:
                total += spec.vram_gb
        return total

    def pinned_fit(
        self, extra: tuple[str, str] | None = None
    ) -> tuple[bool, float, float, str | None]:
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
            return judge(self.effective_device(*extra))
        devices = set(self.pinned_by_device()) or {None}
        return min((judge(d) for d in devices), key=lambda r: r[2] - r[1])

    def resident_llm(
        self, exclude: tuple[str, str] | None = None, device: str | None = None
    ) -> tuple[str, str] | None:
        """The pinned LLM on one card, if any. At most one may be pinned there.

        Every llama-server giq spawns binds that card's internal port, and
        ``Runner.llm_base_url_for`` resolves a model to its server — so two
        pinned LLMs on the SAME card would collide on the port. On different
        cards they get different ports and coexist, which is the point of
        binding.
        """
        for key in self.residents():
            if key[0] != "llm" or key == exclude:
                continue
            if device is None or self.effective_device(*key) == device:
                return key
        return None

    # --- writes --------------------------------------------------------------

    def set(self, worker: str, model: str, policy: str, reason: str | None = None) -> PolicyRecord:
        if policy not in POLICIES:
            raise ValueError(f"unknown policy {policy!r} (expected one of {', '.join(POLICIES)})")
        key = (str(worker), str(model))
        if get_spec(*key) is None:
            raise ValueError(f"{key[0]}/{key[1]} is not a registered model")

        from giq.stats import get_stats

        # Setting a model back to its default clears the override rather than
        # persisting a row that says "same as default" — otherwise a later
        # change to the registry default would be silently pinned in place.
        if policy == self.default_for(*key):
            get_stats().delete_policy(*key)
            with self._lock:
                self._overrides.pop(key, None)
            return PolicyRecord(key[0], key[1], policy, "default")

        ts = get_stats().save_policy(key[0], key[1], policy, reason)
        with self._lock:
            self._overrides[key] = (policy, reason, ts)
        logger.info(f"policy: {key[0]}/{key[1]} -> {policy}" + (f" ({reason})" if reason else ""))
        return PolicyRecord(key[0], key[1], policy, "override", reason, ts)

    def set_device(self, worker: str, model: str, device: str | int | None) -> PolicyRecord:
        """Bind a model to a card (index or UUID), or unbind it with None.

        Stores the UUID, never the index: an index is a position in whatever
        order the driver enumerated the cards this boot, and a binding has to
        outlive that.
        """
        key = (str(worker), str(model))
        if get_spec(*key) is None:
            raise ValueError(f"{key[0]}/{key[1]} is not a registered model")

        uuid: str | None = None
        if device is not None and str(device).strip() != "":
            gpu = resolve_device(device)
            if gpu is None:
                raise ValueError(f"{device!r} matches no GPU on this machine")
            uuid = gpu.uuid

        from giq.stats import get_stats

        get_stats().save_device(key[0], key[1], uuid)
        with self._lock:
            if uuid is None:
                self._devices.pop(key, None)
            else:
                self._devices[key] = uuid
        logger.info(f"policy: {key[0]}/{key[1]} bound to {uuid or 'the default card'}")
        return self.record_for(*key)

    def clear(self, worker: str, model: str) -> PolicyRecord:
        """Revert residency to the registry/config default. Keeps the binding."""
        from giq.stats import get_stats

        key = (str(worker), str(model))
        get_stats().delete_policy(*key)
        with self._lock:
            self._overrides.pop(key, None)
        return self.record_for(*key)


_store: PolicyStore | None = None


def get_policy_store() -> PolicyStore:
    global _store
    if _store is None:
        _store = PolicyStore()
    return _store


def reset_policy_store() -> PolicyStore:
    """Drop the in-memory store (tests; and after a registry reload)."""
    global _store
    _store = None
    return get_policy_store()


def device_of(worker: str, model: str) -> GpuTelemetry | None:
    """The card this model loads on, as live telemetry.

    The one call the scheduler, the VRAM gate and the workers all make: it
    folds "is this model bound?" and "what did giq select?" into a single
    answer, so no caller has to remember the fallback. None when no GPU is
    visible.
    """
    uuid = get_policy_store().effective_device(worker, model)
    return resolve_device(uuid) if uuid else selected_device()
