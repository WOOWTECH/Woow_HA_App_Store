"""Tests for temperature unit behavior.

Verifies that climate entities always use the HA system unit.
The temperature_unit config option has been removed — entities always
inherit from the system setting (Settings → System → General → Unit System).
"""

from __future__ import annotations

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.climate_template.const import DOMAIN
from homeassistant import loader

# ---------------------------------------------------------------------------
# Base config (Simple mode)
# ---------------------------------------------------------------------------

BASE_SIMPLE_CONFIG = {
    "name": "Test Unit Climate",
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

ENTITY_ID = "climate.test_unit_climate"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _setup_entity(
    hass: HomeAssistant,
    config: dict,
    entry_id: str,
):
    """Set up prerequisite entities and a climate config entry."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    hass.states.async_set(
        "sensor.test_room_temperature",
        "21.5",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    hass.states.async_set(
        "input_boolean.test_heater",
        STATE_OFF,
        {"friendly_name": "Test Heater"},
    )

    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")

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

    return entry


# ===========================================================================
# TEST GROUP: Temperature unit always uses system unit
# ===========================================================================


class TestTemperatureUnitSimpleMode:
    """Tests for temperature unit in Simple mode."""

    async def test_uses_system_unit_celsius(self, hass: HomeAssistant):
        """Entity uses system unit (Celsius in test env)."""
        await _setup_entity(hass, BASE_SIMPLE_CONFIG, "test_unit_sys_c")

        state = hass.states.get(ENTITY_ID)
        assert state is not None
        assert state.state == HVACMode.OFF
        # System unit in test env is Celsius
        assert state.attributes.get("current_temperature") == 21.5

    async def test_legacy_temperature_unit_option_ignored(self, hass: HomeAssistant):
        """Old config entries with temperature_unit key are harmlessly ignored."""
        config = {**BASE_SIMPLE_CONFIG, "temperature_unit": "°F"}

        await _setup_entity(hass, config, "test_unit_legacy")

        state = hass.states.get(ENTITY_ID)
        assert state is not None
        # Entity still uses system unit (Celsius), not the stale option
        assert state.state == HVACMode.OFF
