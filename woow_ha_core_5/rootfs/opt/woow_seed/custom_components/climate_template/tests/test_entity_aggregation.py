"""Comprehensive tests for entity aggregation TX/RX in SimpleClimate.

Tests all entity selector TX (sending commands to external entities),
action script TX (executing action scripts), TX priority chain
(action script > entity selector > optimistic), and RX
(reading state back from external entities via state change listeners).

Also tests feature flags and a few Advanced mode (TemplateClimate) scenarios.
"""

from __future__ import annotations

import pytest
from homeassistant.components.climate import (
    HVACMode,
    ClimateEntityFeature,
)
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
    PRESET_HOME,
    PRESET_SLEEP,
    PRESET_ACTIVITY,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.climate_template.const import DOMAIN
from homeassistant import loader

# ---------------------------------------------------------------------------
# Test entity states (pre-set before climate setup)
# ---------------------------------------------------------------------------


def _create_test_entities(hass: HomeAssistant):
    """Create all external entities that the climate entity will aggregate."""
    # Temperature sensor
    hass.states.async_set(
        "sensor.test_room_temperature",
        "21.5",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    # Heater
    hass.states.async_set(
        "input_boolean.test_heater",
        STATE_OFF,
        {"friendly_name": "Test Heater"},
    )
    # Fan mode entity (input_select)
    hass.states.async_set(
        "input_select.test_fan_speed",
        "auto",
        {
            "options": ["auto", "low", "medium", "high"],
            "friendly_name": "Test Fan Speed",
        },
    )
    # Preset mode entity (input_select)
    hass.states.async_set(
        "input_select.test_preset_mode",
        "comfort",
        {
            "options": ["eco", "away", "boost", "comfort", "home", "sleep", "activity"],
            "friendly_name": "Test Preset Mode",
        },
    )
    # Swing mode entity (input_select)
    hass.states.async_set(
        "input_select.test_swing_mode",
        "off",
        {"options": ["on", "off"], "friendly_name": "Test Swing Mode"},
    )
    # Swing mode entity (switch variant)
    hass.states.async_set(
        "switch.test_swing_vane",
        STATE_OFF,
        {"friendly_name": "Test Swing Vane"},
    )
    # Swing horizontal mode entity
    hass.states.async_set(
        "input_select.test_swing_horizontal",
        "off",
        {"options": ["on", "off"], "friendly_name": "Test Horizontal Swing"},
    )
    # HVAC mode entity
    hass.states.async_set(
        "input_select.test_hvac_mode",
        "off",
        {"options": ["off", "heat", "cool"], "friendly_name": "Test HVAC Mode"},
    )
    # Target humidity entity
    hass.states.async_set(
        "input_number.test_target_humidity",
        "50",
        {"min": 30, "max": 80, "step": 5, "friendly_name": "Test Target Humidity"},
    )
    # Humidity sensor
    hass.states.async_set(
        "sensor.test_humidity",
        "55",
        {
            "unit_of_measurement": "%",
            "device_class": "humidity",
            "friendly_name": "Test Humidity Sensor",
        },
    )


# ---------------------------------------------------------------------------
# Base config for full entity aggregation
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "name": "Test Aggregated Climate",
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
    "hvac_modes": ["off", "heat", "cool"],
    "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    "preset_modes": [
        PRESET_ECO,
        PRESET_AWAY,
        PRESET_BOOST,
        PRESET_COMFORT,
        PRESET_HOME,
        PRESET_SLEEP,
        PRESET_ACTIVITY,
    ],
    "swing_modes": ["on", "off"],
}

ENTITY_ID = "climate.test_aggregated_climate"


# ---------------------------------------------------------------------------
# Action script definitions for TX action script tests
# ---------------------------------------------------------------------------

SET_TEMPERATURE_ACTION = [
    {
        "action": "input_number.set_value",
        "target": {"entity_id": "input_number.test_target_temp"},
        "data": {"value": "{{ temperature }}"},
    }
]

SET_HVAC_MODE_ACTION = [
    {
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.test_hvac_action_target"},
        "data": {"option": "{{ hvac_mode }}"},
    }
]

SET_FAN_MODE_ACTION = [
    {
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.test_fan_action_target"},
        "data": {"option": "{{ fan_mode }}"},
    }
]

SET_PRESET_MODE_ACTION = [
    {
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.test_preset_action_target"},
        "data": {"option": "{{ preset_mode }}"},
    }
]

SET_SWING_MODE_ACTION = [
    {
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.test_swing_action_target"},
        "data": {"option": "{{ swing_mode }}"},
    }
]

SET_SWING_HORIZONTAL_MODE_ACTION = [
    {
        "action": "input_select.select_option",
        "target": {"entity_id": "input_select.test_swing_h_action_target"},
        "data": {"option": "{{ swing_horizontal_mode }}"},
    }
]

SET_HUMIDITY_ACTION = [
    {
        "action": "input_number.set_value",
        "target": {"entity_id": "input_number.test_humidity_action_target"},
        "data": {"value": "{{ humidity }}"},
    }
]


# ---------------------------------------------------------------------------
# Helper to set up a climate entity with entity aggregation
# ---------------------------------------------------------------------------


async def _setup_entity(
    hass: HomeAssistant,
    config: dict,
    entry_id: str,
):
    """Set up prerequisite entities and a climate config entry."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    _create_test_entities(hass)

    # Mock services for entity selector TX verification
    select_option_calls = async_mock_service(hass, "input_select", "select_option")
    set_value_calls = async_mock_service(hass, "input_number", "set_value")
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
        "select_option_calls": select_option_calls,
        "set_value_calls": set_value_calls,
        "turn_on_calls": turn_on_calls,
        "turn_off_calls": turn_off_calls,
    }


# ===========================================================================
# TEST GROUP 1: TX via Entity Selectors (7 tests)
# ===========================================================================


class TestTxEntitySelectors:
    """Tests for TX: sending commands to external entities via entity selectors."""

    async def test_tx_fan_entity_input_select(self, hass: HomeAssistant):
        """Setting fan mode should call input_select.select_option on the fan entity."""
        config = {**BASE_CONFIG, "fan_mode_entity": "input_select.test_fan_speed"}
        ctx = await _setup_entity(hass, config, "test_tx_fan_1")

        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": ENTITY_ID, "fan_mode": "high"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Verify TX: select_option called on fan entity
        fan_calls = [
            c
            for c in ctx["select_option_calls"]
            if c.data.get("entity_id") == "input_select.test_fan_speed"
        ]
        assert (
            len(fan_calls) == 1
        ), f"Expected 1 select_option call, got {len(fan_calls)}"
        assert fan_calls[0].data["option"] == "high"

        # Verify internal state updated
        state = hass.states.get(ENTITY_ID)
        assert state.attributes["fan_mode"] == "high"

    async def test_tx_preset_entity_input_select(self, hass: HomeAssistant):
        """Setting preset mode should call input_select.select_option on the preset entity."""
        config = {**BASE_CONFIG, "preset_mode_entity": "input_select.test_preset_mode"}
        ctx = await _setup_entity(hass, config, "test_tx_preset_1")

        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": ENTITY_ID, "preset_mode": "eco"},
            blocking=True,
        )
        await hass.async_block_till_done()

        preset_calls = [
            c
            for c in ctx["select_option_calls"]
            if c.data.get("entity_id") == "input_select.test_preset_mode"
        ]
        assert len(preset_calls) == 1
        assert preset_calls[0].data["option"] == "eco"

        state = hass.states.get(ENTITY_ID)
        assert state.attributes["preset_mode"] == "eco"

    async def test_tx_swing_entity_input_select(self, hass: HomeAssistant):
        """Setting swing mode should call input_select.select_option on the swing entity."""
        config = {**BASE_CONFIG, "swing_mode_entity": "input_select.test_swing_mode"}
        ctx = await _setup_entity(hass, config, "test_tx_swing_1")

        await hass.services.async_call(
            "climate",
            "set_swing_mode",
            {"entity_id": ENTITY_ID, "swing_mode": "on"},
            blocking=True,
        )
        await hass.async_block_till_done()

        swing_calls = [
            c
            for c in ctx["select_option_calls"]
            if c.data.get("entity_id") == "input_select.test_swing_mode"
        ]
        assert len(swing_calls) == 1
        assert swing_calls[0].data["option"] == "on"

        state = hass.states.get(ENTITY_ID)
        assert state.attributes["swing_mode"] == "on"

    async def test_tx_swing_entity_switch(self, hass: HomeAssistant):
        """Setting swing mode 'on' on a switch entity should call homeassistant.turn_on."""
        config = {
            **BASE_CONFIG,
            "swing_mode_entity": "switch.test_swing_vane",
        }
        ctx = await _setup_entity(hass, config, "test_tx_swing_switch_1")

        await hass.services.async_call(
            "climate",
            "set_swing_mode",
            {"entity_id": ENTITY_ID, "swing_mode": "on"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Verify TX: turn_on called on the switch entity
        switch_on_calls = [
            c
            for c in ctx["turn_on_calls"]
            if c.data.get("entity_id") == "switch.test_swing_vane"
        ]
        assert (
            len(switch_on_calls) == 1
        ), f"Expected turn_on call on switch, got {len(switch_on_calls)}"

    async def test_tx_swing_horizontal_entity(self, hass: HomeAssistant):
        """Setting swing horizontal mode should call select_option on the horizontal swing entity."""
        config = {
            **BASE_CONFIG,
            "swing_horizontal_modes": ["on", "off"],
            "swing_horizontal_mode_entity": "input_select.test_swing_horizontal",
        }
        ctx = await _setup_entity(hass, config, "test_tx_swing_h_1")

        await hass.services.async_call(
            "climate",
            "set_swing_horizontal_mode",
            {"entity_id": ENTITY_ID, "swing_horizontal_mode": "on"},
            blocking=True,
        )
        await hass.async_block_till_done()

        sh_calls = [
            c
            for c in ctx["select_option_calls"]
            if c.data.get("entity_id") == "input_select.test_swing_horizontal"
        ]
        assert len(sh_calls) == 1
        assert sh_calls[0].data["option"] == "on"

    async def test_tx_humidity_entity(self, hass: HomeAssistant):
        """Setting humidity should call input_number.set_value on the humidity entity."""
        config = {**BASE_CONFIG, "humidity_entity": "input_number.test_target_humidity"}
        ctx = await _setup_entity(hass, config, "test_tx_humidity_1")

        await hass.services.async_call(
            "climate",
            "set_humidity",
            {"entity_id": ENTITY_ID, "humidity": 60},
            blocking=True,
        )
        await hass.async_block_till_done()

        humidity_calls = [
            c
            for c in ctx["set_value_calls"]
            if c.data.get("entity_id") == "input_number.test_target_humidity"
        ]
        assert len(humidity_calls) == 1
        assert humidity_calls[0].data["value"] == 60.0

    async def test_tx_hvac_mode_entity(self, hass: HomeAssistant):
        """Setting HVAC mode should call select_option on the HVAC mode entity."""
        config = {**BASE_CONFIG, "hvac_mode_entity": "input_select.test_hvac_mode"}
        ctx = await _setup_entity(hass, config, "test_tx_hvac_1")

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.async_block_till_done()

        hvac_calls = [
            c
            for c in ctx["select_option_calls"]
            if c.data.get("entity_id") == "input_select.test_hvac_mode"
        ]
        assert len(hvac_calls) == 1
        assert hvac_calls[0].data["option"] == "heat"


# ===========================================================================
# TEST GROUP 2: TX via Action Scripts (7 tests)
# ===========================================================================


class TestTxActionScripts:
    """Tests for TX: executing action scripts when controls change."""

    async def test_tx_temperature_action_script(self, hass: HomeAssistant):
        """Temperature action script should fire when target temperature changes."""
        config = {**BASE_CONFIG, "set_temperature": SET_TEMPERATURE_ACTION}
        ctx = await _setup_entity(hass, config, "test_tx_temp_script_1")

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 25},
            blocking=True,
        )
        await hass.async_block_till_done()

        # async_mock_service captures raw service calls (templates NOT rendered)
        # target syntax wraps entity_id in a list
        temp_calls = [
            c
            for c in ctx["set_value_calls"]
            if "input_number.test_target_temp" in (c.data.get("entity_id") or [])
        ]
        assert len(temp_calls) == 1

    async def test_tx_hvac_mode_action_script(self, hass: HomeAssistant):
        """HVAC mode action script should fire when HVAC mode changes."""
        config = {**BASE_CONFIG, "set_hvac_mode": SET_HVAC_MODE_ACTION}
        ctx = await _setup_entity(hass, config, "test_tx_hvac_script_1")

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.async_block_till_done()

        hvac_calls = [
            c
            for c in ctx["select_option_calls"]
            if "input_select.test_hvac_action_target" in (c.data.get("entity_id") or [])
        ]
        assert len(hvac_calls) == 1

    async def test_tx_fan_mode_action_script(self, hass: HomeAssistant):
        """Fan mode action script should fire when fan mode changes."""
        config = {**BASE_CONFIG, "set_fan_mode": SET_FAN_MODE_ACTION}
        ctx = await _setup_entity(hass, config, "test_tx_fan_script_1")

        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": ENTITY_ID, "fan_mode": "high"},
            blocking=True,
        )
        await hass.async_block_till_done()

        fan_calls = [
            c
            for c in ctx["select_option_calls"]
            if "input_select.test_fan_action_target" in (c.data.get("entity_id") or [])
        ]
        assert len(fan_calls) == 1

    async def test_tx_preset_mode_action_script(self, hass: HomeAssistant):
        """Preset mode action script should fire when preset mode changes."""
        config = {**BASE_CONFIG, "set_preset_mode": SET_PRESET_MODE_ACTION}
        ctx = await _setup_entity(hass, config, "test_tx_preset_script_1")

        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": ENTITY_ID, "preset_mode": "eco"},
            blocking=True,
        )
        await hass.async_block_till_done()

        preset_calls = [
            c
            for c in ctx["select_option_calls"]
            if "input_select.test_preset_action_target"
            in (c.data.get("entity_id") or [])
        ]
        assert len(preset_calls) == 1

    async def test_tx_swing_mode_action_script(self, hass: HomeAssistant):
        """Swing mode action script should fire when swing mode changes."""
        config = {**BASE_CONFIG, "set_swing_mode": SET_SWING_MODE_ACTION}
        ctx = await _setup_entity(hass, config, "test_tx_swing_script_1")

        await hass.services.async_call(
            "climate",
            "set_swing_mode",
            {"entity_id": ENTITY_ID, "swing_mode": "on"},
            blocking=True,
        )
        await hass.async_block_till_done()

        swing_calls = [
            c
            for c in ctx["select_option_calls"]
            if "input_select.test_swing_action_target"
            in (c.data.get("entity_id") or [])
        ]
        assert len(swing_calls) == 1

    async def test_tx_swing_horizontal_mode_action_script(self, hass: HomeAssistant):
        """Swing horizontal mode action script should fire."""
        config = {
            **BASE_CONFIG,
            "swing_horizontal_modes": ["on", "off"],
            "set_swing_horizontal_mode": SET_SWING_HORIZONTAL_MODE_ACTION,
        }
        ctx = await _setup_entity(hass, config, "test_tx_swing_h_script_1")

        await hass.services.async_call(
            "climate",
            "set_swing_horizontal_mode",
            {"entity_id": ENTITY_ID, "swing_horizontal_mode": "on"},
            blocking=True,
        )
        await hass.async_block_till_done()

        sh_calls = [
            c
            for c in ctx["select_option_calls"]
            if "input_select.test_swing_h_action_target"
            in (c.data.get("entity_id") or [])
        ]
        assert len(sh_calls) == 1

    async def test_tx_humidity_action_script(self, hass: HomeAssistant):
        """Humidity action script should fire when target humidity changes."""
        config = {**BASE_CONFIG, "set_humidity": SET_HUMIDITY_ACTION}
        ctx = await _setup_entity(hass, config, "test_tx_humidity_script_1")

        await hass.services.async_call(
            "climate",
            "set_humidity",
            {"entity_id": ENTITY_ID, "humidity": 60},
            blocking=True,
        )
        await hass.async_block_till_done()

        humidity_calls = [
            c
            for c in ctx["set_value_calls"]
            if "input_number.test_humidity_action_target"
            in (c.data.get("entity_id") or [])
        ]
        assert len(humidity_calls) == 1


# ===========================================================================
# TEST GROUP 3: TX Priority Chain (2 tests)
# ===========================================================================


class TestTxPriority:
    """Tests for TX priority: action script > entity selector > optimistic."""

    async def test_tx_action_script_overrides_entity(self, hass: HomeAssistant):
        """When both action script and entity selector are configured, action script wins."""
        config = {
            **BASE_CONFIG,
            "fan_mode_entity": "input_select.test_fan_speed",
            "set_fan_mode": SET_FAN_MODE_ACTION,
        }
        ctx = await _setup_entity(hass, config, "test_tx_priority_1")

        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": ENTITY_ID, "fan_mode": "high"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Action script target should be called (target syntax wraps entity_id in list)
        action_calls = [
            c
            for c in ctx["select_option_calls"]
            if "input_select.test_fan_action_target" in (c.data.get("entity_id") or [])
        ]
        assert len(action_calls) == 1, "Action script should be called"

        # Entity selector target should NOT be called
        # Entity selector TX uses string entity_id (not list)
        entity_calls = [
            c
            for c in ctx["select_option_calls"]
            if c.data.get("entity_id") == "input_select.test_fan_speed"
        ]
        assert (
            len(entity_calls) == 0
        ), "Entity selector should NOT be called when action script exists"

    async def test_tx_no_entity_optimistic_only(self, hass: HomeAssistant):
        """When no entity selector or action script, only internal state updates."""
        config = {**BASE_CONFIG}  # No fan_mode_entity, no set_fan_mode
        ctx = await _setup_entity(hass, config, "test_tx_optimistic_1")

        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": ENTITY_ID, "fan_mode": "high"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # No select_option calls should have been made for fan
        fan_calls = [
            c
            for c in ctx["select_option_calls"]
            if "fan" in (c.data.get("entity_id") or "")
        ]
        assert len(fan_calls) == 0, "No TX should occur in optimistic-only mode"

        # Internal state should still update
        state = hass.states.get(ENTITY_ID)
        assert state.attributes["fan_mode"] == "high"


# ===========================================================================
# TEST GROUP 4: RX - State Change Listeners (7 tests)
# ===========================================================================


class TestRxStateChangeListeners:
    """Tests for RX: climate state updates when external entities change."""

    async def test_rx_fan_entity_state_change(self, hass: HomeAssistant):
        """Climate fan_mode should update when external fan entity changes."""
        config = {**BASE_CONFIG, "fan_mode_entity": "input_select.test_fan_speed"}
        await _setup_entity(hass, config, "test_rx_fan_1")

        # Verify initial sync (entity was "auto")
        state = hass.states.get(ENTITY_ID)
        assert state.attributes["fan_mode"] == "auto"

        # Simulate external entity change
        hass.states.async_set(
            "input_select.test_fan_speed",
            "high",
            {"options": ["auto", "low", "medium", "high"]},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes["fan_mode"] == "high"

    async def test_rx_preset_entity_state_change(self, hass: HomeAssistant):
        """Climate preset_mode should update when external preset entity changes."""
        config = {**BASE_CONFIG, "preset_mode_entity": "input_select.test_preset_mode"}
        await _setup_entity(hass, config, "test_rx_preset_1")

        # Initial sync: entity was "comfort"
        state = hass.states.get(ENTITY_ID)
        assert state.attributes["preset_mode"] == "comfort"

        hass.states.async_set(
            "input_select.test_preset_mode",
            "eco",
            {
                "options": [
                    "eco",
                    "away",
                    "boost",
                    "comfort",
                    "home",
                    "sleep",
                    "activity",
                ]
            },
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes["preset_mode"] == "eco"

    async def test_rx_swing_entity_state_change(self, hass: HomeAssistant):
        """Climate swing_mode should update when external swing entity changes."""
        config = {**BASE_CONFIG, "swing_mode_entity": "input_select.test_swing_mode"}
        await _setup_entity(hass, config, "test_rx_swing_1")

        # Initial sync: entity was "off"
        state = hass.states.get(ENTITY_ID)
        assert state.attributes["swing_mode"] == "off"

        hass.states.async_set(
            "input_select.test_swing_mode",
            "on",
            {"options": ["on", "off"]},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes["swing_mode"] == "on"

    async def test_rx_swing_horizontal_entity_change(self, hass: HomeAssistant):
        """Climate swing_horizontal_mode should update when external entity changes."""
        config = {
            **BASE_CONFIG,
            "swing_horizontal_modes": ["on", "off"],
            "swing_horizontal_mode_entity": "input_select.test_swing_horizontal",
        }
        await _setup_entity(hass, config, "test_rx_swing_h_1")

        # Initial sync: entity was "off"
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("swing_horizontal_mode") == "off"

        hass.states.async_set(
            "input_select.test_swing_horizontal",
            "on",
            {"options": ["on", "off"]},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("swing_horizontal_mode") == "on"

    async def test_rx_humidity_entity_state_change(self, hass: HomeAssistant):
        """Climate target humidity should update when external humidity entity changes."""
        config = {**BASE_CONFIG, "humidity_entity": "input_number.test_target_humidity"}
        await _setup_entity(hass, config, "test_rx_humidity_1")

        # Initial sync: entity was "50"
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("humidity") == 50

        hass.states.async_set(
            "input_number.test_target_humidity",
            "65",
            {"min": 30, "max": 80, "step": 5},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("humidity") == 65

    async def test_rx_humidity_sensor_state_change(self, hass: HomeAssistant):
        """Climate current_humidity should update when humidity sensor changes."""
        config = {**BASE_CONFIG, "humidity_sensor": "sensor.test_humidity"}
        await _setup_entity(hass, config, "test_rx_humidity_sensor_1")

        # Initial sync: sensor was "55"
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("current_humidity") == 55

        hass.states.async_set(
            "sensor.test_humidity",
            "62",
            {"unit_of_measurement": "%", "device_class": "humidity"},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("current_humidity") == 62

    async def test_rx_hvac_mode_entity_state_change(self, hass: HomeAssistant):
        """Climate HVAC mode should update when external HVAC mode entity changes."""
        config = {**BASE_CONFIG, "hvac_mode_entity": "input_select.test_hvac_mode"}
        await _setup_entity(hass, config, "test_rx_hvac_1")

        # Change external entity to "cool"
        hass.states.async_set(
            "input_select.test_hvac_mode",
            "cool",
            {"options": ["off", "heat", "cool"]},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == "cool"


# ===========================================================================
# TEST GROUP 5: RX Initial Sync + Invalid State (2 tests)
# ===========================================================================


class TestRxInitialSyncAndEdgeCases:
    """Tests for initial state sync on startup and invalid state handling."""

    async def test_rx_initial_sync_on_startup(self, hass: HomeAssistant):
        """Climate should sync state from all entities on startup."""
        config = {
            **BASE_CONFIG,
            "fan_mode_entity": "input_select.test_fan_speed",
            "preset_mode_entity": "input_select.test_preset_mode",
            "swing_mode_entity": "input_select.test_swing_mode",
            "swing_horizontal_modes": ["on", "off"],
            "swing_horizontal_mode_entity": "input_select.test_swing_horizontal",
            "humidity_entity": "input_number.test_target_humidity",
            "humidity_sensor": "sensor.test_humidity",
        }
        await _setup_entity(hass, config, "test_rx_init_1")

        state = hass.states.get(ENTITY_ID)
        # Fan: entity was "auto"
        assert state.attributes["fan_mode"] == "auto"
        # Preset: entity was "comfort"
        assert state.attributes["preset_mode"] == "comfort"
        # Swing: entity was "off"
        assert state.attributes["swing_mode"] == "off"
        # Swing horizontal: entity was "off"
        assert state.attributes.get("swing_horizontal_mode") == "off"
        # Target humidity: entity was "50"
        assert state.attributes.get("humidity") == 50
        # Current humidity: sensor was "55"
        assert state.attributes.get("current_humidity") == 55

    async def test_rx_invalid_state_ignored(self, hass: HomeAssistant):
        """Invalid state values from external entities should be ignored."""
        config = {**BASE_CONFIG, "fan_mode_entity": "input_select.test_fan_speed"}
        await _setup_entity(hass, config, "test_rx_invalid_1")

        # Verify initial state
        state = hass.states.get(ENTITY_ID)
        assert state.attributes["fan_mode"] == "auto"

        # Set external entity to an invalid value (not in fan_modes list)
        hass.states.async_set(
            "input_select.test_fan_speed",
            "turbo",
            {"options": ["auto", "low", "medium", "high", "turbo"]},
        )
        await hass.async_block_till_done()

        # Climate state should remain unchanged
        state = hass.states.get(ENTITY_ID)
        assert state.attributes["fan_mode"] == "auto", "Invalid value should be ignored"


# ===========================================================================
# TEST GROUP 6: Feature Flag Tests (2 tests)
# ===========================================================================


class TestFeatureFlags:
    """Tests for supported_features flags based on configuration."""

    async def test_feature_swing_horizontal_mode(self, hass: HomeAssistant):
        """SWING_HORIZONTAL_MODE feature flag should be set when swing_horizontal_modes configured."""
        config = {
            **BASE_CONFIG,
            "swing_horizontal_modes": ["on", "off"],
        }
        await _setup_entity(hass, config, "test_feature_sh_1")

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features", 0)
        assert (
            features & ClimateEntityFeature.SWING_HORIZONTAL_MODE
        ), "SWING_HORIZONTAL_MODE feature should be set"

    async def test_feature_target_humidity(self, hass: HomeAssistant):
        """TARGET_HUMIDITY feature flag should be set when humidity_entity configured."""
        config = {**BASE_CONFIG, "humidity_entity": "input_number.test_target_humidity"}
        await _setup_entity(hass, config, "test_feature_humidity_1")

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features", 0)
        assert (
            features & ClimateEntityFeature.TARGET_HUMIDITY
        ), "TARGET_HUMIDITY feature should be set"
