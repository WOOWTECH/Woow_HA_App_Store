"""The ha_permission_manager integration."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.frontend import (
    add_extra_js_url,
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_TITLE_ZH,
    PANEL_URL,
    PANEL_VERSION,
    PERM_CLOSED,
    PREFIX_AREA,
    PREFIX_LABEL,
    PREFIX_PANEL,
    STORAGE_KEY,
    STORAGE_VERSION,
    # Control Panel constants
    CONTROL_PANEL_URL,
    CONTROL_PANEL_TITLE,
    CONTROL_PANEL_TITLE_ZH,
    CONTROL_PANEL_ICON,
)
from .services import async_register_services, async_unregister_services
from .websocket_api import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)

async def _async_cleanup_obsolete_permissions(hass: HomeAssistant) -> None:
    """Remove orphaned script, automation, and custom permission entities.

    These resource types were discovered but never enforced in prior versions.
    This cleanup runs once on component load to remove any leftover entities.
    """
    entity_registry = er.async_get(hass)
    entities_to_remove = []

    # Resource types that are no longer supported (removed in v1.0.0)
    obsolete_types = ("script", "automation", "custom")

    # Find all permission entities with obsolete resource types
    for entity_id, entity_entry in entity_registry.entities.items():
        if not entity_id.startswith("select.permission_manager_"):
            continue

        # Check if unique_id contains obsolete resource type prefix
        # Format: perm_{user_id}_{resource_type}_{resource_id}
        unique_id = entity_entry.unique_id or ""
        if not unique_id.startswith("perm_"):
            continue

        # Extract resource_type from unique_id
        # Example: perm_abc123_script_my_script -> resource_type is "script"
        parts = unique_id.split("_", 3)  # ["perm", user_id, resource_type, resource_id]
        if len(parts) >= 3:
            resource_type = parts[2]
            if resource_type in obsolete_types:
                entities_to_remove.append(entity_id)

    # Remove obsolete entities
    if entities_to_remove:
        _LOGGER.info(
            "Cleaning up %d obsolete permission entities (scripts/automations/custom)",
            len(entities_to_remove)
        )
        for entity_id in entities_to_remove:
            entity_registry.async_remove(entity_id)
            _LOGGER.debug("Removed obsolete permission entity: %s", entity_id)
    else:
        _LOGGER.debug("No obsolete permission entities found")


def _get_panel_title(hass: HomeAssistant) -> str:
    """Get panel title based on HA language setting."""
    language = hass.config.language or "en"
    if language.startswith("zh"):
        return PANEL_TITLE_ZH
    return PANEL_TITLE


def _get_control_panel_title(hass: HomeAssistant) -> str:
    """Get control panel title based on HA language setting."""
    language = hass.config.language or "en"
    if language.startswith("zh"):
        return CONTROL_PANEL_TITLE_ZH
    return CONTROL_PANEL_TITLE


# Key for frontend panels storage (internal HA structure)
_FRONTEND_PANELS_KEY = "frontend_panels"


def _get_frontend_panels(hass: HomeAssistant) -> dict[str, Any]:
    """Get frontend panels using available API.

    Note: This accesses hass.data["frontend_panels"] which is an internal API.
    We wrap it in a helper function to centralize the access point and make
    it easier to update if HA provides a public API in the future.
    """
    return hass.data.get(_FRONTEND_PANELS_KEY, {})


# Event types
EVENT_AREA_REGISTRY_UPDATED = "area_registry_updated"
EVENT_LABEL_REGISTRY_UPDATED = "label_registry_updated"
EVENT_USER_ADDED = "user_added"
EVENT_USER_REMOVED = "user_removed"
EVENT_USER_UPDATED = "user_updated"
EVENT_LOVELACE_UPDATED = "lovelace_updated"
EVENT_PANELS_UPDATED = "panels_updated"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Permission Manager from a config entry."""
    _LOGGER.info("Setting up ha_permission_manager v1.0.2")

    # Initialize data storage
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["entry"] = entry
    hass.data[DOMAIN]["unsubscribe"] = []

    # Initialize Store for persistent permission storage
    store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
    hass.data[DOMAIN]["store"] = store

    # Load permissions from persistent storage
    stored_data = await store.async_load()
    if stored_data is not None:
        hass.data[DOMAIN]["permissions"] = stored_data.get("permissions", {})
        _LOGGER.debug(
            "Loaded %d user permission sets from storage",
            len(hass.data[DOMAIN]["permissions"])
        )
    else:
        hass.data[DOMAIN]["permissions"] = {}
        _LOGGER.debug("No existing permissions found, starting fresh")

    # Cleanup obsolete script/automation permission entities (v1.0.0 migration)
    await _async_cleanup_obsolete_permissions(hass)

    # Register WebSocket API
    async_register_websocket_api(hass)

    # Register HA Services (call_service API)
    await async_register_services(hass)

    # Register the sidebar panel
    await _async_register_panel(hass)

    # Set up event listeners for auto-refresh
    await _async_setup_listeners(hass)

    _LOGGER.info("ha_permission_manager setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading ha_permission_manager")

    # Unsubscribe from all event listeners (with safety check)
    domain_data = hass.data.get(DOMAIN, {})
    for unsub in domain_data.get("unsubscribe", []):
        unsub()

    # Unregister services
    async_unregister_services(hass)

    # Remove panels
    async_remove_panel(hass, PANEL_URL)
    async_remove_panel(hass, CONTROL_PANEL_URL)

    # Clean up stored data
    hass.data.pop(DOMAIN, None)

    return True


async def _async_setup_listeners(hass: HomeAssistant) -> None:
    """Set up event listeners for registry changes."""

    async def _handle_area_registry_update(event: Event) -> None:
        """Handle area registry changes."""
        try:
            action = event.data.get("action")
            area_id = event.data.get("area_id")

            _LOGGER.debug("Area registry update: action=%s, area_id=%s", action, area_id)

            if action == "remove":
                resource_id = f"{PREFIX_AREA}{area_id}"
                # Clean up permissions from Store
                await async_delete_resource_permissions(hass, resource_id)
        except Exception:
            _LOGGER.exception("Error handling area registry update")

    async def _handle_label_registry_update(event: Event) -> None:
        """Handle label registry changes."""
        try:
            action = event.data.get("action")
            label_id = event.data.get("label_id")

            _LOGGER.debug("Label registry update: action=%s, label_id=%s", action, label_id)

            if action == "remove":
                resource_id = f"{PREFIX_LABEL}{label_id}"
                # Clean up permissions from Store
                await async_delete_resource_permissions(hass, resource_id)
        except Exception:
            _LOGGER.exception("Error handling label registry update")

    async def _handle_user_added(event: Event) -> None:
        """Handle new user added."""
        try:
            user_id = event.data.get("user_id")
            _LOGGER.debug("User added: user_id=%s", user_id)
            # New users will be visible in the permission manager UI
            # No entity creation needed - permissions are managed via Store
        except Exception:
            _LOGGER.exception("Error handling user added event")

    async def _handle_user_removed(event: Event) -> None:
        """Handle user removed."""
        try:
            user_id = event.data.get("user_id")
            _LOGGER.debug("User removed: user_id=%s", user_id)

            if user_id:
                # Clean up permissions from Store
                await async_delete_user_permissions(hass, user_id)
        except Exception:
            _LOGGER.exception("Error handling user removed event")

    async def _handle_user_updated(event: Event) -> None:
        """Handle user updated (including admin status and name changes)."""
        try:
            user_id = event.data.get("user_id")
            _LOGGER.debug("User updated event: user_id=%s", user_id)
            # User info changes are reflected in permission manager UI dynamically
            # No entity updates needed - permissions are managed via Store
        except Exception:
            _LOGGER.exception("Error handling user updated event")

    async def _handle_lovelace_updated(event: Event) -> None:
        """Handle lovelace dashboard changes (create/delete)."""
        try:
            action = event.data.get("action")
            url_path = event.data.get("url_path")

            _LOGGER.debug("Lovelace updated: action=%s, url_path=%s", action, url_path)

            if not url_path:
                _LOGGER.debug("No url_path in lovelace_updated event, skipping")
                return

            if action == "delete":
                resource_id = f"{PREFIX_PANEL}{url_path}"
                # Clean up permissions from Store
                await async_delete_resource_permissions(hass, resource_id)
                _LOGGER.info("Removed permissions for deleted dashboard: %s", url_path)

        except Exception:
            _LOGGER.exception("Error handling lovelace updated event")

    async def _handle_panels_updated(event: Event) -> None:
        """Handle panel registry changes - clean up deleted panels."""
        try:
            _LOGGER.debug("Panels updated event received")
            # Panel deletion cleanup is handled via lovelace_updated event
            # This handler is kept for potential future use
        except Exception:
            _LOGGER.exception("Error handling panels updated event")

    # Subscribe to events
    unsub_area = hass.bus.async_listen(
        EVENT_AREA_REGISTRY_UPDATED, _handle_area_registry_update
    )
    unsub_label = hass.bus.async_listen(
        EVENT_LABEL_REGISTRY_UPDATED, _handle_label_registry_update
    )
    unsub_user_added = hass.bus.async_listen(
        EVENT_USER_ADDED, _handle_user_added
    )
    unsub_user_removed = hass.bus.async_listen(
        EVENT_USER_REMOVED, _handle_user_removed
    )
    unsub_user_updated = hass.bus.async_listen(
        EVENT_USER_UPDATED, _handle_user_updated
    )
    unsub_lovelace = hass.bus.async_listen(
        EVENT_LOVELACE_UPDATED, _handle_lovelace_updated
    )
    unsub_panels = hass.bus.async_listen(
        EVENT_PANELS_UPDATED, _handle_panels_updated
    )

    # Store unsubscribe functions
    hass.data[DOMAIN]["unsubscribe"].extend([
        unsub_area,
        unsub_label,
        unsub_user_added,
        unsub_user_removed,
        unsub_user_updated,
        unsub_lovelace,
        unsub_panels,
    ])

    _LOGGER.debug("Event listeners registered for area, label, user, lovelace, panels")


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the frontend panels."""
    # Register static path for JS files (skip if already registered)
    try:
        await hass.http.async_register_static_paths([
            # Lit library bundle (shared by all panels, no CDN dependency)
            StaticPathConfig(
                "/local/lit.js",
                hass.config.path(
                    "custom_components/ha_permission_manager/www/lit.js"
                ),
                True,  # cache headers enabled for library bundle
            ),
            StaticPathConfig(
                "/local/ha_permission_manager.js",
                hass.config.path(
                    "custom_components/ha_permission_manager/www/ha_permission_manager.js"
                ),
                False,
            ),
            StaticPathConfig(
                "/local/ha_sidebar_filter.js",
                hass.config.path(
                    "custom_components/ha_permission_manager/www/ha_sidebar_filter.js"
                ),
                False,
            ),
            StaticPathConfig(
                "/local/ha_access_denied.js",
                hass.config.path(
                    "custom_components/ha_permission_manager/www/ha_access_denied.js"
                ),
                False,
            ),
            StaticPathConfig(
                "/local/ha_lovelace_filter.js",
                hass.config.path(
                    "custom_components/ha_permission_manager/www/ha_lovelace_filter.js"
                ),
                False,
            ),
            # Unified Control Panel JS
            StaticPathConfig(
                "/local/ha_control_panel.js",
                hass.config.path(
                    "custom_components/ha_permission_manager/www/ha_control_panel.js"
                ),
                False,
            ),
            # Sidebar title translation JS
            StaticPathConfig(
                "/local/ha_sidebar_title.js",
                hass.config.path(
                    "custom_components/ha_permission_manager/www/sidebar-title.js"
                ),
                False,
            ),
        ])
    except RuntimeError:
        # Path already registered from previous load
        _LOGGER.debug("Static path already registered, skipping")

    # Register the Permission Manager admin panel
    # Only register if not already registered
    if PANEL_URL not in _get_frontend_panels(hass):
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=_get_panel_title(hass),
            sidebar_icon=PANEL_ICON,
            frontend_url_path=PANEL_URL,
            config={
                "_panel_custom": {
                    "name": "ha-permission-manager",
                    "module_url": f"/local/ha_permission_manager.js?v={PANEL_VERSION}",
                }
            },
            require_admin=True,
        )

    # Register the unified Control Panel (for all users)
    # This replaces the separate ha_area_control and ha_label_control panels
    if CONTROL_PANEL_URL not in _get_frontend_panels(hass):
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=_get_control_panel_title(hass),
            sidebar_icon=CONTROL_PANEL_ICON,
            frontend_url_path=CONTROL_PANEL_URL,
            config={
                "_panel_custom": {
                    "name": "ha-control-panel",
                    "module_url": f"/local/ha_control_panel.js?v={PANEL_VERSION}",
                }
            },
            require_admin=False,
        )

    # Register sidebar filter as extra JS (runs on every page)
    # Use version query param for cache busting
    add_extra_js_url(hass, f"/local/ha_sidebar_filter.js?v={PANEL_VERSION}")

    # Register lovelace filter as extra JS (runs on every page)
    add_extra_js_url(hass, f"/local/ha_lovelace_filter.js?v={PANEL_VERSION}")

    # Register sidebar title translation JS (runs on every page)
    cache_buster = int(time.time())
    add_extra_js_url(hass, f"/local/ha_sidebar_title.js?v={cache_buster}")

    _LOGGER.debug("Frontend panels registered")


# =============================================================================
# Permission CRUD Functions (Store-based)
# =============================================================================


async def async_get_permission(
    hass: HomeAssistant, user_id: str, resource_id: str
) -> int:
    """Get permission level for a user and resource.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to check.
        resource_id: The resource ID (e.g., "area_living_room", "panel_config").

    Returns:
        Permission level (0=Closed, 1=View). Defaults to PERM_CLOSED if not set.
    """
    domain_data = hass.data.get(DOMAIN, {})
    permissions = domain_data.get("permissions", {})
    user_perms = permissions.get(user_id, {})
    return user_perms.get(resource_id, PERM_CLOSED)


async def async_set_permission(
    hass: HomeAssistant, user_id: str, resource_id: str, level: int
) -> None:
    """Set permission level for a user and resource.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to set permission for.
        resource_id: The resource ID (e.g., "area_living_room", "panel_config").
        level: Permission level (0=Closed, 1=View).
    """
    domain_data = hass.data.get(DOMAIN, {})
    permissions = domain_data.setdefault("permissions", {})

    if user_id not in permissions:
        permissions[user_id] = {}

    permissions[user_id][resource_id] = level
    _LOGGER.debug(
        "Set permission: user=%s, resource=%s, level=%d",
        user_id, resource_id, level
    )

    # Schedule async save
    await async_save_permissions(hass)

    # Fire event so frontends can react immediately (replaces polling)
    hass.bus.async_fire("permission_manager_updated", {
        "user_id": user_id,
        "resource_id": resource_id,
        "level": level,
    })


@callback
def async_get_all_permissions(hass: HomeAssistant) -> dict[str, dict[str, int]]:
    """Get all permissions from storage.

    Args:
        hass: Home Assistant instance.

    Returns:
        Dictionary mapping user_id -> {resource_id: permission_level}.
    """
    domain_data = hass.data.get(DOMAIN, {})
    return domain_data.get("permissions", {})


@callback
def async_get_user_permissions(hass: HomeAssistant, user_id: str) -> dict[str, int]:
    """Get all permissions for a specific user.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to get permissions for.

    Returns:
        Dictionary mapping resource_id -> permission_level.
    """
    domain_data = hass.data.get(DOMAIN, {})
    permissions = domain_data.get("permissions", {})
    return permissions.get(user_id, {})


async def async_delete_user_permissions(hass: HomeAssistant, user_id: str) -> None:
    """Delete all permissions for a user.

    Called when a user is removed from Home Assistant.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to delete permissions for.
    """
    domain_data = hass.data.get(DOMAIN, {})
    permissions = domain_data.get("permissions", {})

    if user_id in permissions:
        del permissions[user_id]
        _LOGGER.info("Deleted all permissions for user: %s", user_id)
        await async_save_permissions(hass)


async def async_delete_resource_permissions(
    hass: HomeAssistant, resource_id: str
) -> None:
    """Delete permissions for a resource from all users.

    Called when a resource (area, label, panel) is removed.

    Args:
        hass: Home Assistant instance.
        resource_id: The resource ID to delete permissions for.
    """
    domain_data = hass.data.get(DOMAIN, {})
    permissions = domain_data.get("permissions", {})

    modified = False
    for user_id in permissions:
        if resource_id in permissions[user_id]:
            del permissions[user_id][resource_id]
            modified = True

    if modified:
        _LOGGER.info("Deleted permissions for resource: %s", resource_id)
        await async_save_permissions(hass)


async def async_save_permissions(hass: HomeAssistant) -> None:
    """Save permissions to persistent storage.

    This uses Store.async_delay_save to batch writes and avoid
    excessive disk I/O when multiple permissions are changed quickly.

    Args:
        hass: Home Assistant instance.
    """
    domain_data = hass.data.get(DOMAIN, {})
    store: Store | None = domain_data.get("store")
    permissions = domain_data.get("permissions", {})

    if store is None:
        _LOGGER.warning("Store not initialized, cannot save permissions")
        return

    def _data_to_save() -> dict[str, Any]:
        """Return the data to save."""
        return {"permissions": permissions}

    # Use async_delay_save with 1 second delay to batch rapid changes
    store.async_delay_save(_data_to_save, 1.0)
    _LOGGER.debug("Scheduled permission save")
