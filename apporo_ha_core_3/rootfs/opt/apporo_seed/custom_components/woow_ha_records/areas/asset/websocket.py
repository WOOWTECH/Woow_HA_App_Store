"""WebSocket API for household asset management in Home Assistant.

This module exposes seven WebSocket commands that allow the HA frontend
(or any WebSocket client) to perform full CRUD operations on household
assets and asset categories.

Commands
--------
ha_asset_record/list
    List every asset and category stored by the integration.
    Parameters: (none)
    Permission: any authenticated user
    Returns: ``{categories: [...], assets: [{id, name, brand, category_id,
              value, purchase_at, warranty_until, manual_md, maintenance_md,
              created_at, updated_at}, ...]}``

ha_asset_record/create
    Create a new asset and its associated HA entities.
    Parameters:
        name             (str, required, max 255, whitespace-trimmed)
        brand            (str, optional, max 255)
        category_id      (str, optional, must name an existing category
                          or be empty)
        value            (float, optional)
        purchase_at      (str, optional, ISO 8601 datetime)
        warranty_until   (str, optional, ISO 8601 datetime)
        manual_md        (str, optional, max 65535)
        maintenance_md   (str, optional, max 65535)
    Permission: admin only
    Returns: ``{asset: {id, name, brand, ...}}``

ha_asset_record/update
    Update one or more fields on an existing asset.
    Parameters:
        asset_id         (str, required, must match ``^asset_[a-f0-9]+$``)
        name             (str, optional, max 255, cannot be empty)
        brand            (str, optional, max 255)
        category_id      (str, optional, must name an existing category
                          or be empty)
        value            (float, optional)
        purchase_at      (str, optional, ISO 8601 datetime)
        warranty_until   (str, optional, ISO 8601 datetime)
        manual_md        (str, optional, max 65535)
        maintenance_md   (str, optional, max 65535)
    Permission: admin only
    Returns: ``{asset: {...updated}}``

ha_asset_record/delete
    Delete an asset and all of its associated entities.
    Parameters:
        asset_id         (str, required, must match ``^asset_[a-f0-9]+$``)
    Permission: admin only
    Returns: ``{success: true}``

ha_asset_record/create_category
    Create a new asset category.
    Parameters:
        name             (str, required, max 100)
    Permission: admin only
    Returns: ``{category: {id, name, created_at}}``

ha_asset_record/update_category
    Rename an existing category.
    Parameters:
        category_id      (str, required)
        name             (str, required, max 100)
    Permission: admin only
    Returns: ``{category: {id, name, created_at}}``

ha_asset_record/delete_category
    Delete a category, cascade-deleting all assets in it. The cascade is
    opt-in: a category that still holds assets is refused unless ``force``
    is set, and nothing is deleted.
    Parameters:
        category_id      (str, required)
        force            (bool, optional, default false)
    Permission: admin only
    Returns: ``{success: true}``

Permission model
----------------
* ``ha_asset_record/list`` is available to every authenticated user.
* All other commands require admin privileges
  (``@websocket_api.require_admin``).

Error codes
-----------
* ``not_found``       -- integration not configured, or the requested
                         asset/category does not exist.
* ``invalid_input``   -- a required field is empty (e.g. blank name),
                         or a duplicate category name.
* ``invalid_format``  -- a datetime string could not be parsed as
                         ISO 8601.
* ``not_empty``       -- the category still holds assets and ``force``
                         was not set; nothing was deleted.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from ...runtime import get_data
from .const import (
    FIELD_BRAND,
    FIELD_CATEGORY_ID,
    FIELD_MAINTENANCE_MD,
    FIELD_MANUAL_MD,
    FIELD_NAME,
    FIELD_PURCHASE_AT,
    FIELD_VALUE,
    FIELD_WARRANTY_UNTIL,
    MAX_CATEGORY_NAME_LENGTH,
)
from .coordinator import AssetCoordinator

_LOGGER = logging.getLogger(__name__)

# [L-13] Regex pattern for asset_id validation.
# Asset IDs are generated as "asset_" + uuid4().hex (32 hex chars).
ASSET_ID_PATTERN = r"^asset_[a-f0-9]+$"
CATEGORY_ID_PATTERN = r"^cat_[a-f0-9]+$"


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse a datetime string using HA's dt_util.

    [H-10] Uses dt_util.parse_datetime() instead of datetime.fromisoformat().
    Returns the parsed datetime (timezone-aware UTC) or None if the value is
    empty/None.  Raises ValueError if the string is non-empty but unparseable
    so the caller can send a proper error to the client ([H-09]).
    """
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid datetime format: {value!r}")
    # Ensure timezone-aware UTC
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_util.UTC)
    return dt_util.as_utc(parsed)


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register websocket commands."""
    websocket_api.async_register_command(hass, ws_list_assets)
    websocket_api.async_register_command(hass, ws_create_asset)
    websocket_api.async_register_command(hass, ws_update_asset)
    websocket_api.async_register_command(hass, ws_delete_asset)
    websocket_api.async_register_command(hass, ws_create_category)
    websocket_api.async_register_command(hass, ws_update_category)
    websocket_api.async_register_command(hass, ws_delete_category)


def _get_coordinator_from_hass(hass: HomeAssistant) -> AssetCoordinator | None:
    """Get the coordinator from hass.data.

    """
    return get_data(hass).asset


# ---------------------------------------------------------------------------
# Asset commands
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/asset/list",
    }
)
@websocket_api.async_response
async def ws_list_assets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return every category and asset currently managed by the integration."""
    coordinator = _get_coordinator_from_hass(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Integration not configured")
        return

    categories = [cat.to_dict() for cat in coordinator.categories]
    assets = [asset.to_dict() for asset in coordinator.assets.values()]
    connection.send_result(msg["id"], {"categories": categories, "assets": assets})


# [L-12] Write commands require admin access.
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/asset/create",
        # [M-11] String length validation
        vol.Required("name"): vol.All(str, vol.Length(max=255)),
        vol.Optional("brand"): vol.All(str, vol.Length(max=255)),
        vol.Optional("category_id"): str,
        vol.Optional("value"): vol.Coerce(float),
        vol.Optional("purchase_at"): vol.Any(str, None),
        vol.Optional("warranty_until"): vol.Any(str, None),
        vol.Optional("manual_md"): vol.All(str, vol.Length(max=65535)),
        vol.Optional("maintenance_md"): vol.All(str, vol.Length(max=65535)),
    }
)
@websocket_api.async_response
async def ws_create_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a new household asset with associated HA entities."""
    coordinator = _get_coordinator_from_hass(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Integration not configured")
        return

    # Validate name
    name = msg["name"].strip() if msg["name"] else ""
    if not name:
        connection.send_error(msg["id"], "invalid_input", "Asset name is required")
        return

    # A non-empty category_id must name a Category that exists; the empty
    # string stays valid as "uncategorised". Issue #68.
    category_id = msg.get("category_id", "")
    if category_id and coordinator.get_category(category_id) is None:
        connection.send_error(
            msg["id"], "not_found", f"Category {category_id} not found"
        )
        return

    # [H-09] Parse datetime fields with error responses for invalid values
    purchase_at: datetime | None = None
    if "purchase_at" in msg and msg["purchase_at"]:
        try:
            purchase_at = _parse_datetime(msg["purchase_at"])
        except ValueError:
            connection.send_error(
                msg["id"],
                "invalid_format",
                f"Invalid purchase_at datetime: {msg['purchase_at']!r}",
            )
            return

    warranty_until: datetime | None = None
    if "warranty_until" in msg and msg["warranty_until"]:
        try:
            warranty_until = _parse_datetime(msg["warranty_until"])
        except ValueError:
            connection.send_error(
                msg["id"],
                "invalid_format",
                f"Invalid warranty_until datetime: {msg['warranty_until']!r}",
            )
            return

    # [H-11] Use async_create_asset_full() for single save + single notify
    asset = await coordinator.async_create_asset_full(
        name,
        brand=msg.get("brand", ""),
        category_id=category_id,
        value=msg.get("value", 0),
        purchase_at=purchase_at,
        warranty_until=warranty_until,
        manual_md=msg.get("manual_md", ""),
        maintenance_md=msg.get("maintenance_md", ""),
    )

    connection.send_result(msg["id"], {"asset": asset.to_dict()})


# [L-12] Write commands require admin access.
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/asset/update",
        # [L-13] Validate asset_id format
        vol.Required("asset_id"): vol.All(str, vol.Match(ASSET_ID_PATTERN)),
        # [M-11] String length validation
        vol.Optional("name"): vol.All(str, vol.Length(max=255)),
        vol.Optional("brand"): vol.All(str, vol.Length(max=255)),
        vol.Optional("category_id"): str,
        vol.Optional("value"): vol.Coerce(float),
        vol.Optional("purchase_at"): vol.Any(str, None),
        vol.Optional("warranty_until"): vol.Any(str, None),
        vol.Optional("manual_md"): vol.All(str, vol.Length(max=65535)),
        vol.Optional("maintenance_md"): vol.All(str, vol.Length(max=65535)),
    }
)
@websocket_api.async_response
async def ws_update_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update one or more fields on an existing asset."""
    coordinator = _get_coordinator_from_hass(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Integration not configured")
        return

    asset_id = msg["asset_id"]
    asset = coordinator.get_asset(asset_id)
    if asset is None:
        connection.send_error(msg["id"], "not_found", f"Asset {asset_id} not found")
        return

    # The handler writes field by field as it walks the message, so the
    # Category is checked before the first write — a refusal must leave every
    # field of the Asset as it was, not just category_id. The empty string
    # stays valid as "uncategorised". Issue #68.
    if "category_id" in msg:
        category_id = msg["category_id"]
        if category_id and coordinator.get_category(category_id) is None:
            connection.send_error(
                msg["id"], "not_found", f"Category {category_id} not found"
            )
            return

    # Update name if provided
    if "name" in msg:
        name = msg["name"].strip() if msg["name"] else ""
        if not name:
            connection.send_error(
                msg["id"], "invalid_input", "Asset name cannot be empty"
            )
            return
        await coordinator.async_update_asset(asset_id, FIELD_NAME, name)

    # Update other fields
    if "brand" in msg:
        await coordinator.async_update_asset(asset_id, FIELD_BRAND, msg["brand"])
    if "category_id" in msg:
        await coordinator.async_update_asset(
            asset_id, FIELD_CATEGORY_ID, msg["category_id"]
        )
    if "value" in msg:
        await coordinator.async_update_asset(asset_id, FIELD_VALUE, msg["value"])

    # [H-09] Parse datetime fields with error responses for invalid values
    if "purchase_at" in msg:
        try:
            purchase_at = _parse_datetime(msg["purchase_at"])
        except ValueError:
            connection.send_error(
                msg["id"],
                "invalid_format",
                f"Invalid purchase_at datetime: {msg['purchase_at']!r}",
            )
            return
        await coordinator.async_update_asset(asset_id, FIELD_PURCHASE_AT, purchase_at)

    if "warranty_until" in msg:
        try:
            warranty_until = _parse_datetime(msg["warranty_until"])
        except ValueError:
            connection.send_error(
                msg["id"],
                "invalid_format",
                f"Invalid warranty_until datetime: {msg['warranty_until']!r}",
            )
            return
        await coordinator.async_update_asset(
            asset_id, FIELD_WARRANTY_UNTIL, warranty_until
        )

    if "manual_md" in msg:
        await coordinator.async_update_asset(
            asset_id, FIELD_MANUAL_MD, msg["manual_md"]
        )
    if "maintenance_md" in msg:
        await coordinator.async_update_asset(
            asset_id, FIELD_MAINTENANCE_MD, msg["maintenance_md"]
        )

    # [M-12] Return updated asset dict (consistent with ws_create_asset)
    updated_asset = coordinator.get_asset(asset_id)
    connection.send_result(
        msg["id"],
        {"asset": updated_asset.to_dict() if updated_asset else None},
    )


# [L-12] Write commands require admin access.
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/asset/delete",
        # [L-13] Validate asset_id format
        vol.Required("asset_id"): vol.All(str, vol.Match(ASSET_ID_PATTERN)),
    }
)
@websocket_api.async_response
async def ws_delete_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete an asset and remove all of its associated HA entities."""
    coordinator = _get_coordinator_from_hass(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Integration not configured")
        return

    success = await coordinator.async_delete_asset(msg["asset_id"])
    if not success:
        connection.send_error(
            msg["id"], "not_found", f"Asset {msg['asset_id']} not found"
        )
        return

    connection.send_result(msg["id"], {"success": True})


# ---------------------------------------------------------------------------
# Category commands
# ---------------------------------------------------------------------------


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/asset/create_category",
        vol.Required("name"): vol.All(str, vol.Length(max=MAX_CATEGORY_NAME_LENGTH)),
    }
)
@websocket_api.async_response
async def ws_create_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a new asset category."""
    coordinator = _get_coordinator_from_hass(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Integration not configured")
        return

    try:
        category = await coordinator.async_create_category(msg["name"])
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))
        return

    connection.send_result(msg["id"], {"category": category.to_dict()})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/asset/update_category",
        vol.Required("category_id"): vol.All(
            str, vol.Match(CATEGORY_ID_PATTERN)
        ),
        vol.Required("name"): vol.All(str, vol.Length(max=MAX_CATEGORY_NAME_LENGTH)),
    }
)
@websocket_api.async_response
async def ws_update_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename an existing category."""
    coordinator = _get_coordinator_from_hass(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Integration not configured")
        return

    try:
        category = await coordinator.async_update_category(
            msg["category_id"], msg["name"]
        )
    except ValueError as exc:
        error_code = "not_found" if "not found" in str(exc) else "invalid_input"
        connection.send_error(msg["id"], error_code, str(exc))
        return

    connection.send_result(msg["id"], {"category": category.to_dict()})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/asset/delete_category",
        vol.Required("category_id"): vol.All(
            str, vol.Match(CATEGORY_ID_PATTERN)
        ),
        vol.Optional("force"): bool,
    }
)
@websocket_api.async_response
async def ws_delete_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a category, cascade-deleting its assets only if asked to.

    ``force`` confirms that the assets in the category may be destroyed with
    it; without it a category that still holds assets is refused with
    ``not_empty`` and nothing is deleted. The panel names the category and
    counts its assets before asking, so it passes ``force``. Issue #49.

    ``handle_delete_category`` in services.py guards identically and words it
    the same way; the wording is the part that must not drift.
    """
    coordinator = _get_coordinator_from_hass(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Integration not configured")
        return

    category_id = msg["category_id"]

    def _send_not_found() -> None:
        connection.send_error(
            msg["id"], "not_found", f"Category {category_id} not found"
        )

    # Was one call to ``async_delete_category``, whose ``False`` meant "no
    # such category". The guard has to run before the cascade, so the lookup
    # moves up here — and the ``False`` below now says nothing the lookup has
    # not already said. It stays because it is the coordinator's only failure
    # signal, and a second reason to return it must not read as success.
    category = coordinator.get_category(category_id)
    if category is None:
        _send_not_found()
        return

    assets = coordinator.get_assets_by_category(category_id)
    if assets and not msg.get("force", False):
        connection.send_error(
            msg["id"],
            "not_empty",
            f"Category '{category.name}' still holds {len(assets)} asset(s), "
            f"and deleting it deletes them too. Pass force: true to confirm.",
        )
        return

    if not await coordinator.async_delete_category(category_id):
        _send_not_found()
        return

    connection.send_result(msg["id"], {"success": True})
