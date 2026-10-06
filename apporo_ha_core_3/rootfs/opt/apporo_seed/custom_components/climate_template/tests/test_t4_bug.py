"""Regression test for T4 bug: cooling status shows wrong hvac_action."""

from __future__ import annotations
from homeassistant.components.climate import HVACMode, HVACAction
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
from custom_components.climate_template.const import DOMAIN
from homeassistant import loader

T4_CONFIG = {
    "ac_mode": False,
    "config_mode": "simple",
    "cooler": "input_boolean.coolertoggle1",
    "fan_modes": ["high", "low", "auto", "medium"],
    "heater": "input_boolean.heatertoggle",
    "hvac_modes": ["off", "heat", "heat_cool", "cool", "auto", "dry", "fan_only"],
    "max_temp": 50.0,
    "min_temp": 0.0,
    "name": "t4",
    "temp_step": 0.5,
    "temperature_sensor": "sensor.test_outdoor_temperature",
}


async def test_t4_cooling_shows_cooling_action(hass: HomeAssistant):
    """When current > target in cool mode, hvac_action must be COOLING."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    hass.states.async_set(
        "sensor.test_outdoor_temperature",
        "28.0",
        {"unit_of_measurement": "°F", "device_class": "temperature"},
    )
    hass.states.async_set(
        "input_boolean.heatertoggle", STATE_OFF, {"friendly_name": "HeaterToggle"}
    )
    hass.states.async_set(
        "input_boolean.coolertoggle1", STATE_OFF, {"friendly_name": "CoolerToggle1"}
    )

    turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")

    entry = MockConfigEntry(
        domain=DOMAIN, title="t4", data={}, options=T4_CONFIG, entry_id="t4_test"
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "climate.t4"

    # Switch to cool mode
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": "cool"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Set target to 22 (current=28, should be too hot -> cooler ON)
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "temperature": 22},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)

    # Cooler should have been called
    cooler_on = any(
        c.data.get("entity_id") == "input_boolean.coolertoggle1"
        for c in turn_on_calls
    )
    assert cooler_on, "Cooler should be turned ON when current(28) > target(22)"
    assert state.attributes.get("hvac_action") == HVACAction.COOLING, (
        f"hvac_action should be COOLING, got {state.attributes.get('hvac_action')}"
    )


async def test_t4_cooling_shows_idle_when_target_above_current(hass: HomeAssistant):
    """When target > current in cool mode, hvac_action must be IDLE."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    hass.states.async_set(
        "sensor.test_outdoor_temperature",
        "28.0",
        {"unit_of_measurement": "°F", "device_class": "temperature"},
    )
    hass.states.async_set(
        "input_boolean.heatertoggle", STATE_OFF, {"friendly_name": "HeaterToggle"}
    )
    hass.states.async_set(
        "input_boolean.coolertoggle1", STATE_OFF, {"friendly_name": "CoolerToggle1"}
    )

    turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off_calls = async_mock_service(hass, "homeassistant", "turn_off")

    entry = MockConfigEntry(
        domain=DOMAIN, title="t4", data={}, options=T4_CONFIG, entry_id="t4_idle_test"
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "climate.t4"

    # Switch to cool mode first
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": "cool"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Clear calls from mode switch (cooler may fire due to default target=0)
    turn_on_calls.clear()
    turn_off_calls.clear()

    # Now set target above current
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "temperature": 35},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)

    # Cooler should NOT be on (target 35 > current 28)
    cooler_on = any(
        c.data.get("entity_id") == "input_boolean.coolertoggle1"
        for c in turn_on_calls
    )
    assert not cooler_on, "Cooler should NOT be ON when target(35) > current(28)"
    assert state.attributes.get("hvac_action") == HVACAction.IDLE, (
        f"hvac_action should be IDLE, got {state.attributes.get('hvac_action')}"
    )
