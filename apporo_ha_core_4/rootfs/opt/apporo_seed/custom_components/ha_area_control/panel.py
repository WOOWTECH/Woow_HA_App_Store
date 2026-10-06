"""WebSocket API handlers for Area Control."""
from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr

from .const import PERM_PREFIX, PERM_AREA_TYPE, PERM_VIEW

_LOGGER = logging.getLogger(__name__)

# Input validation pattern for area_id
VALID_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


async def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_get_permitted_areas)
    websocket_api.async_register_command(hass, websocket_get_area_entities)


async def get_user_permitted_areas(hass: HomeAssistant, user_id: str) -> list[dict]:
    """Get areas the user has permission to access."""
    permitted = []

    # Get all states for select entities
    states = hass.states.async_all("select")

    _LOGGER.debug("Checking permissions for user_id: %s", user_id)
    _LOGGER.debug("Looking for entities with prefix: %s", PERM_PREFIX)

    matching_count = 0
    for state in states:
        entity_id = state.entity_id
        # Pattern: select.perm_{user_slug}_{resource_type}_{resource_slug}
        if not entity_id.startswith(PERM_PREFIX):
            continue

        matching_count += 1
        attrs = state.attributes
        attr_user_id = attrs.get("user_id")
        attr_resource_type = attrs.get("resource_type")

        _LOGGER.debug(
            "Found entity %s: user_id=%s (match=%s), resource_type=%s (match=%s), state=%s",
            entity_id, attr_user_id, attr_user_id == user_id,
            attr_resource_type, attr_resource_type == PERM_AREA_TYPE, state.state
        )

        if attr_user_id != user_id:
            continue
        if attr_resource_type != PERM_AREA_TYPE:
            continue

        # Check permission level >= 1 (View)
        try:
            perm_level = int(state.state)
        except ValueError:
            continue

        if perm_level >= PERM_VIEW:
            # Extract area_id from resource_id (remove "area_" prefix)
            resource_id = attrs.get("resource_id", "")
            area_id = resource_id[5:] if resource_id.startswith("area_") else resource_id

            permitted.append({
                "id": area_id,
                "name": attrs.get("resource_name", area_id),
                "permission_level": perm_level,
            })
            _LOGGER.info("User %s has permission %d for area %s", user_id, perm_level, area_id)

    _LOGGER.debug("Total entities with prefix: %d, permitted areas: %d", matching_count, len(permitted))
    return permitted


async def get_entities_for_area(hass: HomeAssistant, area_id: str) -> dict[str, list[str]]:
    """Get entities grouped by domain for an area."""
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
    """Handle get permitted areas command."""
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

    _LOGGER.info("get_permitted_areas called by user: %s (id=%s, is_admin=%s)", user.name, user.id, user.is_admin)

    # Admin users see all areas
    if user.is_admin:
        areas = []
        for area in area_reg.async_list_areas():
            areas.append({
                "id": area.id,
                "name": area.name,
                "icon": area.icon,
                "entity_count": entity_counts.get(area.id, 0),
                "permission_level": 3,  # Edit level for admin
            })

        _LOGGER.info("Admin user %s gets all %d areas", user.name, len(areas))
        connection.send_result(msg["id"], {"areas": areas})
        return

    # Non-admin: check permissions
    permitted = await get_user_permitted_areas(hass, user.id)
    _LOGGER.info("Non-admin user %s (id=%s) has %d permitted areas", user.name, user.id, len(permitted))

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
    """Handle get area entities command."""
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
        permitted = await get_user_permitted_areas(hass, user.id)
        area_ids = [p["id"] for p in permitted]
        if area_id not in area_ids:
            connection.send_error(msg["id"], "forbidden", "No permission for this area")
            return

    entities_by_domain = await get_entities_for_area(hass, area_id)

    connection.send_result(msg["id"], {"entities": entities_by_domain})
