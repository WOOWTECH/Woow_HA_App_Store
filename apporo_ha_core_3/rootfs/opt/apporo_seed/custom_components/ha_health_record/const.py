"""Constants for Ha Health Record integration."""
from typing import Final

DOMAIN: Final = "ha_health_record"

# Storage
STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1

# Config keys
CONF_MEMBER_NAME = "member_name"
CONF_MEMBER_ID = "member_id"
CONF_RECORD_SETS = "record_sets"

# Record set keys
CONF_RECORD_TYPE = "record_type"
CONF_RECORD_NAME = "record_name"
CONF_RECORD_UNIT = "record_unit"

# Event names
EVENT_RECORD_LOGGED = f"{DOMAIN}_record_logged"

# Default record types (merged from activity + growth)
DEFAULT_RECORD_TYPES = [
    {"id": "feeding", "name": "Feeding", "unit": "ml"},
    {"id": "sleep", "name": "Sleep", "unit": "min"},
    {"id": "weight", "name": "Weight", "unit": "kg"},
    {"id": "height", "name": "Height", "unit": "cm"},
]

# Custom type identifier
CUSTOM_TYPE = "custom"
