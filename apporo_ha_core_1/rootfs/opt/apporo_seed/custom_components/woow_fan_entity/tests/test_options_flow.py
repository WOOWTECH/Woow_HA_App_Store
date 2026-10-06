"""Tests for config flow and options flow.

Tests: config entry creation, options update, field validation,
and config entry title.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_OFF
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.woow_fan_entity.const import DOMAIN


# ---------------------------------------------------------------------------
# Configs
# ---------------------------------------------------------------------------

BASIC_CONFIG = {
    "name": "Basic Fan",
    "switch_entity": "input_boolean.fan_switch",
    "speed_count": 3,
}

FULL_CONFIG = {
    "name": "Full Fan",
    "switch_entity": "input_boolean.fan_switch",
    "speed_count": 4,
    "preset_modes": ["auto", "sleep", "turbo"],
    "enable_oscillation": True,
    "enable_direction": True,
    "percentage_entity": "input_number.fan_speed",
    "preset_mode_entity": "input_select.fan_preset",
    "oscillating_entity": "input_boolean.fan_osc",
    "direction_entity": "input_select.fan_direction",
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _setup_helpers(hass: HomeAssistant):
    """Set up prerequisite entities for test."""
    hass.states.async_set(
        "input_boolean.fan_switch", STATE_OFF, {"friendly_name": "Fan Switch"}
    )
    hass.states.async_set(
        "input_number.fan_speed", "0", {"friendly_name": "Fan Speed"}
    )
    hass.states.async_set(
        "input_select.fan_preset", "none", {"friendly_name": "Fan Preset"}
    )
    hass.states.async_set(
        "input_boolean.fan_osc", STATE_OFF, {"friendly_name": "Fan Oscillation"}
    )
    hass.states.async_set(
        "input_select.fan_direction", "forward", {"friendly_name": "Fan Direction"}
    )

    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "input_number", "set_value")
    async_mock_service(hass, "input_select", "select_option")


# ===========================================================================
# TEST GROUP: Config Entry Creation
# ===========================================================================


class TestConfigEntryCreation:
    """Tests for creating config entries via config flow."""

    async def test_basic_entry_created(self, hass: HomeAssistant):
        """Basic config creates a valid entry."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Basic Fan",
            data={},
            options=BASIC_CONFIG,
            entry_id="test_basic_entry",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("fan.basic_fan")
        assert state is not None
        assert state.state == "off"

    async def test_full_entry_created(self, hass: HomeAssistant):
        """Full config with all options creates a valid entry."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Full Fan",
            data={},
            options=FULL_CONFIG,
            entry_id="test_full_entry",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("fan.full_fan")
        assert state is not None
        assert state.state == "off"
        assert state.attributes.get("preset_modes") == ["auto", "sleep", "turbo"]

    async def test_entry_with_action_scripts(self, hass: HomeAssistant):
        """Config with action script overrides creates a valid entry."""
        await _setup_helpers(hass)

        config = {
            **FULL_CONFIG,
            "name": "Script Fan",
            "set_percentage": [
                {
                    "action": "input_number.set_value",
                    "target": {"entity_id": "input_number.fan_speed"},
                    "data": {"value": "{{ percentage }}"},
                }
            ],
        }

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Script Fan",
            data={},
            options=config,
            entry_id="test_script_entry",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("fan.script_fan")
        assert state is not None

    async def test_entry_title_matches_name(self, hass: HomeAssistant):
        """Entry title matches configured name."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="My Custom Fan",
            data={},
            options={**BASIC_CONFIG, "name": "My Custom Fan"},
            entry_id="test_title",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.title == "My Custom Fan"

    async def test_entry_unload(self, hass: HomeAssistant):
        """Config entry can be unloaded."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Basic Fan",
            data={},
            options=BASIC_CONFIG,
            entry_id="test_unload",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("fan.basic_fan")
        assert state is not None

        result = await hass.config_entries.async_unload(entry.entry_id)
        assert result is True


# ===========================================================================
# TEST GROUP: Options Flow
# ===========================================================================


class TestOptionsFlow:
    """Tests for modifying config entry options."""

    async def test_options_flow_exists(self, hass: HomeAssistant):
        """Options flow can be initiated."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Basic Fan",
            data={},
            options=BASIC_CONFIG,
            entry_id="test_options_flow",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

    async def test_options_update_speed_count(self, hass: HomeAssistant):
        """Options flow can update speed count."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Basic Fan",
            data={},
            options=BASIC_CONFIG,
            entry_id="test_options_speed",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "switch_entity": "input_boolean.fan_switch",
                "speed_count": 6,
                "enable_oscillation": False,
                "enable_direction": False,
            },
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options.get("speed_count") == 6

    async def test_options_add_preset_modes(self, hass: HomeAssistant):
        """Options flow can add preset modes."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Basic Fan",
            data={},
            options=BASIC_CONFIG,
            entry_id="test_options_presets",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "switch_entity": "input_boolean.fan_switch",
                "speed_count": 3,
                "preset_modes": ["auto", "sleep"],
                "enable_oscillation": False,
                "enable_direction": False,
            },
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options.get("preset_modes") == ["auto", "sleep"]

    async def test_options_enable_oscillation(self, hass: HomeAssistant):
        """Options flow can enable oscillation."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Basic Fan",
            data={},
            options=BASIC_CONFIG,
            entry_id="test_options_osc",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "switch_entity": "input_boolean.fan_switch",
                "speed_count": 3,
                "enable_oscillation": True,
                "enable_direction": False,
            },
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options.get("enable_oscillation") is True

    async def test_options_add_entity_selectors(self, hass: HomeAssistant):
        """Options flow can add entity selectors."""
        await _setup_helpers(hass)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Basic Fan",
            data={},
            options=BASIC_CONFIG,
            entry_id="test_options_entities",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "switch_entity": "input_boolean.fan_switch",
                "speed_count": 3,
                "enable_oscillation": False,
                "enable_direction": False,
                "percentage_entity": "input_number.fan_speed",
            },
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options.get("percentage_entity") == "input_number.fan_speed"


# ===========================================================================
# TEST GROUP: Config Flow User Step
# ===========================================================================


class TestConfigFlowUserStep:
    """Tests for the config flow user step."""

    async def test_config_flow_init(self, hass: HomeAssistant):
        """Config flow can be initiated."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

    async def test_config_flow_create_entry(self, hass: HomeAssistant):
        """Config flow creates entry with user input."""
        hass.states.async_set(
            "input_boolean.fan_switch", STATE_OFF, {"friendly_name": "Fan Switch"}
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "name": "My New Fan",
                "switch_entity": "input_boolean.fan_switch",
                "speed_count": 3,
                "enable_oscillation": False,
                "enable_direction": False,
            },
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "My New Fan"
        assert result["options"]["speed_count"] == 3

    async def test_config_flow_with_presets(self, hass: HomeAssistant):
        """Config flow creates entry with preset modes."""
        hass.states.async_set(
            "input_boolean.fan_switch", STATE_OFF, {"friendly_name": "Fan Switch"}
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "name": "Preset Fan",
                "switch_entity": "input_boolean.fan_switch",
                "speed_count": 3,
                "preset_modes": ["auto", "sleep", "turbo"],
                "enable_oscillation": True,
                "enable_direction": True,
            },
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["options"]["preset_modes"] == ["auto", "sleep", "turbo"]
        assert result["options"]["enable_oscillation"] is True
        assert result["options"]["enable_direction"] is True
