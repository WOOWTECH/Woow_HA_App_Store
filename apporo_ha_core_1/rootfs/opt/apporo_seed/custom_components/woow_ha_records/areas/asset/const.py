"""Constants for Ha Asset Record integration."""

from __future__ import annotations

from typing import Final

from ...const import AREA_ASSET, DOMAIN, STORAGE_VERSION, storage_key

__all__ = ["DOMAIN", "AREA", "STORAGE_KEY", "STORAGE_VERSION"]

AREA: Final = AREA_ASSET
STORAGE_KEY: Final = storage_key(AREA)

# Asset fields
FIELD_NAME: Final = "name"
FIELD_PURCHASE_AT: Final = "purchase_at"
FIELD_WARRANTY_UNTIL: Final = "warranty_until"
FIELD_BRAND: Final = "brand"
FIELD_CATEGORY: Final = "category"
FIELD_CATEGORY_ID: Final = "category_id"
FIELD_MANUAL_MD: Final = "manual_md"
FIELD_MAINTENANCE_MD: Final = "maintenance_md"
FIELD_VALUE: Final = "value"

# Number entity limits
VALUE_MIN: Final = 0
VALUE_MAX: Final = 99999999
# [L-07] Use 0.01 step to allow decimal values (e.g. 1299.99)
VALUE_STEP: Final = 0.01

# [L-05] Maximum length for text entity *state* value.
# HA core TextEntity hard-caps state at 255 characters independently;
# this constant controls the truncation we apply before setting state,
# with the full content stored in the raw_content attribute.
TEXT_MAX_LENGTH: Final = 255

# Attribute keys
ATTR_RAW_CONTENT: Final = "raw_content"
ATTR_ASSET_ID: Final = "asset_id"

# Category constants
MAX_CATEGORY_NAME_LENGTH: Final = 100
CATEGORY_ID_PREFIX: Final = "cat_"

# Options flow actions
ACTION_CREATE_ASSET: Final = "create_asset"
ACTION_DELETE_ASSET: Final = "delete_asset"
