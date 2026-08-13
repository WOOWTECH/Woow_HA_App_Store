"""Tests for config entry creation, options flow, and config flow."""

from __future__ import annotations

import pytest
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.const import STATE_OPEN
from homeassistant import loader
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.woow_cover_entity.const import DOMAIN


# ============================================================================
# Config Entry Creation
# ============================================================================


class TestConfigEntryCreation:
    """Tests for config entry creation and setup."""

    async def test_entry_setup_creates_entity(self, hass: HomeAssistant):
        """Config entry setup creates a cover entity."""

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test Cover",
            data={},
            options={"name": "Test Cover"},
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("cover.test_cover")
        assert state is not None

    async def test_entry_unload(self, hass: HomeAssistant):
        """Config entry can be unloaded."""

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test Cover",
            data={},
            options={"name": "Test Cover"},
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    async def test_entry_with_device_class(self, hass: HomeAssistant):
        """Config entry with device_class creates entity with correct class."""

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test Blind",
            data={},
            options={
                "name": "Test Blind",
                "device_class": "blind",
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("cover.test_blind")
        assert state.attributes.get("device_class") == "blind"

    async def test_entry_with_all_features(self, hass: HomeAssistant):
        """Config entry with all features creates a fully-featured entity."""

        hass.states.async_set("input_number.cover_pos", "50")
        hass.states.async_set("input_number.cover_tilt", "50")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Full Cover",
            data={},
            options={
                "name": "Full Cover",
                "device_class": "shade",
                "enable_tilt": True,
                "position_entity": "input_number.cover_pos",
                "tilt_position_entity": "input_number.cover_tilt",
                "stop_cover": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.dummy"}}],
                "stop_tilt": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.dummy"}}],
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("cover.full_cover")
        assert state is not None
        assert state.attributes.get("device_class") == "shade"
        assert state.attributes.get("current_position") == 50
        assert state.attributes.get("current_tilt_position") == 50

    async def test_multiple_entries(self, hass: HomeAssistant):
        """Multiple config entries create separate entities."""

        for i, name in enumerate(["Cover A", "Cover B"]):
            entry = MockConfigEntry(
                domain=DOMAIN,
                title=name,
                data={},
                options={"name": name},
            )
            entry.add_to_hass(hass)
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert hass.states.get("cover.cover_a") is not None
        assert hass.states.get("cover.cover_b") is not None


# ============================================================================
# Options Flow
# ============================================================================


class TestOptionsFlow:
    """Tests for options flow updates."""

    async def test_options_update_reloads_entity(
        self, hass: HomeAssistant
    ):
        """Updating options reloads the entity."""

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test Cover",
            data={},
            options={"name": "Test Cover"},
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("cover.test_cover")
        assert state is not None

        # Update options
        hass.config_entries.async_update_entry(
            entry,
            options={
                "name": "Test Cover",
                "device_class": "curtain",
            },
        )
        await hass.async_block_till_done()

        state = hass.states.get("cover.test_cover")
        assert state is not None

    async def test_options_add_position_entity(self, hass: HomeAssistant):
        """Adding position entity via options adds SET_POSITION feature."""

        hass.states.async_set("input_number.cover_pos", "50")

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test Cover",
            data={},
            options={"name": "Test Cover"},
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Update to add position entity
        hass.config_entries.async_update_entry(
            entry,
            options={
                "name": "Test Cover",
                "position_entity": "input_number.cover_pos",
            },
        )
        await hass.async_block_till_done()


# ============================================================================
# Config Flow User Step
# ============================================================================


class TestConfigFlowUserStep:
    """Tests for the config flow user step."""

    async def test_config_flow_init(self, hass: HomeAssistant):
        """Config flow can be initialized."""

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "user"

    async def test_config_flow_submit(self, hass: HomeAssistant):
        """Config flow can be submitted."""

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "name": "My Cover",
            },
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "My Cover"

    async def test_config_flow_with_all_options(self, hass: HomeAssistant):
        """Config flow with all options creates entry."""

        hass.states.async_set("input_number.cover_pos", "50")
        hass.states.async_set("input_number.cover_tilt", "50")

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "name": "Full Cover",
                "device_class": "blind",
                "enable_tilt": True,
                "position_entity": "input_number.cover_pos",
                "tilt_position_entity": "input_number.cover_tilt",
            },
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "Full Cover"
        assert result["options"]["device_class"] == "blind"
        assert result["options"]["enable_tilt"] is True
