"""Support for Template climates."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
)
from homeassistant.components.climate.const import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    ATTR_HVAC_MODE,
    ATTR_FAN_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    PRESET_NONE,
    HVACMode,
    HVACAction,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    DOMAIN as HOMEASSISTANT_DOMAIN,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.device import async_device_info_to_link_from_entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.script import Script

from .const import (
    CONF_AC_MODE,
    CONF_COLD_TOLERANCE,
    CONF_COOLER,
    CONF_FAN_MODE_ENTITY,
    CONF_FAN_MODES,
    CONF_HEATER,
    CONF_HOT_TOLERANCE,
    CONF_HUMIDITY_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_HVAC_MODE_ENTITY,
    CONF_HVAC_MODES,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_PRECISION,
    CONF_PRESET_MODE_ENTITY,
    CONF_PRESET_MODES,
    CONF_SET_FAN_MODE_ACTION,
    CONF_SET_HUMIDITY_ACTION,
    CONF_SET_HVAC_MODE_ACTION,
    CONF_SET_PRESET_MODE_ACTION,
    CONF_SET_SWING_HORIZONTAL_MODE_ACTION,
    CONF_SET_SWING_MODE_ACTION,
    CONF_SET_TEMPERATURE_ACTION,
    CONF_SWING_HORIZONTAL_MODE_ENTITY,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODE_ENTITY,
    CONF_SWING_MODES,
    CONF_TARGET_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMP_STEP,
    DEFAULT_NAME,
    DEFAULT_TEMP_STEP,
    DEFAULT_TOLERANCE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Default target temperature when no previous state exists
DEFAULT_TEMP = 21.0


# ============================================================================
# Config Entry Setup (UI-based configuration)
# ============================================================================


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Climate Template from a config entry (UI configuration)."""
    await _async_setup_simple_entry(hass, config_entry, async_add_entities)


async def _async_setup_simple_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SimpleClimate from a config entry (Simple Mode)."""
    options = config_entry.options

    _LOGGER.debug(
        "Setting up SimpleClimate from config entry: %s",
        config_entry.entry_id,
    )

    # Extract configuration from options
    name = options.get(CONF_NAME, DEFAULT_NAME)
    sensor_entity_id = options.get(CONF_TEMPERATURE_SENSOR)
    heater_entity_id = options.get(CONF_HEATER)
    cooler_entity_id = options.get(CONF_COOLER)
    ac_mode = options.get(CONF_AC_MODE, False)

    min_temp = options.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
    max_temp = options.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)
    temp_step = options.get(CONF_TEMP_STEP, DEFAULT_TEMP_STEP)
    precision = options.get(CONF_PRECISION)
    cold_tolerance = options.get(CONF_COLD_TOLERANCE, DEFAULT_TOLERANCE)
    hot_tolerance = options.get(CONF_HOT_TOLERANCE, DEFAULT_TOLERANCE)

    hvac_modes = options.get(CONF_HVAC_MODES, [HVACMode.OFF, HVACMode.HEAT])
    fan_modes = options.get(CONF_FAN_MODES)
    preset_modes = options.get(CONF_PRESET_MODES)
    swing_modes = options.get(CONF_SWING_MODES)
    swing_horizontal_modes = options.get(CONF_SWING_HORIZONTAL_MODES)

    # Entity selectors for TX/RX targets
    hvac_mode_entity_id = options.get(CONF_HVAC_MODE_ENTITY)
    fan_mode_entity_id = options.get(CONF_FAN_MODE_ENTITY)
    preset_mode_entity_id = options.get(CONF_PRESET_MODE_ENTITY)
    swing_mode_entity_id = options.get(CONF_SWING_MODE_ENTITY)
    swing_horizontal_mode_entity_id = options.get(CONF_SWING_HORIZONTAL_MODE_ENTITY)
    humidity_entity_id = options.get(CONF_HUMIDITY_ENTITY)
    target_temperature_entity_id = options.get(CONF_TARGET_TEMPERATURE_ENTITY)
    humidity_sensor_entity_id = options.get(CONF_HUMIDITY_SENSOR)

    # Action scripts — validate through SCRIPT_SCHEMA to convert
    # template strings (e.g. "{{ fan_mode }}") into Template objects
    def _make_script(action_data: list[dict]) -> Script:
        validated = cv.SCRIPT_SCHEMA(action_data)
        return Script(hass, validated, name, DOMAIN)

    set_temperature_script = None
    if action := options.get(CONF_SET_TEMPERATURE_ACTION):
        set_temperature_script = _make_script(action)

    set_hvac_mode_script = None
    if action := options.get(CONF_SET_HVAC_MODE_ACTION):
        set_hvac_mode_script = _make_script(action)

    set_fan_mode_script = None
    if action := options.get(CONF_SET_FAN_MODE_ACTION):
        set_fan_mode_script = _make_script(action)

    set_preset_mode_script = None
    if action := options.get(CONF_SET_PRESET_MODE_ACTION):
        set_preset_mode_script = _make_script(action)

    set_swing_mode_script = None
    if action := options.get(CONF_SET_SWING_MODE_ACTION):
        set_swing_mode_script = _make_script(action)

    set_swing_horizontal_mode_script = None
    if action := options.get(CONF_SET_SWING_HORIZONTAL_MODE_ACTION):
        set_swing_horizontal_mode_script = _make_script(action)

    set_humidity_script = None
    if action := options.get(CONF_SET_HUMIDITY_ACTION):
        set_humidity_script = _make_script(action)

    # Convert precision string to float if needed
    if precision is not None:
        try:
            precision = float(precision)
        except (ValueError, TypeError):
            precision = None

    # Create the climate entity
    entity = SimpleClimate(
        hass=hass,
        name=name,
        sensor_entity_id=sensor_entity_id,
        heater_entity_id=heater_entity_id,
        cooler_entity_id=cooler_entity_id,
        ac_mode=ac_mode,
        min_temp=min_temp,
        max_temp=max_temp,
        temp_step=temp_step,
        precision=precision,
        cold_tolerance=cold_tolerance,
        hot_tolerance=hot_tolerance,
        hvac_modes=hvac_modes,
        fan_modes=fan_modes,
        preset_modes=preset_modes,
        swing_modes=swing_modes,
        swing_horizontal_modes=swing_horizontal_modes,
        unique_id=config_entry.entry_id,
        hvac_mode_entity_id=hvac_mode_entity_id,
        fan_mode_entity_id=fan_mode_entity_id,
        preset_mode_entity_id=preset_mode_entity_id,
        swing_mode_entity_id=swing_mode_entity_id,
        swing_horizontal_mode_entity_id=swing_horizontal_mode_entity_id,
        humidity_entity_id=humidity_entity_id,
        target_temperature_entity_id=target_temperature_entity_id,
        humidity_sensor_entity_id=humidity_sensor_entity_id,
        set_temperature_script=set_temperature_script,
        set_hvac_mode_script=set_hvac_mode_script,
        set_fan_mode_script=set_fan_mode_script,
        set_preset_mode_script=set_preset_mode_script,
        set_swing_mode_script=set_swing_mode_script,
        set_swing_horizontal_mode_script=set_swing_horizontal_mode_script,
        set_humidity_script=set_humidity_script,
    )

    async_add_entities([entity])

    _LOGGER.info(
        "Created SimpleClimate entity '%s' with sensor '%s' and heater '%s'",
        name,
        sensor_entity_id,
        heater_entity_id,
    )


# ============================================================================
# SimpleClimate - Entity for Config Flow entries
# ============================================================================


class SimpleClimate(ClimateEntity, RestoreEntity):
    """A simple climate entity for config flow entries.

    This is similar to generic_thermostat but with more flexibility
    for fan modes, preset modes, and swing modes.
    """

    _attr_should_poll = False
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        sensor_entity_id: str,
        heater_entity_id: str,
        cooler_entity_id: str | None,
        ac_mode: bool,
        min_temp: float,
        max_temp: float,
        temp_step: float,
        precision: float | None,
        cold_tolerance: float,
        hot_tolerance: float,
        hvac_modes: list[str],
        fan_modes: list[str] | None,
        preset_modes: list[str] | None,
        swing_modes: list[str] | None,
        unique_id: str,
        swing_horizontal_modes: list[str] | None = None,
        # Entity selectors for TX/RX
        hvac_mode_entity_id: str | None = None,
        fan_mode_entity_id: str | None = None,
        preset_mode_entity_id: str | None = None,
        swing_mode_entity_id: str | None = None,
        swing_horizontal_mode_entity_id: str | None = None,
        humidity_entity_id: str | None = None,
        target_temperature_entity_id: str | None = None,
        humidity_sensor_entity_id: str | None = None,
        # Action script overrides
        set_temperature_script: Script | None = None,
        set_hvac_mode_script: Script | None = None,
        set_fan_mode_script: Script | None = None,
        set_preset_mode_script: Script | None = None,
        set_swing_mode_script: Script | None = None,
        set_swing_horizontal_mode_script: Script | None = None,
        set_humidity_script: Script | None = None,
    ) -> None:
        """Initialize the climate entity."""
        self._attr_name = name
        self._attr_unique_id = unique_id

        # Entity IDs for sensor and controls
        self.sensor_entity_id = sensor_entity_id
        self.heater_entity_id = heater_entity_id
        self.cooler_entity_id = cooler_entity_id
        self.ac_mode = ac_mode

        # Entity selectors for TX/RX targets
        self._hvac_mode_entity_id = hvac_mode_entity_id
        self._fan_mode_entity_id = fan_mode_entity_id
        self._preset_mode_entity_id = preset_mode_entity_id
        self._swing_mode_entity_id = swing_mode_entity_id
        self._swing_horizontal_mode_entity_id = swing_horizontal_mode_entity_id
        self._humidity_entity_id = humidity_entity_id
        self._target_temperature_entity_id = target_temperature_entity_id
        self._humidity_sensor_entity_id = humidity_sensor_entity_id

        # Action script overrides
        self._set_temperature_script = set_temperature_script
        self._set_hvac_mode_script = set_hvac_mode_script
        self._set_fan_mode_script = set_fan_mode_script
        self._set_preset_mode_script = set_preset_mode_script
        self._set_swing_mode_script = set_swing_mode_script
        self._set_swing_horizontal_mode_script = set_swing_horizontal_mode_script
        self._set_humidity_script = set_humidity_script

        # Temperature settings
        self._attr_min_temp = min_temp
        self._attr_max_temp = max_temp
        self._attr_target_temperature_step = temp_step
        self._attr_temperature_unit = hass.config.units.temperature_unit
        self._temp_precision = precision
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance

        # HVAC modes - ensure they are HVACMode enums
        self._attr_hvac_modes = [
            HVACMode(mode) if isinstance(mode, str) else mode for mode in hvac_modes
        ]

        # Guard: HEAT_COOL requires a cooler entity
        if HVACMode.HEAT_COOL in self._attr_hvac_modes and not cooler_entity_id:
            self._attr_hvac_modes = [
                m for m in self._attr_hvac_modes if m != HVACMode.HEAT_COOL
            ]
            _LOGGER.warning(
                "HEAT_COOL mode removed for %s: requires a cooler entity",
                name,
            )

        # Fan modes
        self._attr_fan_modes = fan_modes if fan_modes else None

        # Preset modes
        if preset_modes:
            self._attr_preset_modes = [PRESET_NONE, *preset_modes]
        else:
            self._attr_preset_modes = None

        # Swing modes
        self._attr_swing_modes = swing_modes if swing_modes else None
        self._attr_swing_horizontal_modes = (
            swing_horizontal_modes if swing_horizontal_modes else None
        )

        # State variables
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_preset_mode = PRESET_NONE if preset_modes else None
        self._attr_fan_mode = fan_modes[0] if fan_modes else None
        self._attr_swing_mode = swing_modes[0] if swing_modes else None
        self._attr_swing_horizontal_mode = (
            swing_horizontal_modes[0] if swing_horizontal_modes else None
        )
        self._attr_current_temperature: float | None = None
        self._attr_target_temperature = DEFAULT_TEMP
        self._attr_target_temperature_high: float | None = None
        self._attr_target_temperature_low: float | None = None
        self._attr_current_humidity: int | None = None
        self._attr_target_humidity: int | None = None

        # Internal state
        self._active = False
        self._heater_active = False  # Tracks whether heater is ON
        self._cooler_active = False  # Tracks whether cooler is ON
        self._temp_lock = asyncio.Lock()
        self._saved_target_temp: float | None = None

        # Device info - link to the heater or cooler device
        link_entity_id = heater_entity_id or cooler_entity_id
        if link_entity_id:
            self._attr_device_info = async_device_info_to_link_from_entity(
                hass, link_entity_id
            )

        # Supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

        if fan_modes:
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE

        if preset_modes:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

        if swing_modes:
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE

        if swing_horizontal_modes:
            self._attr_supported_features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE

        if humidity_entity_id or humidity_sensor_entity_id or set_humidity_script:
            self._attr_supported_features |= ClimateEntityFeature.TARGET_HUMIDITY

        if HVACMode.HEAT_COOL in self._attr_hvac_modes:
            self._attr_supported_features |= (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            )

    @property
    def precision(self) -> float:
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current HVAC action."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        # HEAT_COOL: check which device is active to determine action
        if self._attr_hvac_mode == HVACMode.HEAT_COOL:
            if self._heater_active:
                return HVACAction.HEATING
            if self.cooler_entity_id and self._cooler_active:
                return HVACAction.COOLING
            return HVACAction.IDLE

        if not self._is_device_active:
            return HVACAction.IDLE

        is_cooling = self._attr_hvac_mode == HVACMode.COOL or (
            self.ac_mode
            and self._attr_hvac_mode not in (HVACMode.HEAT, HVACMode.HEAT_COOL)
        )
        if is_cooling:
            return HVACAction.COOLING

        return HVACAction.HEATING

    @property
    def _is_device_active(self) -> bool:
        """Check if the relevant heater/cooler is currently active."""
        if self._attr_hvac_mode == HVACMode.HEAT_COOL:
            return self._heater_active or (
                self.cooler_entity_id is not None and self._cooler_active
            )
        is_cooling = self._attr_hvac_mode == HVACMode.COOL or (
            self.ac_mode
            and self._attr_hvac_mode not in (HVACMode.HEAT, HVACMode.HEAT_COOL)
        )
        if is_cooling and self.cooler_entity_id:
            return self._cooler_active
        return self._heater_active

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()

        # ---------------------------------------------------------------
        # Phase 1: Register state change listeners (order doesn't matter)
        # ---------------------------------------------------------------
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.sensor_entity_id], self._async_sensor_changed
            )
        )
        if self.heater_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self.heater_entity_id], self._async_switch_changed
                )
            )
        if self.cooler_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self.cooler_entity_id],
                    self._async_switch_changed,
                )
            )

        if self._fan_mode_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._fan_mode_entity_id],
                    self._async_fan_mode_entity_changed,
                )
            )

        if self._preset_mode_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._preset_mode_entity_id],
                    self._async_preset_mode_entity_changed,
                )
            )

        if self._swing_mode_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._swing_mode_entity_id],
                    self._async_swing_mode_entity_changed,
                )
            )

        if self._swing_horizontal_mode_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._swing_horizontal_mode_entity_id],
                    self._async_swing_horizontal_entity_changed,
                )
            )

        if self._hvac_mode_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._hvac_mode_entity_id],
                    self._async_hvac_mode_entity_changed,
                )
            )

        if self._target_temperature_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._target_temperature_entity_id],
                    self._async_target_temp_entity_changed,
                )
            )

        if self._humidity_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._humidity_entity_id],
                    self._async_humidity_entity_changed,
                )
            )

        if self._humidity_sensor_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._humidity_sensor_entity_id],
                    self._async_humidity_sensor_changed,
                )
            )

        # ---------------------------------------------------------------
        # Phase 2: Restore previous state (fallback values)
        # ---------------------------------------------------------------
        if (old_state := await self.async_get_last_state()) is not None:
            if (temp := old_state.attributes.get(ATTR_TEMPERATURE)) is not None:
                self._attr_target_temperature = float(temp)

            if old_state.state in [m.value for m in self._attr_hvac_modes]:
                self._attr_hvac_mode = HVACMode(old_state.state)

            if self._attr_preset_modes:
                if (preset := old_state.attributes.get(ATTR_PRESET_MODE)) in (
                    self._attr_preset_modes or []
                ):
                    self._attr_preset_mode = preset

            if self._attr_fan_modes:
                if (fan := old_state.attributes.get(ATTR_FAN_MODE)) in (
                    self._attr_fan_modes or []
                ):
                    self._attr_fan_mode = fan

            if self._attr_swing_modes:
                if (swing := old_state.attributes.get(ATTR_SWING_MODE)) in (
                    self._attr_swing_modes or []
                ):
                    self._attr_swing_mode = swing

            if (
                temp_high := old_state.attributes.get(ATTR_TARGET_TEMP_HIGH)
            ) is not None:
                self._attr_target_temperature_high = float(temp_high)
            if (temp_low := old_state.attributes.get(ATTR_TARGET_TEMP_LOW)) is not None:
                self._attr_target_temperature_low = float(temp_low)

        else:
            if self.ac_mode:
                self._attr_target_temperature = self._attr_max_temp
            else:
                self._attr_target_temperature = self._attr_min_temp

        # ---------------------------------------------------------------
        # Phase 3: Sync from current external entity states (overrides
        # restored state so the climate entity reflects reality)
        # ---------------------------------------------------------------
        sensor_state = self.hass.states.get(self.sensor_entity_id)
        if sensor_state and sensor_state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            self._async_update_temp(sensor_state)

        if self._hvac_mode_entity_id:
            hvac_state = self.hass.states.get(self._hvac_mode_entity_id)
            if hvac_state and hvac_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    mode = HVACMode(hvac_state.state)
                    if mode in self._attr_hvac_modes:
                        self._attr_hvac_mode = mode
                except ValueError:
                    pass

        if self._fan_mode_entity_id:
            fan_state = self.hass.states.get(self._fan_mode_entity_id)
            if fan_state and fan_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                if fan_state.state in (self._attr_fan_modes or []):
                    self._attr_fan_mode = fan_state.state

        if self._preset_mode_entity_id:
            preset_state = self.hass.states.get(self._preset_mode_entity_id)
            if preset_state and preset_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                if preset_state.state in (self._attr_preset_modes or []):
                    self._attr_preset_mode = preset_state.state

        if self._swing_mode_entity_id:
            swing_state = self.hass.states.get(self._swing_mode_entity_id)
            if swing_state and swing_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                if swing_state.state in (self._attr_swing_modes or []):
                    self._attr_swing_mode = swing_state.state

        if self._swing_horizontal_mode_entity_id:
            sh_state = self.hass.states.get(self._swing_horizontal_mode_entity_id)
            if sh_state and sh_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                if sh_state.state in (self._attr_swing_horizontal_modes or []):
                    self._attr_swing_horizontal_mode = sh_state.state

        if self._target_temperature_entity_id:
            tt_state = self.hass.states.get(self._target_temperature_entity_id)
            if tt_state and tt_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    self._attr_target_temperature = float(tt_state.state)
                except (ValueError, TypeError):
                    pass

        if self._humidity_entity_id:
            humidity_state = self.hass.states.get(self._humidity_entity_id)
            if humidity_state and humidity_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                try:
                    self._attr_target_humidity = int(float(humidity_state.state))
                except (ValueError, TypeError):
                    pass

        if self._humidity_sensor_entity_id:
            hs_state = self.hass.states.get(self._humidity_sensor_entity_id)
            if hs_state and hs_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    self._attr_current_humidity = int(float(hs_state.state))
                except (ValueError, TypeError):
                    pass

        # Initialize heater/cooler active tracking from external state
        if self.heater_entity_id:
            heater_state = self.hass.states.get(self.heater_entity_id)
            if heater_state is not None:
                self._heater_active = heater_state.state == STATE_ON
        if self.cooler_entity_id:
            cooler_state = self.hass.states.get(self.cooler_entity_id)
            if cooler_state is not None:
                self._cooler_active = cooler_state.state == STATE_ON

    async def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle temperature sensor state changes."""
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)
        await self._async_control_heating()  # Uses _temp_lock internally
        self.async_write_ha_state()

    @callback
    def _async_switch_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle heater/cooler switch state changes."""
        new_state = event.data["new_state"]
        if new_state is None:
            return
        # Sync internal tracking from external entity state
        entity_id = new_state.entity_id
        if entity_id == self.heater_entity_id:
            self._heater_active = new_state.state == STATE_ON
        elif self.cooler_entity_id and entity_id == self.cooler_entity_id:
            self._cooler_active = new_state.state == STATE_ON
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state: State) -> None:
        """Update current temperature from sensor state."""
        try:
            cur_temp = float(state.state)
            if not math.isfinite(cur_temp):
                raise ValueError(f"Sensor has illegal state: {state.state}")
            self._attr_current_temperature = cur_temp
        except ValueError as ex:
            _LOGGER.error("Unable to update temperature from sensor: %s", ex)

    async def _async_set_entity_state(self, entity_id: str, value: str) -> None:
        """TX helper: send a value to an external entity based on its domain."""
        domain = entity_id.split(".")[0]
        if domain in ("input_select", "select"):
            await self.hass.services.async_call(
                domain,
                "select_option",
                {ATTR_ENTITY_ID: entity_id, "option": value},
                blocking=True,
                context=self._context,
            )
        elif domain in ("switch", "input_boolean"):
            service = SERVICE_TURN_ON if value in (STATE_ON, "on") else SERVICE_TURN_OFF
            await self.hass.services.async_call(
                HOMEASSISTANT_DOMAIN,
                service,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
                context=self._context,
            )
        elif domain in ("input_number", "number"):
            await self.hass.services.async_call(
                domain,
                "set_value",
                {ATTR_ENTITY_ID: entity_id, "value": float(value)},
                blocking=True,
                context=self._context,
            )
        elif domain == "fan":
            await self.hass.services.async_call(
                "fan",
                "set_preset_mode",
                {ATTR_ENTITY_ID: entity_id, "preset_mode": value},
                blocking=True,
                context=self._context,
            )
        else:
            _LOGGER.warning("Unsupported entity domain for TX: %s", domain)

    @callback
    def _async_fan_mode_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle fan mode entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state in (self._attr_fan_modes or []):
            if self._attr_fan_mode != new_state.state:
                self._attr_fan_mode = new_state.state
                self.async_write_ha_state()

    @callback
    def _async_preset_mode_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle preset mode entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state in (self._attr_preset_modes or []):
            if self._attr_preset_mode != new_state.state:
                self._attr_preset_mode = new_state.state
                self.async_write_ha_state()

    @callback
    def _async_swing_mode_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle swing mode entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state in (self._attr_swing_modes or []):
            if self._attr_swing_mode != new_state.state:
                self._attr_swing_mode = new_state.state
                self.async_write_ha_state()

    @callback
    def _async_swing_horizontal_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle swing horizontal mode entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state in (self._attr_swing_horizontal_modes or []):
            if self._attr_swing_horizontal_mode != new_state.state:
                self._attr_swing_horizontal_mode = new_state.state
                self.async_write_ha_state()

    async def _async_hvac_mode_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle HVAC mode entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                mode = HVACMode(new_state.state)
                if mode in self._attr_hvac_modes and self._attr_hvac_mode != mode:
                    self._attr_hvac_mode = mode
                    await self._async_control_heating()
                    self.async_write_ha_state()
            except ValueError:
                pass

    async def _async_target_temp_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle target temperature entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                temp = float(new_state.state)
                if not math.isfinite(temp):
                    return
                if self._attr_target_temperature != temp:
                    self._attr_target_temperature = temp
                    await self._async_control_heating()
                    self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    @callback
    def _async_humidity_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle target humidity entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                humidity = int(float(new_state.state))
                if self._attr_target_humidity != humidity:
                    self._attr_target_humidity = humidity
                    self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    @callback
    def _async_humidity_sensor_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle humidity sensor state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                humidity = int(float(new_state.state))
                if self._attr_current_humidity != humidity:
                    self._attr_current_humidity = humidity
                    self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    async def _async_control_heating(self) -> None:
        """Control the heater/cooler based on current and target temperature."""
        async with self._temp_lock:
            if not self._active and self._attr_current_temperature is not None:
                self._active = True
                _LOGGER.debug(
                    "Climate %s activated. Current: %s, Target: %s",
                    self._attr_name,
                    self._attr_current_temperature,
                    self._attr_target_temperature,
                )

            if not self._active or self._attr_hvac_mode == HVACMode.OFF:
                return

            if self._attr_current_temperature is None:
                return

            current = self._attr_current_temperature

            if self._attr_hvac_mode == HVACMode.HEAT_COOL:
                # HEAT_COOL: three-way control with dual setpoints
                target_high = (
                    self._attr_target_temperature_high or self._attr_target_temperature
                )
                target_low = (
                    self._attr_target_temperature_low or self._attr_target_temperature
                )
                if target_high is None or target_low is None:
                    return

                too_cold = current < target_low - self._cold_tolerance
                too_hot = current > target_high + self._hot_tolerance

                if too_cold:
                    # Need heating: ensure cooler off, heater on
                    if self.cooler_entity_id and self._cooler_active:
                        await self._async_cooler_turn_off()
                    if not self._heater_active:
                        await self._async_heater_turn_on()
                elif too_hot:
                    # Need cooling: ensure heater off, cooler on
                    if self._heater_active:
                        await self._async_heater_turn_off()
                    if self.cooler_entity_id and not self._cooler_active:
                        await self._async_cooler_turn_on()
                else:
                    # Comfortable zone: turn off both
                    if self._heater_active:
                        await self._async_heater_turn_off()
                    if self.cooler_entity_id and self._cooler_active:
                        await self._async_cooler_turn_off()
            else:
                # Single mode: HEAT or COOL (binary path)
                if self._attr_target_temperature is None:
                    return

                target = self._attr_target_temperature
                too_cold = current < target - self._cold_tolerance
                too_hot = current > target + self._hot_tolerance

                is_cooling = self._attr_hvac_mode == HVACMode.COOL or (
                    self.ac_mode
                    and self._attr_hvac_mode not in (HVACMode.HEAT, HVACMode.HEAT_COOL)
                )

                if is_cooling:
                    # Cooling mode: turn on when too hot, off when cool enough
                    if too_hot and not self._is_device_active:
                        if self.cooler_entity_id:
                            await self._async_cooler_turn_on()
                        else:
                            await self._async_heater_turn_on()
                    elif not too_hot and self._is_device_active:
                        if self.cooler_entity_id:
                            await self._async_cooler_turn_off()
                        else:
                            await self._async_heater_turn_off()
                else:
                    # Heating mode: turn on when too cold, off when warm enough
                    if too_cold and not self._is_device_active:
                        await self._async_heater_turn_on()
                    elif not too_cold and self._is_device_active:
                        await self._async_heater_turn_off()

    async def _async_heater_turn_on(self) -> None:
        """Turn on the heater."""
        if not self.heater_entity_id:
            return
        self._heater_active = True
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HOMEASSISTANT_DOMAIN, SERVICE_TURN_ON, data, context=self._context
        )

    async def _async_heater_turn_off(self) -> None:
        """Turn off the heater."""
        if not self.heater_entity_id:
            return
        self._heater_active = False
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HOMEASSISTANT_DOMAIN, SERVICE_TURN_OFF, data, context=self._context
        )

    async def _async_cooler_turn_on(self) -> None:
        """Turn on the cooler."""
        if not self.cooler_entity_id:
            return
        self._cooler_active = True
        data = {ATTR_ENTITY_ID: self.cooler_entity_id}
        await self.hass.services.async_call(
            HOMEASSISTANT_DOMAIN, SERVICE_TURN_ON, data, context=self._context
        )

    async def _async_cooler_turn_off(self) -> None:
        """Turn off the cooler."""
        if not self.cooler_entity_id:
            return
        self._cooler_active = False
        data = {ATTR_ENTITY_ID: self.cooler_entity_id}
        await self.hass.services.async_call(
            HOMEASSISTANT_DOMAIN, SERVICE_TURN_OFF, data, context=self._context
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        if hvac_mode not in self._attr_hvac_modes:
            _LOGGER.error("Invalid HVAC mode: %s", hvac_mode)
            return

        self._attr_hvac_mode = hvac_mode

        # TX: action script > entity selector > default heater/cooler logic
        if self._set_hvac_mode_script:
            await self._set_hvac_mode_script.async_run(
                run_variables={"hvac_mode": str(hvac_mode)},
                context=self._context,
            )
        elif self._hvac_mode_entity_id:
            await self._async_set_entity_state(
                self._hvac_mode_entity_id, str(hvac_mode)
            )

        if hvac_mode == HVACMode.OFF:
            # Turn off both heater and cooler when mode is OFF
            if self._heater_active:
                await self._async_heater_turn_off()
            if self.cooler_entity_id and self._cooler_active:
                await self._async_cooler_turn_off()
        elif hvac_mode == HVACMode.HEAT_COOL:
            # HEAT_COOL: let control loop decide what to turn on/off
            await self._async_control_heating()
        else:
            # Ensure mutual exclusivity: turn off the device not needed
            is_cooling = hvac_mode == HVACMode.COOL or (
                self.ac_mode and hvac_mode not in (HVACMode.HEAT, HVACMode.HEAT_COOL)
            )
            if is_cooling:
                # Switching to cool: turn off heater if it was on
                if self._heater_active:
                    await self._async_heater_turn_off()
            else:
                # Switching to heat: turn off cooler if it was on
                if self.cooler_entity_id and self._cooler_active:
                    await self._async_cooler_turn_off()
            await self._async_control_heating()

        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temperature

        if (temp_high := kwargs.get(ATTR_TARGET_TEMP_HIGH)) is not None:
            self._attr_target_temperature_high = temp_high

        if (temp_low := kwargs.get(ATTR_TARGET_TEMP_LOW)) is not None:
            self._attr_target_temperature_low = temp_low

        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(HVACMode(hvac_mode))

        # TX: action script > entity selector > nothing
        if self._set_temperature_script:
            run_vars = {}
            if temperature is not None:
                run_vars["temperature"] = temperature
            if temp_high is not None:
                run_vars["target_temp_high"] = temp_high
            if temp_low is not None:
                run_vars["target_temp_low"] = temp_low
            await self._set_temperature_script.async_run(
                run_variables=run_vars,
                context=self._context,
            )
        elif self._target_temperature_entity_id and temperature is not None:
            await self._async_set_entity_state(
                self._target_temperature_entity_id, str(temperature)
            )

        await self._async_control_heating()
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        if self._attr_fan_modes and fan_mode in self._attr_fan_modes:
            self._attr_fan_mode = fan_mode

            # TX: action script > entity selector > nothing
            if self._set_fan_mode_script:
                await self._set_fan_mode_script.async_run(
                    run_variables={"fan_mode": fan_mode},
                    context=self._context,
                )
            elif self._fan_mode_entity_id:
                await self._async_set_entity_state(self._fan_mode_entity_id, fan_mode)

            self.async_write_ha_state()
        else:
            _LOGGER.error("Invalid fan mode: %s", fan_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if self._attr_preset_modes and preset_mode in self._attr_preset_modes:
            # Save current target temp when switching from NONE
            if self._attr_preset_mode == PRESET_NONE and preset_mode != PRESET_NONE:
                self._saved_target_temp = self._attr_target_temperature

            # Restore saved temp when switching back to NONE
            if preset_mode == PRESET_NONE and self._saved_target_temp is not None:
                self._attr_target_temperature = self._saved_target_temp

            self._attr_preset_mode = preset_mode

            # TX: action script > entity selector > nothing
            # Don't TX for PRESET_NONE (it's an internal-only state)
            if preset_mode != PRESET_NONE:
                if self._set_preset_mode_script:
                    await self._set_preset_mode_script.async_run(
                        run_variables={"preset_mode": preset_mode},
                        context=self._context,
                    )
                elif self._preset_mode_entity_id:
                    await self._async_set_entity_state(
                        self._preset_mode_entity_id, preset_mode
                    )

            self.async_write_ha_state()
        else:
            _LOGGER.error("Invalid preset mode: %s", preset_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new swing mode."""
        if self._attr_swing_modes and swing_mode in self._attr_swing_modes:
            self._attr_swing_mode = swing_mode

            # TX: action script > entity selector > nothing
            if self._set_swing_mode_script:
                await self._set_swing_mode_script.async_run(
                    run_variables={"swing_mode": swing_mode},
                    context=self._context,
                )
            elif self._swing_mode_entity_id:
                await self._async_set_entity_state(
                    self._swing_mode_entity_id, swing_mode
                )

            self.async_write_ha_state()
        else:
            _LOGGER.error("Invalid swing mode: %s", swing_mode)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Set new swing horizontal mode."""
        if (
            self._attr_swing_horizontal_modes
            and swing_horizontal_mode in self._attr_swing_horizontal_modes
        ):
            self._attr_swing_horizontal_mode = swing_horizontal_mode

            # TX: action script > entity selector > nothing
            if self._set_swing_horizontal_mode_script:
                await self._set_swing_horizontal_mode_script.async_run(
                    run_variables={"swing_horizontal_mode": swing_horizontal_mode},
                    context=self._context,
                )
            elif self._swing_horizontal_mode_entity_id:
                await self._async_set_entity_state(
                    self._swing_horizontal_mode_entity_id, swing_horizontal_mode
                )

            self.async_write_ha_state()
        else:
            _LOGGER.error("Invalid swing horizontal mode: %s", swing_horizontal_mode)

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        self._attr_target_humidity = humidity

        # TX: action script > entity selector > nothing
        if self._set_humidity_script:
            await self._set_humidity_script.async_run(
                run_variables={"humidity": humidity},
                context=self._context,
            )
        elif self._humidity_entity_id:
            await self._async_set_entity_state(self._humidity_entity_id, str(humidity))

        self.async_write_ha_state()
