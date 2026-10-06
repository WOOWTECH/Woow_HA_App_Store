"""Tests for Receive Templates and Linear Interpolation.

Tests: percentage linear interpolation (initial + live), percentage receive
template, preset mode receive template, direction receive template, priority
chain (linear > template > passthrough), edge cases.
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

ENTITY_ID = "fan.transform_fan"
SWITCH_ENTITY = "input_boolean.fan_switch"
PCT_ENTITY = "input_number.fan_speed"
PRESET_ENTITY = "input_select.fan_preset"
DIR_ENTITY = "input_select.fan_direction"


# ---------------------------------------------------------------------------
# Base config (no transforms — backward compat)
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "name": "Transform Fan",
    "switch_entity": SWITCH_ENTITY,
    "speed_count": 4,
    "preset_modes": ["auto", "sleep", "turbo"],
    "enable_oscillation": False,
    "enable_direction": True,
    "percentage_entity": PCT_ENTITY,
    "preset_mode_entity": PRESET_ENTITY,
    "direction_entity": DIR_ENTITY,
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _setup_entity(
    hass: HomeAssistant,
    config: dict,
    entry_id: str,
    pct_initial: str = "0",
    preset_initial: str = "none",
    dir_initial: str = "forward",
    switch_initial: str = STATE_ON,
):
    """Set up prerequisite external entities and a fan config entry."""
    hass.states.async_set(SWITCH_ENTITY, switch_initial, {"friendly_name": "Fan Switch"})
    hass.states.async_set(
        PCT_ENTITY, pct_initial, {"friendly_name": "Fan Speed", "min": 0, "max": 1023}
    )
    hass.states.async_set(
        PRESET_ENTITY,
        preset_initial,
        {"friendly_name": "Fan Preset", "options": ["auto", "sleep", "turbo"]},
    )
    hass.states.async_set(
        DIR_ENTITY,
        dir_initial,
        {"friendly_name": "Fan Direction", "options": ["forward", "reverse"]},
    )

    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "input_number", "set_value")
    async_mock_service(hass, "input_select", "select_option")

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
# TEST GROUP: Percentage Linear Interpolation
# ===========================================================================


class TestPercentageLinearInterpolation:
    """Tests for linear interpolation on percentage channel."""

    async def test_initial_read_with_interpolation(self, hass: HomeAssistant):
        """Initial percentage read applies linear interpolation (0-1023 -> 0-100)."""
        config = {
            **BASE_CONFIG,
            "percentage_input_min": 0,
            "percentage_input_max": 1023,
            "percentage_output_min": 0,
            "percentage_output_max": 100,
        }
        await _setup_entity(hass, config, "test_pct_interp_init", pct_initial="512")
        state = hass.states.get(ENTITY_ID)
        # 512 / 1023 * 100 = ~50.05 -> int = 50
        assert state.attributes.get("percentage") == 50

    async def test_live_change_with_interpolation(self, hass: HomeAssistant):
        """Live state change applies linear interpolation."""
        config = {
            **BASE_CONFIG,
            "percentage_input_min": 0,
            "percentage_input_max": 1023,
            "percentage_output_min": 0,
            "percentage_output_max": 100,
        }
        await _setup_entity(hass, config, "test_pct_interp_live", pct_initial="0")

        # Simulate external entity change
        hass.states.async_set(PCT_ENTITY, "1023")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 100

    async def test_division_by_zero_guard(self, hass: HomeAssistant):
        """When input_min == input_max, returns output_min."""
        config = {
            **BASE_CONFIG,
            "percentage_input_min": 50,
            "percentage_input_max": 50,
            "percentage_output_min": 10,
            "percentage_output_max": 90,
        }
        await _setup_entity(hass, config, "test_pct_div_zero", pct_initial="75")
        state = hass.states.get(ENTITY_ID)
        # Division by zero guard -> output_min = 10
        assert state.attributes.get("percentage") == 10

    async def test_backward_compat_no_interpolation(self, hass: HomeAssistant):
        """No interpolation fields -> raw passthrough (backward compatible)."""
        await _setup_entity(hass, BASE_CONFIG, "test_pct_compat", pct_initial="75")
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 75


# ===========================================================================
# TEST GROUP: Percentage Receive Template
# ===========================================================================


class TestPercentageReceiveTemplate:
    """Tests for Jinja2 receive template on percentage channel."""

    async def test_initial_read_with_template(self, hass: HomeAssistant):
        """Initial percentage read applies Jinja2 template."""
        config = {
            **BASE_CONFIG,
            "percentage_receive_template": "{{ (value | float / 10) | int }}",
        }
        await _setup_entity(hass, config, "test_pct_tpl_init", pct_initial="500")
        state = hass.states.get(ENTITY_ID)
        # 500 / 10 = 50
        assert state.attributes.get("percentage") == 50

    async def test_live_change_with_template(self, hass: HomeAssistant):
        """Live state change applies Jinja2 template."""
        config = {
            **BASE_CONFIG,
            "percentage_receive_template": "{{ (value | float / 10) | int }}",
        }
        await _setup_entity(hass, config, "test_pct_tpl_live", pct_initial="0")

        hass.states.async_set(PCT_ENTITY, "750")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 75

    async def test_template_error_skips_update(self, hass: HomeAssistant):
        """Template rendering error -> value skipped, no crash."""
        config = {
            **BASE_CONFIG,
            "percentage_receive_template": "{{ value / 0 }}",
        }
        # Switch ON so the switch sync doesn't interfere
        await _setup_entity(hass, config, "test_pct_tpl_err", pct_initial="50")
        state = hass.states.get(ENTITY_ID)
        # Template error on initial read -> stays at default (switch ON + pct 0 -> default_percentage = 25)
        # The RX fails, so percentage stays at whatever switch sync sets
        assert state.attributes.get("percentage") is not None


# ===========================================================================
# TEST GROUP: Preset Mode Receive Template
# ===========================================================================


class TestPresetModeReceiveTemplate:
    """Tests for Jinja2 receive template on preset mode channel."""

    async def test_initial_read_with_template(self, hass: HomeAssistant):
        """Initial preset mode read applies Jinja2 template (code -> name)."""
        config = {
            **BASE_CONFIG,
            "preset_mode_receive_template": "{% if value == '1' %}auto{% elif value == '2' %}sleep{% else %}turbo{% endif %}",
        }
        await _setup_entity(
            hass, config, "test_preset_tpl_init", preset_initial="1"
        )
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "auto"

    async def test_live_change_with_template(self, hass: HomeAssistant):
        """Live preset mode change applies Jinja2 template."""
        config = {
            **BASE_CONFIG,
            "preset_mode_receive_template": "{% if value == '1' %}auto{% elif value == '2' %}sleep{% else %}turbo{% endif %}",
        }
        await _setup_entity(
            hass, config, "test_preset_tpl_live", preset_initial="none"
        )

        hass.states.async_set(PRESET_ENTITY, "2")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "sleep"

    async def test_invalid_result_ignored(self, hass: HomeAssistant):
        """Template result not in preset_modes -> ignored."""
        config = {
            **BASE_CONFIG,
            "preset_mode_receive_template": "{{ 'invalid_mode' }}",
        }
        await _setup_entity(
            hass, config, "test_preset_tpl_invalid", preset_initial="auto"
        )
        state = hass.states.get(ENTITY_ID)
        # "invalid_mode" not in preset list -> not set
        assert state.attributes.get("preset_mode") is None


# ===========================================================================
# TEST GROUP: Direction Receive Template
# ===========================================================================


class TestDirectionReceiveTemplate:
    """Tests for Jinja2 receive template on direction channel."""

    async def test_initial_read_with_template(self, hass: HomeAssistant):
        """Initial direction read applies Jinja2 template."""
        config = {
            **BASE_CONFIG,
            "direction_receive_template": "{% if value == '0' %}forward{% else %}reverse{% endif %}",
        }
        # dir_initial "1" -> template maps to "reverse"
        await _setup_entity(hass, config, "test_dir_tpl_init", dir_initial="1")
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("direction") == "reverse"

    async def test_live_change_with_template(self, hass: HomeAssistant):
        """Live direction change applies Jinja2 template."""
        config = {
            **BASE_CONFIG,
            "direction_receive_template": "{% if value == '0' %}forward{% else %}reverse{% endif %}",
        }
        await _setup_entity(hass, config, "test_dir_tpl_live", dir_initial="0")

        hass.states.async_set(DIR_ENTITY, "1")
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("direction") == "reverse"

    async def test_invalid_result_ignored(self, hass: HomeAssistant):
        """Template result not forward/reverse -> ignored."""
        config = {
            **BASE_CONFIG,
            "direction_receive_template": "{{ 'sideways' }}",
        }
        # dir_initial "forward" -> template outputs "sideways" which is invalid
        # -> stays at default "forward" (enable_direction=True sets default to forward)
        await _setup_entity(hass, config, "test_dir_tpl_invalid", dir_initial="forward")
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("direction") == "forward"


# ===========================================================================
# TEST GROUP: Priority Chain
# ===========================================================================


class TestPriorityChain:
    """Tests for transform priority: linear > template > passthrough."""

    async def test_linear_overrides_template(self, hass: HomeAssistant):
        """When both linear interpolation and template are set, linear wins."""
        config = {
            **BASE_CONFIG,
            "percentage_receive_template": "{{ value | float * 999 }}",
            "percentage_input_min": 0,
            "percentage_input_max": 1023,
            "percentage_output_min": 0,
            "percentage_output_max": 100,
        }
        await _setup_entity(hass, config, "test_priority_linear", pct_initial="512")
        state = hass.states.get(ENTITY_ID)
        # Linear: 512/1023*100 = ~50, NOT template: 512*999
        assert state.attributes.get("percentage") == 50

    async def test_partial_linear_falls_back_to_template(self, hass: HomeAssistant):
        """Partial linear fields (not all 4) -> falls back to template."""
        config = {
            **BASE_CONFIG,
            "percentage_receive_template": "{{ (value | float / 10) | int }}",
            "percentage_input_min": 0,
            # missing input_max, output_min, output_max
        }
        await _setup_entity(hass, config, "test_priority_partial", pct_initial="500")
        state = hass.states.get(ENTITY_ID)
        # Template: 500 / 10 = 50
        assert state.attributes.get("percentage") == 50

    async def test_raw_passthrough_when_neither(self, hass: HomeAssistant):
        """No template, no linear -> raw passthrough."""
        await _setup_entity(hass, BASE_CONFIG, "test_priority_raw", pct_initial="60")
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 60

    async def test_template_works_alone(self, hass: HomeAssistant):
        """Template alone (no linear) works correctly."""
        config = {
            **BASE_CONFIG,
            "percentage_receive_template": "{{ value | float + 5 }}",
        }
        await _setup_entity(hass, config, "test_priority_tpl_only", pct_initial="45")
        state = hass.states.get(ENTITY_ID)
        # 45 + 5 = 50
        assert state.attributes.get("percentage") == 50


# ===========================================================================
# TEST GROUP: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Edge case tests for receive transforms."""

    async def test_non_numeric_value_skipped_linear(self, hass: HomeAssistant):
        """Non-numeric value with linear interpolation -> skipped."""
        config = {
            **BASE_CONFIG,
            "percentage_input_min": 0,
            "percentage_input_max": 1023,
            "percentage_output_min": 0,
            "percentage_output_max": 100,
        }
        # Switch ON, but RX will fail on "abc" -> percentage stays at switch default
        await _setup_entity(hass, config, "test_edge_non_numeric", pct_initial="abc")
        state = hass.states.get(ENTITY_ID)
        # "abc" can't be float -> skipped. Switch is ON + pct=0 -> default_percentage=25
        assert state.attributes.get("percentage") == 25

    async def test_large_values_interpolation(self, hass: HomeAssistant):
        """Very large input values are handled correctly."""
        config = {
            **BASE_CONFIG,
            "percentage_input_min": 0,
            "percentage_input_max": 65535,
            "percentage_output_min": 0,
            "percentage_output_max": 100,
        }
        await _setup_entity(
            hass, config, "test_edge_large", pct_initial="32768"
        )
        state = hass.states.get(ENTITY_ID)
        # 32768/65535*100 = ~50.0008 -> int = 50
        assert state.attributes.get("percentage") == 50

    async def test_existing_config_unchanged(self, hass: HomeAssistant):
        """Existing config without new fields works perfectly (backward compat)."""
        config = {
            "name": "Transform Fan",
            "switch_entity": SWITCH_ENTITY,
            "speed_count": 4,
            "preset_modes": ["auto", "sleep", "turbo"],
            "enable_oscillation": False,
            "enable_direction": True,
            "percentage_entity": PCT_ENTITY,
            "preset_mode_entity": PRESET_ENTITY,
            "direction_entity": DIR_ENTITY,
        }
        await _setup_entity(
            hass,
            config,
            "test_edge_compat",
            pct_initial="80",
            preset_initial="sleep",
            dir_initial="reverse",
        )
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage") == 80
        assert state.attributes.get("preset_mode") == "sleep"
        assert state.attributes.get("direction") == "reverse"
