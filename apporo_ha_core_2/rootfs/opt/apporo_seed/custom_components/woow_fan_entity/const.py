"""Constants for the WoowTech Fan Entity integration."""

from homeassistant.const import Platform

DOMAIN = "woow_fan_entity"
PLATFORMS = [Platform.FAN]

# Entity selector for on/off control
CONF_SWITCH_ENTITY = "switch_entity"

# Fan speed settings
CONF_SPEED_COUNT = "speed_count"
CONF_PERCENTAGE = "percentage"

# Mode lists
CONF_PRESET_MODES = "preset_modes"

# Entity selectors for TX/RX targets
CONF_PERCENTAGE_ENTITY = "percentage_entity"
CONF_PRESET_MODE_ENTITY = "preset_mode_entity"
CONF_OSCILLATING_ENTITY = "oscillating_entity"
CONF_DIRECTION_ENTITY = "direction_entity"

# Action script configuration keys
CONF_SET_PERCENTAGE_ACTION = "set_percentage"
CONF_SET_PRESET_MODE_ACTION = "set_preset_mode"
CONF_SET_OSCILLATING_ACTION = "set_oscillating"
CONF_SET_DIRECTION_ACTION = "set_direction"

# Receive Templates
CONF_PERCENTAGE_RECEIVE_TEMPLATE = "percentage_receive_template"
CONF_PRESET_MODE_RECEIVE_TEMPLATE = "preset_mode_receive_template"
CONF_DIRECTION_RECEIVE_TEMPLATE = "direction_receive_template"

# Linear Interpolation (percentage only)
CONF_PERCENTAGE_INPUT_MIN = "percentage_input_min"
CONF_PERCENTAGE_INPUT_MAX = "percentage_input_max"
CONF_PERCENTAGE_OUTPUT_MIN = "percentage_output_min"
CONF_PERCENTAGE_OUTPUT_MAX = "percentage_output_max"

# Feature flags (user-configurable)
CONF_ENABLE_OSCILLATION = "enable_oscillation"
CONF_ENABLE_DIRECTION = "enable_direction"

# Default values
DEFAULT_NAME = "Fan Template"
DEFAULT_SPEED_COUNT = 3

# Direction constants
DIRECTION_FORWARD = "forward"
DIRECTION_REVERSE = "reverse"
