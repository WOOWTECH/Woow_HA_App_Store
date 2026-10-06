"""Common fixtures for Climate Template tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.template import Template
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.climate_template.const import DOMAIN


@pytest.fixture
def mock_hass():
    """Return a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config.units.temperature_unit = "°C"
    hass.states = MagicMock()
    hass.services = MagicMock()
    return hass


@pytest.fixture
def mock_states():
    """Return mock entity states."""
    return {
        "sensor.test_room_temperature": State(
            entity_id="sensor.test_room_temperature",
            state="21.5",
            attributes={
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "friendly_name": "Test Room Temperature",
            },
        ),
        "sensor.test_outdoor_temperature": State(
            entity_id="sensor.test_outdoor_temperature",
            state="-5.0",
            attributes={
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "friendly_name": "Test Outdoor Temperature",
            },
        ),
        "sensor.test_average_temperature": State(
            entity_id="sensor.test_average_temperature",
            state="8.25",
            attributes={
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "friendly_name": "Test Average Temperature",
            },
        ),
        "sensor.test_humidity": State(
            entity_id="sensor.test_humidity",
            state="65",
            attributes={
                "unit_of_measurement": "%",
                "device_class": "humidity",
                "friendly_name": "Test Humidity",
            },
        ),
        "input_boolean.test_heater": State(
            entity_id="input_boolean.test_heater",
            state=STATE_OFF,
            attributes={"friendly_name": "Test Heater"},
        ),
        "input_boolean.test_ac": State(
            entity_id="input_boolean.test_ac",
            state=STATE_OFF,
            attributes={"friendly_name": "Test AC"},
        ),
        "input_boolean.test_fan": State(
            entity_id="input_boolean.test_fan",
            state=STATE_OFF,
            attributes={"friendly_name": "Test Fan"},
        ),
        "input_select.test_hvac_mode": State(
            entity_id="input_select.test_hvac_mode",
            state="off",
            attributes={
                "options": ["off", "heat", "cool", "auto"],
                "friendly_name": "Test HVAC Mode",
            },
        ),
        "input_select.test_fan_mode": State(
            entity_id="input_select.test_fan_mode",
            state="auto",
            attributes={
                "options": ["auto", "low", "medium", "high"],
                "friendly_name": "Test Fan Mode",
            },
        ),
        "input_select.test_preset_mode": State(
            entity_id="input_select.test_preset_mode",
            state="none",
            attributes={
                "options": ["none", "eco", "comfort", "away", "boost"],
                "friendly_name": "Test Preset Mode",
            },
        ),
        "input_number.test_target_temp": State(
            entity_id="input_number.test_target_temp",
            state="21",
            attributes={
                "min": 7,
                "max": 35,
                "step": 0.5,
                "unit_of_measurement": "°C",
                "friendly_name": "Test Target Temperature",
            },
        ),
    }


@pytest.fixture
def simple_mode_config():
    """Return a Simple mode configuration."""
    return {
        "name": "Test Simple Climate",
        "temperature_sensor": "sensor.test_room_temperature",
        "heater": "input_boolean.test_heater",
        "cooler": None,
        "ac_mode": False,
        "min_temp": 7.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
        "cold_tolerance": 0.3,
        "hot_tolerance": 0.3,
        "hvac_modes": [HVACMode.OFF, HVACMode.HEAT],
        "fan_modes": None,
        "preset_modes": None,
        "swing_modes": None,
    }


@pytest.fixture
def advanced_mode_config():
    """Return an Advanced mode configuration with templates."""
    return {
        "name": "Test Advanced Climate",
        "current_temperature_template": (
            "{{ (states('sensor.test_room_temperature') | float + "
            "states('sensor.test_outdoor_temperature') | float) / 2 }}"
        ),
        "hvac_mode_template": "{{ states('input_select.test_hvac_mode') }}",
        "hvac_action_template": (
            "{% if is_state('input_boolean.test_heater', 'on') %}"
            "heating"
            "{% elif is_state('input_boolean.test_ac', 'on') %}"
            "cooling"
            "{% else %}"
            "idle"
            "{% endif %}"
        ),
        "set_temperature_action": [
            {
                "service": "input_number.set_value",
                "target": {"entity_id": "input_number.test_target_temp"},
                "data": {"value": "{{ temperature }}"},
            }
        ],
        "set_hvac_mode_action": [
            {
                "service": "input_select.select_option",
                "target": {"entity_id": "input_select.test_hvac_mode"},
                "data": {"option": "{{ hvac_mode }}"},
            }
        ],
        "min_temp": 7.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
        "hvac_modes": [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL],
    }


@pytest.fixture
def mock_config_entry(simple_mode_config):
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Climate",
        data={},
        options=simple_mode_config,
        entry_id="test_climate_entry_1",
    )


@pytest.fixture
def mock_template():
    """Return a mock Template instance."""
    template = MagicMock(spec=Template)
    template.async_render = AsyncMock(return_value="21.5")
    return template


@pytest.fixture
async def hass_instance(hass: HomeAssistant, mock_states: dict[str, State]):
    """Return a configured Home Assistant instance."""

    # Set up mock states
    def get_state(entity_id: str) -> State | None:
        return mock_states.get(entity_id)

    hass.states.get = get_state

    # Set up mock services
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "input_number", "set_value")
    async_mock_service(hass, "input_select", "select_option")
    async_mock_service(hass, "input_boolean", "turn_on")
    async_mock_service(hass, "input_boolean", "turn_off")

    return hass


@pytest.fixture
def template_test_cases():
    """Return test cases for template validation."""
    return [
        {
            "name": "simple_state",
            "template": "{{ states('sensor.test_room_temperature') }}",
            "expected": "21.5",
            "description": "Simple entity state reading",
        },
        {
            "name": "calculated_average",
            "template": (
                "{{ (states('sensor.test_room_temperature') | float + "
                "states('sensor.test_outdoor_temperature') | float) / 2 }}"
            ),
            "expected": 8.25,
            "description": "Calculated average of two sensors",
        },
        {
            "name": "conditional_logic",
            "template": (
                "{% if is_state('input_boolean.test_heater', 'on') %}"
                "heating"
                "{% else %}"
                "idle"
                "{% endif %}"
            ),
            "expected": "idle",
            "description": "Conditional template logic",
        },
        {
            "name": "filter_chain",
            "template": "{{ states('sensor.test_room_temperature') | float | round(1) }}",
            "expected": 21.5,
            "description": "Template with filter chain",
        },
        {
            "name": "default_value",
            "template": "{{ states('sensor.nonexistent') | float(20) }}",
            "expected": 20.0,
            "description": "Template with default value",
        },
    ]


@pytest.fixture
def invalid_template_test_cases():
    """Return test cases for invalid templates."""
    return [
        {
            "name": "missing_closing_brace",
            "template": "{{ states('sensor.test'",
            "error_type": "TemplateSyntaxError",
            "description": "Missing closing braces",
        },
        {
            "name": "invalid_filter",
            "template": "{{ states('sensor.test') | invalid_filter }}",
            "error_type": "TemplateError",
            "description": "Invalid filter name",
        },
        {
            "name": "undefined_variable",
            "template": "{{ undefined_variable }}",
            "error_type": "TemplateError",
            "description": "Undefined variable reference",
        },
        {
            "name": "invalid_syntax",
            "template": "{{ states('sensor.test') | float + }}",
            "error_type": "TemplateSyntaxError",
            "description": "Invalid Jinja2 syntax",
        },
    ]


@pytest.fixture
def action_script_test_cases():
    """Return test cases for action script testing."""
    return [
        {
            "name": "set_temperature",
            "action": [
                {
                    "service": "input_number.set_value",
                    "target": {"entity_id": "input_number.test_target_temp"},
                    "data": {"value": "{{ temperature }}"},
                }
            ],
            "variables": {"temperature": 22.5},
            "expected_service": "input_number.set_value",
            "expected_data": {"value": 22.5},
        },
        {
            "name": "set_hvac_mode",
            "action": [
                {
                    "service": "input_select.select_option",
                    "target": {"entity_id": "input_select.test_hvac_mode"},
                    "data": {"option": "{{ hvac_mode }}"},
                }
            ],
            "variables": {"hvac_mode": "heat"},
            "expected_service": "input_select.select_option",
            "expected_data": {"option": "heat"},
        },
        {
            "name": "multi_step_action",
            "action": [
                {
                    "service": "input_number.set_value",
                    "target": {"entity_id": "input_number.test_target_temp"},
                    "data": {"value": "{{ temperature }}"},
                },
                {
                    "service": "input_boolean.turn_on",
                    "target": {"entity_id": "input_boolean.test_heater"},
                },
            ],
            "variables": {"temperature": 23.0},
            "expected_calls": 2,
        },
    ]
