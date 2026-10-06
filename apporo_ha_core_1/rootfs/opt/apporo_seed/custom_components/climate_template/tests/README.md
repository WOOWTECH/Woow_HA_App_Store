# Climate Template Integration - Test Suite

## Overview

**Total Tests:** 238 (pytest) + 23 (live E2E shell script)

Tests cover both **Simple Mode** (entity selectors with TX/RX) and **Advanced Mode** (Jinja2 templates and action scripts).

## Quick Start

```bash
# Install dependencies
pip install pytest pytest-homeassistant-custom-component pytest-cov pytest-asyncio

# Run all pytest tests
pytest tests/ -v

# Run live E2E tests against a running HA instance
./tests/test_e2e_live_tx_rx.sh [username] [password]
```

## Test Files

### Core Behavior (pytest)

| File | Tests | Description |
|------|-------|-------------|
| `test_simple_climate.py` | 41 | SimpleClimate heater/cooler control logic, tolerance bands, HVAC modes |
| `test_advanced_climate.py` | 41 | TemplateClimate template rendering, action script execution |
| `test_entity_aggregation.py` | 30 | TX/RX entity selectors + action scripts for all 9 climate controls |
| `test_temperature_change.py` | 14 | Dynamic temperature changes triggering heater/cooler ON/OFF |
| `test_temperature_unit.py` | 4 | Always uses HA system unit (legacy option ignored) |

### Config Flow & Options (pytest)

| File | Tests | Description |
|------|-------|-------------|
| `test_options_flow.py` | 22 | Config entry creation, options flow updates, entity selector add/remove |

### Template & Script Internals (pytest)

| File | Tests | Description |
|------|-------|-------------|
| `test_template_fields.py` | 24 | Template rendering (simple, calculated, conditional, parametrized) |
| `test_action_scripts.py` | 18 | Action script execution, variable passing, error handling |
| `test_advanced_mode.py` | 17 | Advanced mode integration (direct class instantiation, legacy) |
| `test_mode_migration.py` | 17 | Simple-to-Advanced mode migration, template generation |
| `test_t4_bug.py` | 1 | Regression test for a specific bug |

### E2E Tests

| File | Tests | Description |
|------|-------|-------------|
| `test_e2e_ui_simple_mode.py` | 6 | Heater/cooler toggle auto-activation (pytest + manual UI docs) |
| `test_e2e_live_tx_rx.sh` | 23 | Live HA API test: 7 TX + 7 RX + 2 sensor + pre-flight checks |

## Key Test Patterns

### Setup Pattern (MockConfigEntry)

All pytest tests use `MockConfigEntry` + `config_entries.async_setup()`:

```python
entry = MockConfigEntry(
    domain=DOMAIN, title="Test", data={}, options=CONFIG, entry_id="test_1"
)
entry.add_to_hass(hass)
await hass.config_entries.async_setup(entry.entry_id)
await hass.async_block_till_done()
```

Must pop `loader.DATA_CUSTOM_COMPONENTS` from `hass.data` for custom integration
discovery (see `conftest.py`).

### TX Verification (action script)

`async_mock_service` captures raw service call data (templates NOT rendered):

```python
calls = async_mock_service(hass, "input_select", "select_option")
await hass.services.async_call("climate", "set_fan_mode",
    {"entity_id": ENTITY_ID, "fan_mode": "high"}, blocking=True)
# Check target entity_id in call, not rendered template values
assert "input_select.test_fan_speed" in (calls[0].data.get("entity_id") or [])
```

### RX Verification (state listener)

```python
hass.states.async_set("input_select.test_fan_speed", "high", {"options": [...]})
await hass.async_block_till_done()
state = hass.states.get(ENTITY_ID)
assert state.attributes["fan_mode"] == "high"
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# By category
pytest tests/test_simple_climate.py tests/test_entity_aggregation.py -v

# By keyword
pytest tests/ -k "tx" -v        # TX tests
pytest tests/ -k "rx" -v        # RX tests
pytest tests/ -k "fan_mode" -v  # Fan mode tests

# With coverage
pytest tests/ --cov=custom_components.climate_template --cov-report=term-missing

# Live E2E (requires running HA)
./tests/test_e2e_live_tx_rx.sh
HA_URL=http://192.168.1.5:8123 ./tests/test_e2e_live_tx_rx.sh user pass
```

## Resources

- **TX/RX Demo Setup:** `../docs/QUICKSTART_TX_RX_DEMO.md`
- **Test Plan:** `../docs/TESTING_PLAN.md`
- **Test Execution Guide:** `../docs/TEST_EXECUTION_GUIDE.md`
- **Test Entities Config:** `../docs/TEST_ENTITIES_CONFIG.yaml`
- **Helper Entity Examples:** `../example_configuration.yaml`
