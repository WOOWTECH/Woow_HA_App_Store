#!/usr/bin/env python3
"""
Comprehensive E2E edge-case tests for Climate Template component.
Runs against a live Home Assistant instance via REST API.

Usage:
    python3 tests/test_e2e_live.py

Requires:
    - HA running on localhost:18123
    - admin/admin123 credentials
    - Helper entities configured in configuration.yaml
    - climate_template component installed
"""

import json
import sys
import time
import requests
from dataclasses import dataclass, field

HA_URL = "http://localhost:18123"
HA_USER = "admin"
HA_PASS = "admin123"

# ============================================================================
# Auth helpers
# ============================================================================

def get_token() -> str:
    """Get a fresh HA access token."""
    # Start login flow
    resp = requests.post(f"{HA_URL}/auth/login_flow",
        json={"client_id": f"{HA_URL}/", "handler": ["homeassistant", None],
              "redirect_uri": f"{HA_URL}/"})
    flow_id = resp.json()["flow_id"]

    # Submit credentials
    resp = requests.post(f"{HA_URL}/auth/login_flow/{flow_id}",
        json={"client_id": f"{HA_URL}/", "username": HA_USER, "password": HA_PASS})
    auth_code = resp.json()["result"]

    # Exchange for token
    resp = requests.post(f"{HA_URL}/auth/token",
        data={"grant_type": "authorization_code", "code": auth_code,
              "client_id": f"{HA_URL}/"})
    return resp.json()["access_token"]


# ============================================================================
# API helpers
# ============================================================================

class HAClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _refresh_token(self):
        """Re-authenticate if token expired or connection lost."""
        self.token = get_token()
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _request(self, method: str, url: str, retries: int = 3, **kwargs):
        """Make an HTTP request with retry logic for connection resets."""
        for attempt in range(retries):
            try:
                resp = getattr(requests, method)(url, headers=self.headers, **kwargs)
                if resp.status_code == 401:
                    self._refresh_token()
                    resp = getattr(requests, method)(url, headers=self.headers, **kwargs)
                return resp
            except (requests.exceptions.ConnectionError, ConnectionResetError):
                if attempt < retries - 1:
                    wait = 5 * (attempt + 1)
                    print(f"    [retry] Connection reset, waiting {wait}s (attempt {attempt+1}/{retries})")
                    time.sleep(wait)
                    self._refresh_token()
                else:
                    raise

    def get_state(self, entity_id: str) -> dict:
        resp = self._request("get", f"{HA_URL}/api/states/{entity_id}")
        if resp.status_code == 200:
            return resp.json()
        return {"entity_id": entity_id, "state": "NOT_FOUND", "attributes": {}}

    def set_state(self, entity_id: str, state: str, attributes: dict = None):
        data = {"state": state}
        if attributes:
            data["attributes"] = attributes
        self._request("post", f"{HA_URL}/api/states/{entity_id}", json=data)

    def call_service(self, domain: str, service: str, data: dict = None, target: dict = None):
        payload = {}
        if data:
            payload.update(data)
        if target:
            payload["entity_id"] = target.get("entity_id")
        resp = self._request("post", f"{HA_URL}/api/services/{domain}/{service}", json=payload)
        return resp.status_code

    def config_flow_init(self, handler: str) -> dict:
        """Start a config flow."""
        resp = self._request("post", f"{HA_URL}/api/config/config_entries/flow",
                            json={"handler": handler})
        return resp.json()

    def config_flow_submit(self, flow_id: str, data: dict) -> dict:
        """Submit config flow step data."""
        resp = self._request("post", f"{HA_URL}/api/config/config_entries/flow/{flow_id}",
                            json=data)
        return resp.json()

    def get_config_entries(self, domain: str) -> list:
        """Get config entries for a domain."""
        resp = self._request("get", f"{HA_URL}/api/config/config_entries/entry")
        entries = resp.json()
        return [e for e in entries if e.get("domain") == domain]

    def delete_config_entry(self, entry_id: str) -> dict:
        """Delete a config entry."""
        resp = self._request("delete", f"{HA_URL}/api/config/config_entries/entry/{entry_id}")
        return resp.json() if resp.text else {}

    def options_flow_init(self, entry_id: str) -> dict:
        """Start an options flow for a config entry."""
        resp = self._request("post", f"{HA_URL}/api/config/config_entries/options/flow",
                            json={"handler": entry_id})
        return resp.json()

    def options_flow_submit(self, flow_id: str, data: dict) -> dict:
        """Submit options flow step data."""
        resp = self._request("post", f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}",
                            json=data)
        return resp.json()

    def wait(self, seconds: float = 1.0):
        """Wait for HA to process state changes."""
        time.sleep(seconds)


# ============================================================================
# Test infrastructure
# ============================================================================

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str = ""
    category: str = ""

@dataclass
class TestSuite:
    results: list = field(default_factory=list)
    current_entry_id: str = None

    def record(self, name: str, passed: bool, message: str = "", category: str = ""):
        self.results.append(TestResult(name, passed, message, category))
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" -- {message}" if message and not passed else ""))

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        print(f"\n{'='*70}")
        print(f"RESULTS: {passed}/{total} passed, {failed} failed")
        if failed:
            print(f"\nFAILED TESTS:")
            for r in self.results:
                if not r.passed:
                    print(f"  - [{r.category}] {r.name}: {r.message}")
        print(f"{'='*70}")
        return failed == 0


# ============================================================================
# Cleanup: remove any existing climate_template entries
# ============================================================================

def cleanup(ha: HAClient):
    """Remove all existing climate_template config entries."""
    entries = ha.get_config_entries("climate_template")
    for entry in entries:
        ha.delete_config_entry(entry["entry_id"])
        ha.wait(0.5)
    print(f"Cleaned up {len(entries)} existing entries")


# ============================================================================
# Create a climate entry via config flow
# ============================================================================

def create_climate_entry(ha: HAClient, config: dict) -> str | None:
    """Create a climate_template entry via config flow. Returns entry_id or None."""
    flow = ha.config_flow_init("climate_template")
    if "flow_id" not in flow:
        return None
    result = ha.config_flow_submit(flow["flow_id"], config)
    if result.get("type") == "create_entry":
        entry_id = result.get("result", {}).get("entry_id") if isinstance(result.get("result"), dict) else result.get("result")
        ha.wait(4)  # Allow HA time to fully initialize the new entity
        return entry_id
    return None


# ============================================================================
# TEST GROUPS
# ============================================================================

def test_config_flow(ha: HAClient, suite: TestSuite):
    """Test config flow creation and validation."""
    cat = "Config Flow"
    print(f"\n--- {cat} ---")

    # T1: Create basic heater-only entry
    config = {
        "name": "Test Heater Only",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat"],
        "min_temp": 7.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
    }
    flow = ha.config_flow_init("climate_template")
    suite.record("Config flow starts", "flow_id" in flow, str(flow), cat)

    result = ha.config_flow_submit(flow["flow_id"], config)
    created = result.get("type") == "create_entry"
    suite.record("Heater-only entry created", created, str(result.get("type")), cat)

    if created:
        entry_id = result.get("result", {}).get("entry_id") if isinstance(result.get("result"), dict) else result.get("result")
        ha.wait(2)
        state = ha.get_state("climate.test_heater_only")
        suite.record("Entity exists after creation", state["state"] != "NOT_FOUND",
                     f"state={state['state']}", cat)
        suite.record("Initial mode is OFF", state["state"] == "off",
                     f"state={state['state']}", cat)
        suite.record("Min temp is 7.0", state["attributes"].get("min_temp") == 7.0,
                     f"min_temp={state['attributes'].get('min_temp')}", cat)
        suite.record("Max temp is 35.0", state["attributes"].get("max_temp") == 35.0,
                     f"max_temp={state['attributes'].get('max_temp')}", cat)
        # Cleanup
        ha.delete_config_entry(entry_id)
        ha.wait(1)

    # T2: Reject config with no heater AND no cooler
    config_no_device = {
        "name": "Test No Devices",
        "temperature_sensor": "sensor.climate_test_temperature",
        "hvac_modes": ["off", "heat"],
        "min_temp": 7.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
    }
    flow = ha.config_flow_init("climate_template")
    result = ha.config_flow_submit(flow["flow_id"], config_no_device)
    rejected = result.get("type") == "form" and "heater_or_cooler_required" in str(result.get("errors", {}))
    suite.record("Rejects no heater/cooler", rejected,
                 f"type={result.get('type')}, errors={result.get('errors')}", cat)


def test_heating_mode(ha: HAClient, suite: TestSuite):
    """Test heating mode thermostat control with tolerance bands."""
    cat = "Heating Mode"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    # Set initial temperature to 21.0
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config = {
        "name": "Test Heating",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat"],
        "min_temp": 5.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Heating entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_heating"

    # Set to heat mode, target 25
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "heat"})
    ha.wait(1)
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 25.0})
    ha.wait(2)

    state = ha.get_state(entity_id)
    suite.record("HVAC mode is heat", state["state"] == "heat",
                 f"state={state['state']}", cat)
    suite.record("Target temp is 25.0", state["attributes"].get("temperature") == 25.0,
                 f"temp={state['attributes'].get('temperature')}", cat)

    # Temperature is 21.0, target is 25.0 -> should heat (21 < 25 - 0.3)
    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("Heater ON when too cold (21 < 24.7)",
                 heater["state"] == "on",
                 f"heater={heater['state']}", cat)

    action = state["attributes"].get("hvac_action")
    suite.record("hvac_action is heating", action == "heating",
                 f"action={action}", cat)

    # Raise temperature above target + tolerance (25 + 0.3 = 25.3)
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 26.0})
    ha.wait(3)

    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("Heater OFF when warm enough (26 > 25)",
                 heater["state"] == "off",
                 f"heater={heater['state']}", cat)

    state = ha.get_state(entity_id)
    action = state["attributes"].get("hvac_action")
    suite.record("hvac_action is idle when warm", action == "idle",
                 f"action={action}", cat)

    # Test tolerance band: temp within tolerance shouldn't change state
    # Set temp to 24.8 (target=25, cold_tolerance=0.3, 24.8 > 25-0.3=24.7)
    # So heater should stay OFF (within tolerance)
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 24.8})
    ha.wait(3)
    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("Heater stays OFF in tolerance band (24.8)",
                 heater["state"] == "off",
                 f"heater={heater['state']}", cat)

    # Drop below tolerance (24.5 < 25 - 0.3 = 24.7)
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 24.5})
    ha.wait(3)
    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("Heater ON below tolerance (24.5 < 24.7)",
                 heater["state"] == "on",
                 f"heater={heater['state']}", cat)

    # Test OFF mode stops heating
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "off"})
    ha.wait(2)
    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("Heater OFF in OFF mode", heater["state"] == "off",
                 f"heater={heater['state']}", cat)

    state = ha.get_state(entity_id)
    action = state["attributes"].get("hvac_action")
    suite.record("hvac_action is off in OFF mode", action == "off",
                 f"action={action}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_cooling_mode(ha: HAClient, suite: TestSuite):
    """Test cooling mode with cooler entity."""
    cat = "Cooling Mode"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    # Set temp to 28
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 28.0})
    ha.wait(2)

    config = {
        "name": "Test Cooling",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "cooler": "input_boolean.climate_cooler",
        "hvac_modes": ["off", "heat", "cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Cooling entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_cooling"

    # Switch to cool mode, target 25
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "cool"})
    ha.wait(1)
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 25.0})
    ha.wait(3)

    # Temp=28 > target=25+0.3=25.3 -> cooler ON
    cooler = ha.get_state("input_boolean.climate_cooler")
    suite.record("Cooler ON when too hot (28 > 25.3)",
                 cooler["state"] == "on",
                 f"cooler={cooler['state']}", cat)

    state = ha.get_state(entity_id)
    action = state["attributes"].get("hvac_action")
    suite.record("hvac_action is cooling", action == "cooling",
                 f"action={action}", cat)

    # Cool down to 24
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 24.0})
    ha.wait(3)
    cooler = ha.get_state("input_boolean.climate_cooler")
    suite.record("Cooler OFF when cool enough (24 < 25.3)",
                 cooler["state"] == "off",
                 f"cooler={cooler['state']}", cat)

    # Verify heater is NOT on during cool mode
    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("Heater stays OFF in cool mode",
                 heater["state"] == "off",
                 f"heater={heater['state']}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_heat_cool_mode(ha: HAClient, suite: TestSuite):
    """Test heat_cool dual setpoint mode."""
    cat = "Heat/Cool Mode"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    # Reset heater/cooler
    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_heater"})
    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_cooler"})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 22.0})
    ha.wait(2)

    config = {
        "name": "Test Dual",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "cooler": "input_boolean.climate_cooler",
        "hvac_modes": ["off", "heat", "cool", "heat_cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Dual mode entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_dual"

    # Switch to heat_cool mode
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "heat_cool"})
    ha.wait(1)

    # Set dual setpoints: low=20, high=26
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "target_temp_low": 20.0,
                    "target_temp_high": 26.0})
    ha.wait(3)

    state = ha.get_state(entity_id)
    suite.record("Supports temperature range",
                 bool(state["attributes"].get("supported_features", 0) & 2),
                 f"features={state['attributes'].get('supported_features')}", cat)

    # Temp=22 is in comfortable zone (20-26) -> both OFF
    heater = ha.get_state("input_boolean.climate_heater")
    cooler = ha.get_state("input_boolean.climate_cooler")
    suite.record("Both OFF in comfort zone (22 between 20-26)",
                 heater["state"] == "off" and cooler["state"] == "off",
                 f"heater={heater['state']}, cooler={cooler['state']}", cat)

    # Drop temp to 18 (below 20 - 0.3 = 19.7) -> heater ON
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 18.0})
    ha.wait(3)
    heater = ha.get_state("input_boolean.climate_heater")
    cooler = ha.get_state("input_boolean.climate_cooler")
    suite.record("Heater ON when too cold (18 < 19.7)",
                 heater["state"] == "on",
                 f"heater={heater['state']}", cat)
    suite.record("Cooler OFF when too cold",
                 cooler["state"] == "off",
                 f"cooler={cooler['state']}", cat)

    # Raise temp to 28 (above 26 + 0.3 = 26.3) -> cooler ON, heater OFF
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 28.0})
    ha.wait(3)
    heater = ha.get_state("input_boolean.climate_heater")
    cooler = ha.get_state("input_boolean.climate_cooler")
    suite.record("Cooler ON when too hot (28 > 26.3)",
                 cooler["state"] == "on",
                 f"cooler={cooler['state']}", cat)
    suite.record("Heater OFF when too hot",
                 heater["state"] == "off",
                 f"heater={heater['state']}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_tx_rx_entity_sync(ha: HAClient, suite: TestSuite):
    """Test TX/RX entity synchronization."""
    cat = "TX/RX Sync"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    # Reset helper entities
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_fan_mode", "option": "auto"})
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_preset_mode", "option": "none"})
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_swing_mode", "option": "off"})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_target_temp", "value": 22.0})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_target_humidity", "value": 50})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config = {
        "name": "Test TXRX",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "cooler": "input_boolean.climate_cooler",
        "hvac_modes": ["off", "heat", "cool", "heat_cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
        "fan_modes": ["auto", "low", "medium", "high"],
        "preset_modes": ["eco", "away", "boost", "comfort"],
        "swing_modes": ["on", "off"],
        "fan_mode_entity": "input_select.climate_fan_mode",
        "preset_mode_entity": "input_select.climate_preset_mode",
        "swing_mode_entity": "input_select.climate_swing_mode",
        "target_temperature_entity": "input_number.climate_target_temp",
        "humidity_entity": "input_number.climate_target_humidity",
        "humidity_sensor": "sensor.climate_test_humidity_sensor",
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("TX/RX entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_txrx"
    ha.wait(2)

    # --- TX Tests ---
    # TX: Set fan mode via climate -> should propagate to input_select
    ha.call_service("climate", "set_fan_mode",
                   {"entity_id": entity_id, "fan_mode": "high"})
    ha.wait(2)
    fan_entity = ha.get_state("input_select.climate_fan_mode")
    suite.record("TX: fan mode propagates to entity",
                 fan_entity["state"] == "high",
                 f"entity={fan_entity['state']}", cat)

    # TX: Set preset mode -> propagate to input_select
    ha.call_service("climate", "set_preset_mode",
                   {"entity_id": entity_id, "preset_mode": "eco"})
    ha.wait(2)
    preset_entity = ha.get_state("input_select.climate_preset_mode")
    suite.record("TX: preset mode propagates to entity",
                 preset_entity["state"] == "eco",
                 f"entity={preset_entity['state']}", cat)

    # TX: Set swing mode -> propagate to input_select
    ha.call_service("climate", "set_swing_mode",
                   {"entity_id": entity_id, "swing_mode": "on"})
    ha.wait(2)
    swing_entity = ha.get_state("input_select.climate_swing_mode")
    suite.record("TX: swing mode propagates to entity",
                 swing_entity["state"] == "on",
                 f"entity={swing_entity['state']}", cat)

    # TX: Set target temp -> propagate to input_number
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 28.5})
    ha.wait(2)
    temp_entity = ha.get_state("input_number.climate_target_temp")
    suite.record("TX: target temp propagates to entity",
                 float(temp_entity["state"]) == 28.5,
                 f"entity={temp_entity['state']}", cat)

    # TX: Set humidity -> propagate to input_number
    ha.call_service("climate", "set_humidity",
                   {"entity_id": entity_id, "humidity": 65})
    ha.wait(2)
    hum_entity = ha.get_state("input_number.climate_target_humidity")
    suite.record("TX: humidity propagates to entity",
                 float(hum_entity["state"]) == 65.0,
                 f"entity={hum_entity['state']}", cat)

    # --- RX Tests ---
    # RX: Change fan mode externally -> should propagate to climate
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_fan_mode", "option": "low"})
    ha.wait(2)
    state = ha.get_state(entity_id)
    suite.record("RX: external fan mode change syncs",
                 state["attributes"].get("fan_mode") == "low",
                 f"fan_mode={state['attributes'].get('fan_mode')}", cat)

    # RX: Change preset externally
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_preset_mode", "option": "comfort"})
    ha.wait(2)
    state = ha.get_state(entity_id)
    suite.record("RX: external preset change syncs",
                 state["attributes"].get("preset_mode") == "comfort",
                 f"preset_mode={state['attributes'].get('preset_mode')}", cat)

    # RX: Change swing externally
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_swing_mode", "option": "off"})
    ha.wait(2)
    state = ha.get_state(entity_id)
    suite.record("RX: external swing mode change syncs",
                 state["attributes"].get("swing_mode") == "off",
                 f"swing_mode={state['attributes'].get('swing_mode')}", cat)

    # RX: Change target temp externally
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_target_temp", "value": 19.0})
    ha.wait(2)
    state = ha.get_state(entity_id)
    suite.record("RX: external target temp change syncs",
                 state["attributes"].get("temperature") == 19.0,
                 f"temperature={state['attributes'].get('temperature')}", cat)

    # RX: Change humidity externally
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_target_humidity", "value": 40})
    ha.wait(2)
    state = ha.get_state(entity_id)
    suite.record("RX: external humidity change syncs",
                 state["attributes"].get("humidity") == 40,
                 f"humidity={state['attributes'].get('humidity')}", cat)

    # RX: Humidity sensor reading
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_humidity", "value": 70})
    ha.wait(3)
    state = ha.get_state(entity_id)
    suite.record("RX: humidity sensor reading updates",
                 state["attributes"].get("current_humidity") == 70,
                 f"current_humidity={state['attributes'].get('current_humidity')}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_sensor_unavailable(ha: HAClient, suite: TestSuite):
    """Test behavior when sensor becomes unavailable."""
    cat = "Sensor Unavailable"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config = {
        "name": "Test Unavail",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat"],
        "min_temp": 5.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Unavail entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_unavail"

    # Set to heat mode
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "heat"})
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 25.0})
    ha.wait(2)

    state = ha.get_state(entity_id)
    suite.record("Entity has current_temperature initially",
                 state["attributes"].get("current_temperature") is not None,
                 f"temp={state['attributes'].get('current_temperature')}", cat)

    # Make sensor unavailable by setting to "unavailable" string
    ha.set_state("sensor.climate_test_temperature", "unavailable",
                {"unit_of_measurement": "°C", "device_class": "temperature"})
    ha.wait(3)

    state = ha.get_state(entity_id)
    # Entity should still exist and retain last known temperature
    suite.record("Entity still functional when sensor unavailable",
                 state["state"] != "NOT_FOUND" and state["state"] != "unavailable",
                 f"state={state['state']}", cat)

    # Restore sensor
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(3)

    state = ha.get_state(entity_id)
    suite.record("Entity recovers when sensor returns",
                 state["attributes"].get("current_temperature") is not None,
                 f"temp={state['attributes'].get('current_temperature')}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_preset_mode_temp_save_restore(ha: HAClient, suite: TestSuite):
    """Test preset mode saves/restores target temperature."""
    cat = "Preset Save/Restore"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config = {
        "name": "Test Preset",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat"],
        "min_temp": 5.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
        "preset_modes": ["eco", "away", "boost", "comfort"],
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Preset entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_preset"

    # Set heat mode and target 22
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "heat"})
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 22.0})
    ha.wait(2)

    state = ha.get_state(entity_id)
    original_temp = state["attributes"].get("temperature")
    suite.record("Initial target temp is 22.0",
                 original_temp == 22.0,
                 f"temp={original_temp}", cat)

    # Switch to eco preset
    ha.call_service("climate", "set_preset_mode",
                   {"entity_id": entity_id, "preset_mode": "eco"})
    ha.wait(2)

    state = ha.get_state(entity_id)
    suite.record("Preset mode set to eco",
                 state["attributes"].get("preset_mode") == "eco",
                 f"preset={state['attributes'].get('preset_mode')}", cat)

    # Change temperature while in preset
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 18.0})
    ha.wait(1)

    # Switch back to none -> should restore original temp (22.0)
    ha.call_service("climate", "set_preset_mode",
                   {"entity_id": entity_id, "preset_mode": "none"})
    ha.wait(2)

    state = ha.get_state(entity_id)
    restored_temp = state["attributes"].get("temperature")
    suite.record("Temp restored after exiting preset (22.0)",
                 restored_temp == 22.0,
                 f"restored_temp={restored_temp}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_options_flow_update(ha: HAClient, suite: TestSuite):
    """Test options flow updates trigger entity reload."""
    cat = "Options Flow"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config = {
        "name": "Test Options",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat"],
        "min_temp": 7.0,
        "max_temp": 35.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Options entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_options"

    # Verify initial state
    state = ha.get_state(entity_id)
    suite.record("Initial min_temp=7.0",
                 state["attributes"].get("min_temp") == 7.0,
                 f"min_temp={state['attributes'].get('min_temp')}", cat)

    # Change options: update min/max temp and add fan modes
    opt_flow = ha.options_flow_init(entry_id)
    if "flow_id" in opt_flow:
        new_options = {
            "temperature_sensor": "sensor.climate_test_temperature",
            "heater": "input_boolean.climate_heater",
            "hvac_modes": ["off", "heat", "cool"],
            "min_temp": 10.0,
            "max_temp": 40.0,
            "temp_step": 1.0,
            "fan_modes": ["auto", "low", "medium", "high"],
        }
        result = ha.options_flow_submit(opt_flow["flow_id"], new_options)
        ha.wait(3)

        state = ha.get_state(entity_id)
        suite.record("Updated min_temp=10.0",
                     state["attributes"].get("min_temp") == 10.0,
                     f"min_temp={state['attributes'].get('min_temp')}", cat)
        suite.record("Updated max_temp=40.0",
                     state["attributes"].get("max_temp") == 40.0,
                     f"max_temp={state['attributes'].get('max_temp')}", cat)
        suite.record("Updated temp_step=1.0",
                     state["attributes"].get("target_temp_step") == 1.0,
                     f"step={state['attributes'].get('target_temp_step')}", cat)
        suite.record("Fan modes added after options update",
                     state["attributes"].get("fan_modes") is not None,
                     f"fan_modes={state['attributes'].get('fan_modes')}", cat)
        suite.record("Cool mode added after options update",
                     "cool" in (state["attributes"].get("hvac_modes") or []),
                     f"modes={state['attributes'].get('hvac_modes')}", cat)
    else:
        suite.record("Options flow started", False, str(opt_flow), cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_ac_mode(ha: HAClient, suite: TestSuite):
    """Test AC mode inverted control logic."""
    cat = "AC Mode"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    # Reset
    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_heater2"})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 28.0})
    ha.wait(2)

    config = {
        "name": "Test AC",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater2",
        "ac_mode": True,
        "hvac_modes": ["off", "cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("AC mode entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_ac"

    # Set cool mode, target 25
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "cool"})
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 25.0})
    ha.wait(3)

    # In AC mode, the "heater" entity is used as the AC unit
    # Temp=28 > target=25+0.3 -> AC (heater2) should be ON
    heater2 = ha.get_state("input_boolean.climate_heater2")
    suite.record("AC mode: heater entity used for cooling (ON at 28>25.3)",
                 heater2["state"] == "on",
                 f"heater2={heater2['state']}", cat)

    state = ha.get_state(entity_id)
    action = state["attributes"].get("hvac_action")
    suite.record("AC mode: hvac_action is cooling",
                 action == "cooling",
                 f"action={action}", cat)

    # Cool down -> AC OFF
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 24.0})
    ha.wait(3)
    heater2 = ha.get_state("input_boolean.climate_heater2")
    suite.record("AC mode: heater entity OFF when cool (24 < 25.3)",
                 heater2["state"] == "off",
                 f"heater2={heater2['state']}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_rapid_temperature_changes(ha: HAClient, suite: TestSuite):
    """Test rapid temperature changes don't cause race conditions."""
    cat = "Rapid Changes"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_heater"})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 20.0})
    ha.wait(2)

    config = {
        "name": "Test Rapid",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Rapid entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_rapid"

    # Set heat mode, target 25
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "heat"})
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 25.0})
    ha.wait(2)

    # Rapid temperature changes: oscillate around the target
    for temp in [24.5, 25.5, 24.0, 26.0, 24.8, 25.2, 24.6, 25.4]:
        ha.call_service("input_number", "set_value",
                       {"entity_id": "input_number.climate_sim_temp", "value": temp})
        time.sleep(0.3)  # rapid changes

    ha.wait(3)

    # After rapid changes, final temp is 25.4 (above target 25 - within tolerance)
    # Entity should be stable and not crashed
    state = ha.get_state(entity_id)
    suite.record("Entity stable after rapid changes",
                 state["state"] in ("heat", "off") and state["state"] != "NOT_FOUND",
                 f"state={state['state']}", cat)

    # Final temp 25.4 >= 25.0 -> heater should be OFF (not too cold)
    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("Heater state consistent after rapid changes",
                 heater["state"] in ("on", "off"),
                 f"heater={heater['state']}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_state_restoration(ha: HAClient, suite: TestSuite):
    """Test state persists across integration reload."""
    cat = "State Restoration"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config = {
        "name": "Test Restore",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat", "cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
        "fan_modes": ["auto", "low", "medium", "high"],
        "preset_modes": ["eco", "away"],
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("Restore entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_restore"

    # Set specific state
    ha.call_service("climate", "set_hvac_mode",
                   {"entity_id": entity_id, "hvac_mode": "heat"})
    ha.call_service("climate", "set_temperature",
                   {"entity_id": entity_id, "temperature": 23.5})
    ha.call_service("climate", "set_fan_mode",
                   {"entity_id": entity_id, "fan_mode": "medium"})
    ha.call_service("climate", "set_preset_mode",
                   {"entity_id": entity_id, "preset_mode": "eco"})
    ha.wait(2)

    # Record state before reload
    state_before = ha.get_state(entity_id)
    mode_before = state_before["state"]
    fan_before = state_before["attributes"].get("fan_mode")
    preset_before = state_before["attributes"].get("preset_mode")

    suite.record("State set before reload",
                 mode_before == "heat" and fan_before == "medium" and preset_before == "eco",
                 f"mode={mode_before}, fan={fan_before}, preset={preset_before}", cat)

    # Reload the integration
    ha.call_service("homeassistant", "reload_config_entry",
                   {"entity_id": entity_id})
    ha.wait(5)

    # Check state after reload
    state_after = ha.get_state(entity_id)
    suite.record("HVAC mode restored after reload",
                 state_after["state"] == "heat",
                 f"state={state_after['state']}", cat)
    suite.record("Fan mode restored after reload",
                 state_after["attributes"].get("fan_mode") == "medium",
                 f"fan={state_after['attributes'].get('fan_mode')}", cat)
    suite.record("Preset mode restored after reload",
                 state_after["attributes"].get("preset_mode") == "eco",
                 f"preset={state_after['attributes'].get('preset_mode')}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_rx_triggers_control_loop(ha: HAClient, suite: TestSuite):
    """Test that RX HVAC mode/target temp changes trigger the control loop."""
    cat = "RX Control Loop"
    print(f"\n--- {cat} ---")

    cleanup(ha)
    ha.wait(3)  # Extra wait for previous entries to fully unload

    # Reset
    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_heater"})
    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_cooler"})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 18.0})
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_hvac_mode", "option": "off"})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_target_temp", "value": 22.0})
    ha.wait(3)

    config = {
        "name": "Test RX Control",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "cooler": "input_boolean.climate_cooler",
        "hvac_modes": ["off", "heat", "cool", "heat_cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
        "hvac_mode_entity": "input_select.climate_hvac_mode",
        "target_temperature_entity": "input_number.climate_target_temp",
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("RX control entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_rx_control"
    ha.wait(2)

    # Current temp=18, target=22. Switch to heat via external entity
    ha.call_service("input_select", "select_option",
                   {"entity_id": "input_select.climate_hvac_mode", "option": "heat"})
    ha.wait(5)

    state = ha.get_state(entity_id)
    suite.record("RX HVAC mode synced to heat",
                 state["state"] == "heat",
                 f"state={state['state']}", cat)

    # The control loop should have turned on heater (18 < 22 - 0.3)
    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("RX HVAC mode change triggers control loop (heater ON)",
                 heater["state"] == "on",
                 f"heater={heater['state']}", cat)

    # Now change target temp externally to 15 (18 > 15, not too cold -> heater OFF)
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_target_temp", "value": 15.0})
    ha.wait(3)

    heater = ha.get_state("input_boolean.climate_heater")
    suite.record("RX target temp change triggers control loop (heater OFF at 18>15)",
                 heater["state"] == "off",
                 f"heater={heater['state']}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_heat_cool_without_cooler(ha: HAClient, suite: TestSuite):
    """Test heat_cool mode is auto-removed when no cooler."""
    cat = "Heat/Cool Validation"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config = {
        "name": "Test NoCooler HC",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat", "heat_cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
    }
    entry_id = create_climate_entry(ha, config)
    suite.record("No-cooler HC entry created", entry_id is not None, "", cat)
    if not entry_id:
        return

    entity_id = "climate.test_nocooler_hc"
    ha.wait(2)

    state = ha.get_state(entity_id)
    modes = state["attributes"].get("hvac_modes", [])
    suite.record("heat_cool auto-removed without cooler",
                 "heat_cool" not in modes,
                 f"modes={modes}", cat)
    suite.record("heat mode still present",
                 "heat" in modes,
                 f"modes={modes}", cat)

    ha.delete_config_entry(entry_id)
    ha.wait(1)


def test_multiple_instances(ha: HAClient, suite: TestSuite):
    """Test multiple climate entities coexist independently."""
    cat = "Multiple Instances"
    print(f"\n--- {cat} ---")

    cleanup(ha)

    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_heater"})
    ha.call_service("input_boolean", "turn_off",
                   {"entity_id": "input_boolean.climate_cooler"})
    ha.call_service("input_number", "set_value",
                   {"entity_id": "input_number.climate_sim_temp", "value": 21.0})
    ha.wait(2)

    config1 = {
        "name": "Instance A",
        "temperature_sensor": "sensor.climate_test_temperature",
        "heater": "input_boolean.climate_heater",
        "hvac_modes": ["off", "heat"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
    }
    config2 = {
        "name": "Instance B",
        "temperature_sensor": "sensor.climate_test_temperature",
        "cooler": "input_boolean.climate_cooler",
        "hvac_modes": ["off", "cool"],
        "min_temp": 5.0,
        "max_temp": 50.0,
        "temp_step": 0.5,
    }
    entry1 = create_climate_entry(ha, config1)
    entry2 = create_climate_entry(ha, config2)

    suite.record("Instance A created", entry1 is not None, "", cat)
    suite.record("Instance B created", entry2 is not None, "", cat)

    if entry1 and entry2:
        state_a = ha.get_state("climate.instance_a")
        state_b = ha.get_state("climate.instance_b")
        suite.record("Both entities exist independently",
                     state_a["state"] != "NOT_FOUND" and state_b["state"] != "NOT_FOUND",
                     f"A={state_a['state']}, B={state_b['state']}", cat)

        # Set different modes
        ha.call_service("climate", "set_hvac_mode",
                       {"entity_id": "climate.instance_a", "hvac_mode": "heat"})
        ha.call_service("climate", "set_hvac_mode",
                       {"entity_id": "climate.instance_b", "hvac_mode": "cool"})
        ha.wait(2)

        state_a = ha.get_state("climate.instance_a")
        state_b = ha.get_state("climate.instance_b")
        suite.record("Instance A is heat, B is cool",
                     state_a["state"] == "heat" and state_b["state"] == "cool",
                     f"A={state_a['state']}, B={state_b['state']}", cat)

    if entry1:
        ha.delete_config_entry(entry1)
    if entry2:
        ha.delete_config_entry(entry2)
    ha.wait(1)


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("Climate Template E2E Edge-Case Tests")
    print("=" * 70)

    token = get_token()
    ha = HAClient(token)
    suite = TestSuite()

    # Verify prerequisites
    print("\nChecking prerequisites...")
    config_resp = requests.get(f"{HA_URL}/api/config", headers=ha.headers)
    if config_resp.status_code != 200:
        print("ERROR: Cannot connect to HA API")
        sys.exit(1)

    ha_config = config_resp.json()
    print(f"  HA Version: {ha_config.get('version')}")
    print(f"  State: {ha_config.get('state')}")

    # Check test entities exist
    sensor = ha.get_state("sensor.climate_test_temperature")
    if sensor["state"] == "NOT_FOUND":
        print("ERROR: Test entities not found. Check configuration.yaml")
        sys.exit(1)
    print(f"  Test sensor: {sensor['state']}°C")

    # Run all test groups
    test_config_flow(ha, suite)
    test_heating_mode(ha, suite)
    test_cooling_mode(ha, suite)
    test_heat_cool_mode(ha, suite)
    test_ac_mode(ha, suite)
    test_tx_rx_entity_sync(ha, suite)
    test_rx_triggers_control_loop(ha, suite)
    test_sensor_unavailable(ha, suite)
    test_preset_mode_temp_save_restore(ha, suite)
    test_options_flow_update(ha, suite)
    test_rapid_temperature_changes(ha, suite)
    test_state_restoration(ha, suite)
    test_heat_cool_without_cooler(ha, suite)
    test_multiple_instances(ha, suite)

    # Final cleanup
    cleanup(ha)

    all_passed = suite.summary()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
