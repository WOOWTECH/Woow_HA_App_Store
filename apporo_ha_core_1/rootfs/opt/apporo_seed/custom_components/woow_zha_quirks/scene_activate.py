"""Auto-activate the 7-58E8021 / 12-70E8306 scene-switch buttons on ZHA.

Background
----------
Gateway sniff (``docs/7-12-gateway-full-sniff-findings.md``) showed these Tuya scene panels only
transmit a physical press once the pressed gang's endpoint has a **stored scene in group
``0x270f``**: a press then emits ``OnOff cmd 0xFB`` from that gang's endpoint, unicast to the
coordinator (caught by ``ScenePressOnOffCluster`` in the quirks → toggles the HA switch). The
Tuya gateway does this at pairing; ZHA never does, so on ZHA the buttons are inert.

This module replicates the gateway's activation, automatically. For every matched device, on
each endpoint it:
  1. ``Scenes AddScene(group=0x270f, scene=0xff)`` on the device's Scenes server cluster, and
  2. binds the endpoint's **output** OnOff cluster to the coordinator (so the ``0xFB`` is delivered).

The stored scene + bind persist in the device across ZHA restarts, so a plain restart needs no
re-activation; a **re-pair** wipes them, so this runs again on (re-)join. It runs at startup
(bounded retry, since the ZHA gateway may come up after this component), whenever a matching
device (re-)pairs, and on demand via ``woow_zha_quirks.activate_scene_switches``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.start import async_at_start

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"

# (manufacturer, model) of the scene panels that need activating.
TARGETS = {("_TZ3000_hebcnahz", "TS0034"), ("_TZ3000_klkkwshz", "TS0022")}
ONOFF = 0x0006
SCENES = 0x0005
GROUP_ID = 0x270F  # 9999 — the group the Tuya gateway stores the button scene in
SCENE_ID = 0xFF

SERVICE_ACTIVATE = "activate_scene_switches"
# hass.data guard: ieee(str) -> device-registry id. A re-pair yields a new device id, which makes
# the stored value stale and triggers a fresh activation without needing an HA restart.
DATA_DONE = "woow_zha_quirks_scene_activated"
DATA_RETRY_ACTIVE = "woow_zha_quirks_scene_retry_active"

_RETRY_ATTEMPTS = 8
_RETRY_DELAY = 15  # seconds


async def _activate_device(zdev: Any) -> bool:
    """Activate every endpoint of one device. Returns True if all steps succeeded."""
    ok = True
    dev = zdev.device
    for ep_id, ep in dev.endpoints.items():
        if ep_id == 0:
            continue
        scenes = getattr(ep, "in_clusters", {}).get(SCENES)
        if scenes is not None:
            try:
                await scenes.add(GROUP_ID, SCENE_ID, 0, "")
            except Exception as exc:  # noqa: BLE001 - device may be briefly offline
                _LOGGER.debug("%s: AddScene failed %s ep%s: %s", DOMAIN, zdev.ieee, ep_id, exc)
                ok = False
        out = getattr(ep, "out_clusters", {}).get(ONOFF)
        if out is not None:
            try:
                await out.bind()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("%s: bind out-OnOff failed %s ep%s: %s", DOMAIN, zdev.ieee, ep_id, exc)
                ok = False
    return ok


async def _async_activate(hass: HomeAssistant, *, force: bool = False) -> int:
    """Activate all matched panels. Returns the number still **pending** (0 = nothing left)."""
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway
    except ImportError:
        return 0
    try:
        gateway = get_zha_gateway(hass)
    except (ValueError, KeyError):
        return 1  # ZHA still coming up — retry

    panels = [
        d for d in gateway.devices.values() if (d.manufacturer, d.model) in TARGETS
    ]
    if not panels:
        return 0

    done: dict[str, str] = hass.data.setdefault(DATA_DONE, {})
    dev_reg = dr.async_get(hass)
    pending = 0
    for zdev in panels:
        ieee = str(zdev.ieee)
        entry = dev_reg.async_get_device(connections={(dr.CONNECTION_ZIGBEE, ieee)})
        dev_id = entry.id if entry else None
        if not force and dev_id is not None and done.get(ieee) == dev_id:
            continue
        if await _activate_device(zdev):
            if dev_id is not None:
                done[ieee] = dev_id
            _LOGGER.info("%s: activated scene switch %s (grp 0x%04x)", DOMAIN, ieee, GROUP_ID)
        else:
            pending += 1
    return pending


async def _retry_loop(hass: HomeAssistant) -> None:
    if hass.data.get(DATA_RETRY_ACTIVE):
        return
    hass.data[DATA_RETRY_ACTIVE] = True
    try:
        for _ in range(_RETRY_ATTEMPTS):
            if await _async_activate(hass) == 0:
                return
            await asyncio.sleep(_RETRY_DELAY)
    finally:
        hass.data[DATA_RETRY_ACTIVE] = False


async def async_setup_scene_activate(hass: HomeAssistant) -> None:
    """Register the activation service + auto-triggers (called from async_setup)."""

    async def _service(_call: Any) -> None:
        pending = await _async_activate(hass, force=True)
        _LOGGER.info("%s: %s ran (%d still pending)", DOMAIN, SERVICE_ACTIVATE, pending)

    hass.services.async_register(DOMAIN, SERVICE_ACTIVATE, _service)

    @callback
    def _kick(*_: Any) -> None:
        # Background task: HA does NOT wait on these when wrapping up the startup phase, so the
        # (up to ~120s) retry loop can't block startup. getattr keeps very old HA cores working.
        create_bg = getattr(hass, "async_create_background_task", None)
        if create_bg is not None:
            create_bg(_retry_loop(hass), name="woow_zha_quirks scene_activate retry")
        else:
            hass.async_create_task(_retry_loop(hass))

    @callback
    def _on_entity(event: Event) -> None:
        if event.data.get("action") == "create":
            _kick()

    async_at_start(hass, _kick)
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _kick)
    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _on_entity)
