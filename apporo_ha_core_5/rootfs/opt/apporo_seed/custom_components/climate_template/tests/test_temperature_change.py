"""Tests for dynamic temperature change triggering heater/cooler control.

Verifies that when the temperature sensor value changes AFTER the climate
entity is already running, the entity correctly activates or deactivates
the heater and cooler in response.

Test scenarios:
- Heater turns ON when temp drops below target
- Heater turns OFF when temp rises above target
- Cooler turns ON when temp rises above target
- Cooler turns OFF when temp drops below target
- Temperature changes within tolerance band do NOT trigger toggling
- Multiple consecutive temperature changes produce correct final state
"""

from __future__ import annotations

import pytest
from homeassistant.components.climate import HVACMode, HVACAction
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.climate_template.const import DOMAIN
from homeassistant import loader

# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------

HEATER_COOLER_CONFIG = {
    "name": "Test Temp Change",
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
    "fan_modes": None,
    "preset_modes": None,
    "swing_modes": None,
}

ENTITY_ID = "climate.test_temp_change"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _setup_entity(
    hass: HomeAssistant,
    entry_id: str,
    sensor_temp: str = "21.5",
    heater_state: str = STATE_OFF,
    cooler_state: str = STATE_OFF,
):
    """Set up climate entity with initial states."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

    hass.states.async_set(
        "sensor.test_room_temperature",
        sensor_temp,
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    hass.states.async_set(
        "input_boolean.test_heater",
        heater_state,
        {"friendly_name": "Test Heater"},
    )
    hass.states.async_set(
        "input_boolean.test_ac_unit",
        cooler_state,
        {"friendly_name": "Test AC Unit"},
    )

    turn_on_calls = async_mock_service(hass, "homeassistant", "turn_on")
    turn_off_calls = async_mock_service(hass, "homeassistant", "turn_off")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=HEATER_COOLER_CONFIG["name"],
        data={},
        options=HEATER_COOLER_CONFIG,
        entry_id=entry_id,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return {
        "entry": entry,
        "turn_on_calls": turn_on_calls,
        "turn_off_calls": turn_off_calls,
    }


def _set_temp(hass: HomeAssistant, temp: str):
    """Simulate a temperature sensor change."""
    hass.states.async_set(
        "sensor.test_room_temperature",
        temp,
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )


def _heater_turned_on(calls) -> bool:
    """Check if heater turn_on was called."""
    return any(c.data.get("entity_id") == "input_boolean.test_heater" for c in calls)


def _heater_turned_off(calls) -> bool:
    """Check if heater turn_off was called."""
    return any(c.data.get("entity_id") == "input_boolean.test_heater" for c in calls)


def _cooler_turned_on(calls) -> bool:
    """Check if cooler turn_on was called."""
    return any(c.data.get("entity_id") == "input_boolean.test_ac_unit" for c in calls)


def _cooler_turned_off(calls) -> bool:
    """Check if cooler turn_off was called."""
    return any(c.data.get("entity_id") == "input_boolean.test_ac_unit" for c in calls)


# ===========================================================================
# TEST GROUP 1: Heater Responds to Temperature Drop
# ===========================================================================


class TestHeaterOnTempDrop:
    """Heater activates when temperature drops below target."""

    async def test_heater_activates_on_temp_drop(self, hass: HomeAssistant):
        """Start warm (25°C), set heat mode target 22°C, drop temp to 18°C → heater ON."""
        ctx = await _setup_entity(hass, "tc_heat_1", sensor_temp="25.0")

        # Set heat mode with target 22°C — room is warm, heater should stay off
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.async_block_till_done()

        assert not _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Heater should NOT turn on when room (25) is above target (22)"

        # Now temperature drops to 18°C — below target - cold_tolerance (21.7)
        _set_temp(hass, "18.0")
        await hass.async_block_till_done()

        assert _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Heater should turn ON after temp drops to 18 (below target 22)"

    async def test_heater_activates_on_gradual_drop(self, hass: HomeAssistant):
        """Gradual temp drop: 25 → 23 → 21 → heater ON at 21 (below 22-0.3)."""
        ctx = await _setup_entity(hass, "tc_heat_2", sensor_temp="25.0")

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Step 1: drop to 23 — still above target, no heater
        _set_temp(hass, "23.0")
        await hass.async_block_till_done()
        assert not _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Heater should NOT turn on at 23 (above target 22)"

        # Step 2: drop to 21 — below target - cold_tolerance (21.7) → heater ON
        _set_temp(hass, "21.0")
        await hass.async_block_till_done()
        assert _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Heater should turn ON at 21 (below 22 - 0.3 = 21.7)"


# ===========================================================================
# TEST GROUP 2: Heater Responds to Temperature Rise
# ===========================================================================


class TestHeaterOffTempRise:
    """Heater deactivates when temperature rises above target."""

    async def test_heater_deactivates_on_temp_rise(self, hass: HomeAssistant):
        """Start cold (18°C), heater ON, temp rises to 24°C → heater OFF."""
        # Heater starts ON from setup — climate won't re-call turn_on
        ctx = await _setup_entity(
            hass,
            "tc_heat_3",
            sensor_temp="18.0",
            heater_state=STATE_ON,
        )

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Temperature rises to 24 — above target → heater OFF
        _set_temp(hass, "24.0")
        await hass.async_block_till_done()

        assert _heater_turned_off(
            ctx["turn_off_calls"]
        ), "Heater should turn OFF after temp rises to 24 (above target 22)"

    async def test_heater_off_on_gradual_rise(self, hass: HomeAssistant):
        """Gradual rise: 18 → 21 → 23 → heater OFF at 23."""
        ctx = await _setup_entity(
            hass,
            "tc_heat_4",
            sensor_temp="18.0",
            heater_state=STATE_ON,
        )

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()
        ctx["turn_off_calls"].clear()

        # Rise to 21 — still below target (21 < 22 - 0.3), heater stays ON
        _set_temp(hass, "21.0")
        await hass.async_block_till_done()
        assert not _heater_turned_off(
            ctx["turn_off_calls"]
        ), "Heater should stay ON at 21 (still below 21.7)"

        # Rise to 23 — above target → heater OFF
        _set_temp(hass, "23.0")
        await hass.async_block_till_done()
        assert _heater_turned_off(
            ctx["turn_off_calls"]
        ), "Heater should turn OFF at 23 (above target 22)"


# ===========================================================================
# TEST GROUP 3: Cooler Responds to Temperature Rise
# ===========================================================================


class TestCoolerOnTempRise:
    """Cooler activates when temperature rises above target in cool mode."""

    async def test_cooler_activates_on_temp_rise(self, hass: HomeAssistant):
        """Start cool (18°C), set cool mode target 22°C, raise to 26°C → cooler ON."""
        ctx = await _setup_entity(hass, "tc_cool_1", sensor_temp="18.0")

        # Set target BEFORE switching to cool mode (avoid default min_temp trigger)
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()

        assert not _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Cooler should NOT turn on when room (18) is below target (22)"

        # Temperature rises to 26 — above target + hot_tolerance (22.3)
        _set_temp(hass, "26.0")
        await hass.async_block_till_done()

        assert _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Cooler should turn ON after temp rises to 26 (above target 22)"

    async def test_cooler_activates_on_gradual_rise(self, hass: HomeAssistant):
        """Gradual temp rise: 18 → 21 → 24 → cooler ON at 24."""
        ctx = await _setup_entity(hass, "tc_cool_2", sensor_temp="18.0")

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Rise to 21 — still below target, no cooler
        _set_temp(hass, "21.0")
        await hass.async_block_till_done()
        assert not _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Cooler should NOT turn on at 21 (below target 22)"

        # Rise to 24 — above target + hot_tolerance (22.3) → cooler ON
        _set_temp(hass, "24.0")
        await hass.async_block_till_done()
        assert _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Cooler should turn ON at 24 (above 22 + 0.3 = 22.3)"


# ===========================================================================
# TEST GROUP 4: Cooler Responds to Temperature Drop
# ===========================================================================


class TestCoolerOffTempDrop:
    """Cooler deactivates when temperature drops below target."""

    async def test_cooler_deactivates_on_temp_drop(self, hass: HomeAssistant):
        """Start hot (26°C), cooler ON, temp drops to 20°C → cooler OFF."""
        # Cooler starts ON from setup — climate won't re-call turn_on
        ctx = await _setup_entity(
            hass,
            "tc_cool_3",
            sensor_temp="26.0",
            cooler_state=STATE_ON,
        )

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Temperature drops to 20 — below target → cooler OFF
        _set_temp(hass, "20.0")
        await hass.async_block_till_done()

        assert _cooler_turned_off(
            ctx["turn_off_calls"]
        ), "Cooler should turn OFF after temp drops to 20 (below target 22)"

    async def test_cooler_off_on_gradual_drop(self, hass: HomeAssistant):
        """Gradual drop: 26 → 23 → 20 → cooler OFF at 20."""
        ctx = await _setup_entity(
            hass,
            "tc_cool_4",
            sensor_temp="26.0",
            cooler_state=STATE_ON,
        )

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()
        ctx["turn_off_calls"].clear()

        # Drop to 23 — still above target (23 > 22), cooler stays ON
        _set_temp(hass, "23.0")
        await hass.async_block_till_done()
        assert not _cooler_turned_off(
            ctx["turn_off_calls"]
        ), "Cooler should stay ON at 23 (still above target 22)"

        # Drop to 20 — below target → cooler OFF
        _set_temp(hass, "20.0")
        await hass.async_block_till_done()
        assert _cooler_turned_off(
            ctx["turn_off_calls"]
        ), "Cooler should turn OFF at 20 (below target 22)"


# ===========================================================================
# TEST GROUP 5: Tolerance Band — No Toggling
# ===========================================================================


class TestToleranceBand:
    """Temperature changes within tolerance should NOT trigger toggling."""

    async def test_heater_no_toggle_within_cold_tolerance(self, hass: HomeAssistant):
        """Temp at 21.8 with target 22, cold_tolerance 0.3 → no heater ON (21.8 > 21.7)."""
        ctx = await _setup_entity(hass, "tc_tol_1", sensor_temp="25.0")

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()

        # Drop to 21.8 — within tolerance (21.8 > 22 - 0.3 = 21.7)
        _set_temp(hass, "21.8")
        await hass.async_block_till_done()

        assert not _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Heater should NOT turn on at 21.8 (within cold_tolerance of 22)"

    async def test_cooler_no_toggle_within_hot_tolerance(self, hass: HomeAssistant):
        """Temp at 22.2 with target 22, hot_tolerance 0.3 → no cooler ON (22.2 < 22.3)."""
        ctx = await _setup_entity(hass, "tc_tol_2", sensor_temp="18.0")

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()

        # Rise to 22.2 — within tolerance (22.2 < 22 + 0.3 = 22.3)
        _set_temp(hass, "22.2")
        await hass.async_block_till_done()

        assert not _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Cooler should NOT turn on at 22.2 (within hot_tolerance of 22)"

    async def test_heater_triggers_just_outside_tolerance(self, hass: HomeAssistant):
        """Temp at 21.6 with target 22, cold_tolerance 0.3 → heater ON (21.6 < 21.7)."""
        ctx = await _setup_entity(hass, "tc_tol_3", sensor_temp="25.0")

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()

        # Drop to 21.6 — just outside tolerance (21.6 < 22 - 0.3 = 21.7) → heater ON
        _set_temp(hass, "21.6")
        await hass.async_block_till_done()

        assert _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Heater should turn ON at 21.6 (just below 21.7 tolerance threshold)"

    async def test_cooler_triggers_just_outside_tolerance(self, hass: HomeAssistant):
        """Temp at 22.4 with target 22, hot_tolerance 0.3 → cooler ON (22.4 > 22.3)."""
        ctx = await _setup_entity(hass, "tc_tol_4", sensor_temp="18.0")

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()

        # Rise to 22.4 — just outside tolerance (22.4 > 22 + 0.3 = 22.3) → cooler ON
        _set_temp(hass, "22.4")
        await hass.async_block_till_done()

        assert _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Cooler should turn ON at 22.4 (just above 22.3 tolerance threshold)"


# ===========================================================================
# TEST GROUP 6: Multiple Consecutive Temperature Changes
# ===========================================================================


class TestConsecutiveChanges:
    """Multiple rapid temperature changes produce correct final state."""

    async def test_heat_cycle_on_off_on(self, hass: HomeAssistant):
        """Heater ON → OFF → ON through temperature swings."""
        ctx = await _setup_entity(hass, "tc_cycle_1", sensor_temp="25.0")

        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "heat"},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Phase 1: Drop to 18 → heater ON
        _set_temp(hass, "18.0")
        await hass.async_block_till_done()
        assert _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Phase 1: heater should turn ON at 18"

        # Simulate heater actually turning ON (mock doesn't change state)
        hass.states.async_set(
            "input_boolean.test_heater",
            STATE_ON,
            {"friendly_name": "Test Heater"},
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()
        ctx["turn_off_calls"].clear()

        # Phase 2: Rise to 25 → heater OFF
        _set_temp(hass, "25.0")
        await hass.async_block_till_done()
        assert _heater_turned_off(
            ctx["turn_off_calls"]
        ), "Phase 2: heater should turn OFF at 25"

        # Simulate heater actually turning OFF
        hass.states.async_set(
            "input_boolean.test_heater",
            STATE_OFF,
            {"friendly_name": "Test Heater"},
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()
        ctx["turn_off_calls"].clear()

        # Phase 3: Drop to 19 → heater ON again
        _set_temp(hass, "19.0")
        await hass.async_block_till_done()
        assert _heater_turned_on(
            ctx["turn_on_calls"]
        ), "Phase 3: heater should turn ON again at 19"

    async def test_cool_cycle_on_off_on(self, hass: HomeAssistant):
        """Cooler ON → OFF → ON through temperature swings."""
        ctx = await _setup_entity(hass, "tc_cycle_2", sensor_temp="18.0")

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": ENTITY_ID, "temperature": 22},
            blocking=True,
        )
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": ENTITY_ID, "hvac_mode": "cool"},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Phase 1: Rise to 28 → cooler ON
        _set_temp(hass, "28.0")
        await hass.async_block_till_done()
        assert _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Phase 1: cooler should turn ON at 28"

        # Simulate cooler actually turning ON (mock doesn't change state)
        hass.states.async_set(
            "input_boolean.test_ac_unit",
            STATE_ON,
            {"friendly_name": "Test AC Unit"},
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()
        ctx["turn_off_calls"].clear()

        # Phase 2: Drop to 18 → cooler OFF
        _set_temp(hass, "18.0")
        await hass.async_block_till_done()
        assert _cooler_turned_off(
            ctx["turn_off_calls"]
        ), "Phase 2: cooler should turn OFF at 18"

        # Simulate cooler actually turning OFF
        hass.states.async_set(
            "input_boolean.test_ac_unit",
            STATE_OFF,
            {"friendly_name": "Test AC Unit"},
        )
        await hass.async_block_till_done()
        ctx["turn_on_calls"].clear()
        ctx["turn_off_calls"].clear()

        # Phase 3: Rise to 26 → cooler ON again
        _set_temp(hass, "26.0")
        await hass.async_block_till_done()
        assert _cooler_turned_on(
            ctx["turn_on_calls"]
        ), "Phase 3: cooler should turn ON again at 26"
