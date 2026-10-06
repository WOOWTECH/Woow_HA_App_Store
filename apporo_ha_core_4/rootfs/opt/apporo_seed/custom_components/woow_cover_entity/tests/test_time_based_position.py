"""Tests for time-based position estimation in SimpleCover."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    DOMAIN as COVER_DOMAIN,
    CoverEntityFeature,
    SERVICE_CLOSE_COVER_TILT,
    SERVICE_OPEN_COVER_TILT,
    SERVICE_SET_COVER_TILT_POSITION,
    SERVICE_STOP_COVER_TILT,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_STOP_COVER,
)
from homeassistant import loader
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.woow_cover_entity.const import DOMAIN

# Test config: 10s to open, 5s to close (asymmetric to catch direction bugs)
OPEN_TIME = 10.0
CLOSE_TIME = 5.0
TILT_OPEN_TIME = 4.0
TILT_CLOSE_TIME = 2.0


async def _setup_timed_entity(
    hass: HomeAssistant,
    options: dict | None = None,
) -> str:
    """Set up a SimpleCover with time-based estimation."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    default_options = {
        "name": "Timed Cover",
        "open_time": OPEN_TIME,
        "close_time": CLOSE_TIME,
    }
    if options:
        default_options.update(options)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Timed Cover",
        data={},
        options=default_options,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return "cover.timed_cover"


async def _advance_time(hass: HomeAssistant, seconds: int = 1) -> None:
    """Advance time by N seconds, firing one tick per second."""
    for _ in range(seconds):
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=1)
        )
        await hass.async_block_till_done()


# ============================================================================
# Timer Start / Stop Lifecycle
# ============================================================================


class TestTimerStartStop:
    """Tests for timer lifecycle: start, stop, cancel."""

    async def test_open_starts_timer_and_sets_opening(
        self, hass: HomeAssistant
    ):
        """Opening cover sets is_opening and starts position increment."""
        entity_id = await _setup_timed_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 0
        # is_opening should be True (state = "opening")
        assert state.state == "opening"

    async def test_close_starts_timer_and_sets_closing(
        self, hass: HomeAssistant
    ):
        """Closing cover from position 100 sets is_closing."""
        entity_id = await _setup_timed_entity(hass)

        # First open fully via ticks
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(OPEN_TIME) + 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 100

        # Now close
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state == "closing"

    async def test_stop_cancels_timer_and_clears_flags(
        self, hass: HomeAssistant
    ):
        """Stop cancels timer and clears opening/closing flags."""
        entity_id = await _setup_timed_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 3)

        # Stop mid-movement
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state != "opening"
        assert state.state != "closing"
        pos = state.attributes.get("current_position")
        assert pos > 0
        assert pos < 100

    async def test_already_at_target_no_movement(
        self, hass: HomeAssistant
    ):
        """Opening when already at 100 should not start timer."""
        entity_id = await _setup_timed_entity(hass)

        # Open fully
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(OPEN_TIME) + 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 100
        assert state.state == "open"

        # Open again -- should remain at 100 with no "opening" state
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 100
        assert state.state == "open"

    async def test_new_command_cancels_previous_timer(
        self, hass: HomeAssistant
    ):
        """New open/close command cancels existing timer and starts new one."""
        entity_id = await _setup_timed_entity(hass)

        # Start opening
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 5)  # ~50% open

        # Now close (should cancel open timer and start close)
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.state == "closing"

        # After enough ticks to fully close
        await _advance_time(hass, int(CLOSE_TIME) + 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 0

    async def test_timer_cleanup_on_unload(self, hass: HomeAssistant):
        """Timer is cleaned up when entity is unloaded."""
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Timed Cover",
            data={},
            options={
                "name": "Timed Cover",
                "open_time": OPEN_TIME,
                "close_time": CLOSE_TIME,
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Start opening
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: "cover.timed_cover"},
            blocking=True,
        )

        # Unload should not raise
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


# ============================================================================
# Position Estimation Math
# ============================================================================


class TestPositionEstimation:
    """Tests for position calculation accuracy."""

    async def test_position_increments_on_open(self, hass: HomeAssistant):
        """Position increases by 100/open_time per tick when opening."""
        entity_id = await _setup_timed_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        # After 1 tick: 100/10 = 10
        await _advance_time(hass, 1)
        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 10

    async def test_position_decrements_on_close(self, hass: HomeAssistant):
        """Position decreases by 100/close_time per tick when closing."""
        entity_id = await _setup_timed_entity(hass)

        # Open fully first
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(OPEN_TIME) + 1)

        # Close: 100/5 = 20 per tick
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 80

    async def test_asymmetric_open_close_time(self, hass: HomeAssistant):
        """Opening rate differs from closing rate (10s open vs 5s close)."""
        entity_id = await _setup_timed_entity(hass)

        # Open: 10 per tick (100/10)
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 2)  # 20%

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 20

        # Stop and close: 20 per tick (100/5)
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 1)  # 20 - 20 = 0

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 0

    async def test_position_reaches_100_and_stops(self, hass: HomeAssistant):
        """Timer auto-stops when position reaches 100."""
        entity_id = await _setup_timed_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        # open_time=10, so after 10 ticks position should be 100
        await _advance_time(hass, int(OPEN_TIME) + 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 100
        assert state.state == "open"

    async def test_position_reaches_0_and_stops(self, hass: HomeAssistant):
        """Timer auto-stops when position reaches 0."""
        entity_id = await _setup_timed_entity(hass)

        # Open fully
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(OPEN_TIME) + 1)

        # Close: close_time=5, so 5 ticks
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(CLOSE_TIME) + 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 0
        assert state.state == "closed"

    async def test_set_position_to_50_from_0(self, hass: HomeAssistant):
        """set_cover_position(50) from 0 uses open rate."""
        entity_id = await _setup_timed_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_SET_COVER_POSITION,
            {ATTR_ENTITY_ID: entity_id, ATTR_POSITION: 50},
            blocking=True,
        )

        # open rate = 10 per tick, target=50 -> 5 ticks
        await _advance_time(hass, 5)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 50
        assert state.state == "open"

    async def test_set_position_to_30_from_80(self, hass: HomeAssistant):
        """set_cover_position(30) from 80 uses close rate."""
        entity_id = await _setup_timed_entity(hass)

        # Move to 80
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 8)  # 80%
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        assert hass.states.get(entity_id).attributes.get("current_position") == 80

        # Set to 30: close rate = 20 per tick, distance = 50, but capped at target
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_SET_COVER_POSITION,
            {ATTR_ENTITY_ID: entity_id, ATTR_POSITION: 30},
            blocking=True,
        )

        # 80 -> 60 -> 40 -> 30 (3 ticks, last capped)
        await _advance_time(hass, 3)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 30

    async def test_position_clamped_to_0_100(self, hass: HomeAssistant):
        """Position never goes below 0 or above 100."""
        entity_id = await _setup_timed_entity(hass)

        # Extra ticks beyond full travel
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(OPEN_TIME) + 5)  # Way beyond

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 100


# ============================================================================
# Stop Mid-Movement
# ============================================================================


class TestStopMidMovement:
    """Tests for stopping during movement."""

    async def test_stop_mid_open_records_position(self, hass: HomeAssistant):
        """Stop during open records estimated position."""
        entity_id = await _setup_timed_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        # 5 ticks at 10% each = 50%
        await _advance_time(hass, 5)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 50
        assert state.state == "open"

    async def test_stop_mid_close_records_position(self, hass: HomeAssistant):
        """Stop during close records estimated position."""
        entity_id = await _setup_timed_entity(hass)

        # Open fully
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(OPEN_TIME) + 1)

        # Close for 2 ticks: 100 - 2*20 = 60
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 2)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 60

    async def test_stop_position_stable_after_more_ticks(
        self, hass: HomeAssistant
    ):
        """After stop, position does not change on further time ticks."""
        entity_id = await _setup_timed_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 3)  # 30%

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        pos_after_stop = hass.states.get(entity_id).attributes.get(
            "current_position"
        )

        # More ticks should NOT change position
        await _advance_time(hass, 5)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == pos_after_stop

    async def test_stop_fires_action_script(self, hass: HomeAssistant):
        """Stop action script fires even in time-based mode."""
        calls = async_mock_service(hass, "test", "stop_motor")
        entity_id = await _setup_timed_entity(
            hass,
            options={
                "stop_cover": [
                    {
                        "action": "test.stop_motor",
                        "data": {},
                    }
                ],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 2)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        assert len(calls) == 1


# ============================================================================
# Action Script Integration
# ============================================================================


class TestActionScriptIntegration:
    """Tests for action scripts firing alongside timer."""

    async def test_open_fires_open_action_script(self, hass: HomeAssistant):
        """open_cover action script fires when time-based mode active."""
        calls = async_mock_service(hass, "test", "open_motor")
        entity_id = await _setup_timed_entity(
            hass,
            options={
                "open_cover": [
                    {
                        "action": "test.open_motor",
                        "data": {},
                    }
                ],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        assert len(calls) == 1

    async def test_close_fires_close_action_script(self, hass: HomeAssistant):
        """close_cover action script fires when time-based mode active."""
        calls = async_mock_service(hass, "test", "close_motor")
        entity_id = await _setup_timed_entity(
            hass,
            options={
                "close_cover": [
                    {
                        "action": "test.close_motor",
                        "data": {},
                    }
                ],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        assert len(calls) == 1

    async def test_set_position_fires_script(self, hass: HomeAssistant):
        """set_position action script fires with correct variable."""
        calls = async_mock_service(hass, "test", "set_pos")
        entity_id = await _setup_timed_entity(
            hass,
            options={
                "set_position": [
                    {
                        "action": "test.set_pos",
                        "data": {"position": "{{ position }}"},
                    }
                ],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_SET_COVER_POSITION,
            {ATTR_ENTITY_ID: entity_id, ATTR_POSITION: 50},
            blocking=True,
        )

        assert len(calls) == 1

    async def test_open_falls_back_to_set_position_script(
        self, hass: HomeAssistant
    ):
        """Open uses set_position(100) if no open_cover script."""
        calls = async_mock_service(hass, "test", "set_pos")
        entity_id = await _setup_timed_entity(
            hass,
            options={
                "set_position": [
                    {
                        "action": "test.set_pos",
                        "data": {"position": "{{ position }}"},
                    }
                ],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        assert len(calls) == 1


# ============================================================================
# RX Disabled in Time-Based Mode
# ============================================================================


class TestRXDisabledInTimedMode:
    """Tests for RX guard when time-based mode is active."""

    async def test_position_entity_rx_ignored_in_timed_mode(
        self, hass: HomeAssistant
    ):
        """Position entity changes are ignored when time-based mode active."""
        hass.states.async_set("input_number.pos", "0")

        entity_id = await _setup_timed_entity(
            hass,
            options={"position_entity": "input_number.pos"},
        )

        # External change should be IGNORED
        hass.states.async_set("input_number.pos", "75")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        # Position should still be 0 (default), not 75
        assert state.attributes.get("current_position") != 75

    async def test_tilt_rx_ignored_in_tilt_timed_mode(
        self, hass: HomeAssistant
    ):
        """Tilt entity changes are ignored when tilt time-based mode active."""
        hass.states.async_set("input_number.tilt_pos", "0")

        entity_id = await _setup_timed_entity(
            hass,
            options={
                "enable_tilt": True,
                "tilt_position_entity": "input_number.tilt_pos",
                "tilt_open_time": TILT_OPEN_TIME,
                "tilt_close_time": TILT_CLOSE_TIME,
            },
        )

        # External change should be IGNORED
        hass.states.async_set("input_number.tilt_pos", "80")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") != 80


# ============================================================================
# Supported Features
# ============================================================================


class TestSupportedFeaturesWithTimer:
    """Tests for auto-enabled features in time-based mode."""

    async def test_timed_mode_enables_set_position(
        self, hass: HomeAssistant
    ):
        """SET_POSITION is auto-enabled when open_time/close_time are set."""
        entity_id = await _setup_timed_entity(hass)

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.SET_POSITION

    async def test_timed_mode_enables_stop(self, hass: HomeAssistant):
        """STOP is auto-enabled when open_time/close_time are set."""
        entity_id = await _setup_timed_entity(hass)

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.STOP

    async def test_tilt_timed_mode_enables_tilt_features(
        self, hass: HomeAssistant
    ):
        """SET_TILT_POSITION and STOP_TILT auto-enabled with tilt times."""
        entity_id = await _setup_timed_entity(
            hass,
            options={
                "enable_tilt": True,
                "tilt_open_time": TILT_OPEN_TIME,
                "tilt_close_time": TILT_CLOSE_TIME,
            },
        )

        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")
        assert features & CoverEntityFeature.SET_TILT_POSITION
        assert features & CoverEntityFeature.STOP_TILT


# ============================================================================
# State Restoration
# ============================================================================


class TestStateRestoration:
    """Tests for position persistence across restarts."""

    async def test_restore_position_after_restart(self, hass: HomeAssistant):
        """Position is restored from RestoreEntity after HA restart."""
        entity_id = await _setup_timed_entity(hass)

        # Open to 30%
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 3)  # 30%
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 30


# ============================================================================
# Tilt Time-Based Mode
# ============================================================================


class TestTiltTimedMode:
    """Tests for time-based tilt estimation."""

    async def _setup_tilt_entity(self, hass: HomeAssistant) -> str:
        """Set up entity with tilt time config."""
        return await _setup_timed_entity(
            hass,
            options={
                "enable_tilt": True,
                "tilt_open_time": TILT_OPEN_TIME,
                "tilt_close_time": TILT_CLOSE_TIME,
            },
        )

    async def test_tilt_open_starts_tilt_timer(self, hass: HomeAssistant):
        """open_cover_tilt starts tilt timer."""
        entity_id = await self._setup_tilt_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER_TILT,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        # tilt_open_time=4, so 100/4=25 per tick
        await _advance_time(hass, 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 25

    async def test_tilt_close_starts_tilt_timer(self, hass: HomeAssistant):
        """close_cover_tilt starts tilt timer from 100."""
        entity_id = await self._setup_tilt_entity(hass)

        # Open tilt fully
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER_TILT,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, int(TILT_OPEN_TIME) + 1)

        # Close: tilt_close_time=2, so 100/2=50 per tick
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER_TILT,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 50

    async def test_set_tilt_position(self, hass: HomeAssistant):
        """set_cover_tilt_position moves tilt to target."""
        entity_id = await self._setup_tilt_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_SET_COVER_TILT_POSITION,
            {ATTR_ENTITY_ID: entity_id, ATTR_TILT_POSITION: 50},
            blocking=True,
        )
        # 100/4=25 per tick, target=50 -> 2 ticks
        await _advance_time(hass, 2)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 50

    async def test_tilt_stop_cancels_timer(self, hass: HomeAssistant):
        """stop_cover_tilt cancels tilt timer."""
        entity_id = await self._setup_tilt_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER_TILT,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 1)  # 25%

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER_TILT,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        pos = hass.states.get(entity_id).attributes.get(
            "current_tilt_position"
        )

        # More ticks should NOT change tilt
        await _advance_time(hass, 3)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == pos


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    async def test_unknown_position_assumes_0_on_open(
        self, hass: HomeAssistant
    ):
        """If position is None, treat as 0 when opening."""
        entity_id = await _setup_timed_entity(hass)

        # Position starts as None
        state = hass.states.get(entity_id)
        # After open + 1 tick, should be 10 (started from 0)
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 1)

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 10

    async def test_partial_config_ignored(self, hass: HomeAssistant):
        """Only open_time without close_time disables time-based mode."""
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Partial Cover",
            data={},
            options={
                "name": "Partial Cover",
                "open_time": 10.0,
                # No close_time!
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_id = "cover.partial_cover"
        state = hass.states.get(entity_id)
        features = state.attributes.get("supported_features")

        # SET_POSITION should NOT be auto-enabled (time mode disabled)
        # Only OPEN + CLOSE = 3
        assert features == (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        )

    async def test_position_never_negative(self, hass: HomeAssistant):
        """Position is clamped to 0 even if close ticks overshoot."""
        entity_id = await _setup_timed_entity(hass)

        # Close from 0 (should do nothing meaningful)
        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await _advance_time(hass, 5)

        state = hass.states.get(entity_id)
        pos = state.attributes.get("current_position")
        assert pos is not None
        assert pos >= 0
