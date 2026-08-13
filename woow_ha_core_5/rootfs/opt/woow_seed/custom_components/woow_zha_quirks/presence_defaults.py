"""First-pairing default writer for WO_40117 (_TZE204_clrdrnya / TS0601).

The presence quirk exposes the device's config as number/select entities but writes nothing on
pairing. This helper writes a curated set of **optimal defaults** into the device **once, on first
pairing**, and persists that fact (via ``homeassistant.helpers.storage.Store``) so it never
re-writes on later HA restarts — that way any value the user later changes by hand survives. A
manual service (``woow_zha_quirks.apply_presence_defaults``) force-re-applies on demand.

Chosen profile (relay auto-controls a wired light in Local mode, ~6 m range, balanced tuning,
status LED on, light on with presence regardless of ambient brightness). Values are within the
live-verified entity ranges and firmware constraints (near/entry < max; block_time >= 1.5;
min_range >= 0.3; only supported enum options).

Ordering matters and is encoded in ``DEFAULTS`` below:
  * ``detection_distance_max`` (maximum range) is written BEFORE the near/entry distances, which the
    firmware requires to stay below it (else the write is rejected and reverts);
  * ``breaker_mode = Local`` is written LAST, so the auto-relay logic only engages after every
    parameter is set.

Writes go through the normal ``number.set_value`` / ``select.select_option`` services (the
already-verified DP write path), resolved by the stable unique_id ``{ieee}-1-{attribute_name}``.

Modelled on ``relay_resync.py`` / ``knob_rebind.py`` (gateway match by manufacturer/model, startup +
registry-event triggers with a bounded retry, and a manual service).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.start import async_at_start
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"

MANUFACTURER = "_TZE204_clrdrnya"
MODEL = "TS0601"
ENDPOINT = 1

SERVICE_APPLY = "apply_presence_defaults"

STORE_KEY = "woow_zha_quirks_presence_defaults"
STORE_VERSION = 1
DATA_STORE = "woow_zha_quirks_presence_defaults_store"
DATA_RETRY_ACTIVE = "woow_zha_quirks_presence_defaults_retry"

# Seconds between individual DP writes so the Tuya MCU digests each (esp. the cross-field
# distance order). Runs once, so a relaxed pace is fine.
WRITE_DELAY = 2.0
# Retry window for a fresh pair: the backing entities appear a few seconds after interview.
_RETRY_ATTEMPTS = 12
_RETRY_DELAY = 6.0

# Ordered (domain, attribute_name, value). attribute_name == the quirk's tuya_number/tuya_enum name,
# which is the unique_id suffix. DO NOT reorder without re-checking the cross-field rule.
DEFAULTS: list[tuple[str, str, Any]] = [
    ("select", "sensor_mode", "On"),                    # DP115 normal radar detection
    ("number", "move_sensitivity", 7),                  # DP2  1-9 (balanced hold)
    ("number", "entry_sensitivity", 6),                 # DP105 1-7 (quick entry)
    ("number", "detection_distance_max", 6.0),          # DP4  write BEFORE near/entry (must be < this)
    ("number", "detection_distance_min", 0.3),          # DP3  firmware floor (no near blind-zone)
    ("number", "entry_distance_indentation", 0.6),      # DP106 small edge shrink (< max)
    ("number", "detection_delay", 0.1),                 # DP101 entry-filter time (fast response)
    ("number", "fading_time", 30),                      # DP102 hold after last detection
    ("number", "block_time", 1.5),                      # DP112 firmware floor (anti-flicker)
    ("number", "illuminance_threshold", 420),           # DP110 max -> light on regardless of ambient
    ("select", "status_indication", "On"),              # DP109 status LED on
    ("select", "breaker_mode", "Local"),                # DP107 engage auto-relay LAST
]


def _get_store(hass: HomeAssistant) -> Store:
    store = hass.data.get(DATA_STORE)
    if store is None:
        store = Store(hass, STORE_VERSION, STORE_KEY)
        hass.data[DATA_STORE] = store
    return store


async def _apply_one(hass: HomeAssistant, ieee: str, ent_reg: er.EntityRegistry) -> bool:
    """Resolve + write all defaults for one device. Returns False if entities aren't ready yet."""
    resolved: dict[str, str] = {}
    for domain, attr, _value in DEFAULTS:
        eid = ent_reg.async_get_entity_id(domain, "zha", f"{ieee}-{ENDPOINT}-{attr}")
        if eid is None:
            _LOGGER.debug("%s: entity for %s not ready yet (%s)", DOMAIN, attr, ieee)
            return False
        resolved[attr] = eid

    for domain, attr, value in DEFAULTS:
        eid = resolved[attr]
        try:
            if domain == "number":
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": eid, "value": float(value)}, blocking=True,
                )
            else:
                await hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": eid, "option": str(value)}, blocking=True,
                )
            _LOGGER.debug("%s: %s = %s (%s)", DOMAIN, attr, value, eid)
        except Exception as exc:  # noqa: BLE001 - one bad write shouldn't abort the rest
            _LOGGER.warning("%s: failed to set %s=%s: %s", DOMAIN, attr, value, exc)
        await asyncio.sleep(WRITE_DELAY)

    # Best-effort health log: the device reports config errors on DP113.
    pr_eid = ent_reg.async_get_entity_id("sensor", "zha", f"{ieee}-{ENDPOINT}-parameter_result")
    pr = hass.states.get(pr_eid).state if pr_eid and hass.states.get(pr_eid) else "?"
    _LOGGER.info("%s: applied presence defaults to %s (parameter_result=%s)", DOMAIN, ieee, pr)
    return True


async def _async_apply(hass: HomeAssistant, *, force: bool = False) -> int:
    """Apply defaults to each matching device that hasn't been done yet.

    Returns the number of devices still **pending** (gateway/entities not ready) — 0 means nothing
    left to do (none paired, or all applied), so the retry loop can stop.
    """
    try:
        from homeassistant.components.zha.helpers import get_zha_gateway
    except ImportError:
        return 0  # ZHA not installed
    try:
        gateway = get_zha_gateway(hass)
    except (ValueError, KeyError):
        return 1  # ZHA still coming up — retry

    devices = [
        d for d in gateway.devices.values()
        if d.manufacturer == MANUFACTURER and d.model == MODEL
    ]
    if not devices:
        return 0  # none paired

    store = _get_store(hass)
    persisted: dict[str, Any] = await store.async_load() or {}
    ent_reg = er.async_get(hass)

    pending = 0
    changed = False
    for zdev in devices:
        ieee = str(zdev.ieee)
        if not force and persisted.get(ieee, {}).get("applied"):
            continue
        if not await _apply_one(hass, ieee, ent_reg):
            pending += 1  # entities not ready — retry later
            continue
        persisted[ieee] = {"applied": True}
        changed = True

    if changed:
        await store.async_save(persisted)
    return pending


async def _retry_loop(hass: HomeAssistant) -> None:
    """Run apply, retrying while a device is still pending (gateway/entities not ready yet)."""
    if hass.data.get(DATA_RETRY_ACTIVE):
        return
    hass.data[DATA_RETRY_ACTIVE] = True
    try:
        for _attempt in range(_RETRY_ATTEMPTS):
            if await _async_apply(hass) == 0:
                return
            await asyncio.sleep(_RETRY_DELAY)
    finally:
        hass.data[DATA_RETRY_ACTIVE] = False


async def async_setup_presence_defaults(hass: HomeAssistant) -> None:
    """Register the apply service + auto-triggers (called from async_setup)."""
    _get_store(hass)  # create the Store early

    async def _service(_call: Any) -> None:
        pending = await _async_apply(hass, force=True)
        _LOGGER.info(
            "%s: %s service ran (%d device(s) still pending)", DOMAIN, SERVICE_APPLY, pending,
        )

    hass.services.async_register(DOMAIN, SERVICE_APPLY, _service)

    @callback
    def _kick(*_: Any) -> None:
        # Background task: HA does NOT wait on these when wrapping up the startup phase, so the
        # (up to ~120s) retry loop can't block startup. getattr keeps very old HA cores working.
        create_bg = getattr(hass, "async_create_background_task", None)
        if create_bg is not None:
            create_bg(_retry_loop(hass), name="woow_zha_quirks presence_defaults retry")
        else:
            hass.async_create_task(_retry_loop(hass))

    @callback
    def _on_entity(event: Event) -> None:
        # A backing entity appearing is the reliable "device fully interviewed" signal on a fresh
        # pair (device-registry events can fire before the clusters/entities are known).
        if event.data.get("action") == "create":
            _kick()

    async_at_start(hass, _kick)
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _kick)
    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _on_entity)
