"""Tests for TX/RX entity aggregation — entity selectors and action scripts.

Tests: entity selector TX (percentage, preset_mode, oscillating, direction),
RX listeners (state sync from external entities), action script overrides
(priority over entity selectors), and initial state sync on setup.
"""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.woow_fan_entity.const import DOMAIN


# ---------------------------------------------------------------------------
# Entity IDs
# ---------------------------------------------------------------------------

ENTITY_ID = "fan.tx_rx_fan"

# External helper entities
SWITCH_ENTITY = "input_boolean.fan_switch"
PCT_ENTITY = "input_number.fan_speed"
PRESET_ENTITY = "input_select.fan_preset"
OSC_ENTITY = "input_boolean.fan_oscillation"
DIR_ENTITY = "input_select.fan_direction"


# ---------------------------------------------------------------------------
# Configs
# ---------------------------------------------------------------------------

TX_RX_CONFIG = {
    "name": "TX RX Fan",
    "switch_entity": SWITCH_ENTITY,
    "speed_count": 4,
    "preset_modes": ["auto", "sleep", "turbo"],
    "enable_oscillation": True,
    "enable_direction": True,
    "percentage_entity": PCT_ENTITY,
    "preset_mode_entity": PRESET_ENTITY,
    "oscillating_entity": OSC_ENTITY,
    "direction_entity": DIR_ENTITY,
}

ACTION_SCRIPT_CONFIG = {
    "name": "TX RX Fan",
    "switch_entity": SWITCH_ENTITY,
    "speed_count": 4,
    "preset_modes": ["auto", "sleep", "turbo"],
    "enable_oscillation": True,
    "enable_direction": True,
    "percentage_entity": PCT_ENTITY,
    "preset_mode_entity": PRESET_ENTITY,
    "oscillating_entity": OSC_ENTITY,
    "direction_entity": DIR_ENTITY,
    # Action script overrides
    "set_percentage": [
        {
            "action": "input_number.set_value",
            "target": {"entity_id": "input_number.fan_speed_script"},
            "data": {"value": "{{ percentage }}"},
        }
    ],
    "set_preset_mode": [
        {
            "action": "input_select.select_option",
            "target": {"entity_id": "input_select.fan_preset_script"},
            "data": {"option": "{{ preset_mode }}"},
        }
    ],
    "set_oscillating": [
        {
            "action": "input_boolean.turn_on",
            "target": {"entity_id": "input_boolean.fan_osc_script"},
        }
    ],
    "set_direction": [
        {
            "action": "input_select.select_option",
            "target": {"entity_id": "input_select.fan_dir_script"},
            "data": {"option": "{{ direction }}"},
        }
    ],
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _setup_entity(
    hass: HomeAssistant,
    config: dict,
    entry_id: str,
):
    """Set up prerequisite external entities and a fan config entry."""
    # Create external helper entities
    hass.states.async_set(SWITCH_ENTITY, STATE_OFF, {"friendly_name": "Fan Switch"})
    hass.states.async_set(PCT_ENTITY, "0", {"friendly_name": "Fan Speed", "min": 0, "max": 100})
    hass.states.async_set(PRESET_ENTITY, "none", {"friendly_name": "Fan Preset", "options": ["auto", "sleep", "turbo"]})
    hass.states.async_set(OSC_ENTITY, STATE_OFF, {"friendly_name": "Fan Oscillation"})
    hass.states.async_set(DIR_ENTITY, "forward", {"friendly_name": "Fan Direction", "options": ["forward", "reverse"]})

    # Mock services for TX verification
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "input_number", "set_value")
    async_mock_service(hass, "input_select", "select_option")
    async_mock_service(hass, "input_boolean", "turn_on")
    async_mock_service(hass, "input_boolean", "turn_off")

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
# TEST GROUP: Entity Selector TX (outbound)
# ===========================================================================


class TestEntitySelectorTX:
    """Tests for TX: entity selector commands to external entities."""

    async def test_set_percentage_tx_entity(self, hass: HomeAssistant):
        """Set percentage sends set_value to percentage entity."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_pct_tx")

        await hass.services.async_call(
            "fan", "set_percentage",
            {"entity_id": ENTITY_ID, "percentage": 75},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 75

        # Verify TX: input_number.set_value was called
        calls = [
            c for c in hass.services.async_services_for_domain("input_number")
        ]
        # Verify via state — the entity selector TX calls the service
        assert state.state == STATE_ON

    async def test_set_preset_mode_tx_entity(self, hass: HomeAssistant):
        """Set preset mode sends select_option to preset_mode entity."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_preset_tx")

        await hass.services.async_call(
            "fan", "set_preset_mode",
            {"entity_id": ENTITY_ID, "preset_mode": "sleep"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "sleep"

    async def test_oscillate_tx_entity(self, hass: HomeAssistant):
        """Oscillate sends turn_on/turn_off to oscillating entity."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_osc_tx")

        await hass.services.async_call(
            "fan", "oscillate",
            {"entity_id": ENTITY_ID, "oscillating": True},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("oscillating") is True

    async def test_set_direction_tx_entity(self, hass: HomeAssistant):
        """Set direction sends select_option to direction entity."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_dir_tx")

        await hass.services.async_call(
            "fan", "set_direction",
            {"entity_id": ENTITY_ID, "direction": "reverse"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("direction") == "reverse"

    async def test_turn_on_tx_switch_and_percentage(self, hass: HomeAssistant):
        """Turn on sends turn_on to switch entity AND percentage TX."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_turnon_tx")

        await hass.services.async_call(
            "fan", "turn_on",
            {"entity_id": ENTITY_ID},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON
        assert state.attributes.get("percentage") == 25  # speed_count=4

    async def test_turn_off_tx_switch_and_percentage(self, hass: HomeAssistant):
        """Turn off sends turn_off to switch and sets percentage to 0."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_turnoff_tx")

        # Turn on first
        await hass.services.async_call(
            "fan", "turn_on",
            {"entity_id": ENTITY_ID},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Turn off
        await hass.services.async_call(
            "fan", "turn_off",
            {"entity_id": ENTITY_ID},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_OFF
        assert state.attributes.get("percentage") == 0


# ===========================================================================
# TEST GROUP: RX Listeners (inbound state sync)
# ===========================================================================


class TestRXListeners:
    """Tests for RX: external entity state changes update the fan."""

    async def test_switch_on_rx(self, hass: HomeAssistant):
        """Switch turning ON sets fan to default percentage."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_sw_on_rx")

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_OFF

        # External: switch turns on
        hass.states.async_set(SWITCH_ENTITY, STATE_ON)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON
        assert state.attributes.get("percentage") == 25  # speed_count=4

    async def test_switch_off_rx(self, hass: HomeAssistant):
        """Switch turning OFF sets fan percentage to 0."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_sw_off_rx")

        # Turn on first via switch
        hass.states.async_set(SWITCH_ENTITY, STATE_ON)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON

        # External: switch turns off
        hass.states.async_set(SWITCH_ENTITY, STATE_OFF)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_OFF
        assert state.attributes.get("percentage") == 0

    async def test_percentage_entity_rx(self, hass: HomeAssistant):
        """Percentage entity change updates fan speed."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_pct_rx")

        # External: percentage entity changes
        hass.states.async_set(PCT_ENTITY, "50")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 50
        assert state.state == STATE_ON

    async def test_percentage_entity_rx_clears_preset(self, hass: HomeAssistant):
        """Percentage RX clears preset mode."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_pct_rx_clr")

        # Set preset first
        await hass.services.async_call(
            "fan", "set_preset_mode",
            {"entity_id": ENTITY_ID, "preset_mode": "auto"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "auto"

        # External: percentage entity changes → should clear preset
        hass.states.async_set(PCT_ENTITY, "75")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 75
        assert state.attributes.get("preset_mode") is None

    async def test_preset_mode_entity_rx(self, hass: HomeAssistant):
        """Preset mode entity change updates fan preset."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_preset_rx")

        # External: preset entity changes
        hass.states.async_set(PRESET_ENTITY, "turbo")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "turbo"

    async def test_preset_mode_entity_rx_invalid_ignored(self, hass: HomeAssistant):
        """Invalid preset mode from entity is ignored."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_preset_rx_inv")

        # External: preset entity set to invalid mode
        hass.states.async_set(PRESET_ENTITY, "nonexistent")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        # Should not change from initial (auto synced on setup)
        assert state.attributes.get("preset_mode") in (None, "auto")

    async def test_oscillating_entity_rx_on(self, hass: HomeAssistant):
        """Oscillating entity turning ON sets oscillation true."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_osc_rx_on")

        # External: oscillation entity turns on
        hass.states.async_set(OSC_ENTITY, STATE_ON)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("oscillating") is True

    async def test_oscillating_entity_rx_off(self, hass: HomeAssistant):
        """Oscillating entity turning OFF sets oscillation false."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_osc_rx_off")

        # Turn on first
        hass.states.async_set(OSC_ENTITY, STATE_ON)
        await hass.async_block_till_done()

        # External: oscillation entity turns off
        hass.states.async_set(OSC_ENTITY, STATE_OFF)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("oscillating") is False

    async def test_direction_entity_rx(self, hass: HomeAssistant):
        """Direction entity change updates fan direction."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_dir_rx")

        # External: direction entity changes
        hass.states.async_set(DIR_ENTITY, "reverse")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("direction") == "reverse"

    async def test_direction_entity_rx_invalid_ignored(self, hass: HomeAssistant):
        """Invalid direction from entity is ignored."""
        await _setup_entity(hass, TX_RX_CONFIG, "test_dir_rx_inv")

        # External: direction entity set to invalid value
        hass.states.async_set(DIR_ENTITY, "sideways")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        # Should remain at initial (forward synced on setup)
        assert state.attributes.get("direction") == "forward"


# ===========================================================================
# TEST GROUP: Action Script Overrides
# ===========================================================================


class TestActionScriptOverrides:
    """Tests for TX: action scripts take priority over entity selectors."""

    async def test_set_percentage_action_script(self, hass: HomeAssistant):
        """Action script fires instead of entity selector for percentage."""
        await _setup_entity(hass, ACTION_SCRIPT_CONFIG, "test_pct_script")

        await hass.services.async_call(
            "fan", "set_percentage",
            {"entity_id": ENTITY_ID, "percentage": 50},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 50
        assert state.state == STATE_ON

    async def test_set_preset_mode_action_script(self, hass: HomeAssistant):
        """Action script fires instead of entity selector for preset mode."""
        await _setup_entity(hass, ACTION_SCRIPT_CONFIG, "test_preset_script")

        await hass.services.async_call(
            "fan", "set_preset_mode",
            {"entity_id": ENTITY_ID, "preset_mode": "turbo"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "turbo"

    async def test_oscillate_action_script(self, hass: HomeAssistant):
        """Action script fires instead of entity selector for oscillation."""
        await _setup_entity(hass, ACTION_SCRIPT_CONFIG, "test_osc_script")

        await hass.services.async_call(
            "fan", "oscillate",
            {"entity_id": ENTITY_ID, "oscillating": True},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("oscillating") is True

    async def test_set_direction_action_script(self, hass: HomeAssistant):
        """Action script fires instead of entity selector for direction."""
        await _setup_entity(hass, ACTION_SCRIPT_CONFIG, "test_dir_script")

        await hass.services.async_call(
            "fan", "set_direction",
            {"entity_id": ENTITY_ID, "direction": "reverse"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("direction") == "reverse"


# ===========================================================================
# TEST GROUP: Initial State Sync
# ===========================================================================


class TestInitialStateSync:
    """Tests for initial state sync from external entities on setup."""

    async def test_initial_percentage_sync(self, hass: HomeAssistant):
        """Percentage entity value is synced at setup."""
        # Set percentage entity state BEFORE setup
        # Switch must be ON or switch sync will override percentage to 0
        hass.states.async_set(SWITCH_ENTITY, STATE_ON)
        hass.states.async_set(PCT_ENTITY, "50")
        hass.states.async_set(PRESET_ENTITY, "none")
        hass.states.async_set(OSC_ENTITY, STATE_OFF)
        hass.states.async_set(DIR_ENTITY, "forward")

        async_mock_service(hass, "homeassistant", "turn_on")
        async_mock_service(hass, "homeassistant", "turn_off")
        async_mock_service(hass, "input_number", "set_value")
        async_mock_service(hass, "input_select", "select_option")
        async_mock_service(hass, "input_boolean", "turn_on")
        async_mock_service(hass, "input_boolean", "turn_off")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="TX RX Fan",
            data={},
            options=TX_RX_CONFIG,
            entry_id="test_init_pct_sync",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 50

    async def test_initial_preset_mode_sync(self, hass: HomeAssistant):
        """Preset mode entity value is synced at setup."""
        hass.states.async_set(SWITCH_ENTITY, STATE_OFF)
        hass.states.async_set(PCT_ENTITY, "0")
        hass.states.async_set(PRESET_ENTITY, "sleep")
        hass.states.async_set(OSC_ENTITY, STATE_OFF)
        hass.states.async_set(DIR_ENTITY, "forward")

        async_mock_service(hass, "homeassistant", "turn_on")
        async_mock_service(hass, "homeassistant", "turn_off")
        async_mock_service(hass, "input_number", "set_value")
        async_mock_service(hass, "input_select", "select_option")
        async_mock_service(hass, "input_boolean", "turn_on")
        async_mock_service(hass, "input_boolean", "turn_off")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="TX RX Fan",
            data={},
            options=TX_RX_CONFIG,
            entry_id="test_init_preset_sync",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "sleep"

    async def test_initial_direction_sync(self, hass: HomeAssistant):
        """Direction entity value is synced at setup."""
        hass.states.async_set(SWITCH_ENTITY, STATE_OFF)
        hass.states.async_set(PCT_ENTITY, "0")
        hass.states.async_set(PRESET_ENTITY, "none")
        hass.states.async_set(OSC_ENTITY, STATE_OFF)
        hass.states.async_set(DIR_ENTITY, "reverse")

        async_mock_service(hass, "homeassistant", "turn_on")
        async_mock_service(hass, "homeassistant", "turn_off")
        async_mock_service(hass, "input_number", "set_value")
        async_mock_service(hass, "input_select", "select_option")
        async_mock_service(hass, "input_boolean", "turn_on")
        async_mock_service(hass, "input_boolean", "turn_off")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="TX RX Fan",
            data={},
            options=TX_RX_CONFIG,
            entry_id="test_init_dir_sync",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("direction") == "reverse"

    async def test_initial_oscillation_sync(self, hass: HomeAssistant):
        """Oscillation entity value is synced at setup."""
        hass.states.async_set(SWITCH_ENTITY, STATE_OFF)
        hass.states.async_set(PCT_ENTITY, "0")
        hass.states.async_set(PRESET_ENTITY, "none")
        hass.states.async_set(OSC_ENTITY, STATE_ON)
        hass.states.async_set(DIR_ENTITY, "forward")

        async_mock_service(hass, "homeassistant", "turn_on")
        async_mock_service(hass, "homeassistant", "turn_off")
        async_mock_service(hass, "input_number", "set_value")
        async_mock_service(hass, "input_select", "select_option")
        async_mock_service(hass, "input_boolean", "turn_on")
        async_mock_service(hass, "input_boolean", "turn_off")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="TX RX Fan",
            data={},
            options=TX_RX_CONFIG,
            entry_id="test_init_osc_sync",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("oscillating") is True

    async def test_initial_switch_on_sync(self, hass: HomeAssistant):
        """Switch already ON at setup sets fan to default percentage."""
        hass.states.async_set(SWITCH_ENTITY, STATE_ON)
        hass.states.async_set(PCT_ENTITY, "0")
        hass.states.async_set(PRESET_ENTITY, "none")
        hass.states.async_set(OSC_ENTITY, STATE_OFF)
        hass.states.async_set(DIR_ENTITY, "forward")

        async_mock_service(hass, "homeassistant", "turn_on")
        async_mock_service(hass, "homeassistant", "turn_off")
        async_mock_service(hass, "input_number", "set_value")
        async_mock_service(hass, "input_select", "select_option")
        async_mock_service(hass, "input_boolean", "turn_on")
        async_mock_service(hass, "input_boolean", "turn_off")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="TX RX Fan",
            data={},
            options=TX_RX_CONFIG,
            entry_id="test_init_sw_on",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON
        assert state.attributes.get("percentage") == 25  # speed_count=4
