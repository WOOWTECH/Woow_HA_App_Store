"""Tests for SimpleFan core functionality.

Tests: turn on/off, set percentage, preset modes, oscillation, direction,
supported features, state attributes, and invalid inputs.
"""

from __future__ import annotations

import pytest
from homeassistant.components.fan import FanEntityFeature
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.woow_fan_entity.const import DOMAIN


# ---------------------------------------------------------------------------
# Base configs
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "name": "Test Fan",
    "switch_entity": "input_boolean.test_fan_switch",
    "speed_count": 3,
    "preset_modes": None,
    "enable_oscillation": False,
    "enable_direction": False,
}

FULL_CONFIG = {
    "name": "Test Full Fan",
    "switch_entity": "input_boolean.test_fan_switch",
    "speed_count": 4,
    "preset_modes": ["auto", "sleep", "turbo"],
    "enable_oscillation": True,
    "enable_direction": True,
}

ENTITY_ID = "fan.test_fan"
FULL_ENTITY_ID = "fan.test_full_fan"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _setup_entity(
    hass: HomeAssistant,
    config: dict,
    entry_id: str,
    entity_id: str = ENTITY_ID,
):
    """Set up prerequisite entities and a fan config entry."""
    hass.states.async_set(
        "input_boolean.test_fan_switch",
        STATE_OFF,
        {"friendly_name": "Test Fan Switch"},
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
# TEST GROUP: Turn On/Off
# ===========================================================================


class TestTurnOnOff:
    """Tests for basic fan on/off control."""

    async def test_turn_on_default_speed(self, hass: HomeAssistant):
        """Turn on sets default percentage based on speed_count."""
        await _setup_entity(hass, BASE_CONFIG, "test_on_default")
        state = hass.states.get(ENTITY_ID)
        assert state is not None
        assert state.state == STATE_OFF

        await hass.services.async_call(
            "fan", "turn_on", {"entity_id": ENTITY_ID}, blocking=True
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON
        # speed_count=3 → step=33, default = 33
        assert state.attributes.get("percentage") == 33

    async def test_turn_on_with_percentage(self, hass: HomeAssistant):
        """Turn on with specific percentage."""
        await _setup_entity(hass, BASE_CONFIG, "test_on_pct")

        await hass.services.async_call(
            "fan", "turn_on",
            {"entity_id": ENTITY_ID, "percentage": 67},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON
        assert state.attributes.get("percentage") == 67

    async def test_turn_off(self, hass: HomeAssistant):
        """Turn off sets percentage to 0."""
        await _setup_entity(hass, BASE_CONFIG, "test_off")

        # Turn on first
        await hass.services.async_call(
            "fan", "turn_on", {"entity_id": ENTITY_ID}, blocking=True
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON

        # Turn off
        await hass.services.async_call(
            "fan", "turn_off", {"entity_id": ENTITY_ID}, blocking=True
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_OFF
        assert state.attributes.get("percentage") == 0

    async def test_turn_on_calls_switch_service(self, hass: HomeAssistant):
        """Turn on sends turn_on service to switch entity."""
        hass.states.async_set(
            "input_boolean.test_fan_switch",
            STATE_OFF,
            {"friendly_name": "Test Fan Switch"},
        )

        turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")
        async_mock_service(hass, "homeassistant", "turn_off")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=BASE_CONFIG["name"],
            data={},
            options=BASE_CONFIG,
            entry_id="test_on_switch",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "fan", "turn_on", {"entity_id": ENTITY_ID}, blocking=True
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON

        # Verify turn_on was called for the switch entity
        assert len(turn_on_calls) > 0
        assert any(
            "input_boolean.test_fan_switch" in (c.data.get("entity_id") or [])
            or c.data.get("entity_id") == "input_boolean.test_fan_switch"
            for c in turn_on_calls
        )


# ===========================================================================
# TEST GROUP: Set Percentage
# ===========================================================================


class TestSetPercentage:
    """Tests for fan speed percentage control."""

    async def test_set_percentage(self, hass: HomeAssistant):
        """Set specific percentage."""
        await _setup_entity(hass, BASE_CONFIG, "test_set_pct")

        await hass.services.async_call(
            "fan", "set_percentage",
            {"entity_id": ENTITY_ID, "percentage": 50},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON
        assert state.attributes.get("percentage") == 50

    async def test_set_percentage_zero_turns_off(self, hass: HomeAssistant):
        """Setting percentage to 0 turns off the fan."""
        await _setup_entity(hass, BASE_CONFIG, "test_set_pct_zero")

        # Turn on first
        await hass.services.async_call(
            "fan", "turn_on",
            {"entity_id": ENTITY_ID, "percentage": 67},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Set to 0
        await hass.services.async_call(
            "fan", "set_percentage",
            {"entity_id": ENTITY_ID, "percentage": 0},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_OFF
        assert state.attributes.get("percentage") == 0

    async def test_set_percentage_100(self, hass: HomeAssistant):
        """Set percentage to maximum."""
        await _setup_entity(hass, BASE_CONFIG, "test_set_pct_max")

        await hass.services.async_call(
            "fan", "set_percentage",
            {"entity_id": ENTITY_ID, "percentage": 100},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_ON
        assert state.attributes.get("percentage") == 100

    async def test_percentage_step(self, hass: HomeAssistant):
        """Percentage step matches 100/speed_count."""
        await _setup_entity(hass, BASE_CONFIG, "test_pct_step")

        state = hass.states.get(ENTITY_ID)
        # speed_count=3 → step = 100/3 ≈ 33.33
        assert state.attributes.get("percentage_step") == pytest.approx(
            100 / 3, abs=0.1
        )


# ===========================================================================
# TEST GROUP: Preset Modes
# ===========================================================================


class TestPresetModes:
    """Tests for fan preset mode control."""

    async def test_set_preset_mode(self, hass: HomeAssistant):
        """Set valid preset mode."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_preset", entity_id=FULL_ENTITY_ID
        )

        await hass.services.async_call(
            "fan", "set_preset_mode",
            {"entity_id": FULL_ENTITY_ID, "preset_mode": "sleep"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.attributes.get("preset_mode") == "sleep"

    async def test_preset_mode_clears_percentage(self, hass: HomeAssistant):
        """Setting preset mode clears percentage."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_preset_clr", entity_id=FULL_ENTITY_ID
        )

        # Set percentage first
        await hass.services.async_call(
            "fan", "set_percentage",
            {"entity_id": FULL_ENTITY_ID, "percentage": 75},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Set preset mode
        await hass.services.async_call(
            "fan", "set_preset_mode",
            {"entity_id": FULL_ENTITY_ID, "preset_mode": "auto"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.attributes.get("preset_mode") == "auto"
        assert state.attributes.get("percentage") is None

    async def test_turn_on_with_preset(self, hass: HomeAssistant):
        """Turn on with preset_mode parameter."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_on_preset", entity_id=FULL_ENTITY_ID
        )

        await hass.services.async_call(
            "fan", "turn_on",
            {"entity_id": FULL_ENTITY_ID, "preset_mode": "turbo"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.state == STATE_ON
        assert state.attributes.get("preset_mode") == "turbo"

    async def test_no_preset_when_not_configured(self, hass: HomeAssistant):
        """No preset modes when not configured."""
        await _setup_entity(hass, BASE_CONFIG, "test_no_preset")

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_modes") is None
        assert state.attributes.get("preset_mode") is None


# ===========================================================================
# TEST GROUP: Oscillation
# ===========================================================================


class TestOscillation:
    """Tests for fan oscillation control."""

    async def test_oscillate_on(self, hass: HomeAssistant):
        """Enable oscillation."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_osc_on", entity_id=FULL_ENTITY_ID
        )

        await hass.services.async_call(
            "fan", "oscillate",
            {"entity_id": FULL_ENTITY_ID, "oscillating": True},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.attributes.get("oscillating") is True

    async def test_oscillate_off(self, hass: HomeAssistant):
        """Disable oscillation."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_osc_off", entity_id=FULL_ENTITY_ID
        )

        # Enable then disable
        await hass.services.async_call(
            "fan", "oscillate",
            {"entity_id": FULL_ENTITY_ID, "oscillating": True},
            blocking=True,
        )
        await hass.services.async_call(
            "fan", "oscillate",
            {"entity_id": FULL_ENTITY_ID, "oscillating": False},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.attributes.get("oscillating") is False


# ===========================================================================
# TEST GROUP: Direction
# ===========================================================================


class TestDirection:
    """Tests for fan direction control."""

    async def test_set_direction_forward(self, hass: HomeAssistant):
        """Set direction to forward."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_dir_fwd", entity_id=FULL_ENTITY_ID
        )

        await hass.services.async_call(
            "fan", "set_direction",
            {"entity_id": FULL_ENTITY_ID, "direction": "forward"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.attributes.get("direction") == "forward"

    async def test_set_direction_reverse(self, hass: HomeAssistant):
        """Set direction to reverse."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_dir_rev", entity_id=FULL_ENTITY_ID
        )

        await hass.services.async_call(
            "fan", "set_direction",
            {"entity_id": FULL_ENTITY_ID, "direction": "reverse"},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.attributes.get("direction") == "reverse"


# ===========================================================================
# TEST GROUP: Supported Features
# ===========================================================================


class TestSupportedFeatures:
    """Tests for dynamic supported features."""

    async def test_basic_features(self, hass: HomeAssistant):
        """Basic config has speed + turn on/off."""
        await _setup_entity(hass, BASE_CONFIG, "test_basic_feat")

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features", 0)
        assert features & FanEntityFeature.SET_SPEED
        assert features & FanEntityFeature.TURN_ON
        assert features & FanEntityFeature.TURN_OFF
        assert not (features & FanEntityFeature.PRESET_MODE)
        assert not (features & FanEntityFeature.OSCILLATE)
        assert not (features & FanEntityFeature.DIRECTION)

    async def test_full_features(self, hass: HomeAssistant):
        """Full config has all features."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_full_feat", entity_id=FULL_ENTITY_ID
        )

        state = hass.states.get(FULL_ENTITY_ID)
        features = state.attributes.get("supported_features", 0)
        assert features & FanEntityFeature.SET_SPEED
        assert features & FanEntityFeature.TURN_ON
        assert features & FanEntityFeature.TURN_OFF
        assert features & FanEntityFeature.PRESET_MODE
        assert features & FanEntityFeature.OSCILLATE
        assert features & FanEntityFeature.DIRECTION

    async def test_preset_only(self, hass: HomeAssistant):
        """Preset modes enabled but no oscillation/direction."""
        config = {
            **BASE_CONFIG,
            "name": "Preset Fan",
            "preset_modes": ["auto", "sleep"],
        }
        await _setup_entity(hass, config, "test_preset_feat", entity_id="fan.preset_fan")

        state = hass.states.get("fan.preset_fan")
        features = state.attributes.get("supported_features", 0)
        assert features & FanEntityFeature.PRESET_MODE
        assert not (features & FanEntityFeature.OSCILLATE)
        assert not (features & FanEntityFeature.DIRECTION)


# ===========================================================================
# TEST GROUP: Entity Attributes
# ===========================================================================


class TestEntityAttributes:
    """Tests for entity state attributes."""

    async def test_initial_state_off(self, hass: HomeAssistant):
        """Fan starts in OFF state."""
        await _setup_entity(hass, BASE_CONFIG, "test_init_state")

        state = hass.states.get(ENTITY_ID)
        assert state.state == STATE_OFF
        assert state.attributes.get("percentage") == 0

    async def test_speed_count(self, hass: HomeAssistant):
        """Speed count is correct."""
        config = {**BASE_CONFIG, "speed_count": 5}
        await _setup_entity(hass, config, "test_speed_cnt")

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("percentage_step") == pytest.approx(
            20.0, abs=0.1
        )

    async def test_preset_modes_list(self, hass: HomeAssistant):
        """Preset modes list is exposed."""
        await _setup_entity(
            hass, FULL_CONFIG, "test_preset_list", entity_id=FULL_ENTITY_ID
        )

        state = hass.states.get(FULL_ENTITY_ID)
        assert state.attributes.get("preset_modes") == [
            "auto", "sleep", "turbo"
        ]
