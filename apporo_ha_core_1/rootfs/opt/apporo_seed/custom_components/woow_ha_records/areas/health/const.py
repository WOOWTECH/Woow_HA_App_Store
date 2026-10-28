"""Constants for the health Area."""

from typing import Final

from ...const import AREA_HEALTH, DOMAIN, STORAGE_VERSION, event_type, storage_key

__all__ = ["DOMAIN", "AREA", "STORAGE_KEY", "STORAGE_VERSION"]

AREA: Final = AREA_HEALTH
STORAGE_KEY: Final = storage_key(AREA)

# Config keys
CONF_MEMBER_NAME = "member_name"
CONF_MEMBER_ID = "member_id"
CONF_RECORD_SETS = "record_sets"

# Record set keys
CONF_RECORD_TYPE = "record_type"
CONF_RECORD_NAME = "record_name"
CONF_RECORD_UNIT = "record_unit"

# Event names
EVENT_RECORD_LOGGED = event_type(AREA, "record_logged")

# Default record types (merged from activity + growth)
DEFAULT_RECORD_TYPES = [
    {"id": "feeding", "name": "Feeding", "unit": "ml"},
    {"id": "sleep", "name": "Sleep", "unit": "min"},
    {"id": "weight", "name": "Weight", "unit": "kg"},
    {"id": "height", "name": "Height", "unit": "cm"},
]

# Custom type identifier
CUSTOM_TYPE = "custom"
