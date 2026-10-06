"""Config flow for Climate Template integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol

from homeassistant.components import fan, switch
from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_ACTIVITY,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_HOME,
    PRESET_SLEEP,
    HVACMode,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import CONF_NAME, DEGREE, STATE_ON
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
)

from .const import (
    CONF_AC_MODE,
    CONF_COOLER,
    CONF_FAN_MODE_ENTITY,
    CONF_FAN_MODES,
    CONF_HEATER,
    CONF_HUMIDITY_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_HVAC_MODE_ENTITY,
    CONF_HVAC_MODES,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_PRESET_MODE_ENTITY,
    CONF_PRESET_MODES,
    CONF_SET_FAN_MODE_ACTION,
    CONF_SET_HUMIDITY_ACTION,
    CONF_SET_HVAC_MODE_ACTION,
    CONF_SET_PRESET_MODE_ACTION,
    CONF_SET_SWING_HORIZONTAL_MODE_ACTION,
    CONF_SET_SWING_MODE_ACTION,
    CONF_SET_TEMPERATURE_ACTION,
    CONF_SWING_HORIZONTAL_MODE_ENTITY,
    CONF_SWING_HORIZONTAL_MODES,
    CONF_SWING_MODE_ENTITY,
    CONF_SWING_MODES,
    CONF_TARGET_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMP_STEP,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_TEMP_STEP,
    DOMAIN,
)

# Available HVAC modes for selection
HVAC_MODE_OPTIONS = [
    selector.SelectOptionDict(value=HVACMode.OFF, label="Off"),
    selector.SelectOptionDict(value=HVACMode.HEAT, label="Heat"),
    selector.SelectOptionDict(value=HVACMode.COOL, label="Cool"),
    selector.SelectOptionDict(value=HVACMode.HEAT_COOL, label="Heat/Cool (Auto)"),
    selector.SelectOptionDict(value=HVACMode.AUTO, label="Auto"),
    selector.SelectOptionDict(value=HVACMode.DRY, label="Dry"),
    selector.SelectOptionDict(value=HVACMode.FAN_ONLY, label="Fan Only"),
]

# Available fan modes for selection
FAN_MODE_OPTIONS = [
    selector.SelectOptionDict(value=FAN_AUTO, label="Auto"),
    selector.SelectOptionDict(value=FAN_LOW, label="Low"),
    selector.SelectOptionDict(value=FAN_MEDIUM, label="Medium"),
    selector.SelectOptionDict(value=FAN_HIGH, label="High"),
]

# Available preset modes for selection
PRESET_MODE_OPTIONS = [
    selector.SelectOptionDict(value=PRESET_ECO, label="Eco"),
    selector.SelectOptionDict(value=PRESET_AWAY, label="Away"),
    selector.SelectOptionDict(value=PRESET_BOOST, label="Boost"),
    selector.SelectOptionDict(value=PRESET_COMFORT, label="Comfort"),
    selector.SelectOptionDict(value=PRESET_HOME, label="Home"),
    selector.SelectOptionDict(value=PRESET_SLEEP, label="Sleep"),
    selector.SelectOptionDict(value=PRESET_ACTIVITY, label="Activity"),
]

# Available swing modes for selection
SWING_MODE_OPTIONS = [
    selector.SelectOptionDict(value=STATE_ON, label="On"),
    selector.SelectOptionDict(value=str(HVACMode.OFF), label="Off"),
]

# Available swing horizontal modes for selection
SWING_HORIZONTAL_MODE_OPTIONS = [
    selector.SelectOptionDict(value=STATE_ON, label="On"),
    selector.SelectOptionDict(value=str(HVACMode.OFF), label="Off"),
]


# ============================================================================
# CONFIG SCHEMA - Entity selectors for thermostat control
# ============================================================================

CONFIG_SCHEMA = {
    # Basic Settings
    vol.Required(CONF_NAME): selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    ),
    vol.Required(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=SENSOR_DOMAIN,
            device_class=SensorDeviceClass.TEMPERATURE,
        )
    ),
    vol.Optional(CONF_HEATER): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=[switch.DOMAIN, fan.DOMAIN, "climate", "input_boolean"]
        )
    ),
    vol.Optional(CONF_COOLER): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=[switch.DOMAIN, fan.DOMAIN, "climate", "input_boolean"]
        )
    ),
    vol.Optional(CONF_AC_MODE, default=False): selector.BooleanSelector(
        selector.BooleanSelectorConfig()
    ),
    # HVAC Modes
    vol.Required(
        CONF_HVAC_MODES,
        default=[HVACMode.OFF, HVACMode.HEAT],
    ): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=HVAC_MODE_OPTIONS,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    # Temperature Settings
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=DEGREE,
            step=0.5,
        )
    ),
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=DEGREE,
            step=0.5,
        )
    ),
    vol.Optional(CONF_TEMP_STEP, default=DEFAULT_TEMP_STEP): selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=DEGREE,
            step=0.1,
            min=0.1,
            max=5.0,
        )
    ),
    # Optional mode lists
    vol.Optional(CONF_FAN_MODES): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=FAN_MODE_OPTIONS,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    vol.Optional(CONF_PRESET_MODES): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=PRESET_MODE_OPTIONS,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    # Swing modes
    vol.Optional(CONF_SWING_MODES): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=SWING_MODE_OPTIONS,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    vol.Optional(CONF_SWING_HORIZONTAL_MODES): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=SWING_HORIZONTAL_MODE_OPTIONS,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    ),
    # Humidity sensor
    vol.Optional(CONF_HUMIDITY_SENSOR): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=SENSOR_DOMAIN,
            device_class=SensorDeviceClass.HUMIDITY,
        )
    ),
    # Entity selectors for TX/RX targets
    vol.Optional(CONF_HVAC_MODE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["input_select", "select"])
    ),
    vol.Optional(CONF_FAN_MODE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["input_select", "select", fan.DOMAIN])
    ),
    vol.Optional(CONF_PRESET_MODE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["input_select", "select"])
    ),
    vol.Optional(CONF_SWING_MODE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_select", "select", switch.DOMAIN, "input_boolean"]
        )
    ),
    vol.Optional(CONF_SWING_HORIZONTAL_MODE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_select", "select", switch.DOMAIN, "input_boolean"]
        )
    ),
    vol.Optional(CONF_TARGET_TEMPERATURE_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["input_number", "number"])
    ),
    vol.Optional(CONF_HUMIDITY_ENTITY): selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["input_number", "number"])
    ),
    # Optional action script overrides
    vol.Optional(CONF_SET_TEMPERATURE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_HVAC_MODE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_FAN_MODE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_PRESET_MODE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_SWING_MODE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_SWING_HORIZONTAL_MODE_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
    vol.Optional(CONF_SET_HUMIDITY_ACTION): selector.ActionSelector(
        selector.ActionSelectorConfig()
    ),
}

# ============================================================================
# OPTIONS FLOW SCHEMA (reuse CONFIG_SCHEMA fields minus the name)
# ============================================================================

OPTIONS_SCHEMA = {
    k: v
    for k, v in CONFIG_SCHEMA.items()
    if not (isinstance(k, vol.Required) and k.schema == CONF_NAME)
}

# ============================================================================
# VALIDATION
# ============================================================================


async def _validate_climate_config(
    handler: SchemaConfigFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate that at least one of heater or cooler is provided."""
    if not user_input.get(CONF_HEATER) and not user_input.get(CONF_COOLER):
        raise SchemaFlowError("heater_or_cooler_required")
    return user_input


# ============================================================================
# CONFIG FLOW DEFINITIONS
# ============================================================================

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        vol.Schema(CONFIG_SCHEMA),
        validate_user_input=_validate_climate_config,
    ),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        vol.Schema(OPTIONS_SCHEMA),
        validate_user_input=_validate_climate_config,
    ),
}


class ClimateTemplateConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config flow for Climate Template."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options[CONF_NAME])
