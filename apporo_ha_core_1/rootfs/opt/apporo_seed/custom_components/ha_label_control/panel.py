"""WebSocket API handlers for Label Control."""
from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers import entity_registry as er

from .const import PERM_PREFIX, PERM_LABEL_TYPE, PERM_VIEW

_LOGGER = logging.getLogger(__name__)

# Input validation pattern for label_id
VALID_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


async def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_get_permitted_labels)
    websocket_api.async_register_command(hass, websocket_get_label_entities)


async def get_user_permitted_labels(hass: HomeAssistant, user_id: str) -> list[dict]:
    """Get labels the user has permission to access."""
    permitted = []

    # Get all states for select entities
    states = hass.states.async_all("select")

    for state in states:
        entity_id = state.entity_id
        # Pattern: select.perm_{user_slug}_label_{label_slug}
        if not entity_id.startswith(PERM_PREFIX):
            continue

        attrs = state.attributes
        if attrs.get("user_id") != user_id:
            continue
        if attrs.get("resource_type") != PERM_LABEL_TYPE:
            continue

        # Check permission level >= 1 (View)
        try:
            perm_level = int(state.state)
        except ValueError:
            _LOGGER.debug("Invalid permission level for %s: %s", entity_id, state.state)
            continue

        if perm_level >= PERM_VIEW:
            # Extract label_id from resource_id (remove "label_" prefix)
            resource_id = attrs.get("resource_id", "")
            label_id = resource_id[6:] if resource_id.startswith("label_") else resource_id

            permitted.append({
                "id": label_id,
                "name": attrs.get("resource_name", label_id),
                "permission_level": perm_level,
            })

    return permitted


async def get_entities_for_label(hass: HomeAssistant, label_id: str) -> dict[str, list[str]]:
    """Get entities grouped by domain for a label."""
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
    """Handle get permitted labels command."""
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
                "permission_level": 3,  # Edit level for admin
            })

        connection.send_result(msg["id"], {"labels": labels})
        return

    # Non-admin: check permissions
    permitted = await get_user_permitted_labels(hass, user.id)

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
    """Handle get label entities command."""
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
        permitted = await get_user_permitted_labels(hass, user.id)
        label_ids = [p["id"] for p in permitted]
        if label_id not in label_ids:
            connection.send_error(msg["id"], "forbidden", "No permission for this label")
            return

    entities_by_domain = await get_entities_for_label(hass, label_id)

    connection.send_result(msg["id"], {"entities": entities_by_domain})
