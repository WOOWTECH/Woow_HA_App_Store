"""Keep woow v2 quirks authoritative when upstream ships a competing v2 quirk.

The v2 quirk registry resolves a device to the **first matching entry** for its
``(manufacturer, model)`` key. Entries are inserted newest-first, so the quirk that
registers *last* wins. The woow component registers all its quirks at **import time**
(see ``__init__._load_quirks``) — before ZHA runs ``zhaquirks.setup()`` at gateway
startup — so a woow quirk starts at the front. But when upstream registers a v2 quirk
for the same signature during ``zhaquirks.setup()``, it jumps ahead and upstream wins.

The first device to hit this was ``_TZE204_clrdrnya`` (WO_40117): upstream
``zhaquirks.tuya.tuya_motion`` ships a full v2 builder for it, silently shadowing the
woow quirk.

Fix: install a one-time guard on the registry's registration method so that, for any
``(manufacturer, model)`` key a woow quirk already owns, a later **non-woow** (upstream)
entry is **dropped** — never added — rather than merely reordered. This leaves exactly
one matching entry (the woow one), so the woow quirk wins deterministically, on every
boot, with no ZHA reload. Signatures owned only by upstream are left completely untouched.

Why *drop* instead of *demote to the back*: dropping removes the two-entry "tie" entirely
and is independent of the container type (list/deque/set), so it stays correct if a future
zigpy/zha swaps the container or raises on a multi-match tie (see zigpy #1508). Every guard
body is wrapped so any future signature/internals change degrades to a safe passthrough
rather than breaking registration.

Registry API compatibility
---------------------------
HA 2026.7 moved the v2 registry from zigpy to ZHA and renamed its methods:
  * **New** (HA 2026.7+): ``zha.quirks.DeviceRegistry.register(entry)``; storage is
    ``self._registry[ModelInfo(mfr, model)]`` (a list, newest inserted at index 0);
    provenance is ``entry.source`` (``QuirkSource`` with ``.file`` / ``.module``).
  * **Old** (fallback, HA 2026.3): ``zigpy.quirks.registry.DeviceRegistry
    .add_to_registry_v2``; storage is ``self._registry_v2[(mfr, model)]`` (a deque,
    ``appendleft`` = newest); provenance is ``entry.quirk_file``.
This module patches whichever it finds, preferring the new one.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

_GUARD_INSTALLED_FLAG = "_woow_priority_guard_installed"
_WOOW_MARKER = "woow_zha_quirks"


def install_priority_guard() -> None:
    """Keep woow quirks in front of competing upstream v2 quirks. Idempotent.

    Must be called *after* the woow quirks have registered (so the relevant keys are
    already woow-owned), which ``__init__`` guarantees by calling this right after
    ``_load_quirks()``. Tries the new ``zha.quirks`` registry first, then the legacy
    zigpy one; if neither matches a known API it logs and skips (quirks still load —
    only cross-quirk priority ordering is affected).
    """
    try:
        if _install_new_guard():
            return
    except Exception:  # noqa: BLE001 - never break startup on an unexpected API shape
        _LOGGER.debug("WOOW ZHA Quirks: new-registry guard unavailable", exc_info=True)

    try:
        if _install_legacy_guard():
            return
    except Exception:  # noqa: BLE001
        _LOGGER.debug("WOOW ZHA Quirks: legacy-registry guard unavailable", exc_info=True)

    _LOGGER.warning(
        "WOOW ZHA Quirks: no known v2 quirk registry found; priority guard skipped"
    )


# ──────────────────────────────────────────────────────────────────────────
# New registry (HA 2026.7+): zha.quirks.DeviceRegistry.register
# ──────────────────────────────────────────────────────────────────────────
def _is_woow_entry_v2(entry: object) -> bool:
    """True if a QuirkRegistryEntry originates from a woow_zha_quirks quirk file."""
    source = getattr(entry, "source", None)
    if source is None:
        return False
    return _WOOW_MARKER in str(getattr(source, "file", "") or "") or _WOOW_MARKER in str(
        getattr(source, "module", "") or ""
    )


def _install_new_guard() -> bool:
    """Patch ``zha.quirks.DeviceRegistry.register``. Returns True if installed."""
    from zha.quirks import DeviceRegistry, ModelInfo

    if getattr(DeviceRegistry, _GUARD_INSTALLED_FLAG, False):
        return True

    original_register = DeviceRegistry.register

    def _guarded_register(self, entry):  # noqa: ANN001, ANN202
        applies = getattr(getattr(entry, "device_match", None), "applies_to", None)
        # Wildcard entries and woow entries always follow the original path (front).
        if not applies or _is_woow_entry_v2(entry):
            return original_register(self, entry)

        for manufacturer, model in applies:
            if manufacturer is None and model is None:
                # Let the original raise its ValueError for an all-None match.
                return original_register(self, entry)
            entries = self._registry[ModelInfo(manufacturer, model)]
            if entry in entries:
                continue
            if any(_is_woow_entry_v2(e) for e in entries):
                # A woow quirk owns this signature — DROP the competing (upstream) entry
                # entirely so exactly one entry matches and the woow quirk wins
                # match_entry() deterministically.
                _LOGGER.info(
                    "WOOW ZHA Quirks: kept woow quirk authoritative for %s "
                    "(dropped competing %s)",
                    (manufacturer, model),
                    getattr(getattr(entry, "source", None), "file", "?"),
                )
                continue
            entries.insert(0, entry)  # normal newest-first insertion
        return entry

    DeviceRegistry.register = _guarded_register
    setattr(DeviceRegistry, _GUARD_INSTALLED_FLAG, True)
    _LOGGER.info("WOOW ZHA Quirks: v2 quirk-priority guard installed (zha.quirks)")
    return True


# ──────────────────────────────────────────────────────────────────────────
# Legacy registry (fallback, HA 2026.3): zigpy DeviceRegistry.add_to_registry_v2
# ──────────────────────────────────────────────────────────────────────────
def _is_woow_entry_legacy(entry: object) -> bool:
    """True if a legacy registry entry originates from a woow_zha_quirks quirk file."""
    return _WOOW_MARKER in str(getattr(entry, "quirk_file", "") or "")


def _install_legacy_guard() -> bool:
    """Patch ``zigpy...DeviceRegistry.add_to_registry_v2``. Returns True if installed."""
    from zigpy.quirks.registry import DeviceRegistry

    if not hasattr(DeviceRegistry, "add_to_registry_v2"):
        return False
    if getattr(DeviceRegistry, _GUARD_INSTALLED_FLAG, False):
        return True

    original_add = DeviceRegistry.add_to_registry_v2

    def _guarded_add(self, manufacturer, model, entry):  # noqa: ANN001, ANN202
        try:
            key = (manufacturer, model)
            existing = self._registry_v2.get(key)
            if existing and not _is_woow_entry_legacy(entry) and any(
                _is_woow_entry_legacy(e) for e in existing
            ):
                # A woow quirk owns this signature — DROP the competing (upstream) entry
                # entirely so exactly one entry matches and the woow quirk wins
                # get_device(). Touches no container method (safe for deque/list/set).
                _LOGGER.info(
                    "WOOW ZHA Quirks: kept woow quirk authoritative for %s "
                    "(dropped competing %s)",
                    key,
                    getattr(entry, "quirk_file", "?"),
                )
                return
        except Exception:  # noqa: BLE001 - never let the guard break registration
            _LOGGER.debug(
                "WOOW ZHA Quirks: legacy priority guard passthrough for %s/%s",
                manufacturer,
                model,
            )
        original_add(self, manufacturer, model, entry)

    DeviceRegistry.add_to_registry_v2 = _guarded_add
    setattr(DeviceRegistry, _GUARD_INSTALLED_FLAG, True)
    _LOGGER.info("WOOW ZHA Quirks: v2 quirk-priority guard installed (legacy zigpy)")
    return True
