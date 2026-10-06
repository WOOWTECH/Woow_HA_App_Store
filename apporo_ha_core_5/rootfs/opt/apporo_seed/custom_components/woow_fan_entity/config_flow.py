"""Config flow for WoowTech Fan Entity integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol

from homeassistant.components import fan, switch
from homeassistant.const import CONF_NAME, STATE_ON
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowFormStep,
)

from .const import (
    CONF_DIRECTION_ENTITY,
    CONF_DIRECTION_RECEIVE_TEMPLATE,
    CONF_ENABLE_DIRECTION,
    CONF_ENABLE_OSCILLATION,
    CONF_OSCILLATING_ENTITY,
    CONF_PERCENTAGE_ENTITY,
    CONF_PERCENTAGE_INPUT_MAX,
    CONF_PERCENTAGE_INPUT_MIN,
    CONF_PERCENTAGE_OUTPUT_MAX,
    CONF_PERCENTAGE_OUTPUT_MIN,
    CONF_PERCENTAGE_RECEIVE_TEMPLATE,
    CONF_PRESET_MODE_ENTITY,
    CONF_PRESET_MODE_RECEIVE_TEMPLATE,
    CONF_PRESET_MODES,
    CONF_SET_DIRECTION_ACTION,
    CONF_SET_OSCILLATING_ACTION,
    CONF_SET_PERCENTAGE_ACTION,
    CONF_SET_PRESET_MODE_ACTION,
    CONF_SPEED_COUNT,
    CONF_SWITCH_ENTITY,
    DEFAULT_SPEED_COUNT,
    DOMAIN,
)

# Preset mode options
PRESET_MODE_OPTIONS = [
    selector.SelectOptionDict(value="auto", label="Auto"),
    selector.SelectOptionDict(value="sleep", label="Sleep"),
    selector.SelectOptionDict(value="smart", label="Smart"),
    selector.SelectOptionDict(value="natural", label="Natural"),
    selector.SelectOptionDict(value="breeze", label="Breeze"),
    selector.SelectOptionDict(value="silent", label="Silent"),
    selector.SelectOptionDict(value="turbo", label="Turbo"),
]


# ============================================================================
# SHARED SCHEMA FIELDS (used by both config and options flows)
# ============================================================================

_COMMON_SCHEMA: dict[vol.Optional | vol.Required, selector.Selector] = {
    vol.Optional(CONF_SWITCH_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=[switch.DOMAIN, fan.DOMAIN, "input_boolean"]
        )
    ),
    vol.Optional(
        CONF_SPEED_COUNT, default=DEFAULT_SPEED_COUNT
    ): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX,
            min=1,
            max=100,
            step=1,
        )
    ),
    # Preset modes
    vol.Optional(CONF_PRESET_MODES): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=PRESET_MODE_OPTIONS,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    # Feature flags
    vol.Optional(CONF_ENABLE_OSCILLATION, default=False): selector.BooleanSelector(
        selector.BooleanSelectorConfig()
    ),
    vol.Optional(CONF_ENABLE_DIRECTION, default=False): selector.BooleanSelector(
        selector.BooleanSelectorConfig()
    ),
    # Entity selectors for TX/RX targets
    vol.Optional(CONF_PERCENTAGE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_number", "number"]
        )
    ),
    vol.Optional(CONF_PERCENTAGE_RECEIVE_TEMPLATE): selector.TemplateSelector(),
    vol.Optional(CONF_PERCENTAGE_INPUT_MIN): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX, step="any", min=-1000000, max=1000000
        )
    ),
    vol.Optional(CONF_PERCENTAGE_INPUT_MAX): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX, step="any", min=-1000000, max=1000000
        )
    ),
    vol.Optional(CONF_PERCENTAGE_OUTPUT_MIN): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX, step="any", min=-1000000, max=1000000
        )
    ),
    vol.Optional(CONF_PERCENTAGE_OUTPUT_MAX): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX, step="any", min=-1000000, max=1000000
        )
    ),
    vol.Optional(CONF_PRESET_MODE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_select", "select"]
        )
    ),
    vol.Optional(CONF_PRESET_MODE_RECEIVE_TEMPLATE): selector.TemplateSelector(),
    vol.Optional(CONF_OSCILLATING_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=[switch.DOMAIN, "input_boolean"]
        )
    ),
    vol.Optional(CONF_DIRECTION_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_select", "select"]
        )
    ),
    vol.Optional(CONF_DIRECTION_RECEIVE_TEMPLATE): selector.TemplateSelector(),
    # Action script overrides
    vol.Optional(CONF_SET_PERCENTAGE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_PRESET_MODE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_OSCILLATING_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_DIRECTION_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
}


# ============================================================================
# CONFIG SCHEMA (adds required Name field)
# ============================================================================

CONFIG_SCHEMA = {
    vol.Required(CONF_NAME): selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    ),
    **_COMMON_SCHEMA,
}


# ============================================================================
# OPTIONS FLOW SCHEMA (no Name field — title is immutable after creation)
# ============================================================================

OPTIONS_SCHEMA = {**_COMMON_SCHEMA}


# ============================================================================
# FLOW DEFINITIONS
# ============================================================================

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        vol.Schema(CONFIG_SCHEMA),
    ),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        vol.Schema(OPTIONS_SCHEMA),
    ),
}


class WoowFanEntityConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config flow for WoowTech Fan Entity."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options[CONF_NAME])
