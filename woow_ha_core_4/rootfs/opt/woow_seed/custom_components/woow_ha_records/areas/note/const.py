"""Constants for the note Area."""

from typing import Final

from ...const import AREA_NOTE, DOMAIN, STORAGE_VERSION, storage_key

__all__ = ["DOMAIN", "AREA", "STORAGE_KEY", "STORAGE_VERSION"]

AREA: Final = AREA_NOTE
STORAGE_KEY: Final = storage_key(AREA)

# Attributes
ATTR_RAW_CONTENT: Final = "raw_content"
ATTR_TITLE: Final = "title"
ATTR_CATEGORY: Final = "category"
ATTR_CREATED_AT: Final = "created_at"
ATTR_UPDATED_AT: Final = "updated_at"
ATTR_NOTE_ID: Final = "note_id"
ATTR_CATEGORY_ID: Final = "category_id"

# Options Flow Actions
ACTION_CREATE_CATEGORY: Final = "create_category"
ACTION_CREATE_NOTE: Final = "create_note"
ACTION_DELETE_NOTE: Final = "delete_note"
ACTION_DELETE_CATEGORY: Final = "delete_category"

# Default values
DEFAULT_CONTENT: Final = ""
DEFAULT_PINNED: Final = False

# Input validation limits
MAX_CATEGORY_NAME_LENGTH: Final = 100
MAX_NOTE_TITLE_LENGTH: Final = 200
MAX_NOTE_CONTENT_LENGTH: Final = 100000  # 100KB

# Icon
ICON_PINNED: Final = "mdi:pin"
ICON_UNPINNED: Final = "mdi:pin-off"
ICON_NOTE: Final = "mdi:note-text"
