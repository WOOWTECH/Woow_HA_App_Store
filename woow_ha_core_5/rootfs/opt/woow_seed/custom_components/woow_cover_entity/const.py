"""Constants for the WoowTech Cover Entity integration."""

from homeassistant.const import Platform

DOMAIN = "woow_cover_entity"
PLATFORMS = [Platform.COVER]

# Basic settings
CONF_DEVICE_CLASS = "device_class"
CONF_ENABLE_TILT = "enable_tilt"

# Entity selectors for TX/RX targets
CONF_POSITION_ENTITY = "position_entity"
CONF_TILT_POSITION_ENTITY = "tilt_position_entity"

# Action script configuration keys
CONF_SET_POSITION_ACTION = "set_position"
CONF_SET_TILT_POSITION_ACTION = "set_tilt_position"
CONF_OPEN_COVER_ACTION = "open_cover"
CONF_CLOSE_COVER_ACTION = "close_cover"
CONF_STOP_COVER_ACTION = "stop_cover"
CONF_OPEN_TILT_ACTION = "open_tilt"
CONF_CLOSE_TILT_ACTION = "close_tilt"
CONF_STOP_TILT_ACTION = "stop_tilt"

# Time-based position estimation
CONF_OPEN_TIME = "open_time"
CONF_CLOSE_TIME = "close_time"
CONF_TILT_OPEN_TIME = "tilt_open_time"
CONF_TILT_CLOSE_TIME = "tilt_close_time"

# Default values
DEFAULT_NAME = "Cover Template"
