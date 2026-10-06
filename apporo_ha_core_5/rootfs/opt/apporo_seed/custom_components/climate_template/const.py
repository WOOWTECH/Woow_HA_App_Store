"""Constants for the Climate Template integration."""

from homeassistant.const import Platform

DOMAIN = "climate_template"
PLATFORMS = [Platform.CLIMATE]

# Config flow configuration keys
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_HEATER = "heater"
CONF_COOLER = "cooler"
CONF_AC_MODE = "ac_mode"

# Temperature settings
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TEMP_STEP = "temp_step"
CONF_PRECISION = "precision"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"

# Mode lists
CONF_HVAC_MODES = "hvac_modes"
CONF_FAN_MODES = "fan_modes"
CONF_PRESET_MODES = "preset_modes"
CONF_SWING_MODES = "swing_modes"
CONF_SWING_HORIZONTAL_MODES = "swing_horizontal_modes"

# Entity selectors for TX/RX targets
CONF_HVAC_MODE_ENTITY = "hvac_mode_entity"
CONF_FAN_MODE_ENTITY = "fan_mode_entity"
CONF_PRESET_MODE_ENTITY = "preset_mode_entity"
CONF_SWING_MODE_ENTITY = "swing_mode_entity"
CONF_SWING_HORIZONTAL_MODE_ENTITY = "swing_horizontal_mode_entity"
CONF_HUMIDITY_ENTITY = "humidity_entity"
CONF_TARGET_TEMPERATURE_ENTITY = "target_temperature_entity"

# Action script configuration keys
CONF_SET_TEMPERATURE_ACTION = "set_temperature"
CONF_SET_HVAC_MODE_ACTION = "set_hvac_mode"
CONF_SET_FAN_MODE_ACTION = "set_fan_mode"
CONF_SET_PRESET_MODE_ACTION = "set_preset_mode"
CONF_SET_SWING_MODE_ACTION = "set_swing_mode"
CONF_SET_SWING_HORIZONTAL_MODE_ACTION = "set_swing_horizontal_mode"
CONF_SET_HUMIDITY_ACTION = "set_humidity"

# Default values
DEFAULT_NAME = "Template Climate"
DEFAULT_MIN_TEMP = 7.0
DEFAULT_MAX_TEMP = 35.0
DEFAULT_TEMP_STEP = 0.5
DEFAULT_TOLERANCE = 0.3
