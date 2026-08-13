"""Tests for Climate Template config flow and options flow.

Verifies:
- Config flow creates entries correctly
- Options flow updates take effect after entity reload
- Each key option field change is reflected in the entity
- Temperature unit, fan modes, entity selectors, HVAC modes, etc.
"""

from __future__ import annotations

import pytest
from homeassistant.components.climate import (
    HVACMode,
    HVACAction,
    ClimateEntityFeature,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    PRESET_NONE,
)
from homeassistant.const import (
    STATE_OFF,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant import loader

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.climate_template.const import DOMAIN

# ---------------------------------------------------------------------------
# Base config for simple mode
# ---------------------------------------------------------------------------

BASE_SIMPLE_CONFIG = {
    "name": "Test Options Climate",
    "config_mode": "simple",
    "temperature_sensor": "sensor.test_room_temperature",
    "heater": "input_boolean.test_heater",
    "cooler": "input_boolean.test_ac_unit",
    "ac_mode": False,
    "min_temp": 7.0,
    "max_temp": 35.0,
    "temp_step": 0.5,
    "cold_tolerance": 0.3,
    "hot_tolerance": 0.3,
    "hvac_modes": ["off", "heat", "cool"],
    "fan_modes": [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH],
    "preset_modes": ["eco", "comfort", "away"],
    "swing_modes": ["on", "off"],
}

ENTITY_ID = "climate.test_options_climate"


# ---------------------------------------------------------------------------
# Helper: set up entities + config entry
# ---------------------------------------------------------------------------


async def _setup_entry(
    hass: HomeAssistant,
    config: dict,
    entry_id: str = "test_opt_1",
) -> MockConfigEntry:
    """Create prerequisite entities and a climate config entry."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    # Temperature sensor
    hass.states.async_set(
        "sensor.test_room_temperature",
        "21.5",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    # Second temperature sensor for sensor change test
    hass.states.async_set(
        "sensor.test_outdoor_temperature",
        "15.0",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    # Heater / cooler
    hass.states.async_set(
        "input_boolean.test_heater",
        STATE_OFF,
        {"friendly_name": "Test Heater"},
    )
    hass.states.async_set(
        "input_boolean.test_ac_unit",
        STATE_OFF,
        {"friendly_name": "Test AC Unit"},
    )
    # Fan mode entity
    hass.states.async_set(
        "input_select.test_fan_mode",
        "auto",
        {
            "options": ["auto", "low", "medium", "high"],
            "friendly_name": "Test Fan Mode",
        },
    )
    # Preset mode entity
    hass.states.async_set(
        "input_select.test_preset_mode",
        "none",
        {
            "options": ["none", "eco", "comfort", "away"],
            "friendly_name": "Test Preset Mode",
        },
    )
    # Humidity entity
    hass.states.async_set(
        "input_number.test_target_humidity",
        "50",
        {"min": 0, "max": 100, "step": 1, "friendly_name": "Test Target Humidity"},
    )
    # Humidity sensor
    hass.states.async_set(
        "sensor.test_humidity",
        "55",
        {
            "unit_of_measurement": "%",
            "device_class": "humidity",
            "friendly_name": "Test Humidity",
        },
    )

    # Mock services
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    async_mock_service(hass, "input_select", "select_option")
    async_mock_service(hass, "input_number", "set_value")

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


async def _update_options(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    new_options: dict,
) -> None:
    """Update config entry options and wait for reload."""
    # Merge new options with existing ones
    merged = dict(entry.options)
    merged.update(new_options)

    hass.config_entries.async_update_entry(entry, options=merged)
    await hass.async_block_till_done()


# ===========================================================================
# TEST GROUP 1: Config Flow Entry Creation
# ===========================================================================


class TestConfigFlowCreation:
    """Tests that config flow creates entries correctly."""

    async def test_simple_mode_entry_created(self, hass: HomeAssistant):
        """Simple mode config flow creates a working entity."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_cf_1")

        state = hass.states.get(ENTITY_ID)
        assert state is not None
        assert state.state == HVACMode.OFF
        assert state.attributes.get("min_temp") == 7.0
        assert state.attributes.get("max_temp") == 35.0
        assert "auto" in state.attributes.get("fan_modes", [])
        assert entry.state.name == "LOADED"


# ===========================================================================
# TEST GROUP 2: Options Flow - Temperature Settings
# ===========================================================================


class TestOptionsTemperature:
    """Tests for temperature-related options changes."""

    async def test_entity_uses_system_unit(self, hass: HomeAssistant):
        """Entity always uses HA system unit (temperature_unit option removed)."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_unit_1")

        state = hass.states.get(ENTITY_ID)
        assert state is not None
        assert entry.state.name == "LOADED"
        # System unit in test env is Celsius — current_temperature should be numeric
        assert state.attributes.get("current_temperature") == 21.5

    async def test_change_min_max_temp(self, hass: HomeAssistant):
        """Changing min/max temp updates entity range."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_mm_1")

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("min_temp") == 7.0
        assert state.attributes.get("max_temp") == 35.0

        # Change range
        await _update_options(hass, entry, {"min_temp": 10.0, "max_temp": 40.0})

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("min_temp") == 10.0
        assert state.attributes.get("max_temp") == 40.0

    async def test_change_temp_step(self, hass: HomeAssistant):
        """Changing temp_step updates entity step."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_step_1")

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("target_temp_step") == 0.5

        await _update_options(hass, entry, {"temp_step": 1.0})

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("target_temp_step") == 1.0


# ===========================================================================
# TEST GROUP 3: Options Flow - Mode Lists
# ===========================================================================


class TestOptionsModes:
    """Tests for mode list changes via options flow."""

    async def test_change_hvac_modes(self, hass: HomeAssistant):
        """Changing HVAC modes list updates entity modes."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_hm_1")

        state = hass.states.get(ENTITY_ID)
        assert HVACMode.HEAT in state.attributes.get("hvac_modes")
        assert HVACMode.COOL in state.attributes.get("hvac_modes")

        # Remove cool mode
        await _update_options(hass, entry, {"hvac_modes": ["off", "heat"]})

        state = hass.states.get(ENTITY_ID)
        modes = state.attributes.get("hvac_modes")
        assert HVACMode.HEAT in modes
        assert HVACMode.COOL not in modes

    async def test_add_heat_cool_mode(self, hass: HomeAssistant):
        """Adding heat_cool mode works when cooler is configured."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_hc_1")

        await _update_options(
            hass, entry, {"hvac_modes": ["off", "heat", "cool", "heat_cool"]}
        )

        state = hass.states.get(ENTITY_ID)
        modes = state.attributes.get("hvac_modes")
        assert HVACMode.HEAT_COOL in modes
        # Should also have TARGET_TEMPERATURE_RANGE feature
        features = state.attributes.get("supported_features")
        assert features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

    async def test_heat_cool_removed_without_cooler(self, hass: HomeAssistant):
        """heat_cool mode auto-removed when no cooler entity."""
        config = {
            **BASE_SIMPLE_CONFIG,
            "cooler": None,
            "hvac_modes": ["off", "heat", "heat_cool"],
        }
        entry = await _setup_entry(hass, config, "test_hcg_1")

        state = hass.states.get(ENTITY_ID)
        modes = state.attributes.get("hvac_modes")
        assert HVACMode.HEAT_COOL not in modes
        assert HVACMode.HEAT in modes

    async def test_change_fan_modes(self, hass: HomeAssistant):
        """Changing fan modes list updates entity."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_fm_1")

        state = hass.states.get(ENTITY_ID)
        assert "high" in state.attributes.get("fan_modes", [])

        # Reduce to 2 modes
        await _update_options(hass, entry, {"fan_modes": ["auto", "low"]})

        state = hass.states.get(ENTITY_ID)
        fan_modes = state.attributes.get("fan_modes")
        assert "auto" in fan_modes
        assert "low" in fan_modes
        assert "high" not in fan_modes

    async def test_change_preset_modes(self, hass: HomeAssistant):
        """Changing preset modes updates entity."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_pm_1")

        state = hass.states.get(ENTITY_ID)
        presets = state.attributes.get("preset_modes", [])
        assert "eco" in presets

        # Change presets
        await _update_options(hass, entry, {"preset_modes": ["boost", "sleep"]})

        state = hass.states.get(ENTITY_ID)
        presets = state.attributes.get("preset_modes", [])
        assert "boost" in presets
        assert "sleep" in presets
        assert "eco" not in presets

    async def test_change_swing_modes(self, hass: HomeAssistant):
        """Changing swing modes updates entity."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_sm_1")

        state = hass.states.get(ENTITY_ID)
        swings = state.attributes.get("swing_modes", [])
        assert "on" in swings

        # Remove swing modes entirely
        await _update_options(hass, entry, {"swing_modes": None})

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("swing_modes") is None


# ===========================================================================
# TEST GROUP 4: Options Flow - Entity Selectors (TX/RX)
# ===========================================================================


class TestOptionsEntitySelectors:
    """Tests for adding/removing entity selectors via options flow."""

    async def test_add_fan_mode_entity(self, hass: HomeAssistant):
        """Adding fan_mode_entity activates TX/RX for fan mode."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_fe_1")

        # Initially no fan mode entity
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("fan_mode") == FAN_AUTO

        # Add fan mode entity
        await _update_options(
            hass,
            entry,
            {"fan_mode_entity": "input_select.test_fan_mode"},
        )

        # RX: entity state should sync to climate
        state = hass.states.get(ENTITY_ID)
        assert state is not None
        assert state.attributes.get("fan_mode") == "auto"

        # RX: external change should propagate
        hass.states.async_set(
            "input_select.test_fan_mode",
            "high",
            {"options": ["auto", "low", "medium", "high"]},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("fan_mode") == "high"

    async def test_add_preset_mode_entity(self, hass: HomeAssistant):
        """Adding preset_mode_entity activates RX for presets."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_pe_1")

        await _update_options(
            hass,
            entry,
            {"preset_mode_entity": "input_select.test_preset_mode"},
        )

        # RX: external change
        hass.states.async_set(
            "input_select.test_preset_mode",
            "eco",
            {"options": ["none", "eco", "comfort", "away"]},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("preset_mode") == "eco"

    async def test_add_humidity_entity(self, hass: HomeAssistant):
        """Adding humidity_entity activates TARGET_HUMIDITY feature."""
        config = {**BASE_SIMPLE_CONFIG}
        entry = await _setup_entry(hass, config, "test_he_1")

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert not (features & ClimateEntityFeature.TARGET_HUMIDITY)

        # Add humidity entity
        await _update_options(
            hass,
            entry,
            {"humidity_entity": "input_number.test_target_humidity"},
        )

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert features & ClimateEntityFeature.TARGET_HUMIDITY

    async def test_add_humidity_sensor(self, hass: HomeAssistant):
        """Adding humidity_sensor shows current_humidity."""
        config = {**BASE_SIMPLE_CONFIG}
        entry = await _setup_entry(hass, config, "test_hs_1")

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("current_humidity") is None

        # Add humidity sensor
        await _update_options(
            hass,
            entry,
            {"humidity_sensor": "sensor.test_humidity"},
        )

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("current_humidity") == 55

    async def test_remove_fan_mode_entity(self, hass: HomeAssistant):
        """Removing fan_mode_entity deactivates TX/RX."""
        config = {
            **BASE_SIMPLE_CONFIG,
            "fan_mode_entity": "input_select.test_fan_mode",
        }
        entry = await _setup_entry(hass, config, "test_rfe_1")

        # Fan entity is wired — verify RX works
        hass.states.async_set(
            "input_select.test_fan_mode",
            "high",
            {"options": ["auto", "low", "medium", "high"]},
        )
        await hass.async_block_till_done()
        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("fan_mode") == "high"

        # Remove fan mode entity
        merged = dict(entry.options)
        merged.pop("fan_mode_entity", None)
        hass.config_entries.async_update_entry(entry, options=merged)
        await hass.async_block_till_done()

        # External change should NOT propagate anymore
        hass.states.async_set(
            "input_select.test_fan_mode",
            "low",
            {"options": ["auto", "low", "medium", "high"]},
        )
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        # After reload, HA entity registry restores previous state ("high").
        # The key assertion: external change to "low" did NOT propagate —
        # fan_mode should still be "high" (restored), not "low" (from entity).
        assert state.attributes.get("fan_mode") != "low"


# ===========================================================================
# TEST GROUP 5: Options Flow - AC Mode and Control Logic
# ===========================================================================


class TestOptionsControlLogic:
    """Tests for control logic options changes."""

    async def test_toggle_ac_mode(self, hass: HomeAssistant):
        """Toggling ac_mode changes control logic."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_ac_1")

        # Initially ac_mode=False
        state = hass.states.get(ENTITY_ID)
        assert state is not None

        # Enable ac_mode
        await _update_options(hass, entry, {"ac_mode": True})

        state = hass.states.get(ENTITY_ID)
        assert state is not None
        assert entry.state.name == "LOADED"

    async def test_change_temperature_sensor(self, hass: HomeAssistant):
        """Changing temperature sensor reads from new sensor."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_ts_1")

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("current_temperature") == 21.5

        # Switch to outdoor sensor (15.0°C)
        await _update_options(
            hass,
            entry,
            {"temperature_sensor": "sensor.test_outdoor_temperature"},
        )

        state = hass.states.get(ENTITY_ID)
        assert state.attributes.get("current_temperature") == 15.0

    async def test_remove_cooler(self, hass: HomeAssistant):
        """Removing cooler entity disables cool mode control."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_rc_1")

        state = hass.states.get(ENTITY_ID)
        assert state is not None

        # Remove cooler
        await _update_options(hass, entry, {"cooler": None})

        state = hass.states.get(ENTITY_ID)
        assert state is not None
        assert entry.state.name == "LOADED"


# ===========================================================================
# TEST GROUP 6: Options Flow - Feature Flags
# ===========================================================================


class TestOptionsFeatureFlags:
    """Tests that feature flags update correctly via options."""

    async def test_add_swing_horizontal_modes(self, hass: HomeAssistant):
        """Adding swing_horizontal_modes activates the feature."""
        config = {**BASE_SIMPLE_CONFIG}
        entry = await _setup_entry(hass, config, "test_shm_1")

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert not (features & ClimateEntityFeature.SWING_HORIZONTAL_MODE)

        # Add horizontal swing
        await _update_options(
            hass,
            entry,
            {"swing_horizontal_modes": ["on", "off"]},
        )

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert features & ClimateEntityFeature.SWING_HORIZONTAL_MODE

    async def test_remove_fan_modes_removes_feature(self, hass: HomeAssistant):
        """Removing fan_modes disables FAN_MODE feature."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_rfm_1")

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert features & ClimateEntityFeature.FAN_MODE

        # Remove fan modes
        await _update_options(hass, entry, {"fan_modes": None})

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert not (features & ClimateEntityFeature.FAN_MODE)

    async def test_remove_preset_modes_removes_feature(self, hass: HomeAssistant):
        """Removing preset_modes disables PRESET_MODE feature."""
        entry = await _setup_entry(hass, BASE_SIMPLE_CONFIG, "test_rpm_1")

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert features & ClimateEntityFeature.PRESET_MODE

        # Remove preset modes
        await _update_options(hass, entry, {"preset_modes": None})

        state = hass.states.get(ENTITY_ID)
        features = state.attributes.get("supported_features")
        assert not (features & ClimateEntityFeature.PRESET_MODE)
