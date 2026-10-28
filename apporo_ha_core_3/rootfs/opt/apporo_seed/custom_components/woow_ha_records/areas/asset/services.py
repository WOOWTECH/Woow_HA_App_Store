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

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from ...runtime import get_data
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
    """Return the asset Area's coordinator."""
    return get_data(hass).asset


def _parse_datetime(value: str | None, field: str) -> datetime | None:
    """Parse an ISO 8601 datetime string from the service field ``field``.

    Returns None if value is empty/None.
    Raises ServiceValidationError if the string is non-empty but unparseable.

    ``field`` names the service field the value came from. It is required
    because the ``invalid_datetime`` message interpolates it, and Home
    Assistant discards the whole formatted message — not just the one word —
    when a placeholder is missing.
    """
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ServiceValidationError(
            f"Invalid datetime for '{field}': {value!r}",
            translation_domain=DOMAIN,
            translation_key="asset.invalid_datetime",
            translation_placeholders={"field": field, "value": str(value)},
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_util.UTC)
    return dt_util.as_utc(parsed)


def _require_category(coordinator: AssetCoordinator, category_id: str) -> None:
    """Refuse a non-empty ``category_id`` that names no Category.

    The empty string passes: it is "uncategorised", a legitimate state, not a
    claim about any Category. A non-empty id that resolves to nothing would
    file the Asset where no listing and no export can find it, so it is
    refused before anything is written. Issue #68, mirroring what #43 did for
    the note Area.
    """
    if category_id and coordinator.get_category(category_id) is None:
        raise ServiceValidationError(
            f"Category '{category_id}' not found",
            translation_domain=DOMAIN,
            translation_key="asset.category_not_found",
            translation_placeholders={"category_id": category_id},
        )


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
            translation_key="asset.asset_not_found",
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
            translation_key="asset.name_required",
        )

    category_id = call.data.get("category_id", "")
    _require_category(coordinator, category_id)

    purchase_at = _parse_datetime(call.data.get("purchase_at"), "purchase_at")
    warranty_until = _parse_datetime(
        call.data.get("warranty_until"), "warranty_until"
    )

    asset = await coordinator.async_create_asset_full(
        name,
        brand=call.data.get("brand", ""),
        category_id=category_id,
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
            translation_key="asset.asset_not_found",
            translation_placeholders={"asset_id": asset_id},
        )

    # The handler writes field by field as it walks the call, so the Category
    # is checked before the first write — a refusal must leave every field of
    # the Asset as it was, not just ``category_id``. Issue #68.
    if "category_id" in call.data:
        _require_category(coordinator, call.data["category_id"])

    # Validate name if provided
    if "name" in call.data:
        name = call.data["name"].strip() if call.data["name"] else ""
        if not name:
            raise ServiceValidationError(
                "Asset name cannot be empty",
                translation_domain=DOMAIN,
                translation_key="asset.name_required",
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
            dt_val = _parse_datetime(call.data[field_key], field_key)
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
            translation_key="asset.asset_not_found",
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
            translation_key="asset.category_name_required",
        )
    try:
        category = await coordinator.async_create_category(name)
    except ValueError as exc:
        raise ServiceValidationError(
            str(exc),
            translation_domain=DOMAIN,
            translation_key="asset.category_error",
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
            translation_key="asset.category_name_required",
        )
    try:
        category = await coordinator.async_update_category(category_id, name)
    except ValueError as exc:
        raise ServiceValidationError(
            str(exc),
            translation_domain=DOMAIN,
            translation_key="asset.category_error",
        ) from exc
    return {"success": True, "category": category.to_dict()}


async def handle_delete_category(call: ServiceCall) -> ServiceResponse:
    """Delete a category, cascade-deleting its assets only if asked to.

    The cascade destroys an arbitrary number of Assets and there is no undo,
    so ``force`` is the opt-in. An Asset can be moved to another Category
    first, which is the escape route a Note lacks and the reason this ranked
    below #45 — but ``services.yaml`` points AI assistants straight at this
    surface either way. Issue #49.

    The panel already names the Category and counts its Assets before asking,
    so it passes ``force: true`` and nothing changes there.
    """
    coordinator = _get_coordinator(call.hass)
    category_id = call.data["category_id"]

    def _not_found() -> ServiceValidationError:
        return ServiceValidationError(
            f"Category '{category_id}' not found",
            translation_domain=DOMAIN,
            translation_key="asset.category_not_found",
            translation_placeholders={"category_id": category_id},
        )

    # Was one call to ``async_delete_category``, whose ``False`` meant "no
    # such category". The guard has to run before the cascade, so the lookup
    # moves up here — and the ``False`` below now says nothing the lookup has
    # not already said. It stays because it is the coordinator's only failure
    # signal, and a second reason to return it must not read as success.
    category = coordinator.get_category(category_id)
    if category is None:
        raise _not_found()

    # ``ws_delete_category`` guards identically and words it the same way;
    # the wording is the part that must not drift between the two surfaces.
    assets = coordinator.get_assets_by_category(category_id)
    if assets and not call.data.get("force", False):
        raise ServiceValidationError(
            f"Category '{category.name}' still holds {len(assets)} asset(s), "
            f"and deleting it deletes them too. Pass force: true to confirm.",
            translation_domain=DOMAIN,
            translation_key="asset.category_not_empty",
            translation_placeholders={
                "name": category.name,
                "asset_count": str(len(assets)),
            },
        )

    if not await coordinator.async_delete_category(category_id):
        raise _not_found()
    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# Field names, requiredness and types mirror this Area's WebSocket commands;
# ``services.yaml`` is the reference where no command covers the operation.
# What those commands also check and this deliberately does not is the value
# domain — ``vol.Length`` on the text fields, ``vol.Match`` on the ids.
# Rejecting a *value* the service accepts today is a different change from
# rejecting a *field* it should never have accepted, which is all issue #44
# asked for.
#
# No optional field carries a ``default=`` either. Handlers read absence with
# ``"field" in call.data`` and treat it as "leave unchanged", so a
# default would turn every omitted field into an explicit overwrite — on the
# update verbs that silently rewrites data the caller never mentioned.
#
# ``purchase_at`` and ``warranty_until`` accept None as well as a string:
# ``_parse_datetime`` reads either as "no date", and the WebSocket command
# allows the same.
SERVICE_HANDLERS = {
    # Query — ONLY
    "list_assets": (
        handle_list_assets,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    "get_asset": (
        handle_get_asset,
        SupportsResponse.ONLY,
        vol.Schema({vol.Required("asset_id"): cv.string}),
    ),
    "list_categories": (
        handle_list_categories,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    "export_csv": (
        handle_export_csv,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    # Asset CRUD — OPTIONAL
    "create_asset": (
        handle_create_asset,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Optional("brand"): cv.string,
                vol.Optional("category_id"): cv.string,
                vol.Optional("value"): vol.Coerce(float),
                vol.Optional("purchase_at"): vol.Any(cv.string, None),
                vol.Optional("warranty_until"): vol.Any(cv.string, None),
                vol.Optional("manual_md"): cv.string,
                vol.Optional("maintenance_md"): cv.string,
            }
        ),
    ),
    "update_asset": (
        handle_update_asset,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("asset_id"): cv.string,
                vol.Optional("name"): cv.string,
                vol.Optional("brand"): cv.string,
                vol.Optional("category_id"): cv.string,
                vol.Optional("value"): vol.Coerce(float),
                vol.Optional("purchase_at"): vol.Any(cv.string, None),
                vol.Optional("warranty_until"): vol.Any(cv.string, None),
                vol.Optional("manual_md"): cv.string,
                vol.Optional("maintenance_md"): cv.string,
            }
        ),
    ),
    "delete_asset": (
        handle_delete_asset,
        SupportsResponse.OPTIONAL,
        vol.Schema({vol.Required("asset_id"): cv.string}),
    ),
    # Category CRUD — OPTIONAL
    "create_category": (
        handle_create_category,
        SupportsResponse.OPTIONAL,
        vol.Schema({vol.Required("name"): cv.string}),
    ),
    "update_category": (
        handle_update_category,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("category_id"): cv.string,
                vol.Required("name"): cv.string,
            }
        ),
    ),
    "delete_category": (
        handle_delete_category,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("category_id"): cv.string,
                vol.Optional("force"): cv.boolean,
            }
        ),
    ),
}
