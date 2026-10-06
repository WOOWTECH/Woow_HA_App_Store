"""Relay state re-sync for 21-TYZGTH1CH-D1RF (_TZ3218_7fiyo3kv / TS000F).

Background
----------
The relay is a standard ZCL OnOff (0x0006) cluster. With OnOff attribute reporting configured
(quirk v1.0.35 — no more ``skip_configuration``), all *runtime* relay changes sync to HA fine
(physical button, HA control, Tuya-side). But after a **power-cycle** the module comes up at its
Power-on State (e.g. Off) and does **not** emit an attribute report for that boot state, and ZHA
does **not** re-read attributes when a device rejoins — so HA's ``switch`` keeps the pre-power-cycle
value until the next on-change event. (Confirmed: after a power-cycle the physical button still
updates HA, i.e. the reporting binding survives; only the boot state is missing.)

Fix
---
This is a full custom integration (like ``knob_rebind.py``), so it can reach the ZHA gateway and
force a read. It re-reads the OnOff ``on_off`` attribute from the device:
  * at HA startup,
  * on device-registry changes (a rejoin/re-pair updates the device), and
  * on a periodic backstop (a bare rejoin may fire no registry event, and the device sends no
    periodic reports), so HA converges to the real relay state within the backstop interval.

The device is matched by **manufacturer/model** (not a hard-coded IEEE), so it works on any server
and for multiple units. A read from the coordinator updates the zigpy cluster cache, which ZHA
propagates to the ``switch`` entity.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_start

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"

# Matched by manufacturer/model so it works on any server / multiple units.
MANUFACTURER = "_TZ3218_7fiyo3kv"
MODEL = "TS000F"
ENDPOINT = 1
ONOFF_CLUSTER = 0x0006  # standard ZCL OnOff — the real relay control/state cluster

SERVICE_RESYNC = "resync_relay"
# Backstop: guarantees convergence after a power-cycle even if no registry event fires.
# The read is one tiny frame for a single device; a few-minute cadence is negligible.
BACKSTOP_INTERVAL = timedelta(minutes=5)


async def _async_resync(hass: HomeAssistant) -> int:
    """Force-read OnOff ``on_off`` from each matching device.

    Returns the number of matching devices found (-1 if the ZHA gateway isn't ready yet).
    Safe to call repeatedly; a failed read (device briefly offline mid-power-cycle) is ignored.
    """
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway
    except ImportError:
        return 0  # ZHA not installed
    try:
        gateway = get_zha_gateway(hass)
    except (ValueError, KeyError):
        return -1  # ZHA still coming up — a later registry event / backstop will retry

    matched = 0
    for zdev in gateway.devices.values():
        if zdev.manufacturer != MANUFACTURER or zdev.model != MODEL:
            continue
        matched += 1
        try:
            cluster = zdev.device.endpoints[ENDPOINT].in_clusters[ONOFF_CLUSTER]
        except (KeyError, AttributeError):
            continue
        try:
            await cluster.read_attributes(["on_off"], allow_cache=False)
            _LOGGER.debug("%s: re-read on_off from %s", DOMAIN, zdev.ieee)
        except Exception as exc:  # noqa: BLE001 - device may be briefly offline
            _LOGGER.debug("%s: on_off re-read failed for %s: %s", DOMAIN, zdev.ieee, exc)
    return matched


async def async_setup_relay_resync(hass: HomeAssistant) -> None:
    """Register the relay-resync triggers + a manual service (called from async_setup)."""

    @callback
    def _kick(*_: Any) -> None:
        # Background task: consistent with the other woow helpers so it's never awaited during
        # HA's startup wrap-up. getattr keeps very old HA cores working.
        create_bg = getattr(hass, "async_create_background_task", None)
        if create_bg is not None:
            create_bg(_async_resync(hass), name="woow_zha_quirks relay_resync")
        else:
            hass.async_create_task(_async_resync(hass))

    async def _service(_call: Any) -> None:
        n = await _async_resync(hass)
        _LOGGER.info("%s: %s ran (%d device(s) matched)", DOMAIN, SERVICE_RESYNC, max(n, 0))

    hass.services.async_register(DOMAIN, SERVICE_RESYNC, _service)

    # Startup (existing device), device (re)join/re-pair, and a periodic backstop.
    async_at_start(hass, _kick)
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _kick)
    async_track_time_interval(hass, _kick, BACKSTOP_INTERVAL)
