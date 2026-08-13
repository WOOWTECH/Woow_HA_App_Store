"""Constants for the WoowTech Somfy Cover integration.

This integration provides control for Somfy PoE motors using encrypted UDP communication.
The motors use AES-128-CBC encryption with zero-padding and communicate via JSON-RPC protocol.
"""
from typing import Final

# Integration domain
DOMAIN: Final = "woow_tech_somfy_cover"

# Configuration keys
CONF_NAME: Final = "name"
CONF_HOST: Final = "host"
CONF_TARGET_ID: Final = "target_id"
CONF_KEY: Final = "key"
CONF_PORT: Final = "port"

# Defaults
DEFAULT_PORT: Final = 55055
DEFAULT_TIMEOUT: Final = 5.0
DEFAULT_NAME: Final = "Somfy Cover"

# Update intervals
UPDATE_INTERVAL_NORMAL: Final = 30  # seconds - normal polling when motor is stopped
UPDATE_INTERVAL_FAST: Final = 2  # seconds - fast polling during movement

# API constants
API_PORT: Final = 55055  # UDP port for motor communication
AES_BLOCK_SIZE: Final = 16  # AES-128 block size in bytes
TARGET_ID_LENGTH: Final = 6  # Expected length of target ID
KEY_LENGTH: Final = 32  # Expected length of encryption key in hex characters

# API Methods (JSON-RPC)
METHOD_PING: Final = "status.ping"
METHOD_STATUS_INFO: Final = "status.info"
METHOD_STATUS_POSITION: Final = "status.position"
METHOD_MOVE_UP: Final = "move.up"
METHOD_MOVE_DOWN: Final = "move.down"
METHOD_MOVE_STOP: Final = "move.stop"
METHOD_MOVE_TO: Final = "move.to"

# Error codes from Somfy PoE Motor API documentation
ERROR_DATA_OUT_OF_RANGE: Final = 1  # Parameter value out of acceptable range
ERROR_UNKNOWN_MESSAGE: Final = 16  # Unrecognized JSON-RPC method
ERROR_MESSAGE_LENGTH: Final = 17  # Message exceeds maximum length
ERROR_FEATURE_NOT_SUPPORTED: Final = 37  # Feature not available on this motor
ERROR_DEVICE_LOCKED: Final = 32  # Motor is locked by another client
ERROR_END_LIMITS_NOT_SET: Final = 34  # End limits must be configured first
ERROR_THERMAL_PROTECTION: Final = 48  # Motor thermal protection activated
ERROR_OBSTACLE_DETECTION: Final = 49  # Obstacle detected during movement
ERROR_TARGET_OUT_OF_RANGE: Final = 36  # Target position outside valid range
ERROR_IN_MOTION: Final = 38  # Motor is currently moving
ERROR_WRONG_POSITION: Final = 33  # Position command invalid for current state
ERROR_NO_PRESET_POSITION: Final = 35  # Requested preset not configured
ERROR_END_LIMITS_SET: Final = 47  # End limits already configured
ERROR_LAST_PRESET_REACHED: Final = 40  # Already at the last preset position
ERROR_LOW_PRIORITY: Final = 42  # Command rejected due to low priority
ERROR_WINK_IN_PROGRESS: Final = 43  # Wink operation in progress
ERROR_DIAGNOSTIC_UNAVAILABLE: Final = 45  # Diagnostic data not available
ERROR_INCORRECT_PARAMS: Final = 50  # Invalid or missing parameters
ERROR_UNKNOWN: Final = 254  # Unknown error occurred
ERROR_BUSY: Final = 255  # Motor is busy processing another command
