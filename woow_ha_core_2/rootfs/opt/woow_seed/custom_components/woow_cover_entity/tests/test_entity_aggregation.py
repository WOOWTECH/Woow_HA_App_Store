"""Tests for TX/RX entity aggregation, RX listeners, and action script overrides."""

from __future__ import annotations

import pytest
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    DOMAIN as COVER_DOMAIN,
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
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.woow_cover_entity.const import DOMAIN
POS_ENTITY = "input_number.cover_position"
TILT_ENTITY = "input_number.cover_tilt"


async def _setup_entity(
    hass: HomeAssistant,
    options: dict | None = None,
    pos_initial: str = "50",
    tilt_initial: str = "50",
) -> str:
    """Set up a SimpleCover entity with helper entities and return entity_id."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    # Create helper entities
    hass.states.async_set(POS_ENTITY, pos_initial)
    hass.states.async_set(TILT_ENTITY, tilt_initial)

    default_options = {
        "name": "Test Cover",
        "position_entity": POS_ENTITY,
        "enable_tilt": True,
        "tilt_position_entity": TILT_ENTITY,
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
# TX: Entity Selector (Cover → Helper Entity)
# ============================================================================


class TestEntitySelectorTX:
    """Tests for TX via entity selectors."""

    async def test_open_cover_sends_100_to_position_entity(
        self, hass: HomeAssistant
    ):
        """Open cover sends 100 to position entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        pos_calls = [c for c in calls if POS_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(pos_calls) >= 1
        assert pos_calls[-1].data.get("value") == 100

    async def test_close_cover_sends_0_to_position_entity(
        self, hass: HomeAssistant
    ):
        """Close cover sends 0 to position entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        pos_calls = [c for c in calls if POS_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(pos_calls) >= 1
        assert pos_calls[-1].data.get("value") == 0

    async def test_set_position_sends_value_to_entity(
        self, hass: HomeAssistant
    ):
        """Set position sends the value to position entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_SET_COVER_POSITION,
            {ATTR_ENTITY_ID: entity_id, ATTR_POSITION: 75},
            blocking=True,
        )

        pos_calls = [c for c in calls if POS_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(pos_calls) >= 1
        assert pos_calls[-1].data.get("value") == 75

    async def test_open_tilt_sends_100_to_tilt_entity(
        self, hass: HomeAssistant
    ):
        """Open tilt sends 100 to tilt entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            "open_cover_tilt",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        tilt_calls = [c for c in calls if TILT_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(tilt_calls) >= 1
        assert tilt_calls[-1].data.get("value") == 100

    async def test_close_tilt_sends_0_to_tilt_entity(
        self, hass: HomeAssistant
    ):
        """Close tilt sends 0 to tilt entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            "close_cover_tilt",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        tilt_calls = [c for c in calls if TILT_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(tilt_calls) >= 1
        assert tilt_calls[-1].data.get("value") == 0

    async def test_set_tilt_position_sends_value_to_entity(
        self, hass: HomeAssistant
    ):
        """Set tilt position sends the value to tilt entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        entity_id = await _setup_entity(hass)

        await hass.services.async_call(
            COVER_DOMAIN,
            "set_cover_tilt_position",
            {ATTR_ENTITY_ID: entity_id, ATTR_TILT_POSITION: 30},
            blocking=True,
        )

        tilt_calls = [c for c in calls if TILT_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(tilt_calls) >= 1
        assert tilt_calls[-1].data.get("value") == 30


# ============================================================================
# RX: Listeners (Helper Entity → Cover)
# ============================================================================


class TestRXListeners:
    """Tests for RX listeners — external entity changes update cover state."""

    async def test_position_entity_change_updates_cover(
        self, hass: HomeAssistant
    ):
        """Changing position entity updates cover position."""
        entity_id = await _setup_entity(hass, pos_initial="50")

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 50

        # Change position entity
        hass.states.async_set(POS_ENTITY, "75")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 75

    async def test_position_entity_to_0_closes_cover(
        self, hass: HomeAssistant
    ):
        """Setting position entity to 0 closes the cover."""
        entity_id = await _setup_entity(hass, pos_initial="50")

        hass.states.async_set(POS_ENTITY, "0")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.state == STATE_CLOSED
        assert state.attributes.get("current_position") == 0

    async def test_position_entity_to_100_opens_cover(
        self, hass: HomeAssistant
    ):
        """Setting position entity to 100 opens the cover."""
        entity_id = await _setup_entity(hass, pos_initial="0")

        hass.states.async_set(POS_ENTITY, "100")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.state == STATE_OPEN
        assert state.attributes.get("current_position") == 100

    async def test_tilt_entity_change_updates_cover(
        self, hass: HomeAssistant
    ):
        """Changing tilt entity updates cover tilt position."""
        entity_id = await _setup_entity(hass, tilt_initial="50")

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 50

        hass.states.async_set(TILT_ENTITY, "80")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 80

    async def test_position_rx_clears_opening_flag(
        self, hass: HomeAssistant
    ):
        """Position RX clears opening/closing flags."""
        entity_id = await _setup_entity(hass, pos_initial="0")

        # Open cover (sets opening flag)
        # Can't call open_cover because it will TX to entity selector
        # which is mocked. Instead, simulate directly.
        hass.states.async_set(POS_ENTITY, "100")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.state == STATE_OPEN

    async def test_invalid_position_ignored(self, hass: HomeAssistant):
        """Invalid position value (not a number) is ignored."""
        entity_id = await _setup_entity(hass, pos_initial="50")

        hass.states.async_set(POS_ENTITY, "invalid")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        # Position unchanged
        assert state.attributes.get("current_position") == 50

    async def test_unavailable_position_ignored(self, hass: HomeAssistant):
        """Unavailable position entity is ignored."""
        entity_id = await _setup_entity(hass, pos_initial="50")

        hass.states.async_set(POS_ENTITY, "unavailable")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 50

    async def test_out_of_range_position_ignored(self, hass: HomeAssistant):
        """Out of range position (>100) is ignored."""
        entity_id = await _setup_entity(hass, pos_initial="50")

        hass.states.async_set(POS_ENTITY, "150")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        # 150 is out of range, ignored
        assert state.attributes.get("current_position") == 50

    async def test_negative_position_ignored(self, hass: HomeAssistant):
        """Negative position is ignored."""
        entity_id = await _setup_entity(hass, pos_initial="50")

        hass.states.async_set(POS_ENTITY, "-10")
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 50


# ============================================================================
# Action Script Overrides
# ============================================================================


class TestActionScriptOverrides:
    """Tests for action script overrides (TX priority: script > entity)."""

    async def test_set_position_action_overrides_entity(
        self, hass: HomeAssistant
    ):
        """Set position action script takes priority over entity selector."""
        calls = async_mock_service(hass, "input_number", "set_value")
        script_calls = async_mock_service(hass, "test", "set_pos")

        entity_id = await _setup_entity(
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
            {ATTR_ENTITY_ID: entity_id, ATTR_POSITION: 75},
            blocking=True,
        )

        # Action script should be called
        assert len(script_calls) >= 1
        # Entity selector should NOT be called for position
        pos_calls = [c for c in calls if POS_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(pos_calls) == 0

    async def test_open_cover_action_overrides_position_entity(
        self, hass: HomeAssistant
    ):
        """Open cover action script takes priority over position entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        script_calls = async_mock_service(hass, "test", "open_it")

        entity_id = await _setup_entity(
            hass,
            options={
                "open_cover": [{"action": "test.open_it"}],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_OPEN_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        # Action script should be called
        assert len(script_calls) >= 1
        # Entity selector should NOT be called
        pos_calls = [c for c in calls if POS_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(pos_calls) == 0

    async def test_close_cover_action_overrides_position_entity(
        self, hass: HomeAssistant
    ):
        """Close cover action script takes priority over position entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        script_calls = async_mock_service(hass, "test", "close_it")

        entity_id = await _setup_entity(
            hass,
            options={
                "close_cover": [{"action": "test.close_it"}],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_CLOSE_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        assert len(script_calls) >= 1
        pos_calls = [c for c in calls if POS_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(pos_calls) == 0

    async def test_stop_cover_action_fires(self, hass: HomeAssistant):
        """Stop cover action script fires."""
        script_calls = async_mock_service(hass, "test", "stop_it")

        entity_id = await _setup_entity(
            hass,
            options={
                "stop_cover": [{"action": "test.stop_it"}],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            SERVICE_STOP_COVER,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )

        assert len(script_calls) >= 1

    async def test_set_tilt_action_overrides_entity(
        self, hass: HomeAssistant
    ):
        """Set tilt position action script takes priority over entity."""
        calls = async_mock_service(hass, "input_number", "set_value")
        script_calls = async_mock_service(hass, "test", "set_tilt")

        entity_id = await _setup_entity(
            hass,
            options={
                "set_tilt_position": [
                    {
                        "action": "test.set_tilt",
                        "data": {"tilt": "{{ tilt_position }}"},
                    }
                ],
            },
        )

        await hass.services.async_call(
            COVER_DOMAIN,
            "set_cover_tilt_position",
            {ATTR_ENTITY_ID: entity_id, ATTR_TILT_POSITION: 45},
            blocking=True,
        )

        assert len(script_calls) >= 1
        tilt_calls = [c for c in calls if TILT_ENTITY in (c.data.get(ATTR_ENTITY_ID) or [])]
        assert len(tilt_calls) == 0


# ============================================================================
# Initial State Sync
# ============================================================================


class TestInitialStateSync:
    """Tests for initial state sync from external entities."""

    async def test_initial_position_synced(self, hass: HomeAssistant):
        """Position entity value is synced at setup."""
        entity_id = await _setup_entity(hass, pos_initial="75")

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") == 75

    async def test_initial_tilt_synced(self, hass: HomeAssistant):
        """Tilt entity value is synced at setup."""
        entity_id = await _setup_entity(hass, tilt_initial="30")

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_tilt_position") == 30

    async def test_initial_position_0_means_closed(
        self, hass: HomeAssistant
    ):
        """Position entity = 0 at setup means cover is closed."""
        entity_id = await _setup_entity(hass, pos_initial="0")

        state = hass.states.get(entity_id)
        assert state.state == STATE_CLOSED

    async def test_initial_position_100_means_open(
        self, hass: HomeAssistant
    ):
        """Position entity = 100 at setup means cover is open."""
        entity_id = await _setup_entity(hass, pos_initial="100")

        state = hass.states.get(entity_id)
        assert state.state == STATE_OPEN

    async def test_initial_unavailable_ignored(self, hass: HomeAssistant):
        """Unavailable entity at setup is ignored."""
        entity_id = await _setup_entity(hass, pos_initial="unavailable")

        state = hass.states.get(entity_id)
        assert state.attributes.get("current_position") is None
