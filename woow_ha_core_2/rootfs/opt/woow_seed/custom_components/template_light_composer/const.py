"""Constants for Template Light Composer integration."""

from __future__ import annotations

from typing import Final

# Domain
DOMAIN: Final = "template_light_composer"

# Configuration keys
CONF_NAME: Final = "name"
CONF_UNIQUE_ID: Final = "unique_id"
CONF_LEVEL_ENTITY: Final = "level_entity"
CONF_LEVEL_ATTRIBUTE: Final = "level_attribute"
CONF_LEVEL_UNIT: Final = "level_unit"
CONF_STATE_ENTITY: Final = "state_entity"
CONF_STATE_ATTRIBUTE: Final = "state_attribute"
CONF_STATE_OPERATOR: Final = "state_operator"
CONF_STATE_THRESHOLD: Final = "state_threshold"
CONF_TEMPERATURE_ENTITY: Final = "temperature_entity"
CONF_TEMPERATURE_ATTRIBUTE: Final = "temperature_attribute"
CONF_MIN_TEMPERATURE: Final = "min_temperature"
CONF_MAX_TEMPERATURE: Final = "max_temperature"
CONF_TURN_ON_ACTION: Final = "turn_on_action"
CONF_TURN_OFF_ACTION: Final = "turn_off_action"
CONF_SET_LEVEL_ACTION: Final = "set_level_action"
CONF_SET_TEMPERATURE_ACTION: Final = "set_temperature_action"
CONF_ACTION_TYPE: Final = "action_type"
CONF_ACTION_TARGET: Final = "action_target"
CONF_ACTION_PARAMETERS: Final = "action_parameters"
CONF_PARAMETER_MAPPING: Final = "parameter_mapping"
CONF_SUPPORTS_TRANSITION: Final = "supports_transition"
CONF_ICON: Final = "icon"
CONF_AVAILABILITY_TEMPLATE: Final = "availability_template"

# Config flow step IDs (simplified to 3 steps)
STEP_USER: Final = "user"
STEP_ACTIONS: Final = "actions"
STEP_ADVANCED: Final = "advanced"

# Action types
ACTION_TYPE_SCRIPT: Final = "script"
ACTION_TYPE_SERVICE: Final = "service"
ACTION_TYPE_SCENE: Final = "scene"

# Operators
OPERATORS: Final = {
    ">": "greater_than",
    "<": "less_than",
    ">=": "greater_equal",
    "<=": "less_equal",
    "==": "equal",
    "!=": "not_equal",
}

# Default values
DEFAULT_NAME: Final = "Custom Template Light"
DEFAULT_MIN_TEMPERATURE: Final = 2500  # 2500K
DEFAULT_MAX_TEMPERATURE: Final = 6500  # 6500K
DEFAULT_SUPPORTS_TRANSITION: Final = True
DEFAULT_ICON: Final = "mdi:lightbulb"

# Template patterns
LEVEL_TEMPLATE: Final = "{{{{ states('{entity}')|int(0) }}}}"
# STATE_TEMPLATE uses states() for primary state, state_attr() for actual attributes
STATE_TEMPLATE: Final = (
    "{{{{ states('{entity}')|int(0) {operator} {threshold} }}}}"
)
STATE_ATTR_TEMPLATE: Final = (
    "{{{{ state_attr('{entity}', '{attribute}')|int(0) {operator} {threshold} }}}}"
)
TEMPERATURE_TEMPLATE: Final = "{{{{ states('{entity}')|int(0) }}}}"
AVAILABILITY_TEMPLATE: Final = "{{{{ is_state('{entity}', 'on') }}}}"

# Error messages
ERROR_INVALID_ENTITY: Final = "invalid_entity"
ERROR_INVALID_ATTRIBUTE: Final = "invalid_attribute"
ERROR_INVALID_TEMPLATE: Final = "invalid_template"
ERROR_INVALID_ACTION: Final = "invalid_action"
ERROR_MISSING_PARAMETER: Final = "missing_parameter"

# Common service parameters
COMMON_LIGHT_PARAMETERS: Final = {
    "entity_id": "Entity ID",
    "brightness": "Brightness",
    "brightness_pct": "Brightness %",
    "color_temp": "Color Temperature",
    "kelvin": "Kelvin",
    "rgb_color": "RGB Color",
    "xy_color": "XY Color",
    "hs_color": "HS Color",
    "color_name": "Color Name",
    "white": "White",
    "profile": "Profile",
    "flash": "Flash",
    "effect": "Effect",
    "transition": "Transition",
}
