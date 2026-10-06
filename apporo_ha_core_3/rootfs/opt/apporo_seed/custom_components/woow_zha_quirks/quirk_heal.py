"""Self-healing ZHA quirk application for woow_zha_quirks (reload safety-net).

Background
----------
This component registers its quirks into zigpy's ``DEVICE_REGISTRY`` at *module-import
time* so they are available before ZHA restores/creates its device objects.  The
``manifest.json`` deliberately declares **no** ``dependencies``/``after_dependencies``
on ``zha`` (adding ``dependencies: ["zha"]`` would force ZHA to set up *first*, which is
the exact ordering that leaves devices unquirked — see commit ``81cd348``).

Even so, HA's boot ordering is not guaranteed: on some restarts ZHA restores its devices
*before* our import-time registration lands, so those devices come up with
``quirk_applied=False`` and ZHA falls back to the raw signature (e.g. a 3-gang switch
that advertises ``device_type 0x0100`` shows up as 3 *lights* instead of 3 *switches*).
The historical fix was a manual "reload ZHA integration".

This module automates that cure as a **safety-net**: once per HA start, detect ZHA
devices that *match a registered woow quirk* yet have ``quirk_applied=False``, and — only
when ZHA looks healthy — reload the ZHA config entry once.  Re-creating the devices
against the now-populated registry applies the quirks (this needs no live comms, so
offline/powered-off devices are healed too, from their cached signature).

Orphan-entity cleanup is a *separate* concern handled by ``orphan_sweep.py``.  A heal
reload here re-creates devices, which fires ``EVENT_DEVICE_REGISTRY_UPDATED`` — a trigger
``orphan_sweep`` already listens to — so any entities orphaned by the reload are cleaned
up there.  The two hooks are independent and do not import each other.

This is a *cure, not a prevention*: on a race-lost boot the wrong entities are still
briefly created, then healed.  A healthy boot (quirks won the race) is a complete no-op.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.start import async_at_start

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"
ZHA_DOMAIN = "zha"

# Seconds to let ZHA settle (re-create devices) after a reload before re-scanning.
SETTLE_SECONDS = 20
# Bounded wait for the ZHA gateway to become ready at startup.
GATEWAY_RETRY_ATTEMPTS = 6
GATEWAY_RETRY_DELAY = 10  # seconds
# If more than this fraction of (non-coordinator) devices are unavailable, assume the
# coordinator is wedged — a reload won't help and may worsen it, so skip.
MASS_OUTAGE_RATIO = 0.5

# hass.data guard: the one-shot reload ran this boot.
DATA_HEAL_DONE = f"{DOMAIN}_heal_done"


def _get_gateway(hass: HomeAssistant):
    """Return the ZHA gateway, or None if ZHA is absent / not ready. Never raises."""
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway
    except ImportError:
        return None  # ZHA not installed
    try:
        return get_zha_gateway(hass)
    except (ValueError, KeyError):
        return None  # ZHA still coming up


def _safe_matches(entry: Any, zigpy_device: Any) -> bool:
    try:
        return bool(entry.matches_device(zigpy_device))
    except Exception:  # noqa: BLE001
        return False


def _registry_lookup():
    """Return a ``lookup(manufacturer, model) -> entries`` for the live v2 quirk registry.

    Tries the new ZHA registry first (HA 2026.7+: ``zha.quirks.DEVICE_REGISTRY._registry``
    keyed by ``ModelInfo(mfr, model)``), then the legacy zigpy one (HA 2026.3:
    ``zigpy.quirks.DEVICE_REGISTRY._registry_v2`` keyed by a ``(mfr, model)`` tuple).
    Returns ``None`` if neither is accessible. Never raises.
    """
    try:
        from zha.quirks import DEVICE_REGISTRY, ModelInfo

        reg = DEVICE_REGISTRY._registry
        return lambda mfr, model: reg.get(ModelInfo(mfr, model))
    except Exception:  # noqa: BLE001 - not HA 2026.7 / API moved; fall through to legacy
        pass

    try:
        from zigpy.quirks import DEVICE_REGISTRY

        reg = DEVICE_REGISTRY._registry_v2
        return lambda mfr, model: reg.get((mfr, model))
    except Exception:  # noqa: BLE001 - zigpy internals may change across versions
        _LOGGER.debug("%s: could not access any v2 quirk DEVICE_REGISTRY", DOMAIN)
        return None


def _find_unquirked(gateway) -> list[str]:
    """IEEEs of devices that match a registered woow quirk but are not quirk_applied.

    Uses the singleton v2 quirk registry (the one quirks register into) and mirrors ZHA's
    own decision via ``entry.matches_device`` (signature-only, works offline). Supports
    both the HA 2026.7 ``zha.quirks`` registry and the legacy zigpy one (see
    ``_registry_lookup``). Never raises — any introspection failure degrades to "nothing
    to heal".
    """
    lookup = _registry_lookup()
    if lookup is None:
        return []

    out: list[str] = []
    for zdev in gateway.devices.values():
        try:
            if zdev.quirk_applied:
                continue
            entries = lookup(zdev.manufacturer, zdev.model)
            if not entries:
                continue
            if any(_safe_matches(e, zdev.device) for e in entries):
                out.append(str(zdev.ieee))
        except Exception:  # noqa: BLE001 - be defensive per-device
            continue
    return out


def _zha_healthy(gateway) -> bool:
    """True if ZHA looks healthy enough to safely reload.

    Guards against reloading a wedged coordinator (where reload won't help and may leave
    the entry unloaded / all devices gone).
    """
    try:
        coord = getattr(gateway, "coordinator_zha_device", None)
        if coord is not None and not coord.available:
            _LOGGER.warning("%s: ZHA coordinator unavailable — skipping heal reload", DOMAIN)
            return False
        others = [d for d in gateway.devices.values() if not d.is_active_coordinator]
        if others:
            unavailable = sum(1 for d in others if not d.available)
            if unavailable / len(others) > MASS_OUTAGE_RATIO:
                _LOGGER.warning(
                    "%s: %d/%d devices unavailable (likely wedged coordinator) — "
                    "skipping heal reload",
                    DOMAIN, unavailable, len(others),
                )
                return False
    except Exception:  # noqa: BLE001
        # If we can't assess health, err on the side of not reloading.
        _LOGGER.debug("%s: could not assess ZHA health — skipping heal reload", DOMAIN)
        return False
    return True


def _loaded_zha_entry(hass: HomeAssistant):
    """The loaded ZHA config entry (there is normally exactly one), or None."""
    for entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        if entry.state == ConfigEntryState.LOADED:
            return entry
    return None


async def _async_heal(hass: HomeAssistant) -> None:
    """One-shot: detect unquirked devices and reload ZHA once to heal them."""
    if hass.data.get(DATA_HEAL_DONE):
        return

    # Wait (bounded) for the gateway to be ready.
    gateway = None
    for _ in range(GATEWAY_RETRY_ATTEMPTS):
        gateway = _get_gateway(hass)
        if gateway is not None:
            break
        await asyncio.sleep(GATEWAY_RETRY_DELAY)
    if gateway is None:
        _LOGGER.debug("%s: ZHA gateway not ready — heal skipped this boot", DOMAIN)
        return

    unquirked = _find_unquirked(gateway)
    if not unquirked:
        hass.data[DATA_HEAL_DONE] = True
        _LOGGER.debug("%s: all matching devices already quirked — no heal needed", DOMAIN)
        return

    if not _zha_healthy(gateway):
        hass.data[DATA_HEAL_DONE] = True  # don't reload a wedged ZHA; leave it alone
        return

    entry = _loaded_zha_entry(hass)
    if entry is None:
        _LOGGER.warning("%s: no loaded ZHA config entry — cannot heal %d device(s)",
                        DOMAIN, len(unquirked))
        hass.data[DATA_HEAL_DONE] = True
        return

    # Set the guard BEFORE reloading so nothing re-enters and reloads again.
    hass.data[DATA_HEAL_DONE] = True
    _LOGGER.warning("%s: %d device(s) unquirked (load-order race) — reloading ZHA to "
                    "heal: %s", DOMAIN, len(unquirked), unquirked)
    try:
        await hass.config_entries.async_reload(entry.entry_id)
    except Exception as exc:  # noqa: BLE001 - never loop on a failed reload
        _LOGGER.error("%s: ZHA reload failed (%s) — leaving ZHA to HA, no retry",
                      DOMAIN, exc)
        return

    await asyncio.sleep(SETTLE_SECONDS)

    gateway = _get_gateway(hass)
    if gateway is None:
        _LOGGER.warning("%s: ZHA gateway not back after reload", DOMAIN)
        return

    still = set(_find_unquirked(gateway))
    healed = [ieee for ieee in unquirked if ieee not in still]
    _LOGGER.info("%s: post-reload — %d healed, %d still unquirked", DOMAIN,
                 len(healed), len(still))
    if still:
        _LOGGER.warning("%s: still unquirked after reload (possible genuine signature "
                        "mismatch, NOT a timing issue — not reloading again): %s",
                        DOMAIN, sorted(still))
    # Orphan entities left by the reload are cleaned by orphan_sweep.py, which listens to
    # the EVENT_DEVICE_REGISTRY_UPDATED that this reload fired.


async def async_setup_quirk_heal(hass: HomeAssistant) -> None:
    """Register the one-shot self-heal trigger (called from async_setup)."""

    @callback
    def _kick_heal(*_: Any) -> None:
        hass.async_create_task(_async_heal(hass))

    # One-shot heal after HA has fully started (all config entries set up).
    async_at_start(hass, _kick_heal)
