"""Service handlers for ha_permission_manager.

Provides 14 HA Services for programmatic permission management:
  Write: set_permission, bulk_set_permissions, remove_user_permissions,
         remove_resource_permissions, reset_all_permissions
  Query (admin): get_permissions, get_users, get_resources,
         get_panel_permissions, get_all_permissions (SupportsResponse)
  Query (user-context): get_permitted_areas, get_area_entities,
         get_permitted_labels, get_label_entities (SupportsResponse)
"""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .const import (
    DOMAIN,
    PERM_CLOSED,
    PERM_VIEW,
    PREFIX_AREA,
    PREFIX_LABEL,
    PREFIX_PANEL,
    RESOURCE_TYPES,
    RESOURCE_TYPE_PREFIX_MAP,
    SERVICE_SET_PERMISSION,
    SERVICE_BULK_SET_PERMISSIONS,
    SERVICE_REMOVE_USER_PERMISSIONS,
    SERVICE_REMOVE_RESOURCE_PERMISSIONS,
    SERVICE_RESET_ALL_PERMISSIONS,
    SERVICE_GET_PERMISSIONS,
    SERVICE_GET_USERS,
    SERVICE_GET_RESOURCES,
    SERVICE_GET_PERMITTED_AREAS,
    SERVICE_GET_AREA_ENTITIES,
    SERVICE_GET_PERMITTED_LABELS,
    SERVICE_GET_LABEL_ENTITIES,
    SERVICE_GET_PANEL_PERMISSIONS,
    SERVICE_GET_ALL_PERMISSIONS,
)
from .discovery import discover_all_resources
from .users import discover_users

_LOGGER = logging.getLogger(__name__)

# Regex for valid resource/user IDs
_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
_RESOURCE_ID_PATTERN = re.compile(r"^(panel_|area_|label_)[a-zA-Z0-9_\-]+$")

# Max entries in a bulk operation
_BULK_MAX = 500

# =============================================================================
# Voluptuous Schemas
# =============================================================================

_VALID_ID = vol.All(str, vol.Length(min=1, max=255))

_SCHEMA_SET_PERMISSION = vol.Schema({
    vol.Required("user_id"): _VALID_ID,
    vol.Required("resource_id"): _VALID_ID,
    vol.Required("level"): vol.All(vol.Coerce(int), vol.In([PERM_CLOSED, PERM_VIEW])),
})

_SINGLE_PERMISSION_ENTRY = vol.Schema({
    vol.Required("user_id"): _VALID_ID,
    vol.Required("resource_id"): _VALID_ID,
    vol.Required("level"): vol.All(vol.Coerce(int), vol.In([PERM_CLOSED, PERM_VIEW])),
})

_SCHEMA_BULK_SET = vol.Schema({
    vol.Required("permissions"): vol.All(
        [_SINGLE_PERMISSION_ENTRY],
        vol.Length(min=1, max=_BULK_MAX),
    ),
})

_SCHEMA_REMOVE_USER = vol.Schema({
    vol.Required("user_id"): _VALID_ID,
})

_SCHEMA_REMOVE_RESOURCE = vol.Schema({
    vol.Required("resource_id"): _VALID_ID,
})

_SCHEMA_RESET_ALL = vol.Schema({
    vol.Required("confirm"): True,
})

_SCHEMA_GET_PERMISSIONS = vol.Schema({
    vol.Optional("user_id"): _VALID_ID,
    vol.Optional("resource_type"): vol.In(RESOURCE_TYPES),
    vol.Optional("resource_id"): _VALID_ID,
})

_SCHEMA_GET_USERS = vol.Schema({})

_SCHEMA_GET_RESOURCES = vol.Schema({
    vol.Optional("type"): vol.In(RESOURCE_TYPES),
})

_SCHEMA_GET_PERMITTED_AREAS = vol.Schema({
    vol.Required("user_id"): _VALID_ID,
})

_SCHEMA_GET_AREA_ENTITIES = vol.Schema({
    vol.Required("area_id"): _VALID_ID,
})

_SCHEMA_GET_PERMITTED_LABELS = vol.Schema({
    vol.Required("user_id"): _VALID_ID,
})

_SCHEMA_GET_LABEL_ENTITIES = vol.Schema({
    vol.Required("label_id"): _VALID_ID,
})

_SCHEMA_GET_PANEL_PERMISSIONS = vol.Schema({
    vol.Required("user_id"): _VALID_ID,
})

_SCHEMA_GET_ALL_PERMISSIONS_USER = vol.Schema({
    vol.Required("user_id"): _VALID_ID,
})


# =============================================================================
# Helper Functions
# =============================================================================


async def _async_validate_admin(hass: HomeAssistant, call: ServiceCall) -> None:
    """Verify the caller is an admin user.

    Raises HomeAssistantError if the caller is not admin.
    Internal/system calls (no user context) are allowed.
    """
    user_id = call.context.user_id
    if user_id is None:
        # Internal/system call (e.g., from automation without user context)
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise HomeAssistantError(
            "Admin access required. Only administrators can manage permissions. "
            "需要管理员权限。只有管理员可以管理权限。"
        )


def _validate_resource_id(resource_id: str) -> None:
    """Validate resource_id has correct prefix and format."""
    if not _RESOURCE_ID_PATTERN.match(resource_id):
        raise HomeAssistantError(
            f"Invalid resource_id: '{resource_id}'. "
            f"Must start with 'panel_', 'area_', or 'label_' followed by alphanumeric/underscore/hyphen characters. "
            f"无效的 resource_id：'{resource_id}'。必须以 'panel_'、'area_' 或 'label_' 开头。"
        )


def _validate_user_id(user_id: str) -> None:
    """Validate user_id format."""
    if not _ID_PATTERN.match(user_id):
        raise HomeAssistantError(
            f"Invalid user_id: '{user_id}'. "
            f"Must contain only alphanumeric, underscore, or hyphen characters. "
            f"无效的 user_id：'{user_id}'。只能包含字母、数字、下划线或连字号。"
        )


def _get_domain_data(hass: HomeAssistant) -> dict[str, Any]:
    """Get domain data, raising error if integration not loaded."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None:
        raise HomeAssistantError(
            "Permission Manager is not loaded. "
            "权限管理器未加载。"
        )
    return domain_data


# =============================================================================
# Write Service Handlers
# =============================================================================


async def async_handle_set_permission(call: ServiceCall) -> None:
    """Handle set_permission service call.

    Sets the permission level for a specific user on a specific resource.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    user_id = call.data["user_id"]
    resource_id = call.data["resource_id"]
    level = call.data["level"]

    _validate_user_id(user_id)
    _validate_resource_id(resource_id)

    # Import here to avoid circular imports
    from . import async_set_permission

    await async_set_permission(hass, user_id, resource_id, level)

    _LOGGER.info(
        "Service set_permission: user=%s, resource=%s, level=%d",
        user_id, resource_id, level,
    )


async def async_handle_bulk_set_permissions(call: ServiceCall) -> None:
    """Handle bulk_set_permissions service call.

    Sets multiple permission entries in one call. Validates every entry before
    applying any, then hands the batch to async_bulk_set_permissions, which
    saves and announces once for the whole of it.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    permissions_list = call.data["permissions"]

    # Validate all entries first before applying any
    for entry in permissions_list:
        _validate_user_id(entry["user_id"])
        _validate_resource_id(entry["resource_id"])

    from . import async_bulk_set_permissions

    await async_bulk_set_permissions(hass, permissions_list)

    _LOGGER.info(
        "Service bulk_set_permissions: applied %d entries",
        len(permissions_list),
    )


async def async_handle_remove_user_permissions(call: ServiceCall) -> None:
    """Handle remove_user_permissions service call.

    Deletes all permissions for a specific user.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    user_id = call.data["user_id"]
    _validate_user_id(user_id)

    from . import async_delete_user_permissions

    await async_delete_user_permissions(hass, user_id)

    _LOGGER.info("Service remove_user_permissions: user=%s", user_id)


async def async_handle_remove_resource_permissions(call: ServiceCall) -> None:
    """Handle remove_resource_permissions service call.

    Deletes all permissions for a specific resource across all users.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    resource_id = call.data["resource_id"]
    _validate_resource_id(resource_id)

    from . import async_delete_resource_permissions

    await async_delete_resource_permissions(hass, resource_id)

    _LOGGER.info("Service remove_resource_permissions: resource=%s", resource_id)


async def async_handle_reset_all_permissions(call: ServiceCall) -> None:
    """Handle reset_all_permissions service call.

    Clears the entire permission table. Requires confirm=true.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    # confirm is already validated by schema to be True
    from . import async_reset_all_permissions

    await async_reset_all_permissions(hass)

    _LOGGER.warning("Service reset_all_permissions: all permissions cleared")


# =============================================================================
# Query Service Handlers (SupportsResponse)
# =============================================================================


async def async_handle_get_permissions(call: ServiceCall) -> ServiceResponse:
    """Handle get_permissions service call.

    Returns permissions filtered by optional user_id, resource_type, resource_id.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    from . import async_get_all_permissions, async_get_user_permissions

    user_id = call.data.get("user_id")
    resource_type = call.data.get("resource_type")
    resource_id = call.data.get("resource_id")

    # Start with all or single-user permissions
    if user_id:
        _validate_user_id(user_id)
        raw_perms = {user_id: async_get_user_permissions(hass, user_id)}
    else:
        raw_perms = dict(async_get_all_permissions(hass))

    # Filter by resource_type if specified
    if resource_type:
        prefix = RESOURCE_TYPE_PREFIX_MAP[resource_type]
        filtered = {}
        for uid, user_perms in raw_perms.items():
            type_filtered = {
                rid: lvl for rid, lvl in user_perms.items()
                if rid.startswith(prefix)
            }
            if type_filtered:
                filtered[uid] = type_filtered
        raw_perms = filtered

    # Filter by specific resource_id if specified
    if resource_id:
        _validate_resource_id(resource_id)
        filtered = {}
        for uid, user_perms in raw_perms.items():
            if resource_id in user_perms:
                filtered[uid] = {resource_id: user_perms[resource_id]}
        raw_perms = filtered

    return {"permissions": raw_perms}


async def async_handle_get_users(call: ServiceCall) -> ServiceResponse:
    """Handle get_users service call.

    Returns all manageable (non-system) users.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    users = await discover_users(hass)

    return {
        "users": [
            {
                "id": user.id,
                "name": user.name,
                "is_admin": user.is_admin,
            }
            for user in users
        ]
    }


async def async_handle_get_resources(call: ServiceCall) -> ServiceResponse:
    """Handle get_resources service call.

    Returns all manageable resources, optionally filtered by type.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    resource_type = call.data.get("type")

    all_resources = discover_all_resources(hass)

    result = []

    if resource_type:
        # Return only the requested type
        type_key = resource_type + "s"  # "panel" -> "panels", "area" -> "areas"
        for resource in all_resources.get(type_key, []):
            result.append({
                "id": resource.id,
                "name": resource.name,
                "type": resource.type,
            })
    else:
        # Return all types
        for type_key in ("panels", "areas", "labels"):
            for resource in all_resources.get(type_key, []):
                result.append({
                    "id": resource.id,
                    "name": resource.name,
                    "type": resource.type,
                })

    return {"resources": result}


# =============================================================================
# User-Context Query Service Handlers (SupportsResponse)
# =============================================================================


async def async_handle_get_permitted_areas(call: ServiceCall) -> ServiceResponse:
    """Handle get_permitted_areas service call.

    Returns areas a specific user has permission to access, with entity counts.
    Admin users get all areas with permission_level=1.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    user_id = call.data["user_id"]
    _validate_user_id(user_id)

    # Look up the target user to check admin status
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise HomeAssistantError(
            f"User '{user_id}' not found. Call get_users to discover valid user IDs. "
            f"找不到用戶 '{user_id}'。請先呼叫 get_users 查詢有效的用戶 ID。"
        )

    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    # Pre-compute entity counts for all areas (O(n))
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

    # Admin users see all areas
    if user.is_admin:
        areas = []
        for area in area_reg.async_list_areas():
            areas.append({
                "id": area.id,
                "name": area.name,
                "icon": area.icon,
                "entity_count": entity_counts.get(area.id, 0),
                "permission_level": 1,
            })
        return {"areas": areas, "is_admin": True}

    # Non-admin: check permissions from Store
    domain_data = _get_domain_data(hass)
    permissions = domain_data.get("permissions", {})
    user_perms = permissions.get(user_id, {})

    areas = []
    for resource_id, perm_level in user_perms.items():
        if not resource_id.startswith(PREFIX_AREA):
            continue
        if perm_level < PERM_VIEW:
            continue

        area_id = resource_id[len(PREFIX_AREA):]
        area = area_reg.async_get_area(area_id)
        if area:
            areas.append({
                "id": area.id,
                "name": area.name,
                "icon": area.icon,
                "entity_count": entity_counts.get(area.id, 0),
                "permission_level": perm_level,
            })

    return {"areas": areas, "is_admin": False}


async def async_handle_get_area_entities(call: ServiceCall) -> ServiceResponse:
    """Handle get_area_entities service call.

    Returns entities grouped by domain for a specific area.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    area_id = call.data["area_id"]
    if not _ID_PATTERN.match(area_id):
        raise HomeAssistantError(
            f"Invalid area_id: '{area_id}'. "
            f"Must contain only alphanumeric, underscore, or hyphen characters. "
            f"無效的 area_id：'{area_id}'。只能包含字母、數字、下劃線或連字號。"
        )

    # Verify the area exists
    area_reg = ar.async_get(hass)
    area = area_reg.async_get_area(area_id)
    if area is None:
        raise HomeAssistantError(
            f"Area '{area_id}' not found. Call get_resources with type='area' to discover valid area IDs. "
            f"找不到區域 '{area_id}'。請呼叫 get_resources（type='area'）查詢有效的區域 ID。"
        )

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

    return {
        "area_id": area_id,
        "area_name": area.name,
        "entities": entities_by_domain,
    }


async def async_handle_get_permitted_labels(call: ServiceCall) -> ServiceResponse:
    """Handle get_permitted_labels service call.

    Returns labels a specific user has permission to access, with entity counts.
    Admin users get all labels with permission_level=1.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    user_id = call.data["user_id"]
    _validate_user_id(user_id)

    # Look up the target user to check admin status
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise HomeAssistantError(
            f"User '{user_id}' not found. Call get_users to discover valid user IDs. "
            f"找不到用戶 '{user_id}'。請先呼叫 get_users 查詢有效的用戶 ID。"
        )

    label_reg = lr.async_get(hass)
    entity_reg = er.async_get(hass)

    # Pre-compute entity counts for all labels (O(n))
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
                "permission_level": 1,
            })
        return {"labels": labels, "is_admin": True}

    # Non-admin: check permissions from Store
    domain_data = _get_domain_data(hass)
    permissions = domain_data.get("permissions", {})
    user_perms = permissions.get(user_id, {})

    labels = []
    for resource_id, perm_level in user_perms.items():
        if not resource_id.startswith(PREFIX_LABEL):
            continue
        if perm_level < PERM_VIEW:
            continue

        label_id = resource_id[len(PREFIX_LABEL):]
        label = label_reg.async_get_label(label_id)
        if label:
            labels.append({
                "id": label.label_id,
                "name": label.name,
                "icon": label.icon,
                "color": label.color,
                "entity_count": entity_counts.get(label.label_id, 0),
                "permission_level": perm_level,
            })

    return {"labels": labels, "is_admin": False}


async def async_handle_get_label_entities(call: ServiceCall) -> ServiceResponse:
    """Handle get_label_entities service call.

    Returns entities grouped by domain for a specific label.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    label_id = call.data["label_id"]
    if not _ID_PATTERN.match(label_id):
        raise HomeAssistantError(
            f"Invalid label_id: '{label_id}'. "
            f"Must contain only alphanumeric, underscore, or hyphen characters. "
            f"無效的 label_id：'{label_id}'。只能包含字母、數字、下劃線或連字號。"
        )

    # Verify the label exists
    label_reg = lr.async_get(hass)
    label = label_reg.async_get_label(label_id)
    if label is None:
        raise HomeAssistantError(
            f"Label '{label_id}' not found. Call get_resources with type='label' to discover valid label IDs. "
            f"找不到標籤 '{label_id}'。請呼叫 get_resources（type='label'）查詢有效的標籤 ID。"
        )

    entity_reg = er.async_get(hass)

    entities_by_domain: dict[str, list[str]] = {}

    for entry in entity_reg.entities.values():
        if label_id in (entry.labels or set()) and not entry.disabled:
            domain = entry.entity_id.split(".")[0]
            if domain not in entities_by_domain:
                entities_by_domain[domain] = []
            entities_by_domain[domain].append(entry.entity_id)

    return {
        "label_id": label_id,
        "label_name": label.name,
        "entities": entities_by_domain,
    }


async def async_handle_get_panel_permissions(call: ServiceCall) -> ServiceResponse:
    """Handle get_panel_permissions service call.

    Returns panel permission levels for a specific user.
    Admin users always get level=1 for ha_permission_manager panel.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    user_id = call.data["user_id"]
    _validate_user_id(user_id)

    # Look up the target user to check admin status
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise HomeAssistantError(
            f"User '{user_id}' not found. Call get_users to discover valid user IDs. "
            f"找不到用戶 '{user_id}'。請先呼叫 get_users 查詢有效的用戶 ID。"
        )

    domain_data = _get_domain_data(hass)
    all_permissions = domain_data.get("permissions", {})
    user_perms = all_permissions.get(user_id, {})

    panels: dict[str, int] = {}

    for resource_id, perm_level in user_perms.items():
        if not resource_id.startswith(PREFIX_PANEL):
            continue

        panel_id = resource_id[len(PREFIX_PANEL):]

        # Admin users always get level 1 for permission_manager panel
        if user.is_admin and panel_id == "ha_permission_manager":
            perm_level = 1

        panels[panel_id] = perm_level

    return {
        "panels": panels,
        "is_admin": user.is_admin,
    }


async def async_handle_get_all_permissions_user(call: ServiceCall) -> ServiceResponse:
    """Handle get_all_permissions service call.

    Returns all permission types (panels, areas, labels) for a specific user,
    categorized by resource type.
    """
    hass = call.hass
    await _async_validate_admin(hass, call)

    user_id = call.data["user_id"]
    _validate_user_id(user_id)

    # Look up the target user to check admin status
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise HomeAssistantError(
            f"User '{user_id}' not found. Call get_users to discover valid user IDs. "
            f"找不到用戶 '{user_id}'。請先呼叫 get_users 查詢有效的用戶 ID。"
        )

    domain_data = _get_domain_data(hass)
    all_permissions = domain_data.get("permissions", {})
    user_perms = all_permissions.get(user_id, {})

    panels: dict[str, int] = {}
    areas: dict[str, int] = {}
    labels: dict[str, int] = {}

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

    return {
        "panels": panels,
        "areas": areas,
        "labels": labels,
        "is_admin": user.is_admin,
    }


# =============================================================================
# Service Registration
# =============================================================================


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all permission manager services."""

    # Write services (no response)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PERMISSION,
        async_handle_set_permission,
        schema=_SCHEMA_SET_PERMISSION,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_BULK_SET_PERMISSIONS,
        async_handle_bulk_set_permissions,
        schema=_SCHEMA_BULK_SET,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_USER_PERMISSIONS,
        async_handle_remove_user_permissions,
        schema=_SCHEMA_REMOVE_USER,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_RESOURCE_PERMISSIONS,
        async_handle_remove_resource_permissions,
        schema=_SCHEMA_REMOVE_RESOURCE,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_ALL_PERMISSIONS,
        async_handle_reset_all_permissions,
        schema=_SCHEMA_RESET_ALL,
    )

    # Query services (with SupportsResponse)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PERMISSIONS,
        async_handle_get_permissions,
        schema=_SCHEMA_GET_PERMISSIONS,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_USERS,
        async_handle_get_users,
        schema=_SCHEMA_GET_USERS,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_RESOURCES,
        async_handle_get_resources,
        schema=_SCHEMA_GET_RESOURCES,
        supports_response=SupportsResponse.ONLY,
    )

    # User-context query services (with SupportsResponse)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PERMITTED_AREAS,
        async_handle_get_permitted_areas,
        schema=_SCHEMA_GET_PERMITTED_AREAS,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_AREA_ENTITIES,
        async_handle_get_area_entities,
        schema=_SCHEMA_GET_AREA_ENTITIES,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PERMITTED_LABELS,
        async_handle_get_permitted_labels,
        schema=_SCHEMA_GET_PERMITTED_LABELS,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_LABEL_ENTITIES,
        async_handle_get_label_entities,
        schema=_SCHEMA_GET_LABEL_ENTITIES,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PANEL_PERMISSIONS,
        async_handle_get_panel_permissions,
        schema=_SCHEMA_GET_PANEL_PERMISSIONS,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ALL_PERMISSIONS,
        async_handle_get_all_permissions_user,
        schema=_SCHEMA_GET_ALL_PERMISSIONS_USER,
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.info("Registered %d permission manager services", 14)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister all permission manager services."""
    for service_name in (
        SERVICE_SET_PERMISSION,
        SERVICE_BULK_SET_PERMISSIONS,
        SERVICE_REMOVE_USER_PERMISSIONS,
        SERVICE_REMOVE_RESOURCE_PERMISSIONS,
        SERVICE_RESET_ALL_PERMISSIONS,
        SERVICE_GET_PERMISSIONS,
        SERVICE_GET_USERS,
        SERVICE_GET_RESOURCES,
        SERVICE_GET_PERMITTED_AREAS,
        SERVICE_GET_AREA_ENTITIES,
        SERVICE_GET_PERMITTED_LABELS,
        SERVICE_GET_LABEL_ENTITIES,
        SERVICE_GET_PANEL_PERMISSIONS,
        SERVICE_GET_ALL_PERMISSIONS,
    ):
        hass.services.async_remove(DOMAIN, service_name)

    _LOGGER.info("Unregistered permission manager services")
