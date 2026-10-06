"""Standalone orphan-entity cleanup for woow_zha_quirks.

Background
----------
When a ZHA device's stored configuration changes — a quirk starts/stops applying, its
endpoints/entity types change (e.g. a 3-gang switch that briefly came up as 3 *lights*
before its quirk applied), or a device is re-paired — the entity registry keeps the
*old* rows.  ZHA does not re-create those entities as live objects, so they linger
forever as ``unavailable`` "orphans" (old ``light.*`` / firmware / power-on-behavior
rows next to the now-correct ``switch.*`` / ``select.*``).

This hook removes them automatically, independently of the ``quirk_heal`` reload
safety-net.  The two are orthogonal: ``quirk_heal`` fixes a device that is *currently* in
the wrong state; this sweep removes the *dead leftover* entities of any device.

Safe-orphan signal (all four must hold)
--------------------------------------
  * ``ent.platform == "zha"``                     — only touch ZHA rows
  * live state is ``unavailable``                 — no live value
  * ``state.attributes["restored"] is True``      — ZHA did NOT re-create it this session
                                                    (a live entity is never "restored")
  * the owning device is currently ``available``  — never touch a genuinely-offline
                                                    device's entities (they'd be swept
                                                    only once the device is back online)

Disabled entities have no state object, so they are skipped and never removed.

Protection A — only sweep quirk-applied devices
-----------------------------------------------
Only devices that are ``available`` **and** ``quirk_applied`` are swept.  A device that
lost the load-order race is transiently ``quirk_applied=False`` and exposes its *correct*
entities as ``unavailable`` (they look like orphans) until ``quirk_heal`` reloads.
Skipping such devices guarantees a user-renamed/automated switch is never deleted during
that window.  The coordinator and quirk-less devices are skipped for the same reason.

Protection B — never delete user-customized entities
----------------------------------------------------
An entity with a custom name / area / icon / label / alias / category is skipped
regardless — the user has invested in it, so we never delete it even if it looks orphaned.

Two-pass stability
------------------
An entity can be *transiently* ``restored+unavailable`` for a moment while ZHA is still
attaching it (during startup or right after a ``quirk_heal`` reload).  To avoid deleting
such an entity, we only delete a candidate that was **also** flagged on the previous
sweep (``DATA_SWEEP_SEEN``).  A transient entity goes live before the next sweep, so it is
never removed.

Safety
------
``CLEANUP_ENABLED`` gates real deletion: when ``False`` the sweep only logs
("[dry-run] would remove ...") and deletes nothing; when ``True`` it removes the
entities.  It shipped ``False`` for review, then was enabled after the dry-run list was
verified live.  Every real removal is logged for auditability.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_start

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"
ZHA_PLATFORM = "zha"

# When False, the sweep only *logs* ("would remove ...") and deletes nothing (dry-run).
# When True, it actually removes the entities. Enabled 2026-07-22 after verifying the
# dry-run list live and confirming Protections A/B (see module docstring).
CLEANUP_ENABLED = True

# Catch devices that power on after startup (bench / sleepy devices).
BACKSTOP_INTERVAL = timedelta(minutes=5)

# hass.data keys
DATA_SWEEP_RUNNING = f"{DOMAIN}_sweep_running"  # bool: re-entry guard
DATA_SWEEP_SEEN = f"{DOMAIN}_sweep_seen"        # set[str entity_id]: last pass's candidates


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


def _sweepable_ieees(gateway) -> set[str]:
    """IEEEs (str) of devices that are SAFE to sweep: available AND quirk_applied.

    Protection A — never sweep a device that is not in its final quirk-applied state:
      * A device that lost the load-order race comes up ``quirk_applied=False`` and ZHA
        exposes it under its raw signature (e.g. a switch shows up as a *light*).  In
        that transient window the device's *correct* entities (the switches the user may
        have renamed / automated) are ``unavailable`` and would look like orphans.
        ``quirk_heal`` is about to reload and restore them, so we must NOT touch this
        device until it is quirk_applied again.
      * The coordinator and any genuinely quirk-less device are also skipped (their
        orphan judgment is out of scope for this component).
    Only once a device is ``quirk_applied`` are its live entities its *final* correct set,
    making its ``unavailable``/``restored`` rows true dead leftovers.
    """
    out: set[str] = set()
    for zdev in gateway.devices.values():
        try:
            if zdev.available and zdev.quirk_applied:
                out.add(str(zdev.ieee))
        except Exception:  # noqa: BLE001 - be defensive per-device
            continue
    return out


def _is_user_customized(ent) -> bool:
    """True if the user has invested in this entity (custom name / area / icon / labels /
    aliases / categories).

    Protection B — never delete an entity the user has customized, even if it currently
    looks like an orphan.  If we can't tell, assume customized (skip) — the safe default.
    """
    try:
        return bool(
            ent.name
            or ent.area_id
            or ent.icon
            or ent.labels
            or ent.aliases
            or ent.categories
        )
    except Exception:  # noqa: BLE001
        return True


def _candidate_orphans(hass: HomeAssistant, sweepable: set[str]) -> dict[str, str]:
    """entity_id -> ieee for ZHA orphans (unavailable + restored, NOT user-customized)
    on devices that are safe to sweep (available + quirk_applied)."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    out: dict[str, str] = {}
    for ieee in sweepable:
        device = dev_reg.async_get_device(connections={(dr.CONNECTION_ZIGBEE, ieee)})
        if device is None:
            continue
        for ent in er.async_entries_for_device(
            ent_reg, device.id, include_disabled_entities=True
        ):
            if ent.platform != ZHA_PLATFORM:
                continue
            if _is_user_customized(ent):  # Protection B
                continue
            state = hass.states.get(ent.entity_id)
            if state is None or state.state != "unavailable":
                continue
            if state.attributes.get("restored") is not True:
                continue
            out[ent.entity_id] = ieee
    return out


async def _async_sweep(hass: HomeAssistant) -> None:
    """Remove (or dry-run log) stable ZHA orphan entities on online devices."""
    if hass.data.get(DATA_SWEEP_RUNNING):
        return
    gateway = _get_gateway(hass)
    if gateway is None:
        return
    hass.data[DATA_SWEEP_RUNNING] = True
    try:
        sweepable = _sweepable_ieees(gateway)
        candidates = _candidate_orphans(hass, sweepable)
        seen: set[str] = hass.data.get(DATA_SWEEP_SEEN) or set()

        # Two-pass stability: only act on candidates that were flagged last pass too.
        stable = {eid: ieee for eid, ieee in candidates.items() if eid in seen}
        # Remember this pass's candidates for the next one.
        hass.data[DATA_SWEEP_SEEN] = set(candidates)

        if not stable:
            return
        ent_reg = er.async_get(hass)
        for eid, ieee in stable.items():
            if CLEANUP_ENABLED:
                ent_reg.async_remove(eid)
                _LOGGER.info("%s: removed orphan entity %s (device %s)", DOMAIN, eid, ieee)
            else:
                _LOGGER.info(
                    "%s: [dry-run] would remove orphan entity %s (device %s)",
                    DOMAIN, eid, ieee,
                )
    finally:
        hass.data[DATA_SWEEP_RUNNING] = False


async def async_setup_orphan_sweep(hass: HomeAssistant) -> None:
    """Register the standalone orphan-sweep triggers (called from async_setup)."""
    hass.data.setdefault(DATA_SWEEP_SEEN, set())

    @callback
    def _kick(*_: Any) -> None:
        hass.async_create_task(_async_sweep(hass))

    # Startup, device (re)join / online / re-pair, and a periodic backstop for devices
    # that power on later. All three are idempotent and eventually-consistent.
    async_at_start(hass, _kick)
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _kick)
    async_track_time_interval(hass, _kick, BACKSTOP_INTERVAL)
