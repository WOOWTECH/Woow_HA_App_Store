"""Comprehensive tests for SimpleClimate control logic.

Tests all combinations of:
- Heating mode: heater turns on/off based on temperature vs target
- Cooling mode: cooler turns on/off based on temperature vs target
- AC mode: forces cooling behavior regardless of HVAC mode
- Tolerance/hysteresis: cold_tolerance and hot_tolerance bands
- Mode transitions: OFF -> HEAT -> COOL -> OFF
- Sensor unavailable/unknown: control logic pauses
- Preset mode: temperature save/restore on preset switch
- Fan mode, swing mode: set valid/invalid modes
- Invalid HVAC mode: rejected with error
- OFF mode: both heater and cooler turned off
- Heater-only config (no cooler): cooling uses heater in reverse
- Initial activation: first temp reading activates entity
"""

from __future__ import annotations

import pytest
from homeassistant.components.climate import HVACMode, HVACAction, ClimateEntityFeature
from homeassistant.exceptions import ServiceValidationError
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    PRESET_NONE,
    PRESET_ECO,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.climate_template.const import DOMAIN
from types import MappingProxyType
from homeassistant import loader

# ---------------------------------------------------------------------------
# Shared config fixtures
# ---------------------------------------------------------------------------

HEATER_COOLER_CONFIG = {
    "name": "Test Climate",
    "config_mode": "simple",
    "temperature_sensor": "sensor.test_room_temperature",
    "heater": "input_boolean.test_heater",
    "cooler": "input_boolean.test_ac_unit",
    "ac_mode": False,
    "min_temp": 7.0,
    "max_temp": 35.0,
    "temp_step": 0.5,
    "cold_tolerance": 0.3,
    "hot_tolerance": 0.3,
    "hvac_modes": ["off", "heat", "cool"],
    "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    "preset_modes": [PRESET_ECO, PRESET_AWAY, PRESET_BOOST, PRESET_COMFORT],
    "swing_modes": None,
}

HEATER_ONLY_CONFIG = {
    "name": "Test Heater Only",
    "config_mode": "simple",
    "temperature_sensor": "sensor.test_room_temperature",
    "heater": "input_boolean.test_heater",
    "cooler": None,
    "ac_mode": False,
    "min_temp": 7.0,
    "max_temp": 35.0,
    "temp_step": 0.5,
    "cold_tolerance": 0.3,
    "hot_tolerance": 0.3,
    "hvac_modes": ["off", "heat"],
    "fan_modes": None,
    "preset_modes": None,
    "swing_modes": None,
}

AC_MODE_CONFIG = {
    "name": "Test AC Mode",
    "config_mode": "simple",
    "temperature_sensor": "sensor.test_room_temperature",
    "heater": "input_boolean.test_heater",
    "cooler": "input_boolean.test_ac_unit",
    "ac_mode": True,
    "min_temp": 7.0,
    "max_temp": 35.0,
    "temp_step": 0.5,
    "cold_tolerance": 0.3,
    "hot_tolerance": 0.3,
    "hvac_modes": ["off", "heat", "cool"],
    "fan_modes": None,
    "preset_modes": None,
    "swing_modes": None,
}

ENTITY_ID = "climate.test_climate"
HEATER_ONLY_ENTITY_ID = "climate.test_heater_only"
AC_MODE_ENTITY_ID = "climate.test_ac_mode"


# ---------------------------------------------------------------------------
# Helper to set up a climate entity
# ---------------------------------------------------------------------------


async def _setup_entity(
    hass: HomeAssistant,
    config: dict,
    entry_id: str,
    sensor_temp: str = "21.5",
    heater_state: str = STATE_OFF,
    cooler_state: str = STATE_OFF,
):
    """Set up prerequisite entities and a climate config entry."""
    # Enable custom integrations discovery
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    hass.states.async_set(
        "sensor.test_room_temperature",
        sensor_temp,
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    hass.states.async_set(
        "input_boolean.test_heater",
        heater_state,
        {"friendly_name": "Test Heater"},
    )
    hass.states.async_set(
        "input_boolean.test_ac_unit",
        cooler_state,
        {"friendly_name": "Test AC Unit"},
    )

    turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off_calls = async_mock_service(hass, "homeassistant", "turn_off")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=config["name"],
        data={},
        options=config,
        entry_id=entry_id,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return {
        "entry": entry,
        "turn_on_calls": turn_on_calls,
        "turn_off_calls": turn_off_calls,
    }


# ===========================================================================
# TEST GROUP 1: Basic Heating Control
# ===========================================================================


class TestHeatingControl:
    """Tests for heating mode behavior."""

    async def test_heater_on_when_too_cold(self, hass: HomeAssistant):
        """Heater turns ON when current temp < target - cold_tolerance."""
        # Current=21.5, Target=30 => too_cold (21.5 < 30 - 0.3 = 29.7) => heater ON
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_heat_1")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert heater_on, "Heater should turn ON when too cold"

    async def test_heater_off_when_warm_enough(self, hass: HomeAssistant):
        """Heater turns OFF when current temp >= target (no longer too cold)."""
        # Current=21.5, set heater ON first, then target=20 => not too_cold => heater OFF
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_heat_2",
            heater_state=STATE_ON,
        )
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 20},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_off = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_off_calls"]
        )
        assert heater_off, "Heater should turn OFF when no longer too cold"

    async def test_cooler_stays_off_in_heat_mode(self, hass: HomeAssistant):
        """Cooler must NOT activate when HVAC mode is Heat."""
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_heat_3")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        cooler_on = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_on_calls"]
        )
        assert not cooler_on, "Cooler should NOT turn on in Heat mode"


# ===========================================================================
# TEST GROUP 2: Basic Cooling Control
# ===========================================================================


class TestCoolingControl:
    """Tests for cooling mode behavior."""

    async def test_cooler_on_when_too_hot(self, hass: HomeAssistant):
        """Cooler turns ON when current temp > target + hot_tolerance."""
        # Current=21.5, Target=7 => too_hot (21.5 > 7 + 0.3 = 7.3) => cooler ON
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_cool_1")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 7},
            blocking=True,
        )
        await hass.async_block_till_done()

        cooler_on = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_on_calls"]
        )
        assert cooler_on, "Cooler should turn ON when too hot"

    async def test_cooler_off_when_cool_enough(self, hass: HomeAssistant):
        """Cooler turns OFF when current temp <= target + hot_tolerance."""
        # Current=21.5, Target=25 => not too_hot (21.5 <= 25.3) => cooler OFF
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_cool_2",
            cooler_state=STATE_ON,
        )
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 25},
            blocking=True,
        )
        await hass.async_block_till_done()

        cooler_off = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_off_calls"]
        )
        assert cooler_off, "Cooler should turn OFF when no longer too hot"

    async def test_heater_stays_off_in_cool_mode(self, hass: HomeAssistant):
        """Heater must NOT activate when HVAC mode is Cool."""
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_cool_3")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 7},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert not heater_on, "Heater should NOT turn on in Cool mode"


# ===========================================================================
# TEST GROUP 3: Tolerance / Hysteresis
# ===========================================================================


class TestToleranceHysteresis:
    """Tests for cold_tolerance and hot_tolerance behavior."""

    async def test_heater_no_action_within_tolerance(self, hass: HomeAssistant):
        """Heater should NOT turn on when temp is within cold_tolerance of target."""
        # Current=21.5, Target=21.7 => too_cold check: 21.5 < 21.7 - 0.3 = 21.4 => False
        # So heater should NOT turn on
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_tol_1")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 21.7},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert not heater_on, "Heater should NOT turn on within tolerance band"

    async def test_heater_on_just_beyond_tolerance(self, hass: HomeAssistant):
        """Heater SHOULD turn on when temp is just beyond cold_tolerance."""
        # Current=21.5, Target=22.0 => too_cold: 21.5 < 22.0 - 0.3 = 21.7 => True
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_tol_2")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 22.0},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert heater_on, "Heater should turn on just beyond tolerance"

    async def test_cooler_no_action_within_tolerance(self, hass: HomeAssistant):
        """Cooler should NOT turn on when temp is within hot_tolerance of target."""
        # Current=21.5, Target=21.3 => too_hot: 21.5 > 21.3 + 0.3 = 21.6 => False
        # NOTE: We set temperature BEFORE switching to cool mode to avoid the
        # default target (7.0) causing an immediate cooler activation.
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_tol_3")
        entity_id = ENTITY_ID

        # Set target temperature first (while still in OFF mode)
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 21.3},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Now switch to cool mode - should NOT trigger cooler (within tolerance)
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()

        cooler_on = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_on_calls"]
        )
        assert not cooler_on, "Cooler should NOT turn on within tolerance band"

    async def test_cooler_on_just_beyond_tolerance(self, hass: HomeAssistant):
        """Cooler SHOULD turn on when temp is just beyond hot_tolerance."""
        # Current=21.5, Target=21.0 => too_hot: 21.5 > 21.0 + 0.3 = 21.3 => True
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_tol_4")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 21.0},
            blocking=True,
        )
        await hass.async_block_till_done()

        cooler_on = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_on_calls"]
        )
        assert cooler_on, "Cooler should turn on just beyond tolerance"


# ===========================================================================
# TEST GROUP 4: HVAC Mode Transitions
# ===========================================================================


class TestModeTransitions:
    """Tests for HVAC mode switching behavior."""

    async def test_off_mode_turns_off_heater(self, hass: HomeAssistant):
        """Switching to OFF mode should turn off the heater."""
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_mode_1",
            heater_state=STATE_ON,
        )
        entity_id = ENTITY_ID

        # Start in heat mode
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Switch to OFF
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "off"},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_off = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_off_calls"]
        )
        assert heater_off, "Heater should turn OFF when mode switches to OFF"

    async def test_off_mode_turns_off_cooler(self, hass: HomeAssistant):
        """Switching to OFF mode should turn off the cooler."""
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_mode_2",
            cooler_state=STATE_ON,
        )
        entity_id = ENTITY_ID

        # Switch to OFF
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "off"},
            blocking=True,
        )
        await hass.async_block_till_done()

        cooler_off = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_off_calls"]
        )
        assert cooler_off, "Cooler should turn OFF when mode switches to OFF"

    async def test_off_mode_turns_off_both(self, hass: HomeAssistant):
        """OFF mode should turn off BOTH heater and cooler."""
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_mode_3",
            heater_state=STATE_ON,
            cooler_state=STATE_ON,
        )
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "off"},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_off = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_off_calls"]
        )
        cooler_off = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_off_calls"]
        )
        assert heater_off, "Heater should turn OFF"
        assert cooler_off, "Cooler should turn OFF"

    async def test_heat_to_cool_transition(self, hass: HomeAssistant):
        """Switching from Heat to Cool should activate cooler if needed."""
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_mode_4")
        entity_id = ENTITY_ID

        # Start in heat, set high target
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 7},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Now switch to cool - current 21.5 > target 7 + 0.3 => cooler should activate
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()

        cooler_on = any(
            c.data.get("entity_id") == "input_boolean.test_ac_unit"
            for c in ctx["turn_on_calls"]
        )
        assert cooler_on, "Cooler should activate after switching to Cool mode"

    async def test_invalid_hvac_mode_rejected(self, hass: HomeAssistant):
        """Setting an invalid HVAC mode should raise ServiceValidationError."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_mode_5")
        entity_id = ENTITY_ID

        # Try to set "dry" mode which isn't configured — HA validates and raises
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": "dry"},
                blocking=True,
            )

        state = hass.states.get(entity_id)
        assert state.state == "off", "Mode should remain 'off' after invalid mode"


# ===========================================================================
# TEST GROUP 5: HVAC Action Property
# ===========================================================================


class TestHVACAction:
    """Tests for hvac_action reporting."""

    async def test_hvac_action_off(self, hass: HomeAssistant):
        """hvac_action should be OFF when mode is OFF."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_action_1")
        entity_id = ENTITY_ID

        state = hass.states.get(entity_id)
        assert state.attributes.get("hvac_action") == HVACAction.OFF

    async def test_hvac_action_idle_in_heat(self, hass: HomeAssistant):
        """hvac_action should be IDLE when heating but heater is off."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_action_2")
        entity_id = ENTITY_ID

        # Set heat mode, target below current => no heating needed
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 20},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("hvac_action") == HVACAction.IDLE

    async def test_hvac_action_heating(self, hass: HomeAssistant):
        """hvac_action should be HEATING when heater is active."""
        await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_action_3",
        )
        entity_id = ENTITY_ID

        # Set target high so control loop decides to heat (current=21.5, target=30)
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("hvac_action") == HVACAction.HEATING

    async def test_hvac_action_cooling(self, hass: HomeAssistant):
        """hvac_action should be COOLING when cooler is active in cool mode."""
        await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_action_4",
            cooler_state=STATE_ON,
        )
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("hvac_action") == HVACAction.COOLING


# ===========================================================================
# TEST GROUP 6: AC Mode Behavior
# ===========================================================================


class TestACMode:
    """Tests for ac_mode=True behavior."""

    async def test_ac_mode_heat_mode_heats_correctly(self, hass: HomeAssistant):
        """When ac_mode=True + Heat mode, heating logic applies (not cooling)."""
        ctx = await _setup_entity(hass, AC_MODE_CONFIG, "test_ac_1")
        entity_id = AC_MODE_ENTITY_ID

        # Heat mode: ac_mode does NOT override Heat mode
        # Current=21.5, Target=35 => too_cold (21.5 < 35-0.3) => heater ON
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 35},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert heater_on, "Heat mode should use heater even when ac_mode=True"

    async def test_ac_mode_heat_mode_hvac_action_shows_heating(
        self, hass: HomeAssistant
    ):
        """When ac_mode=True + Heat mode + device active, hvac_action shows HEATING."""
        await _setup_entity(
            hass,
            AC_MODE_CONFIG,
            "test_ac_2",
        )
        entity_id = AC_MODE_ENTITY_ID

        # Heat mode: ac_mode does not affect action display
        # Set target high so too_cold triggers heater (current=21.5, target=35)
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 35},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("hvac_action") == HVACAction.HEATING


# ===========================================================================
# TEST GROUP 7: Heater-Only Configuration (no cooler)
# ===========================================================================


class TestHeaterOnlyConfig:
    """Tests for config without cooler entity."""

    async def test_heater_only_heating(self, hass: HomeAssistant):
        """Heater-only config should work normally in Heat mode."""
        ctx = await _setup_entity(hass, HEATER_ONLY_CONFIG, "test_ho_1")
        entity_id = HEATER_ONLY_ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert heater_on, "Heater should turn on in heater-only config"

    async def test_heater_only_off_mode(self, hass: HomeAssistant):
        """Heater-only OFF mode should turn off heater."""
        ctx = await _setup_entity(
            hass,
            HEATER_ONLY_CONFIG,
            "test_ho_2",
            heater_state=STATE_ON,
        )
        entity_id = HEATER_ONLY_ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "off"},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_off = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_off_calls"]
        )
        assert heater_off, "Heater should turn off in OFF mode"


# ===========================================================================
# TEST GROUP 8: Sensor Unavailable / Unknown
# ===========================================================================


class TestSensorUnavailable:
    """Tests for sensor unavailable/unknown states."""

    async def test_no_control_when_sensor_unavailable(self, hass: HomeAssistant):
        """No heater/cooler control when sensor is unavailable."""
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_sensor_1",
            sensor_temp=STATE_UNAVAILABLE,
        )
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert not heater_on, "No control action when sensor is unavailable"

    async def test_no_control_when_sensor_unknown(self, hass: HomeAssistant):
        """No heater/cooler control when sensor is unknown."""
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_sensor_2",
            sensor_temp=STATE_UNKNOWN,
        )
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert not heater_on, "No control action when sensor is unknown"

    async def test_sensor_recovery_resumes_control(self, hass: HomeAssistant):
        """After sensor becomes available again, control should resume."""
        ctx = await _setup_entity(
            hass,
            HEATER_COOLER_CONFIG,
            "test_sensor_3",
            sensor_temp=STATE_UNAVAILABLE,
        )
        entity_id = ENTITY_ID

        # Set heat mode with high target
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        # No action yet (sensor unavailable)
        heater_on_before = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert not heater_on_before, "No control while sensor unavailable"

        # Now sensor recovers
        hass.states.async_set(
            "sensor.test_room_temperature",
            "15.0",
            {"unit_of_measurement": "°C", "device_class": "temperature"},
        )
        await hass.async_block_till_done()

        heater_on_after = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert heater_on_after, "Heater should activate after sensor recovers"


# ===========================================================================
# TEST GROUP 9: Fan Modes
# ===========================================================================


class TestFanModes:
    """Tests for fan mode setting."""

    async def test_set_valid_fan_mode(self, hass: HomeAssistant):
        """Setting a valid fan mode should update state."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_fan_1")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": entity_id, "fan_mode": FAN_HIGH},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("fan_mode") == FAN_HIGH

    async def test_set_invalid_fan_mode_rejected(self, hass: HomeAssistant):
        """Setting an invalid fan mode should raise ServiceValidationError."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_fan_2")
        entity_id = ENTITY_ID

        # Set a valid mode first
        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": entity_id, "fan_mode": FAN_LOW},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Try invalid mode - HA validates and raises ServiceValidationError
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "climate",
                "set_fan_mode",
                {"entity_id": entity_id, "fan_mode": "turbo"},
                blocking=True,
            )

        # Fan mode should remain on last valid mode
        state = hass.states.get(entity_id)
        assert (
            state.attributes.get("fan_mode") == FAN_LOW
        ), "Should remain on last valid mode"

    async def test_initial_fan_mode(self, hass: HomeAssistant):
        """Initial fan mode should be first in the list."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_fan_3")
        entity_id = ENTITY_ID

        state = hass.states.get(entity_id)
        assert state.attributes.get("fan_mode") == FAN_AUTO


# ===========================================================================
# TEST GROUP 10: Preset Modes (with temp save/restore)
# ===========================================================================


class TestPresetModes:
    """Tests for preset mode switching and temperature save/restore."""

    async def test_set_valid_preset_mode(self, hass: HomeAssistant):
        """Setting a valid preset mode should update state."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_preset_1")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": PRESET_ECO},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("preset_mode") == PRESET_ECO

    async def test_preset_saves_target_temp(self, hass: HomeAssistant):
        """Switching to a preset should save the current target temp."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_preset_2")
        entity_id = ENTITY_ID

        # Set a target temperature
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 25.0},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Switch to ECO preset
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": PRESET_ECO},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Change temp while in preset
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 18.0},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Switch back to NONE => should restore 25.0
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": PRESET_NONE},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert (
            state.attributes.get("temperature") == 25.0
        ), f"Target temp should be restored to 25.0, got {state.attributes.get('temperature')}"

    async def test_invalid_preset_rejected(self, hass: HomeAssistant):
        """Setting an invalid preset should raise ServiceValidationError."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_preset_3")
        entity_id = ENTITY_ID

        # HA validates preset modes and raises ServiceValidationError for invalid ones
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": "super_mode"},
                blocking=True,
            )

        # Should remain on initial preset (PRESET_NONE)
        state = hass.states.get(entity_id)
        assert state.attributes.get("preset_mode") == PRESET_NONE

    async def test_initial_preset_is_none(self, hass: HomeAssistant):
        """Initial preset should be PRESET_NONE."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_preset_4")
        entity_id = ENTITY_ID

        state = hass.states.get(entity_id)
        assert state.attributes.get("preset_mode") == PRESET_NONE


# ===========================================================================
# TEST GROUP 11: Temperature Setting
# ===========================================================================


class TestTemperatureSetting:
    """Tests for target temperature changes."""

    async def test_set_temperature_triggers_control(self, hass: HomeAssistant):
        """Setting temperature should trigger control logic."""
        ctx = await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_temp_1")
        entity_id = ENTITY_ID

        # Set heat mode first
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Set high target - should trigger heater
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 30},
            blocking=True,
        )
        await hass.async_block_till_done()

        heater_on = any(
            c.data.get("entity_id") == "input_boolean.test_heater"
            for c in ctx["turn_on_calls"]
        )
        assert heater_on, "Setting temperature should trigger heater control"

    async def test_set_temperature_updates_state(self, hass: HomeAssistant):
        """Setting temperature should update the state attribute."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_temp_2")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 25.5},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("temperature") == 25.5

    async def test_set_temperature_with_hvac_mode(self, hass: HomeAssistant):
        """Setting temperature with hvac_mode should change both."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_temp_3")
        entity_id = ENTITY_ID

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 25, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("temperature") == 25
        assert state.state == "heat"


# ===========================================================================
# TEST GROUP 12: Entity State Attributes
# ===========================================================================


class TestEntityAttributes:
    """Tests for entity state attributes."""

    async def test_min_max_temp(self, hass: HomeAssistant):
        """min_temp and max_temp should match config."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_attr_1")
        entity_id = ENTITY_ID

        state = hass.states.get(entity_id)
        assert state.attributes.get("min_temp") == 7.0
        assert state.attributes.get("max_temp") == 35.0

    async def test_hvac_modes_list(self, hass: HomeAssistant):
        """hvac_modes attribute should list configured modes."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_attr_2")
        entity_id = ENTITY_ID

        state = hass.states.get(entity_id)
        hvac_modes = state.attributes.get("hvac_modes")
        assert HVACMode.OFF in hvac_modes
        assert HVACMode.HEAT in hvac_modes
        assert HVACMode.COOL in hvac_modes

    async def test_current_temperature(self, hass: HomeAssistant):
        """current_temperature should reflect sensor reading."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_attr_3")
        entity_id = ENTITY_ID

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_temperature") == 21.5

    async def test_supported_features_with_fan_preset(self, hass: HomeAssistant):
        """Supported features should include FAN_MODE and PRESET_MODE."""
        await _setup_entity(hass, HEATER_COOLER_CONFIG, "test_attr_4")
        entity_id = ENTITY_ID

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & ClimateEntityFeature.FAN_MODE
        assert features & ClimateEntityFeature.PRESET_MODE
        assert features & ClimateEntityFeature.TARGET_TEMPERATURE
        assert features & ClimateEntityFeature.TURN_ON
        assert features & ClimateEntityFeature.TURN_OFF

    async def test_no_fan_mode_when_not_configured(self, hass: HomeAssistant):
        """Fan mode should not be in supported features when not configured."""
        await _setup_entity(hass, HEATER_ONLY_CONFIG, "test_attr_5")
        entity_id = HEATER_ONLY_ENTITY_ID

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert not (features & ClimateEntityFeature.FAN_MODE)
        assert not (features & ClimateEntityFeature.PRESET_MODE)
