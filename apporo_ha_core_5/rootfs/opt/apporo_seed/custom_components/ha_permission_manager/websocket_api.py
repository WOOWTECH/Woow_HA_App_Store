"""WebSocket API for ha_permission_manager."""
from __future__ import annotations

import logging
import re
from typing import Any, TYPE_CHECKING

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .const import DOMAIN, PREFIX_PANEL, PREFIX_AREA, PREFIX_LABEL

if TYPE_CHECKING:
    from homeassistant.components.websocket_api import ActiveConnection

_LOGGER = logging.getLogger(__name__)

# Input validation pattern for IDs
VALID_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

# Permission levels (2-level model)
# Level 0 = Closed (hidden, no access)
# Level 1 = View (full access - can view and control)
PERM_CLOSED = 0
PERM_VIEW = 1

# Resource types
PERM_AREA_TYPE = "area"
PERM_LABEL_TYPE = "label"


def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register WebSocket API handlers."""
    websocket_api.async_register_command(hass, ws_get_panel_permissions)
    websocket_api.async_register_command(hass, ws_get_all_permissions)
    # Admin panel handlers
    websocket_api.async_register_command(hass, ws_get_admin_data)
    websocket_api.async_register_command(hass, ws_set_permission)
    # Area control handlers
    websocket_api.async_register_command(hass, websocket_get_permitted_areas)
    websocket_api.async_register_command(hass, websocket_get_area_entities)
    # Label control handlers
    websocket_api.async_register_command(hass, websocket_get_permitted_labels)
    websocket_api.async_register_command(hass, websocket_get_label_entities)


# =============================================================================
# Store-based Permission Helpers
# =============================================================================


@callback
def _get_user_permissions(hass: HomeAssistant, user_id: str) -> dict[str, int]:
    """Get all permissions for a user from Store.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to get permissions for.

    Returns:
        Dictionary mapping resource_id -> permission_level.
    """
    domain_data = hass.data.get(DOMAIN, {})
    permissions = domain_data.get("permissions", {})
    return permissions.get(user_id, {})


# =============================================================================
# Area Control WebSocket Handlers
# =============================================================================


@callback
def get_user_permitted_areas(hass: HomeAssistant, user_id: str) -> list[dict]:
    """Get areas the user has permission to access.

    Uses Store-based permission data instead of entity state queries.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to check permissions for.

    Returns:
        List of permitted area dicts with id, name, and permission_level.
    """
    permitted = []
    area_reg = ar.async_get(hass)

    # Get all permissions for this user from Store
    user_perms = _get_user_permissions(hass, user_id)

    _LOGGER.debug("Checking area permissions for user_id: %s", user_id)
    _LOGGER.debug("User has %d total permissions", len(user_perms))

    for resource_id, perm_level in user_perms.items():
        # Only process area resources
        if not resource_id.startswith(PREFIX_AREA):
            continue

        # Check permission level >= 1 (View)
        if perm_level < PERM_VIEW:
            continue

        # Extract area_id from resource_id (remove "area_" prefix)
        area_id = resource_id[len(PREFIX_AREA):]

        # Get area info from registry for the name
        area = area_reg.async_get_area(area_id)
        area_name = area.name if area else area_id

        permitted.append({
            "id": area_id,
            "name": area_name,
            "permission_level": perm_level,
        })
        _LOGGER.debug(
            "User %s has permission %d for area %s",
            user_id, perm_level, area_id
        )

    _LOGGER.debug(
        "User %s has %d permitted areas",
        user_id, len(permitted)
    )
    return permitted


async def get_entities_for_area(
    hass: HomeAssistant, area_id: str
) -> dict[str, list[str]]:
    """Get entities grouped by domain for an area.

    Args:
        hass: Home Assistant instance.
        area_id: The area ID to get entities for.

    Returns:
        Dictionary mapping domain -> list of entity_ids.
    """
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    entities_by_domain: dict[str, list[str]] = {}

    for entry in entity_reg.entities.values():
        entity_area = entry.area_id

        # If entity doesn't have area, check device
        if not entity_area and entry.device_id:
            device = device_reg.async_get(entry.device_id)
            if device:
                entity_area = device.area_id

        if entity_area == area_id and not entry.disabled:
            domain = entry.entity_id.split(".")[0]
            if domain not in entities_by_domain:
                entities_by_domain[domain] = []
            entities_by_domain[domain].append(entry.entity_id)

    return entities_by_domain


@websocket_api.websocket_command({
    vol.Required("type"): "area_control/get_permitted_areas",
})
@websocket_api.async_response
async def websocket_get_permitted_areas(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle get permitted areas command.

    Returns areas the user has permission to access, with entity counts.
    Admin users get all areas with full access.
    """
    user = connection.user

    if user is None:
        connection.send_error(msg["id"], "not_authenticated", "User not authenticated")
        return

    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    # Pre-compute entity counts for all areas (O(n) instead of O(n*m))
    entity_counts: dict[str, int] = {}
    for entry in entity_reg.entities.values():
        if entry.disabled:
            continue
        entity_area = entry.area_id
        if not entity_area and entry.device_id:
            device = device_reg.async_get(entry.device_id)
            if device:
                entity_area = device.area_id
        if entity_area:
            entity_counts[entity_area] = entity_counts.get(entity_area, 0) + 1

    _LOGGER.info(
        "get_permitted_areas called by user: %s (id=%s, is_admin=%s)",
        user.name, user.id, user.is_admin
    )

    # Admin users see all areas
    if user.is_admin:
        areas = []
        for area in area_reg.async_list_areas():
            areas.append({
                "id": area.id,
                "name": area.name,
                "icon": area.icon,
                "entity_count": entity_counts.get(area.id, 0),
                "permission_level": 1,  # Full access for admin
            })

        _LOGGER.info("Admin user %s gets all %d areas", user.name, len(areas))
        connection.send_result(msg["id"], {"areas": areas})
        return

    # Non-admin: check permissions from Store
    permitted = get_user_permitted_areas(hass, user.id)
    _LOGGER.info(
        "Non-admin user %s (id=%s) has %d permitted areas",
        user.name, user.id, len(permitted)
    )

    # Enrich with area details and entity count
    areas = []
    for perm in permitted:
        area = area_reg.async_get_area(perm["id"])
        if area:
            areas.append({
                "id": area.id,
                "name": area.name,
                "icon": area.icon,
                "entity_count": entity_counts.get(area.id, 0),
                "permission_level": perm["permission_level"],
            })

    connection.send_result(msg["id"], {"areas": areas})


@websocket_api.websocket_command({
    vol.Required("type"): "area_control/get_area_entities",
    vol.Required("area_id"): vol.All(str, vol.Length(min=1, max=255)),
})
@websocket_api.async_response
async def websocket_get_area_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle get area entities command.

    Returns entities grouped by domain for a specific area.
    Validates user has permission for the area.
    """
    user = connection.user
    area_id = msg["area_id"]

    if user is None:
        connection.send_error(msg["id"], "not_authenticated", "User not authenticated")
        return

    # Validate area_id format
    if not VALID_ID_PATTERN.match(area_id):
        connection.send_error(msg["id"], "invalid_area_id", "Invalid area_id format")
        return

    # Verify permission (admin or has area permission)
    if not user.is_admin:
        permitted = get_user_permitted_areas(hass, user.id)
        area_ids = [p["id"] for p in permitted]
        if area_id not in area_ids:
            connection.send_error(msg["id"], "forbidden", "No permission for this area")
            return

    entities_by_domain = await get_entities_for_area(hass, area_id)

    connection.send_result(msg["id"], {"entities": entities_by_domain})


# =============================================================================
# Label Control WebSocket Handlers
# =============================================================================


@callback
def get_user_permitted_labels(hass: HomeAssistant, user_id: str) -> list[dict]:
    """Get labels the user has permission to access.

    Uses Store-based permission data instead of entity state queries.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to check permissions for.

    Returns:
        List of permitted label dicts with id, name, and permission_level.
    """
    permitted = []
    label_reg = lr.async_get(hass)

    # Get all permissions for this user from Store
    user_perms = _get_user_permissions(hass, user_id)

    _LOGGER.debug("Checking label permissions for user_id: %s", user_id)

    for resource_id, perm_level in user_perms.items():
        # Only process label resources
        if not resource_id.startswith(PREFIX_LABEL):
            continue

        # Check permission level >= 1 (View)
        if perm_level < PERM_VIEW:
            continue

        # Extract label_id from resource_id (remove "label_" prefix)
        label_id = resource_id[len(PREFIX_LABEL):]

        # Get label info from registry for the name
        label = label_reg.async_get_label(label_id)
        label_name = label.name if label else label_id

        permitted.append({
            "id": label_id,
            "name": label_name,
            "permission_level": perm_level,
        })

    _LOGGER.debug(
        "User %s has %d permitted labels",
        user_id, len(permitted)
    )
    return permitted


async def get_entities_for_label(
    hass: HomeAssistant, label_id: str
) -> dict[str, list[str]]:
    """Get entities grouped by domain for a label.

    Args:
        hass: Home Assistant instance.
        label_id: The label ID to get entities for.

    Returns:
        Dictionary mapping domain -> list of entity_ids.
    """
    entity_reg = er.async_get(hass)

    entities_by_domain: dict[str, list[str]] = {}

    for entry in entity_reg.entities.values():
        # Check if entity has this label
        if label_id in (entry.labels or set()) and not entry.disabled:
            domain = entry.entity_id.split(".")[0]
            if domain not in entities_by_domain:
                entities_by_domain[domain] = []
            entities_by_domain[domain].append(entry.entity_id)

    return entities_by_domain


@websocket_api.websocket_command({
    vol.Required("type"): "label_control/get_permitted_labels",
})
@websocket_api.async_response
async def websocket_get_permitted_labels(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle get permitted labels command.

    Returns labels the user has permission to access, with entity counts.
    Admin users get all labels with full access.
    """
    user = connection.user

    if user is None:
        connection.send_error(msg["id"], "not_authenticated", "User not authenticated")
        return

    label_reg = lr.async_get(hass)
    entity_reg = er.async_get(hass)

    # Pre-compute entity counts for all labels (O(n) instead of O(n*m))
    entity_counts: dict[str, int] = {}
    for entry in entity_reg.entities.values():
        if entry.disabled:
            continue
        for label_id in (entry.labels or set()):
            entity_counts[label_id] = entity_counts.get(label_id, 0) + 1

    # Admin users see all labels
    if user.is_admin:
        labels = []
        for label in label_reg.async_list_labels():
            labels.append({
                "id": label.label_id,
                "name": label.name,
                "icon": label.icon,
                "color": label.color,
                "entity_count": entity_counts.get(label.label_id, 0),
                "permission_level": 1,  # Full access for admin
            })

        connection.send_result(msg["id"], {"labels": labels})
        return

    # Non-admin: check permissions from Store
    permitted = get_user_permitted_labels(hass, user.id)

    # Enrich with label details and entity count
    labels = []
    for perm in permitted:
        label = label_reg.async_get_label(perm["id"])
        if label:
            labels.append({
                "id": label.label_id,
                "name": label.name,
                "icon": label.icon,
                "color": label.color,
                "entity_count": entity_counts.get(label.label_id, 0),
                "permission_level": perm["permission_level"],
            })

    connection.send_result(msg["id"], {"labels": labels})


@websocket_api.websocket_command({
    vol.Required("type"): "label_control/get_label_entities",
    vol.Required("label_id"): vol.All(str, vol.Length(min=1, max=255)),
})
@websocket_api.async_response
async def websocket_get_label_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle get label entities command.

    Returns entities grouped by domain for a specific label.
    Validates user has permission for the label.
    """
    user = connection.user
    label_id = msg["label_id"]

    if user is None:
        connection.send_error(msg["id"], "not_authenticated", "User not authenticated")
        return

    # Validate label_id format
    if not VALID_ID_PATTERN.match(label_id):
        connection.send_error(msg["id"], "invalid_label_id", "Invalid label_id format")
        return

    # Verify permission (admin or has label permission)
    if not user.is_admin:
        permitted = get_user_permitted_labels(hass, user.id)
        label_ids = [p["id"] for p in permitted]
        if label_id not in label_ids:
            connection.send_error(msg["id"], "forbidden", "No permission for this label")
            return

    entities_by_domain = await get_entities_for_label(hass, label_id)

    connection.send_result(msg["id"], {"entities": entities_by_domain})


# =============================================================================
# Permission Manager WebSocket Handlers
# =============================================================================


@websocket_api.websocket_command(
    {
        vol.Required("type"): "permission_manager/get_panel_permissions",
    }
)
@callback
def ws_get_panel_permissions(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return panel permissions for the current user.

    Uses Store-based permission data instead of entity state queries.

    Returns dict of panel_id -> permission_level (0 or 1)
    Level 0 = Closed (hidden, no access)
    Level 1 = View (full access - can view and control)
    """
    user_id = connection.user.id
    is_admin = connection.user.is_admin

    permissions: dict[str, int] = {}

    # Get all permissions for this user from Store
    user_perms = _get_user_permissions(hass, user_id)

    matched_panel = 0

    for resource_id, perm_level in user_perms.items():
        # Only process panel resources
        if not resource_id.startswith(PREFIX_PANEL):
            continue

        matched_panel += 1

        # Extract panel_id from resource_id (strip prefix)
        panel_id = resource_id[len(PREFIX_PANEL):]

        # Admin users always get level 1 (full access) for permission_manager panel
        if is_admin and panel_id == "ha_permission_manager":
            perm_level = 1

        permissions[panel_id] = perm_level

    _LOGGER.debug(
        "Panel permissions for user %s (is_admin=%s): matched_panel=%d, permissions=%s",
        user_id,
        is_admin,
        matched_panel,
        permissions,
    )

    # Return is_admin flag so frontend knows to skip filtering
    # Note: user_id intentionally not included for security
    connection.send_result(msg["id"], {
        "permissions": permissions,
        "is_admin": is_admin,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "permission_manager/get_all_permissions",
    }
)
@callback
def ws_get_all_permissions(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all permissions for the current user.

    Uses Store-based permission data instead of entity state queries.

    Returns dict with:
    - panels: dict of panel_id -> permission_level
    - areas: dict of area_id -> permission_level
    - labels: dict of label_id -> permission_level
    - is_admin: bool
    """
    user_id = connection.user.id
    is_admin = connection.user.is_admin

    panels: dict[str, int] = {}
    areas: dict[str, int] = {}
    labels: dict[str, int] = {}

    # Get all permissions for this user from Store
    user_perms = _get_user_permissions(hass, user_id)

    for resource_id, perm_level in user_perms.items():
        if resource_id.startswith(PREFIX_PANEL):
            panel_id = resource_id[len(PREFIX_PANEL):]
            panels[panel_id] = perm_level

        elif resource_id.startswith(PREFIX_AREA):
            area_id = resource_id[len(PREFIX_AREA):]
            areas[area_id] = perm_level

        elif resource_id.startswith(PREFIX_LABEL):
            label_id = resource_id[len(PREFIX_LABEL):]
            labels[label_id] = perm_level

    _LOGGER.info(
        "All permissions for user %s (is_admin=%s): panels=%d, areas=%d, labels=%d",
        user_id, is_admin, len(panels), len(areas), len(labels),
    )

    # Note: user_id intentionally not included for security
    connection.send_result(msg["id"], {
        "panels": panels,
        "areas": areas,
        "labels": labels,
        "is_admin": is_admin,
    })


# =============================================================================
# Admin Panel WebSocket Handlers
# =============================================================================


@websocket_api.websocket_command(
    {
        vol.Required("type"): "permission_manager/get_admin_data",
    }
)
@websocket_api.async_response
async def ws_get_admin_data(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all data needed for the admin permission manager panel.

    This endpoint is only available to admin users and returns:
    - users: list of all non-owner, non-system users with id, name, is_admin
    - resources: dict of resource_type -> list of resources (panels, areas, labels)
    - permissions: dict of user_id -> {resource_id: permission_level}

    The frontend uses this data to display the permission matrix.
    """
    user = connection.user

    if user is None:
        connection.send_error(msg["id"], "not_authenticated", "User not authenticated")
        return

    if not user.is_admin:
        connection.send_error(msg["id"], "forbidden", "Admin access required")
        return

    # Get all users (excluding owner and system accounts)
    users_data = []
    for ha_user in await hass.auth.async_get_users():
        # Skip owner and system accounts
        if ha_user.is_owner or ha_user.system_generated:
            continue
        users_data.append({
            "id": ha_user.id,
            "name": ha_user.name or "Unknown",
            "is_admin": ha_user.is_admin,
        })

    # Sort users by name
    users_data.sort(key=lambda u: u["name"].lower())

    # Get all resources
    resources = {
        "panels": [],
        "areas": [],
        "labels": [],
    }

    # Get panels from frontend_panels (excluding internal panels)
    frontend_panels = hass.data.get("frontend_panels", {})
    excluded_panels = {
        "developer-tools", "config", "profile",
    }
    for panel_id, panel in frontend_panels.items():
        if panel_id in excluded_panels:
            continue
        # Get panel title
        title = panel_id
        if hasattr(panel, "title") and panel.title:
            title = panel.title
        elif hasattr(panel, "config") and isinstance(panel.config, dict):
            title = panel.config.get("title", panel_id)
        resources["panels"].append({
            "id": panel_id,
            "name": title,
            "type": "panel",
        })

    # Get areas
    area_reg = ar.async_get(hass)
    for area in area_reg.async_list_areas():
        resources["areas"].append({
            "id": area.id,
            "name": area.name,
            "type": "area",
        })

    # Get labels
    label_reg = lr.async_get(hass)
    for label in label_reg.async_list_labels():
        resources["labels"].append({
            "id": label.label_id,
            "name": label.name,
            "type": "label",
        })

    # Sort resources by name
    for key in resources:
        resources[key].sort(key=lambda r: r["name"].lower())

    # Get all permissions from Store
    domain_data = hass.data.get(DOMAIN, {})
    all_permissions = domain_data.get("permissions", {})

    _LOGGER.info(
        "Admin data: %d users, %d panels, %d areas, %d labels",
        len(users_data),
        len(resources["panels"]),
        len(resources["areas"]),
        len(resources["labels"]),
    )

    connection.send_result(msg["id"], {
        "users": users_data,
        "resources": resources,
        "permissions": all_permissions,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "permission_manager/set_permission",
        vol.Required("user_id"): vol.All(str, vol.Length(min=1, max=255)),
        vol.Required("resource_id"): vol.All(str, vol.Length(min=1, max=255)),
        vol.Required("level"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1)),
    }
)
@websocket_api.async_response
async def ws_set_permission(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set permission level for a user and resource.

    This endpoint is only available to admin users.

    Args (in msg):
        user_id: The user ID to set permission for.
        resource_id: The resource ID with prefix (e.g., "panel_config", "area_living_room").
        level: Permission level (0=Closed, 1=View).

    Returns success status.
    """
    user = connection.user

    if user is None:
        connection.send_error(msg["id"], "not_authenticated", "User not authenticated")
        return

    if not user.is_admin:
        connection.send_error(msg["id"], "forbidden", "Admin access required")
        return

    target_user_id = msg["user_id"]
    resource_id = msg["resource_id"]
    level = msg["level"]

    # Validate resource_id format (must have valid prefix)
    valid_prefixes = (PREFIX_PANEL, PREFIX_AREA, PREFIX_LABEL)
    if not any(resource_id.startswith(p) for p in valid_prefixes):
        connection.send_error(
            msg["id"],
            "invalid_resource",
            f"Resource ID must start with one of: {valid_prefixes}"
        )
        return

    # Import the async_set_permission function from __init__.py
    from . import async_set_permission

    try:
        await async_set_permission(hass, target_user_id, resource_id, level)
        _LOGGER.info(
            "Permission set: user=%s, resource=%s, level=%d (by admin %s)",
            target_user_id, resource_id, level, user.id
        )
        connection.send_result(msg["id"], {"success": True})
    except Exception as err:
        _LOGGER.exception("Failed to set permission: %s", err)
        connection.send_error(msg["id"], "set_failed", str(err))
