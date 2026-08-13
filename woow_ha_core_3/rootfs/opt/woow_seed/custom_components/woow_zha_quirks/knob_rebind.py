"""Self-healing ZHA group bind for the 4-58E8017 rotary knob (TS0034 / _TZ3000_ocqo8iwd).

Background
----------
This Tuya rotary knob is a *controller*: it transmits its gestures only as an APS group
multicast to a Zigbee group, never as a unicast to the coordinator. ZHA's automatic
unicast "bind to coordinator" performed on pairing is therefore **ignored** by the
firmware, and a (re-)pair wipes the knob's previous group bind. With no delivery path the
knob's read-only entities (On/Off ``binary_sensor``, Brightness / Colour-Temperature
``sensor``) stay stuck on "Unknown" because no command ever reaches ZHA — see
``docs/4-58E8017-sniff-findings.md`` / ``docs/4-58E8017-rebind-issue.html``.

A bare zigpy quirk cannot fix this (it can't reach the ZHA group/coordinator layer), but
this is a full custom integration, so it can recreate — in ZHA itself, with no manual
WebSocket calls — the two halves a working setup needs (the same thing ``zha/group/add`` +
``zha/groups/bind`` do):

  (A) ensure a ZHA group ``0x2760`` exists with the **coordinator** as a member, so the
      coordinator's radio subscribes to that multicast group; and
  (B) ZDO **group-bind** the knob's ep1 OnOff(6)/LevelControl(8)/ColorControl(768) output
      clusters to that group, so the knob transmits there.

It runs automatically — at startup (with a bounded retry, because the ZHA gateway may come
up after this component) and whenever a matching knob (re-)pairs — and on demand via the
``woow_zha_quirks.rebind_knob`` service. The knob is matched by manufacturer/model (not a
hard-coded IEEE), so it works on any server and for multiple units, and the coordinator
IEEE is auto-discovered.

NOTE: the very first time the group is created, the coordinator radio's multicast table may
need one ZHA reload/restart to take effect. Once the group is persisted by ZHA it is
re-applied to the radio on every startup, so later re-pairs only need the knob re-bound
(done here automatically) — no reload.

Verified against Home Assistant 2026.3.4 (standalone ``zha`` lib): gateway via
``homeassistant.components.zha.helpers.get_zha_gateway``; group create via
``gateway.async_create_zigpy_group(name, members, group_id)`` with
``zha.zigbee.group.GroupMemberReference``; group bind via
``device.async_bind_to_group(group_id, [ClusterBinding(...)])`` reusing ZHA's own
``ClusterBinding`` from ``homeassistant.components.zha.websocket_api`` (a Group-mode ZDO
``Bind_req``, ``addrmode=1``).
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

# The knob is matched by manufacturer/model so this works on any server / multiple units.
KNOB_MANUFACTURER = "_TZ3000_ocqo8iwd"
KNOB_MODEL = "TS0034"

GROUP_ID = 0x2760  # 10080 — the group the knob firmware multicasts to
GROUP_NAME = "knob_58e8017_0x2760"
KNOB_ENDPOINT = 1
# (binding name, cluster id) for the knob's ep1 OUTPUT (client) clusters
BIND_CLUSTERS: tuple[tuple[str, int], ...] = (
    ("OnOff", 0x0006),
    ("LevelControl", 0x0008),
    ("ColorControl", 0x0300),
)

SERVICE_REBIND = "rebind_knob"
# hass.data guard: ieee(str) -> device-registry id. A re-pair yields a new device id, which
# makes the stored value stale and triggers a fresh rebind without an HA restart.
DATA_REBOUND = "woow_zha_quirks_knob_rebound"
DATA_RETRY_ACTIVE = "woow_zha_quirks_knob_retry_active"

# Startup retry: the ZHA gateway can finish loading after this component, and an
# already-paired knob fires no entity "create" event, so a single attempt can miss.
_RETRY_ATTEMPTS = 8
_RETRY_DELAY = 15  # seconds


def _coordinator_endpoint(coordinator: Any) -> int:
    """Pick a usable coordinator endpoint id (prefer 1, as the Tuya gateway used)."""
    try:
        eps = [ep for ep in coordinator.device.endpoints if ep != 0]
    except Exception:  # noqa: BLE001
        return 1
    if 1 in eps:
        return 1
    return eps[0] if eps else 1


def _knob_ready(knob: Any) -> bool:
    """True once the knob is interviewed and its ep1 output clusters are present."""
    try:
        out = knob.device.endpoints[KNOB_ENDPOINT].out_clusters
    except (KeyError, AttributeError):
        return False
    return all(cid in out for _name, cid in BIND_CLUSTERS)


async def _async_rebind(hass: HomeAssistant, *, force: bool = False) -> int:
    """Ensure the group + group-bind exist for every paired knob.

    Returns the number of knobs still **pending** a successful bind (0 means nothing left
    to do — either none paired or all bound — so the startup retry loop can stop). Safe to
    call repeatedly: group creation and the ZDO group-bind are idempotent. ``force``
    ignores the dedup guard (used by the manual service).
    """
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway
        from homeassistant.components.zha.websocket_api import ClusterBinding
        from zha.zigbee.group import GroupMemberReference
    except ImportError:
        _LOGGER.debug("%s: ZHA not installed; skipping knob rebind", DOMAIN)
        return 0

    try:
        gateway = get_zha_gateway(hass)
    except (ValueError, KeyError):
        _LOGGER.debug("%s: ZHA gateway not ready; will retry", DOMAIN)
        return 1  # pending: ZHA still coming up

    coordinator = gateway.coordinator_zha_device
    if coordinator is None:
        return 1  # pending: ZHA still coming up

    knobs = [
        d
        for d in gateway.devices.values()
        if d.manufacturer == KNOB_MANUFACTURER and d.model == KNOB_MODEL
    ]
    if not knobs:
        return 0  # no knob paired — nothing to do

    done: dict[str, str] = hass.data.setdefault(DATA_REBOUND, {})
    dev_reg = dr.async_get(hass)
    coord_ep = _coordinator_endpoint(coordinator)

    pending = 0
    group_ensured = False
    for knob in knobs:
        ieee = str(knob.ieee)

        # Dedup like climate.py: a re-pair yields a new device-registry id, so a stale
        # guard value triggers a fresh rebind without needing an HA restart.
        dev_entry = dev_reg.async_get_device(
            connections={(dr.CONNECTION_ZIGBEE, ieee)}
        )
        dev_id = dev_entry.id if dev_entry else None
        if not force and dev_id is not None and done.get(ieee) == dev_id:
            continue

        if not _knob_ready(knob):
            _LOGGER.debug("%s: knob %s not interviewed yet; will retry", DOMAIN, ieee)
            pending += 1
            continue

        # (A) ensure group 0x2760 exists with the coordinator as a member (idempotent).
        if not group_ensured:
            member = GroupMemberReference(ieee=coordinator.ieee, endpoint_id=coord_ep)
            group = gateway.get_group(GROUP_ID)
            try:
                if group is None:
                    await gateway.async_create_zigpy_group(
                        GROUP_NAME, [member], GROUP_ID
                    )
                    _LOGGER.info(
                        "%s: created ZHA group 0x%04x with coordinator %s ep %s",
                        DOMAIN, GROUP_ID, coordinator.ieee, coord_ep,
                    )
                else:
                    await group.async_add_members([member])
            except Exception:  # noqa: BLE001
                _LOGGER.exception("%s: failed ensuring group 0x%04x", DOMAIN, GROUP_ID)
                pending += 1
                continue
            group_ensured = True

        # (B) group-bind the knob's ep1 output clusters to the group.
        bindings = [
            ClusterBinding(name=name, type="out", id=cid, endpoint_id=KNOB_ENDPOINT)
            for name, cid in BIND_CLUSTERS
        ]
        try:
            await knob.async_bind_to_group(GROUP_ID, bindings)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("%s: group-bind failed for knob %s", DOMAIN, ieee)
            pending += 1
            continue

        if dev_id is not None:
            done[ieee] = dev_id
        _LOGGER.info(
            "%s: group-bound knob %s ep%s OnOff/Level/Color -> group 0x%04x (10080)",
            DOMAIN, ieee, KNOB_ENDPOINT, GROUP_ID,
        )

    return pending


async def _retry_loop(hass: HomeAssistant) -> None:
    """Run rebind, retrying while knobs are still pending (gateway/knob not ready yet)."""
    if hass.data.get(DATA_RETRY_ACTIVE):
        return
    hass.data[DATA_RETRY_ACTIVE] = True
    try:
        for _attempt in range(_RETRY_ATTEMPTS):
            if await _async_rebind(hass) == 0:
                return
            await asyncio.sleep(_RETRY_DELAY)
    finally:
        hass.data[DATA_RETRY_ACTIVE] = False


async def async_setup_knob_rebind(hass: HomeAssistant) -> None:
    """Register the rebind service + auto-triggers (called from async_setup)."""

    async def _service(_call: Any) -> None:
        pending = await _async_rebind(hass, force=True)
        _LOGGER.info(
            "%s: %s service ran (%d knob(s) still pending)",
            DOMAIN, SERVICE_REBIND, pending,
        )

    hass.services.async_register(DOMAIN, SERVICE_REBIND, _service)

    @callback
    def _kick(*_: Any) -> None:
        # Background task: HA does NOT wait on these when wrapping up the startup phase, so the
        # (up to ~120s) retry loop can't block startup. getattr keeps very old HA cores working.
        create_bg = getattr(hass, "async_create_background_task", None)
        if create_bg is not None:
            create_bg(_retry_loop(hass), name="woow_zha_quirks knob_rebind retry")
        else:
            hass.async_create_task(_retry_loop(hass))

    @callback
    def _on_entity(event: Event) -> None:
        # A backing entity appearing is the reliable "device fully interviewed" signal on a
        # fresh pair — device-registry events can fire before clusters are known.
        if event.data.get("action") == "create":
            _kick()

    # Run at startup (existing knobs, with retry), and on later device/entity changes.
    async_at_start(hass, _kick)
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _kick)
    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _on_entity)
