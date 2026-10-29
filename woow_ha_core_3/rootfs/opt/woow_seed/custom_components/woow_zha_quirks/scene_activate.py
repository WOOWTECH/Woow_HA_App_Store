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
  1. ``Groups AddGroup(0x270f)`` — the gateway did this at the device's *original* pairing, so
     the two panels we own kept their membership when they moved over to ZHA. A factory-reset
     (or brand-new) panel arrives with an empty Group Table, and ZCL rejects ``AddScene`` for a
     group the device is not a member of, which would kill the whole activation. So add it
     explicitly; an already-joined device answers ``DUPLICATE_EXISTS``, which counts as success.
  2. ``Scenes AddScene(group=0x270f, scene=0xff)`` on the device's Scenes server cluster, and
  3. binds the endpoint's **output** OnOff cluster to the coordinator (so the ``0xFB`` is delivered).

The stored scene is only an *enablement token*: it is never recalled and carries no attribute
values — storing it is simply what makes the firmware willing to transmit a press. The
coordinator deliberately does **not** join group 0x270f, because the press we act on is the
``0xFB`` unicast, not the ``RecallScene`` multicast that accompanies it.

Every step's ZCL status is checked. A rejected command answers with a non-SUCCESS status rather
than raising, so without the check a refused ``AddScene`` would be recorded as "activated",
suppress all further retries, and leave the buttons inert with nothing in the log.

The stored scene + bind persist in the device across ZHA restarts, so a plain restart needs no
re-activation; a **re-pair** wipes them, so this runs again on (re-)join. It runs at startup
(bounded retry, since the ZHA gateway may come up after this component), whenever a matching
device (re-)pairs, and on demand via ``woow_zha_quirks.activate_scene_switches``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.start import async_at_start

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"

# (manufacturer, model) of the scene panels that need activating.
#
# NOT here on purpose: the TS0726 panels (9-241E8008TY / 10-66E8025). Those have no load output
# terminals, so their gangs are held in Switch mode, where the firmware reports every press
# immediately — no enablement needed. See docs/adr/0001-press-to-ha-via-coordinator.md.
TARGETS = {("_TZ3000_hebcnahz", "TS0034"), ("_TZ3000_klkkwshz", "TS0022")}
ONOFF = 0x0006
SCENES = 0x0005
GROUPS = 0x0004
GROUP_ID = 0x270F  # 9999 — the group the Tuya gateway stores the button scene in
SCENE_ID = 0xFF

_STATUS_SUCCESS = 0x00
_STATUS_DUPLICATE_EXISTS = 0x8A  # AddGroup on a group the device already belongs to

SERVICE_ACTIVATE = "activate_scene_switches"
# hass.data guard: ieee(str) -> device-registry id. A re-pair yields a new device id, which makes
# the stored value stale and triggers a fresh activation without needing an HA restart.
DATA_DONE = "woow_zha_quirks_scene_activated"
DATA_RETRY_ACTIVE = "woow_zha_quirks_scene_retry_active"

_RETRY_ATTEMPTS = 8
_RETRY_DELAY = 15  # seconds

# Stands in for a device ieee in the "pending" list while the ZHA gateway itself is unavailable.
_ZHA_NOT_READY = "<zha-gateway-not-ready>"


def _status_of(resp: Any) -> Any:
    """Pull the status out of a ZCL command response or a ZDO reply list."""
    status = getattr(resp, "status", None)
    if status is not None:
        return status
    if isinstance(resp, (list, tuple)) and resp:
        return resp[0]
    return resp


def _succeeded(status: Any, allow: tuple[int, ...] = ()) -> bool:
    """True if this status means the step landed. Anything unreadable counts as failure."""
    try:
        value = int(status)
    except (TypeError, ValueError):
        return False
    return value == _STATUS_SUCCESS or value in allow


async def _step(
    zdev: Any, ep_id: int, what: str, coro: Any, allow: tuple[int, ...] = ()
) -> bool:
    """Await one activation step and report whether it actually landed.

    A device that refuses the command answers with a non-SUCCESS status instead of raising, so
    both paths have to be handled or a refusal reads as success.
    """
    try:
        resp = await coro
    except Exception as exc:  # noqa: BLE001 - device may be briefly offline
        # Log the exception *type* as well: a delivery timeout stringifies to "", so the message
        # alone cannot tell an unreachable device apart from a genuinely wrong call.
        _LOGGER.debug(
            "%s: %s raised on %s ep%s: %s: %s",
            DOMAIN,
            what,
            zdev.ieee,
            ep_id,
            type(exc).__name__,
            exc,
        )
        return False
    status = _status_of(resp)
    if _succeeded(status, allow):
        return True
    _LOGGER.debug(
        "%s: %s refused on %s ep%s: status=%s", DOMAIN, what, zdev.ieee, ep_id, status
    )
    return False


async def _activate_device(zdev: Any) -> bool:
    """Activate every endpoint of one device. Returns True if all steps succeeded."""
    ok = True
    dev = zdev.device
    for ep_id, ep in dev.endpoints.items():
        if ep_id == 0:
            continue
        in_clusters = getattr(ep, "in_clusters", {})

        # 1. Group membership first — AddScene is rejected for a non-member group.
        #    `add` is the ZCL AddGroup command (Groups.ServerCommandDefs.add); do not confuse it
        #    with ZHA's device-level async_add_to_group helper.
        groups = in_clusters.get(GROUPS)
        if groups is not None:
            if not await _step(
                zdev,
                ep_id,
                "AddGroup",
                groups.add(GROUP_ID, ""),
                (_STATUS_DUPLICATE_EXISTS,),
            ):
                ok = False

        # 2. The enablement scene (never recalled — it just unlocks the press).
        scenes = in_clusters.get(SCENES)
        if scenes is not None:
            if not await _step(
                zdev, ep_id, "AddScene", scenes.add(GROUP_ID, SCENE_ID, 0, "")
            ):
                ok = False

        # 3. Delivery path for the 0xFB press command.
        out = getattr(ep, "out_clusters", {}).get(ONOFF)
        if out is not None:
            if not await _step(zdev, ep_id, "bind out-OnOff", out.bind()):
                ok = False
    return ok


async def _async_activate(hass: HomeAssistant, *, force: bool = False) -> list[str]:
    """Activate all matched panels. Returns the ieees still **pending** ([] = nothing left)."""
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway
    except ImportError:
        return []
    try:
        gateway = get_zha_gateway(hass)
    except (ValueError, KeyError):
        return [_ZHA_NOT_READY]  # ZHA still coming up — retry

    panels = [
        d for d in gateway.devices.values() if (d.manufacturer, d.model) in TARGETS
    ]
    if not panels:
        return []

    done: dict[str, str] = hass.data.setdefault(DATA_DONE, {})
    dev_reg = dr.async_get(hass)
    pending: list[str] = []
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
            pending.append(ieee)
    return pending


async def _retry_loop(hass: HomeAssistant) -> None:
    if hass.data.get(DATA_RETRY_ACTIVE):
        return
    hass.data[DATA_RETRY_ACTIVE] = True
    try:
        pending: list[str] = []
        for _ in range(_RETRY_ATTEMPTS):
            pending = await _async_activate(hass)
            if not pending:
                return
            await asyncio.sleep(_RETRY_DELAY)
        # Giving up quietly is what made the original bug invisible: the buttons were dead and
        # the log said nothing. Failure has to be loud enough to act on.
        _LOGGER.warning(
            "%s: scene-switch activation still failing after %d attempts (%s) — physical "
            "presses on these panels will not reach HA. Turn on debug logging for %s to see the "
            "per-step ZCL status, then re-run the %s.%s service.",
            DOMAIN,
            _RETRY_ATTEMPTS,
            ", ".join(pending),
            DOMAIN,
            DOMAIN,
            SERVICE_ACTIVATE,
        )
    finally:
        hass.data[DATA_RETRY_ACTIVE] = False


async def async_setup_scene_activate(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the activation service + auto-triggers (called from async_setup_entry)."""

    async def _service(_call: Any) -> None:
        pending = await _async_activate(hass, force=True)
        if pending:
            _LOGGER.warning(
                "%s: %s ran; still pending: %s", DOMAIN, SERVICE_ACTIVATE, ", ".join(pending)
            )
        else:
            _LOGGER.info("%s: %s ran; all panels activated", DOMAIN, SERVICE_ACTIVATE)

    hass.services.async_register(DOMAIN, SERVICE_ACTIVATE, _service)
    entry.async_on_unload(
        lambda: hass.services.async_remove(DOMAIN, SERVICE_ACTIVATE)
    )

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

    entry.async_on_unload(async_at_start(hass, _kick))
    entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _kick))
    entry.async_on_unload(hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _on_entity))
