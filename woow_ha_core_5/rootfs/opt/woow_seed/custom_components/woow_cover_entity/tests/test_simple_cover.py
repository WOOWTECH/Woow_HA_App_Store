"""Tests for SimpleCover core operations."""

from __future__ import annotations

import pytest
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    DOMAIN as COVER_DOMAIN,
    CoverEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_STOP_COVER,
    STATE_OPEN,
    STATE_CLOSED,
)
from homeassistant import loader
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.woow_cover_entity.const import DOMAIN


async def _setup_entity(
    hass: HomeAssistant,
    options: dict | None = None,
) -> str:
    """Set up a SimpleCover entity and return its entity_id."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    default_options = {
        "name": "Test Cover",
    }
    if options:
        default_options.update(options)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Cover",
        data={},
        options=default_options,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return "cover.test_cover"


# ============================================================================
# Open / Close / Stop
# ============================================================================


class TestOpenCloseStop:
    """Tests for open, close, and stop operations."""

    async def test_open_cover_sets_position_100(self, hass: HomeAssistant):
        """Opening cover without TX target sets position to 100."""
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state == STATE_OPEN
        assert state.attributes.get("current_position") == 100

    async def test_close_cover_sets_position_0(self, hass: HomeAssistant):
        """Closing cover without TX target sets position to 0."""
        entity_id = await _setup_entity(hass)

        # First open
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        # Then close
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state == STATE_CLOSED
        assert state.attributes.get("current_position") == 0

    async def test_stop_cover_clears_movement_flags(
        self, hass: HomeAssistant
    ):
        """Stop cover clears opening/closing flags."""
        entity_id = await _setup_entity(
            hass,
            options={"stop_cover": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.dummy"}}]},
        )

        state = hass.states.get(entity_id)
        # After stop, not opening or closing
        assert state.attributes.get("opening") is not True
        assert state.attributes.get("closing") is not True

    async def test_initial_state_is_unknown(self, hass: HomeAssistant):
        """Cover starts with unknown state (position=None)."""
        entity_id = await _setup_entity(hass)

        state = hass.states.get(entity_id)
        # Position is None -> state is "unknown"
        assert state.attributes.get("current_position") is None


# ============================================================================
# Set Position
# ============================================================================


class TestSetPosition:
    """Tests for set_cover_position."""

    async def test_set_position_50(self, hass: HomeAssistant):
        """Setting position to 50 without TX target sets it directly."""
        entity_id = await _setup_entity(
            hass,
            options={"set_position": [{"action": "input_number.set_value", "target": {"entity_id": "input_number.dummy"}, "data": {"value": "{{ position }}"}}]},
        )

        # Open first so we have a known position
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        # Now set to 50
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_SET_COVER_POSITION,
            {ATTR_ENTITY_ID: entity_id, ATTR_POSITION: 50},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state == STATE_OPEN

    async def test_set_position_0_means_closed(self, hass: HomeAssistant):
        """Setting position to 0 means cover is closed."""
        entity_id = await _setup_entity(hass)

        # Open first
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        # Close by setting position 0
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state == STATE_CLOSED

    async def test_set_position_100_means_open(self, hass: HomeAssistant):
        """Setting position to 100 means cover is open."""
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state == STATE_OPEN
        assert state.attributes.get("current_position") == 100


# ============================================================================
# Tilt
# ============================================================================


class TestTilt:
    """Tests for tilt operations."""

    async def test_open_tilt_sets_tilt_100(self, hass: HomeAssistant):
        """Open tilt sets tilt position to 100."""
        entity_id = await _setup_entity(
            hass, options={"enable_tilt": True}
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            "open_cover_tilt",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 100

    async def test_close_tilt_sets_tilt_0(self, hass: HomeAssistant):
        """Close tilt sets tilt position to 0."""
        entity_id = await _setup_entity(
            hass, options={"enable_tilt": True}
        )

        # Open tilt first
        await hass.services.async_call(
            COVER_DOMAIN,
            "open_cover_tilt",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        # Close tilt
        await hass.services.async_call(
            COVER_DOMAIN,
            "close_cover_tilt",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 0

    async def test_set_tilt_position_50(self, hass: HomeAssistant):
        """Set tilt position to 50 with tilt entity updates via RX."""
        hass.states.async_set("input_number.tilt_pos", "0")

        entity_id = await _setup_entity(
            hass,
            options={
                "enable_tilt": True,
                "tilt_position_entity": "input_number.tilt_pos",
            },
        )

        # Simulate RX: external entity changes to 50
        hass.states.async_set("input_number.tilt_pos", "50")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 50


# ============================================================================
# Supported Features
# ============================================================================


class TestSupportedFeatures:
    """Tests for supported features based on config."""

    async def test_basic_features(self, hass: HomeAssistant):
        """Basic cover has OPEN + CLOSE."""
        entity_id = await _setup_entity(hass)

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.OPEN
        assert features & CoverEntityFeature.CLOSE
        assert not (features & CoverEntityFeature.SET_POSITION)

    async def test_position_entity_adds_set_position(
        self, hass: HomeAssistant
    ):
        """Position entity adds SET_POSITION feature."""
        hass.states.async_set("input_number.cover_pos", "50")

        entity_id = await _setup_entity(
            hass,
            options={"position_entity": "input_number.cover_pos"},
        )

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.SET_POSITION

    async def test_set_position_action_adds_set_position(
        self, hass: HomeAssistant
    ):
        """Set position action adds SET_POSITION feature."""
        entity_id = await _setup_entity(
            hass,
            options={"set_position": [{"action": "input_number.set_value", "target": {"entity_id": "input_number.dummy"}, "data": {"value": "{{ position }}"}}]},
        )

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.SET_POSITION

    async def test_stop_action_adds_stop(self, hass: HomeAssistant):
        """Stop cover action adds STOP feature."""
        entity_id = await _setup_entity(
            hass,
            options={"stop_cover": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.dummy"}}]},
        )

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.STOP

    async def test_tilt_features(self, hass: HomeAssistant):
        """Enable tilt adds tilt features."""
        entity_id = await _setup_entity(
            hass, options={"enable_tilt": True}
        )

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.OPEN_TILT
        assert features & CoverEntityFeature.CLOSE_TILT

    async def test_tilt_position_entity_adds_set_tilt(
        self, hass: HomeAssistant
    ):
        """Tilt position entity adds SET_TILT_POSITION feature."""
        hass.states.async_set("input_number.tilt_pos", "50")

        entity_id = await _setup_entity(
            hass,
            options={
                "enable_tilt": True,
                "tilt_position_entity": "input_number.tilt_pos",
            },
        )

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.SET_TILT_POSITION

    async def test_stop_tilt_action_adds_stop_tilt(
        self, hass: HomeAssistant
    ):
        """Stop tilt action adds STOP_TILT feature."""
        entity_id = await _setup_entity(
            hass,
            options={
                "enable_tilt": True,
                "stop_tilt": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.dummy"}}],
            },
        )

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.STOP_TILT


# ============================================================================
# Device Class
# ============================================================================


class TestDeviceClass:
    """Tests for device class configuration."""

    async def test_device_class_blind(self, hass: HomeAssistant):
        """Cover with device_class=blind."""
        entity_id = await _setup_entity(
            hass, options={"device_class": "blind"}
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("device_class") == "blind"

    async def test_device_class_shade(self, hass: HomeAssistant):
        """Cover with device_class=shade."""
        entity_id = await _setup_entity(
            hass, options={"device_class": "shade"}
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("device_class") == "shade"

    async def test_no_device_class(self, hass: HomeAssistant):
        """Cover without device class."""
        entity_id = await _setup_entity(hass)

        state = hass.states.get(entity_id)
        assert state.attributes.get("device_class") is None


# ============================================================================
# State Restoration
# ============================================================================


class TestStateRestoration:
    """Tests for state restoration."""

    async def test_restore_position(self, hass: HomeAssistant):
        """Cover restores position from previous state."""
        entity_id = await _setup_entity(hass)

        # Open the cover
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 100
        assert state.state == STATE_OPEN
