"""Home Assistant service handlers for ha_asset_record.

Exposes 10 services that mirror (and extend) the existing WebSocket API,
allowing automations, scripts, and AI agents to interact with asset records
via ``hass.services.async_call()``.

Query services (list_assets, get_asset, list_categories, export_csv) use
``SupportsResponse.ONLY`` — callers must request a response.

Write services use ``SupportsResponse.OPTIONAL`` — callers may
optionally receive a response dict.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FIELD_BRAND,
    FIELD_CATEGORY_ID,
    FIELD_MAINTENANCE_MD,
    FIELD_MANUAL_MD,
    FIELD_NAME,
    FIELD_PURCHASE_AT,
    FIELD_VALUE,
    FIELD_WARRANTY_UNTIL,
)
from .coordinator import AssetCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_coordinator(hass: HomeAssistant) -> AssetCoordinator:
    """Retrieve the singleton AssetCoordinator from hass.data."""
    coordinator = hass.data.get(DOMAIN)
    if coordinator is None:
        raise ServiceValidationError(
            "Asset Record integration is not configured",
            translation_domain=DOMAIN,
            translation_key="not_configured",
        )
    return coordinator


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string.

    Returns None if value is empty/None.
    Raises ServiceValidationError if the string is non-empty but unparseable.
    """
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ServiceValidationError(
            f"Invalid datetime format: {value!r}",
            translation_domain=DOMAIN,
            translation_key="invalid_datetime",
            translation_placeholders={"value": str(value)},
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_util.UTC)
    return dt_util.as_utc(parsed)


# ---------------------------------------------------------------------------
# Query services — SupportsResponse.ONLY
# ---------------------------------------------------------------------------


async def handle_list_assets(call: ServiceCall) -> ServiceResponse:
    """List every asset and category."""
    coordinator = _get_coordinator(call.hass)
    categories = [cat.to_dict() for cat in coordinator.categories]
    assets = [asset.to_dict() for asset in coordinator.assets.values()]
    return {"categories": categories, "assets": assets}


async def handle_get_asset(call: ServiceCall) -> ServiceResponse:
    """Get a single asset by ID."""
    coordinator = _get_coordinator(call.hass)
    asset_id = call.data["asset_id"]
    asset = coordinator.get_asset(asset_id)
    if asset is None:
        raise ServiceValidationError(
            f"Asset '{asset_id}' not found",
            translation_domain=DOMAIN,
            translation_key="asset_not_found",
            translation_placeholders={"asset_id": asset_id},
        )
    return {"asset": asset.to_dict()}


async def handle_list_categories(call: ServiceCall) -> ServiceResponse:
    """List all asset categories."""
    coordinator = _get_coordinator(call.hass)
    return {"categories": [cat.to_dict() for cat in coordinator.categories]}


async def handle_export_csv(call: ServiceCall) -> ServiceResponse:
    """Export all assets as CSV text."""
    coordinator = _get_coordinator(call.hass)

    # Build category name lookup
    cat_map = {cat.id: cat.name for cat in coordinator.categories}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "brand", "category", "value",
        "purchase_at", "warranty_until",
        "manual_md", "maintenance_md",
        "created_at", "updated_at",
    ])

    for asset in sorted(coordinator.assets.values(), key=lambda a: a.name):
        d = asset.to_dict()
        writer.writerow([
            d["id"],
            d["name"],
            d["brand"],
            cat_map.get(d["category_id"], ""),
            d["value"],
            d["purchase_at"] or "",
            d["warranty_until"] or "",
            d["manual_md"],
            d["maintenance_md"],
            d["created_at"],
            d["updated_at"],
        ])

    return {
        "csv_content": output.getvalue(),
        "asset_count": len(coordinator.assets),
    }


# ---------------------------------------------------------------------------
# Asset CRUD — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_create_asset(call: ServiceCall) -> ServiceResponse:
    """Create a new asset with all fields."""
    coordinator = _get_coordinator(call.hass)
    name = call.data.get("name", "").strip()
    if not name:
        raise ServiceValidationError(
            "Asset name is required",
            translation_domain=DOMAIN,
            translation_key="name_required",
        )

    purchase_at = _parse_datetime(call.data.get("purchase_at"))
    warranty_until = _parse_datetime(call.data.get("warranty_until"))

    asset = await coordinator.async_create_asset_full(
        name,
        brand=call.data.get("brand", ""),
        category_id=call.data.get("category_id", ""),
        value=call.data.get("value", 0),
        purchase_at=purchase_at,
        warranty_until=warranty_until,
        manual_md=call.data.get("manual_md", ""),
        maintenance_md=call.data.get("maintenance_md", ""),
    )
    return {"success": True, "asset": asset.to_dict()}


async def handle_update_asset(call: ServiceCall) -> ServiceResponse:
    """Update one or more fields on an existing asset."""
    coordinator = _get_coordinator(call.hass)
    asset_id = call.data["asset_id"]
    asset = coordinator.get_asset(asset_id)
    if asset is None:
        raise ServiceValidationError(
            f"Asset '{asset_id}' not found",
            translation_domain=DOMAIN,
            translation_key="asset_not_found",
            translation_placeholders={"asset_id": asset_id},
        )

    # Validate name if provided
    if "name" in call.data:
        name = call.data["name"].strip() if call.data["name"] else ""
        if not name:
            raise ServiceValidationError(
                "Asset name cannot be empty",
                translation_domain=DOMAIN,
                translation_key="name_required",
            )
        await coordinator.async_update_asset(asset_id, FIELD_NAME, name)

    # Simple string fields
    for field_key, const in [
        ("brand", FIELD_BRAND),
        ("category_id", FIELD_CATEGORY_ID),
        ("manual_md", FIELD_MANUAL_MD),
        ("maintenance_md", FIELD_MAINTENANCE_MD),
    ]:
        if field_key in call.data:
            await coordinator.async_update_asset(
                asset_id, const, call.data[field_key]
            )

    # Numeric field
    if "value" in call.data:
        await coordinator.async_update_asset(
            asset_id, FIELD_VALUE, call.data["value"]
        )

    # Datetime fields
    for field_key, const in [
        ("purchase_at", FIELD_PURCHASE_AT),
        ("warranty_until", FIELD_WARRANTY_UNTIL),
    ]:
        if field_key in call.data:
            dt_val = _parse_datetime(call.data[field_key])
            await coordinator.async_update_asset(asset_id, const, dt_val)

    updated = coordinator.get_asset(asset_id)
    return {
        "success": True,
        "asset": updated.to_dict() if updated else None,
    }


async def handle_delete_asset(call: ServiceCall) -> ServiceResponse:
    """Delete an asset and its associated entities."""
    coordinator = _get_coordinator(call.hass)
    asset_id = call.data["asset_id"]
    success = await coordinator.async_delete_asset(asset_id)
    if not success:
        raise ServiceValidationError(
            f"Asset '{asset_id}' not found",
            translation_domain=DOMAIN,
            translation_key="asset_not_found",
            translation_placeholders={"asset_id": asset_id},
        )
    return {"success": True}


# ---------------------------------------------------------------------------
# Category CRUD — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_create_category(call: ServiceCall) -> ServiceResponse:
    """Create a new asset category."""
    coordinator = _get_coordinator(call.hass)
    name = call.data.get("name", "").strip()
    if not name:
        raise ServiceValidationError(
            "Category name is required",
            translation_domain=DOMAIN,
            translation_key="category_name_required",
        )
    try:
        category = await coordinator.async_create_category(name)
    except ValueError as exc:
        raise ServiceValidationError(
            str(exc),
            translation_domain=DOMAIN,
            translation_key="category_error",
        ) from exc
    return {"success": True, "category": category.to_dict()}


async def handle_update_category(call: ServiceCall) -> ServiceResponse:
    """Rename an existing category."""
    coordinator = _get_coordinator(call.hass)
    category_id = call.data["category_id"]
    name = call.data.get("name", "").strip()
    if not name:
        raise ServiceValidationError(
            "Category name is required",
            translation_domain=DOMAIN,
            translation_key="category_name_required",
        )
    try:
        category = await coordinator.async_update_category(category_id, name)
    except ValueError as exc:
        raise ServiceValidationError(
            str(exc),
            translation_domain=DOMAIN,
            translation_key="category_error",
        ) from exc
    return {"success": True, "category": category.to_dict()}


async def handle_delete_category(call: ServiceCall) -> ServiceResponse:
    """Delete a category and cascade-delete all assets in it."""
    coordinator = _get_coordinator(call.hass)
    category_id = call.data["category_id"]
    success = await coordinator.async_delete_category(category_id)
    if not success:
        raise ServiceValidationError(
            f"Category '{category_id}' not found",
            translation_domain=DOMAIN,
            translation_key="category_not_found",
            translation_placeholders={"category_id": category_id},
        )
    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_SERVICE_HANDLERS = {
    # Query — ONLY
    "list_assets": (handle_list_assets, SupportsResponse.ONLY),
    "get_asset": (handle_get_asset, SupportsResponse.ONLY),
    "list_categories": (handle_list_categories, SupportsResponse.ONLY),
    "export_csv": (handle_export_csv, SupportsResponse.ONLY),
    # Asset CRUD — OPTIONAL
    "create_asset": (handle_create_asset, SupportsResponse.OPTIONAL),
    "update_asset": (handle_update_asset, SupportsResponse.OPTIONAL),
    "delete_asset": (handle_delete_asset, SupportsResponse.OPTIONAL),
    # Category CRUD — OPTIONAL
    "create_category": (handle_create_category, SupportsResponse.OPTIONAL),
    "update_category": (handle_update_category, SupportsResponse.OPTIONAL),
    "delete_category": (handle_delete_category, SupportsResponse.OPTIONAL),
}


def async_register_services(hass: HomeAssistant) -> None:
    """Register all ha_asset_record services."""
    for name, (handler, response_type) in _SERVICE_HANDLERS.items():
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            supports_response=response_type,
        )
    _LOGGER.debug("Registered %d services for %s", len(_SERVICE_HANDLERS), DOMAIN)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all ha_asset_record services."""
    for name in _SERVICE_HANDLERS:
        hass.services.async_remove(DOMAIN, name)
    _LOGGER.debug("Unregistered services for %s", DOMAIN)
