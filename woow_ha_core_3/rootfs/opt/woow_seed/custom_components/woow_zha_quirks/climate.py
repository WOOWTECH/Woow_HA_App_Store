"""Unified HA-core climate entities for the WOOW / Simon AC panels.

ZHA's own climate entity (built from a Zigbee Thermostat cluster) is too limited for
these devices: its hvac_modes have no `fan_only`, its fan is hardcoded to auto/on (no
low/med/high), and it has no presets. So instead of producing a climate via the quirk,
this platform creates a normal **HA-core ClimateEntity** that wraps the quirk's existing
entities and exposes one combined climate:

  hvac_mode  off / cool / heat / fan_only   <- power switch + mode select
  fan_mode   low / medium / high / auto     <- fan select
  preset     (device-specific)              <- a select (scenario / sleep)
  target_temperature                        <- number (Thermostat setpoint)
  current_temperature                       <- sensor (Thermostat local_temperature)

It is auto-discovered: on HA start it scans the device registry for any known device
(see DEVICE_SPECS) and resolves the backing entities by their stable ZHA unique-id
suffixes, then hides them so only the single climate entity remains on the device card.

Staying in sync with the device is the hard part, because everything this entity shows is
second-hand. Three rules, all learned the hard way on real hardware (see
docs/adr/0001-backing-state-semantics.md):

  * The power switch is the only authority on off-vs-running. If it cannot be read, the
    hvac_mode is left alone -- never inferred from the mode select.
  * A backing entity that is *absent* from the state machine is ZHA rebuilding it and means
    nothing; a backing entity that is explicitly *unavailable* means the device is
    unreachable and makes this entity unavailable too.
  * The state-change subscription is a fast path, not a guarantee. A 60 s reconcile
    (SCAN_INTERVAL) bounds how long a missed delivery can keep this entity stale, and a
    5 min platform watchdog (WATCHDOG_INTERVAL) rebuilds a climate that has vanished.

Supported devices:
  - 14-66E7109TY  (_TZC200_qbuzgrdocufrqgdu / SM0308F) — Tuya 0xEF00 panel
  - 8-58E7101     (_TZ2000_cykrrj2x / SM0308C)        — standard-ZCL fan-coil thermostat

To add another device, append a DeviceSpec to DEVICE_SPECS.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
)
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_start
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"
DATA_CREATED = "woow_zha_quirks_climate_created"

# How often each climate reconciles itself against its backing entities. The
# state-change subscription is the fast path; this is the safety net that bounds how long
# a missed delivery can keep the entity stale. Reads the HA state machine only -- it
# produces no Zigbee traffic, so the integration stays local_push in substance.
SCAN_INTERVAL = timedelta(seconds=60)

# How often the platform re-runs discovery. Registry events already drive it; this only
# catches the case where the entity behind the `created` guard has vanished, which no
# event would report.
WATCHDOG_INTERVAL = timedelta(minutes=5)

# Roles that decide hvac_mode. If one of these is explicitly `unavailable` the device is
# unreachable and the climate must say so rather than serve a stale reading. The rest
# (fan, preset, temperature, current_temp) only fill in attributes, so losing them keeps
# the last known value and never affects availability.
ESSENTIAL_ROLES = ("power", "mode")

HVAC_TO_ACTION = {
    HVACMode.COOL: HVACAction.COOLING,
    HVACMode.HEAT: HVACAction.HEATING,
    HVACMode.FAN_ONLY: HVACAction.FAN,
}


@dataclass(frozen=True)
class DeviceSpec:
    """Per-device wiring for the wrapped climate entity."""

    manufacturer: str
    model: str
    # role -> ZHA unique-id suffix (unique_id is "{ieee}-1-{suffix}")
    role_suffix: dict[str, str]
    # climate hvac_mode <-> mode-select option strings (the select's enum member names)
    hvac_to_mode_option: dict[HVACMode, str]
    mode_option_to_hvac: dict[str, HVACMode]
    fan_modes: list[str]
    # preset (HA name) <-> preset-select option string
    preset_modes: list[str]
    preset_to_option: dict[str, str]
    option_to_preset: dict[str, str]
    default_preset: str
    min_temp: int = 15
    max_temp: int = 35
    temp_step: int = 1
    # divide the current-temp sensor state by this (1 if the sensor is already scaled)
    current_temp_divisor: float = 1.0

    @property
    def required_roles(self) -> set[str]:
        return set(self.role_suffix)


# ── 14-66E7109TY / SM0308F (Tuya 0xEF00 panel) — preserves the original behaviour ──
SM0308F_SPEC = DeviceSpec(
    manufacturer="_TZC200_qbuzgrdocufrqgdu",
    model="SM0308F",
    role_suffix={
        "power": "ac_power",
        "mode": "ac_mode",
        "fan": "ac_fan",
        "preset": "ac_scenario",
        "temperature": "occupied_cooling_setpoint",
        "current_temp": "local_temperature",
    },
    hvac_to_mode_option={
        HVACMode.COOL: "cool",
        HVACMode.HEAT: "heat",
        HVACMode.FAN_ONLY: "fan only",
    },
    mode_option_to_hvac={
        "cool": HVACMode.COOL,
        "heat": HVACMode.HEAT,
        "fan only": HVACMode.FAN_ONLY,
        "fan_only": HVACMode.FAN_ONLY,
    },
    fan_modes=["low", "medium", "high", "auto"],
    preset_modes=["standard", "sleep"],
    preset_to_option={"standard": "standard", "sleep": "sleep"},
    option_to_preset={"standard": "standard", "sleep": "sleep"},
    default_preset="standard",
)

# ── 8-58E7101 / SM0308C (standard-ZCL fan-coil thermostat) ──
SM0308C_SPEC = DeviceSpec(
    manufacturer="_TZ2000_cykrrj2x",
    model="SM0308C",
    role_suffix={
        "power": "6",  # auto-created OnOff switch -> unique_id "{ieee}-1-6"
        "mode": "system_mode",
        "fan": "fan_mode",
        "preset": "sleep_mode",
        "temperature": "occupied_cooling_setpoint",
        "current_temp": "local_temperature",
    },
    hvac_to_mode_option={
        HVACMode.COOL: "Cool",
        HVACMode.HEAT: "Heat",
        HVACMode.FAN_ONLY: "Fan",
    },
    mode_option_to_hvac={
        "Cool": HVACMode.COOL,
        "Heat": HVACMode.HEAT,
        "Fan": HVACMode.FAN_ONLY,
    },
    fan_modes=["low", "medium", "high", "auto"],
    preset_modes=["none", "sleep"],
    preset_to_option={"none": "Null", "sleep": "Sleep"},
    option_to_preset={"Null": "none", "Sleep": "sleep"},
    default_preset="none",
)

DEVICE_SPECS: list[DeviceSpec] = [SM0308F_SPEC, SM0308C_SPEC]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the WOOW climate platform (auto-discovery for all DEVICE_SPECS).

    Forwarded from the config entry since 1.4.0 (it used to be a discovery platform set up
    by async_load_platform). Unique ids are unchanged, so the existing entity registry rows
    are re-pointed at the entry rather than replaced -- see
    docs/adr/0005-config-entry-setup.md.
    """
    # ieee -> device-registry id of the device we built a climate for. Keyed by IEEE
    # (stable across a re-pair) but tied to the *device entry* so a remove+re-add (which
    # produces a fresh device id) rebuilds the climate without an HA restart. Cleared by
    # WoowClimate.async_will_remove_from_hass when the device/entity is torn down.
    created: dict[str, str] = hass.data.setdefault(DATA_CREATED, {})
    by_key = {(s.manufacturer, s.model): s for s in DEVICE_SPECS}

    @callback
    def _discover(*_: Any) -> None:
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        new_entities: list[WoowClimate] = []
        _LOGGER.debug("discover: running, live climates=%s", created)

        for device in list(dev_reg.devices.values()):
            spec = by_key.get((device.manufacturer, device.model))
            if spec is None:
                continue
            ieee = next(
                (val for typ, val in device.connections if typ == dr.CONNECTION_ZIGBEE),
                None,
            )
            if not ieee:
                continue
            # A disabled device has no live ZHA entities, and HA stamps disabled_by=DEVICE on
            # every entity attached to it. Building the climate now would occupy the `created`
            # guard below (so the later "Enable device" would never rebuild it) and leave our
            # own registry row disabled. Wait instead — enabling the device fires a
            # device-registry update, which calls us straight back. Drop any stale guard so
            # that rebuild is not skipped.
            if device.disabled_by is not None:
                _LOGGER.debug(
                    "discover: %s %s device disabled_by=%s; dropping guard and waiting",
                    spec.model, ieee, device.disabled_by,
                )
                created.pop(ieee, None)
                continue
            entries = er.async_entries_for_device(
                ent_reg, device.id, include_disabled_entities=True
            )
            roles: dict[str, str] = {}
            for entry in entries:
                if entry.platform != "zha":
                    continue
                uid = entry.unique_id or ""
                for role, suffix in spec.role_suffix.items():
                    if uid.endswith(f"-1-{suffix}"):
                        roles[role] = entry.entity_id
            missing = spec.required_roles - set(roles)
            if missing:
                _LOGGER.debug(
                    "%s %s not ready (missing %s, resolved %s); will retry",
                    spec.model, ieee, missing, roles,
                )
                continue

            # An entity for this IEEE is already live (whatever device entry it was built for),
            # so never build a second one for the same unique_id -- just re-attach it to the
            # current device entry. Deleting a ZHA device does NOT tear our climate down: our
            # row has no config entry, so HA only nulls its device_id, which leaves the entity
            # running but detached from the device card (and leaves `created` populated, since
            # async_will_remove_from_hass never fires). A re-pair usually restores the very same
            # device.id, so the guard alone would skip the device forever.
            if ieee in created:
                row = _existing_row(ent_reg, ieee)
                live = row is not None and hass.states.get(row.entity_id) is not None
                _LOGGER.debug(
                    "discover: %s %s guard hit (created=%s, device=%s, row=%s, live_state=%s)",
                    spec.model, ieee, created.get(ieee), device.id,
                    row.entity_id if row is not None else None, live,
                )
                if live:
                    _repair_row(ent_reg, row, device.id)
                    created[ieee] = device.id
                    _hide_backing(ent_reg, entries)
                    continue
                # The guard is held for an entity that is no longer in the state machine, so
                # nothing is driving this climate and no event will ever say so -- async_will_
                # remove_from_hass is what normally clears the guard, and it did not run. Drop
                # the guard and fall through to rebuild. This is the branch the 5-minute
                # watchdog exists to reach.
                _LOGGER.warning(
                    "WOOW ZHA Quirks: %s %s was guarded but its entity is gone; rebuilding",
                    spec.model, ieee,
                )
                created.pop(ieee, None)

            dev_name = device.name_by_user or device.name or f"{spec.model} {ieee}"
            # Claim the guard FIRST: _prepare_registry_row() below can create the registry row,
            # and the registry fires its "create" event synchronously -- straight into our own
            # _on_entity_added listener. Without the guard already set, that re-entrant
            # _discover() would build a second WoowClimate for the same unique_id.
            created[ieee] = device.id
            # Create/restore and repair our registry row BEFORE the entity is added -- see
            # _prepare_registry_row for why this can't be left to async_added_to_hass.
            _prepare_registry_row(ent_reg, ieee, device.id, _object_id(dev_name))
            _hide_backing(ent_reg, entries)
            new_entities.append(WoowClimate(hass, spec, ieee, roles, device.id, dev_name))
            _LOGGER.info(
                "WOOW ZHA Quirks: created climate for %s %s", spec.model, ieee
            )

        if new_entities:
            async_add_entities(new_entities)

    @callback
    def _on_entity_added(event: Event) -> None:
        # A backing entity (select/number/sensor) appearing after the device entry is
        # what we were waiting for on a fresh pair — the device-registry events alone
        # can fire before the entities are registered. Only react to new entities.
        if event.data.get("action") == "create":
            _LOGGER.debug(
                "entity registry create: %s; re-running discover", event.data.get("entity_id")
            )
            _discover()

    # discover at startup (ZHA entities exist by then) and on later device/entity changes.
    # All four hang off the config entry so a reload does not leave a second discover loop
    # and a second watchdog running against the same devices.
    entry.async_on_unload(async_at_start(hass, _discover))
    entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _discover))
    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _on_entity_added)
    )
    # Platform-level watchdog. It deliberately does NOT hang off an entity: the failure it
    # covers is "the climate is gone and nothing rebuilt it", and an entity that no longer
    # exists cannot poll itself.
    entry.async_on_unload(async_track_time_interval(hass, _discover, WATCHDOG_INTERVAL))


def _object_id(device_name: str) -> str:
    """Object id for the climate: device name minus the internal "N-" index prefix.

    e.g. "14-66E7109TY" -> "66e7109ty", "8-58E7101" -> "58e7101". Only takes effect on first
    creation; an existing registry row keeps whatever entity_id it already has.
    """
    return slugify(re.sub(r"^\d+[-_\s]+", "", device_name)) or slugify(device_name)


@callback
def _existing_row(ent_reg: er.EntityRegistry, ieee: str) -> er.RegistryEntry | None:
    """This climate's registry row, or None if it has never been registered."""
    eid = ent_reg.async_get_entity_id("climate", DOMAIN, f"{ieee}-climate")
    return ent_reg.async_get(eid) if eid is not None else None


@callback
def _repair_row(
    ent_reg: er.EntityRegistry, entry: er.RegistryEntry, device_id: str
) -> None:
    """Re-attach our row to its device and shed a stale automatic disable flag.

    Only the automatic DEVICE flag is cleared; a user's own disable is left untouched.
    """
    updates: dict[str, Any] = {}
    if entry.device_id != device_id:
        updates["device_id"] = device_id
    if entry.disabled_by is er.RegistryEntryDisabler.DEVICE:
        updates["disabled_by"] = None
    if updates:
        _LOGGER.info(
            "WOOW ZHA Quirks: repairing climate registry row %s: %s", entry.entity_id, updates
        )
        ent_reg.async_update_entity(entry.entity_id, **updates)


@callback
def _prepare_registry_row(
    ent_reg: er.EntityRegistry, ieee: str, device_id: str, object_id: str
) -> None:
    """Create/restore this climate's registry row and repair its device link + disabled flag.

    This must happen *before* async_add_entities(): a row that comes back disabled is skipped
    there, so the entity is never added and async_added_to_hass() -- the only other place that
    restores the device link -- never runs. That state then survives every restart.

    Two shapes need repairing:

    * A row left by a *previous* device entry for this IEEE (a re-pair usually yields a new
      device.id). It is re-pointed, not removed: async_remove() would merely move the row into
      deleted_entities, and the immediate re-add restores it verbatim -- including the very flags
      we are trying to shed -- while dropping device_id. (Removing also produced the "_2"
      entity-id suffix, because the old entity_id was still in use at that moment.)
    * A row restored from deleted_entities. async_get_or_create() brings back disabled_by and
      hidden_by but NOT device_id, so "disable -> delete while disabled -> re-pair" yields
      disabled_by=DEVICE with device_id=None. "Enable device" only clears the DEVICE flag on
      entities whose device_id matches that device, so nothing would ever clear it again.
    """
    entry = ent_reg.async_get_or_create(
        "climate", DOMAIN, f"{ieee}-climate", suggested_object_id=object_id
    )
    _repair_row(ent_reg, entry, device_id)


@callback
def _hide_backing(ent_reg: er.EntityRegistry, entries) -> None:
    """Hide EVERY ZHA entity on the device so only the climate entity shows.

    The climate is platform 'woow_zha_quirks', so filtering on the ZHA platform
    leaves it visible while hiding the backing entities (controls, sensors, lqi/rssi,
    and any future ZHA entity on this device).
    """
    for entry in entries:
        if entry.platform == "zha" and entry.hidden_by is None:
            ent_reg.async_update_entity(
                entry.entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION
            )


class WoowClimate(ClimateEntity, RestoreEntity):
    """One climate entity proxying a device's discrete ZHA entities (per DeviceSpec)."""

    # Polled on SCAN_INTERVAL purely to reconcile with the backing entities -- see
    # async_update(). No I/O, no Zigbee traffic.
    _attr_should_poll = True
    _attr_has_entity_name = False
    _enable_turn_on_off_backwards_compatibility = False

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        hass: HomeAssistant,
        spec: DeviceSpec,
        ieee: str,
        roles: dict[str, str],
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialise the climate from the resolved backing entity_ids."""
        self.hass = hass
        self._spec = spec
        self._ieee = ieee
        self._ent = roles  # role -> entity_id
        self._device_id = device_id
        self._attr_name = device_name

        self._attr_fan_modes = spec.fan_modes
        self._attr_preset_modes = spec.preset_modes
        self._attr_min_temp = spec.min_temp
        self._attr_max_temp = spec.max_temp
        self._attr_target_temperature_step = spec.temp_step

        self.entity_id = f"climate.{_object_id(device_name)}"
        self._attr_unique_id = f"{ieee}-climate"
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode: str | None = None
        self._attr_preset_mode = spec.default_preset
        self._attr_target_temperature: float | None = None
        self._attr_current_temperature: float | None = None
        self._last_on_mode = HVACMode.COOL

    # ───────────────────────── lifecycle / RX ─────────────────────────

    async def async_added_to_hass(self) -> None:
        """Subscribe to the backing entities and seed initial state."""
        await super().async_added_to_hass()

        # Attach this entity to the ZHA device card (YAML platforms have no config
        # entry, so DeviceInfo merge doesn't work — set the device_id explicitly).
        ent_reg = er.async_get(self.hass)
        entry = ent_reg.async_get(self.entity_id)
        if entry is not None and entry.device_id != self._device_id:
            ent_reg.async_update_entity(self.entity_id, device_id=self._device_id)

        if (last := await self.async_get_last_state()) is not None:
            try:
                mode = HVACMode(last.state)
                if mode in self._attr_hvac_modes and mode != HVACMode.OFF:
                    self._last_on_mode = mode
            except ValueError:
                pass

        _LOGGER.debug(
            "%s added_to_hass: subscribing to %s", self.entity_id, self._ent
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, list(self._ent.values()), self._async_backing_changed
            )
        )
        self._recompute()

    async def async_will_remove_from_hass(self) -> None:
        """Clear the discovery guard so a later re-pair rebuilds this climate.

        When the ZHA device is removed, HA tears down this entity; dropping our IEEE
        from the shared map lets _discover() recreate the climate on the next pair
        without needing an HA restart.
        """
        _LOGGER.debug(
            "%s will_remove_from_hass: dropping guard for %s", self.entity_id, self._ieee
        )
        created: dict[str, str] = self.hass.data.get(DATA_CREATED, {})
        created.pop(self._ieee, None)
        await super().async_will_remove_from_hass()

    @callback
    def _async_backing_changed(self, event: Event) -> None:
        new = event.data.get("new_state")
        _LOGGER.debug(
            "%s backing changed: %s -> %s",
            self.entity_id,
            event.data.get("entity_id"),
            "<removed>" if new is None else new.state,
        )
        self._recompute()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Reconcile against the backing entities.

        The state-change subscription is the fast path; this is the safety net. On
        2026-08-13 an entire ZHA restore batch never reached the listener and the entity
        sat on a stale reading for three minutes, recovering only when an unrelated later
        report happened to arrive -- with nothing in the design guaranteeing that it ever
        would. Re-reading here bounds that staleness to SCAN_INTERVAL.
        """
        self._recompute()

    def _raw(self, role: str) -> str | None:
        """The literal backing state, or None when the entity is not in the state machine.

        Absence and the literal "unavailable" mean different things and must not be
        conflated: absence is ZHA rebuilding the entity (transient, say nothing), while
        "unavailable" is ZHA reporting the device unreachable (surface it).
        """
        eid = self._ent.get(role)
        if eid is None:
            return None
        st = self.hass.states.get(eid)
        return None if st is None else st.state

    def _state(self, role: str) -> str | None:
        """Return a backing entity's usable state, or None if there isn't one."""
        raw = self._raw(role)
        if raw is None or raw in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return raw

    @property
    def available(self) -> bool:
        """False once ZHA reports the device unreachable.

        Only an explicit "unavailable" on a role that decides hvac_mode counts. A backing
        entity that is merely absent is ZHA rebuilding it, which lasts milliseconds and
        must not flap this entity.
        """
        return not any(self._raw(role) == STATE_UNAVAILABLE for role in ESSENTIAL_ROLES)

    @callback
    def _recompute(self) -> None:
        """Recompute climate facets from the backing entity states."""
        power = self._state("power")
        mode_opt = self._state("mode")
        # The power switch is the only authority on off-vs-running. When it cannot be read,
        # the honest answer is "unchanged": inferring from the mode select instead reports a
        # running mode for a unit that is off. That is what happened on 2026-08-13
        # 18:31:38.886 -- power='unavailable' produced hvac_mode=cool, corrected 106 ms later
        # only because the switch happened to be restored last.
        if power is not None:
            if power != STATE_ON:
                self._attr_hvac_mode = HVACMode.OFF
            elif mode_opt is not None and mode_opt in self._spec.mode_option_to_hvac:
                self._attr_hvac_mode = self._spec.mode_option_to_hvac[mode_opt]
                self._last_on_mode = self._attr_hvac_mode

        fan = self._state("fan")
        if fan in self._spec.fan_modes:
            self._attr_fan_mode = fan

        preset_opt = self._state("preset")
        if preset_opt is not None and preset_opt in self._spec.option_to_preset:
            self._attr_preset_mode = self._spec.option_to_preset[preset_opt]

        val = self._state("temperature")
        if val is not None:
            try:
                self._attr_target_temperature = float(val)
            except ValueError:
                pass
        cur = self._state("current_temp")
        if cur is not None:
            try:
                self._attr_current_temperature = float(cur) / self._spec.current_temp_divisor
            except ValueError:
                pass

        if _LOGGER.isEnabledFor(logging.DEBUG):
            # "<missing>" is an entity absent from the state machine (ZHA rebuilding it);
            # the literal "unavailable" is ZHA reporting the device unreachable. The two
            # drive different behaviour now, so the log has to keep them apart.
            snap = {
                role: "<missing>" if (raw := self._raw(role)) is None else raw
                for role in self._ent
            }
            _LOGGER.debug(
                "%s recompute: backing=%s -> available=%s hvac_mode=%s fan=%s preset=%s "
                "target=%s current=%s",
                self.entity_id, snap, self.available, self._attr_hvac_mode,
                self._attr_fan_mode, self._attr_preset_mode, self._attr_target_temperature,
                self._attr_current_temperature,
            )

    @property
    def hvac_action(self) -> HVACAction:
        """Approximate action from power + mode (no demand sensor on this unit)."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return HVAC_TO_ACTION.get(self._attr_hvac_mode, HVACAction.IDLE)

    # ───────────────────────── commands / TX ─────────────────────────

    async def _select(self, role: str, option: str) -> None:
        if role not in self._ent:
            return
        await self.hass.services.async_call(
            "select", "select_option",
            {ATTR_ENTITY_ID: self._ent[role], "option": option},
            blocking=False,
        )

    async def _power(self, on: bool) -> None:
        await self.hass.services.async_call(
            "switch", SERVICE_TURN_ON if on else SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self._ent["power"]},
            blocking=False,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Map hvac_mode to the power switch + mode select."""
        if hvac_mode not in self._attr_hvac_modes:
            return
        if hvac_mode == HVACMode.OFF:
            await self._power(False)
        else:
            await self._power(True)
            await self._select("mode", self._spec.hvac_to_mode_option[hvac_mode])
            self._last_on_mode = hvac_mode
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(HVACMode(hvac_mode))
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.hass.services.async_call(
                "number", "set_value",
                {ATTR_ENTITY_ID: self._ent["temperature"], "value": float(temperature)},
                blocking=False,
            )
            self._attr_target_temperature = float(temperature)
            self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in self._spec.fan_modes:
            return
        await self._select("fan", fan_mode)
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._spec.preset_modes:
            return
        await self._select("preset", self._spec.preset_to_option[preset_mode])
        self._attr_preset_mode = preset_mode
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(self._last_on_mode or HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
