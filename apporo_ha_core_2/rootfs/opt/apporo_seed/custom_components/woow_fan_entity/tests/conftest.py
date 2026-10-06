"""Shared fixtures for WoowTech Fan Entity tests."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant import loader

from pytest_homeassistant_custom_component.common import async_mock_service


@pytest.fixture(autouse=True)
def clear_custom_components_cache(hass: HomeAssistant):
    """Clear the custom components cache before each test.

    This prevents stale integration caches from interfering across tests.
    """
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)


@pytest.fixture
def mock_ha_services(hass: HomeAssistant):
    """Mock common homeassistant services used by fan entity tests.

    Returns a dict of service name -> list of service call objects.
    """
    return {
        "turn_on": async_mock_service(hass, "homeassistant", "turn_on"),
        "turn_off": async_mock_service(hass, "homeassistant", "turn_off"),
    }


@pytest.fixture
def mock_all_services(hass: HomeAssistant, mock_ha_services):
    """Mock all services including entity-domain-specific ones.

    Returns a dict of service name -> list of service call objects.
    """
    return {
        **mock_ha_services,
        "set_value": async_mock_service(hass, "input_number", "set_value"),
        "select_option": async_mock_service(hass, "input_select", "select_option"),
        "input_boolean_turn_on": async_mock_service(hass, "input_boolean", "turn_on"),
        "input_boolean_turn_off": async_mock_service(hass, "input_boolean", "turn_off"),
    }
