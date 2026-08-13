"""Config flow for WoowTech Cover Entity integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol

from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
)

from .const import (
    CONF_CLOSE_COVER_ACTION,
    CONF_CLOSE_TILT_ACTION,
    CONF_CLOSE_TIME,
    CONF_DEVICE_CLASS,
    CONF_ENABLE_TILT,
    CONF_OPEN_COVER_ACTION,
    CONF_OPEN_TIME,
    CONF_OPEN_TILT_ACTION,
    CONF_POSITION_ENTITY,
    CONF_SET_POSITION_ACTION,
    CONF_SET_TILT_POSITION_ACTION,
    CONF_STOP_COVER_ACTION,
    CONF_STOP_TILT_ACTION,
    CONF_TILT_CLOSE_TIME,
    CONF_TILT_OPEN_TIME,
    CONF_TILT_POSITION_ENTITY,
    DOMAIN,
)

# Device class options
DEVICE_CLASS_OPTIONS = [
    selector.SelectOptionDict(value="awning", label="Awning"),
    selector.SelectOptionDict(value="blind", label="Blind"),
    selector.SelectOptionDict(value="curtain", label="Curtain"),
    selector.SelectOptionDict(value="damper", label="Damper"),
    selector.SelectOptionDict(value="door", label="Door"),
    selector.SelectOptionDict(value="garage", label="Garage"),
    selector.SelectOptionDict(value="gate", label="Gate"),
    selector.SelectOptionDict(value="shade", label="Shade"),
    selector.SelectOptionDict(value="shutter", label="Shutter"),
    selector.SelectOptionDict(value="window", label="Window"),
]


# ============================================================================
# CONFIG SCHEMA
# ============================================================================

CONFIG_SCHEMA = {
    # Basic Settings
    vol.Required(CONF_NAME): selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    ),
    vol.Optional(CONF_DEVICE_CLASS): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=DEVICE_CLASS_OPTIONS,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    vol.Optional(CONF_ENABLE_TILT, default=False): selector.BooleanSelector(
        selector.BooleanSelectorConfig()
    ),
    # Entity selectors for TX/RX targets
    vol.Optional(CONF_POSITION_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_number", "number"]
        )
    ),
    vol.Optional(CONF_TILT_POSITION_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_number", "number"]
        )
    ),
    # Time-based position estimation
    vol.Optional(CONF_OPEN_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1.0,
            max=300.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    vol.Optional(CONF_CLOSE_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1.0,
            max=300.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    vol.Optional(CONF_TILT_OPEN_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.5,
            max=60.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    vol.Optional(CONF_TILT_CLOSE_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.5,
            max=60.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    # Action script overrides
    vol.Optional(CONF_SET_POSITION_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_TILT_POSITION_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_OPEN_COVER_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_CLOSE_COVER_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_STOP_COVER_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_OPEN_TILT_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_CLOSE_TILT_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_STOP_TILT_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
}


# ============================================================================
# OPTIONS FLOW SCHEMA
# ============================================================================

OPTIONS_SCHEMA = {
    vol.Optional(CONF_DEVICE_CLASS): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=DEVICE_CLASS_OPTIONS,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    vol.Optional(CONF_ENABLE_TILT, default=False): selector.BooleanSelector(
        selector.BooleanSelectorConfig()
    ),
    vol.Optional(CONF_POSITION_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_number", "number"]
        )
    ),
    vol.Optional(CONF_TILT_POSITION_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_number", "number"]
        )
    ),
    # Time-based position estimation
    vol.Optional(CONF_OPEN_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1.0,
            max=300.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    vol.Optional(CONF_CLOSE_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1.0,
            max=300.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    vol.Optional(CONF_TILT_OPEN_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.5,
            max=60.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    vol.Optional(CONF_TILT_CLOSE_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.5,
            max=60.0,
            step=0.5,
            unit_of_measurement="seconds",
            mode=selector.NumberSelectorMode.BOX,
        )
    ),
    vol.Optional(CONF_SET_POSITION_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_TILT_POSITION_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_OPEN_COVER_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_CLOSE_COVER_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_STOP_COVER_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_OPEN_TILT_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_CLOSE_TILT_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_STOP_TILT_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
}


# ============================================================================
# VALIDATION
# ============================================================================


async def _validate_time_pairs(
    handler: SchemaConfigFlowHandler,
    user_input: dict[str, Any],
) -> dict[str, Any]:
    """Validate that time-based pairs are both set or both unset."""
    has_open = user_input.get(CONF_OPEN_TIME) is not None
    has_close = user_input.get(CONF_CLOSE_TIME) is not None
    if has_open != has_close:
        raise SchemaFlowError("time_pair_incomplete")

    has_tilt_open = user_input.get(CONF_TILT_OPEN_TIME) is not None
    has_tilt_close = user_input.get(CONF_TILT_CLOSE_TIME) is not None
    if has_tilt_open != has_tilt_close:
        raise SchemaFlowError("tilt_time_pair_incomplete")

    return user_input


# ============================================================================
# FLOW DEFINITIONS
# ============================================================================

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        vol.Schema(CONFIG_SCHEMA),
        validate_user_input=_validate_time_pairs,
    ),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        vol.Schema(OPTIONS_SCHEMA),
        validate_user_input=_validate_time_pairs,
    ),
}


class WoowCoverEntityConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config flow for WoowTech Cover Entity."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options[CONF_NAME])
