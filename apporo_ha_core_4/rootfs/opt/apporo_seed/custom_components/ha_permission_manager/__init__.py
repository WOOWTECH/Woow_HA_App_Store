"""The ha_permission_manager integration."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import (
    add_extra_js_url,
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant, Event, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    FRONTEND_URL_BASE,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_TITLE_ZH,
    PANEL_URL,
    PANEL_VERSION,
    PERM_CLOSED,
    PREFIX_AREA,
    PREFIX_LABEL,
    STORAGE_KEY,
    STORAGE_VERSION,
    # Control Panel constants
    CONTROL_PANEL_URL,
    CONTROL_PANEL_TITLE,
    CONTROL_PANEL_TITLE_ZH,
    CONTROL_PANEL_ICON,
)
from . import permission_store
from .discovery import get_registered_panels
from .panel_gate import (
    EVENT_PANELS_UPDATED,
    async_broadcast_panels_changed,
    async_install_panel_gate,
    async_panel_gate_store_loaded,
    async_restore_panel_gate,
    async_stop_panel_broadcasts,
)
from .panel_policy import deleted_dashboard_resource_id
from .permission_store import EVENT_PERMISSION_MANAGER_UPDATED
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


# Event types
EVENT_AREA_REGISTRY_UPDATED = "area_registry_updated"
EVENT_LABEL_REGISTRY_UPDATED = "label_registry_updated"
EVENT_USER_ADDED = "user_added"
EVENT_USER_REMOVED = "user_removed"
EVENT_USER_UPDATED = "user_updated"
EVENT_LOVELACE_UPDATED = "lovelace_updated"
# EVENT_PANELS_UPDATED is imported from panel_gate, which owns it and is the
# only place in this integration that fires it. The listener below is the one
# other use of the name here, and it has done nothing since it was written.


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Install the Panel Gate, before anything can ask for a panel list.

    This runs before any config entry is set up, which is the whole reason it
    exists: the Gate has to be answering `get_panels` before the store is read,
    before the services are registered and before our own panels are. A browser
    that reconnects through any of that reads whatever is answering at the time
    and has no reason to ask again — `85d4977` caught exactly that.

    It runs once per Home Assistant lifetime, so `async_setup_entry` installs
    too: a disable/enable cycle never comes back through here.
    """
    async_install_panel_gate(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Permission Manager from a config entry."""
    _LOGGER.info("Setting up ha_permission_manager v1.0.2")

    # Initialize data storage
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["entry"] = entry
    hass.data[DOMAIN]["unsubscribe"] = []

    # Re-enabling the integration comes back through here and not through
    # async_setup, so the Gate is installed again — and ahead of the store
    # read, so the window in which a non-administrator is refused is the same
    # window either way, rather than one in which they are served.
    async_install_panel_gate(hass)

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

    # The Gate can answer from now on. Until this line it refuses every
    # non-administrator, so whoever asked inside that window is holding the
    # degraded set and has to be told to ask again.
    async_panel_gate_store_loaded(hass)

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

    # Drop any panels broadcast still waiting on the debounce, before the
    # restore below fires one of its own. Not awaited: see the docstring.
    async_stop_panel_broadcasts(hass)

    # Hand `get_panels` back to Home Assistant. Ahead of the pop below, which
    # throws away the record of what to put back. Every restriction lifts here:
    # disabling this integration is how an administrator recovers an instance
    # they have locked themselves out of.
    async_restore_panel_gate(hass)

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
        """Forget the Permissions of a dashboard Home Assistant no longer has.

        The event says only which dashboard changed — `{"url_path": ...}`, the
        same on a save as on a delete. This handler used to read an `action`
        key that Home Assistant has never sent, so the deletion branch was
        never taken and every deleted dashboard kept its rows (issue #8).
        deleted_dashboard_resource_id holds what is read instead, and why.

        Two things belong here rather than in that decision, because both are
        about this Home Assistant rather than about dashboards: nothing is
        deleted unless the instance is running, and a registry that cannot be
        read is reported rather than passed over in silence.
        """
        try:
            url_path = event.data.get("url_path")
            _LOGGER.debug("Lovelace updated: url_path=%s", url_path)

            # A dashboard is deleted by someone using a running instance. The
            # registry is still filling during startup — `lovelace` is not a
            # dependency of this integration, deliberately, so that the Panel
            # Gate is installed before anything can ask for a panel list — and
            # a dashboard whose panel has not been registered yet is
            # indistinguishable from one that has been deleted.
            if hass.state is not CoreState.running:
                _LOGGER.debug(
                    "Lovelace updated for %s while Home Assistant is %s, not "
                    "while it is running: leaving its Permissions alone",
                    url_path, hass.state,
                )
                return

            panels = get_registered_panels(hass)
            # Reported rather than skipped in silence: with no registry to read,
            # every save looks like a deletion, and this is the one shape that
            # would cost a live dashboard its Permissions. The refusal itself
            # belongs to deleted_dashboard_resource_id, which makes it again.
            if url_path and not panels:
                _LOGGER.warning(
                    "lovelace_updated for %s arrived with no readable panel "
                    "registry; leaving its Permissions alone",
                    url_path,
                )

            resource_id = deleted_dashboard_resource_id(url_path, panels)
            if resource_id is None:
                return

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
    # Serve the whole frontend directory under our own URL prefix.
    # Deliberately NOT /local/: that namespace belongs to the user's config/www
    # folder, and borrowing it forced a hardcoded install path that breaks
    # anywhere the integration is not at config/custom_components/.
    frontend_path = Path(__file__).parent / "frontend"
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(FRONTEND_URL_BASE, str(frontend_path), False)
        ])
    except RuntimeError:
        # Path already registered from previous load
        _LOGGER.debug("Static path already registered, skipping")

    # Register the Permission Manager admin panel
    # Only register if not already registered
    if PANEL_URL not in get_registered_panels(hass):
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=_get_panel_title(hass),
            sidebar_icon=PANEL_ICON,
            frontend_url_path=PANEL_URL,
            config={
                "_panel_custom": {
                    "name": "ha-permission-manager",
                    "module_url": f"{FRONTEND_URL_BASE}/ha_permission_manager.js?v={PANEL_VERSION}",
                }
            },
            require_admin=True,
        )

    # Register the unified Control Panel (for all users)
    # The only device-control surface this integration ships (see ADR-0002)
    if CONTROL_PANEL_URL not in get_registered_panels(hass):
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=_get_control_panel_title(hass),
            sidebar_icon=CONTROL_PANEL_ICON,
            frontend_url_path=CONTROL_PANEL_URL,
            config={
                "_panel_custom": {
                    "name": "ha-control-panel",
                    "module_url": f"{FRONTEND_URL_BASE}/ha_control_panel.js?v={PANEL_VERSION}",
                }
            },
            require_admin=False,
        )

    # The one asset this integration puts on a page it does not own. It
    # translates the sidebar titles of the two panels above and decides nothing
    # about access — the Panel Gate did that before the panel map left Home
    # Assistant (ADR-0011). Until v2.0.13 two Filters were injected here too.
    #
    # Busted by PANEL_VERSION like every other asset, rather than by a restart
    # timestamp: one bump has to move the whole graph, or the version query
    # stops being the thing that says which release a browser is running.
    add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/sidebar-title.js?v={PANEL_VERSION}")

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


async def _async_write(
    hass: HomeAssistant,
    write: Callable[[permission_store.Permissions], dict[str, Any]],
) -> dict[str, Any]:
    """Apply one write to the Permission store, persist it, and announce it.

    The only way this integration writes the store. Persisting and announcing
    live here rather than in each helper so that a write path cannot be added
    without both — issue #14, where two of five write paths were added without
    the announcement, and the two were the revocations.

    `write` is one of the functions in permission_store: it mutates the map and
    returns what to announce, which is returned here too so the caller can log
    what it did.

    Args:
        hass: Home Assistant instance.
        write: A permission_store write, already bound to its arguments.

    Returns:
        The announcement that was fired.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    permissions = domain_data.setdefault("permissions", {})

    announcement = write(permissions)

    # Schedule async save
    await async_save_permissions(hass)

    # Fire event so frontends can react immediately (replaces polling). The
    # payload is diagnostic: every consumer re-fetches — see ADR-0010.
    hass.bus.async_fire(EVENT_PERMISSION_MANAGER_UPDATED, announcement)

    # And the same thing again for everybody Home Assistant will not let hear
    # that one. A non-administrator's subscription to the announcement above is
    # refused (#13), and a revocation is about a non-administrator, so the
    # panels event is the only channel that reaches them. Debounced, and fired
    # for every write for the reason the announcement is: a decision in front
    # of it is how two write paths came to be silent (ADR-0010).
    await async_broadcast_panels_changed(hass)

    return announcement


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
    await _async_write(
        hass,
        lambda permissions: permission_store.set_permission(
            permissions, user_id, resource_id, level
        ),
    )
    _LOGGER.debug(
        "Set permission: user=%s, resource=%s, level=%d",
        user_id, resource_id, level
    )


async def async_bulk_set_permissions(
    hass: HomeAssistant, entries: list[dict[str, Any]]
) -> None:
    """Set many permission levels, saving and announcing once for the batch.

    Args:
        hass: Home Assistant instance.
        entries: Dicts of user_id, resource_id and level, already validated.
    """
    announcement = await _async_write(
        hass,
        lambda permissions: permission_store.bulk_set_permissions(permissions, entries),
    )
    # Debug, like async_set_permission: the only caller is the service handler,
    # and it logs the call itself. The delete helpers below log at info because
    # the registry listeners reach them with nothing else recording it.
    _LOGGER.debug("Bulk set %d permission entries", announcement["count"])


async def async_reset_all_permissions(hass: HomeAssistant) -> None:
    """Clear the entire Permission store.

    Args:
        hass: Home Assistant instance.
    """
    announcement = await _async_write(hass, permission_store.reset_all_permissions)
    _LOGGER.debug("Cleared all permissions: %d users affected", announcement["count"])


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

    Called when a user is removed from Home Assistant, and by the
    remove_user_permissions service.

    Args:
        hass: Home Assistant instance.
        user_id: The user ID to delete permissions for.
    """
    announcement = await _async_write(
        hass,
        lambda permissions: permission_store.remove_user_permissions(
            permissions, user_id
        ),
    )
    _LOGGER.info(
        "Deleted all permissions for user %s: %d resources",
        user_id, announcement["count"],
    )


async def async_delete_resource_permissions(
    hass: HomeAssistant, resource_id: str
) -> None:
    """Delete permissions for a resource from all users.

    Called when a resource (area, label, panel) is removed, and by the
    remove_resource_permissions service.

    Args:
        hass: Home Assistant instance.
        resource_id: The resource ID to delete permissions for.
    """
    announcement = await _async_write(
        hass,
        lambda permissions: permission_store.remove_resource_permissions(
            permissions, resource_id
        ),
    )
    _LOGGER.info(
        "Deleted permissions for resource %s: %d users",
        resource_id, announcement["count"],
    )


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
