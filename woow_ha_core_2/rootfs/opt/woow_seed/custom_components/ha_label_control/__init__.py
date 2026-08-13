"""The Label Control integration."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PANEL_URL, PANEL_TITLE, PANEL_TITLE_ZH, PANEL_ICON, PANEL_VERSION

_LOGGER = logging.getLogger(__name__)

# Domain name of ha_permission_manager
_PERM_MANAGER_DOMAIN = "ha_permission_manager"


def _get_panel_title(hass: HomeAssistant) -> str:
    """Get panel title based on HA language setting."""
    language = hass.config.language or "en"
    if language.startswith("zh"):
        return PANEL_TITLE_ZH
    return PANEL_TITLE


def _has_permission_manager(hass: HomeAssistant) -> bool:
    """Check if ha_permission_manager is loaded and providing WebSocket handlers."""
    return _PERM_MANAGER_DOMAIN in hass.data


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Label Control component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Label Control from a config entry."""
    _LOGGER.info("Setting up ha_label_control")

    # Register static path for frontend files
    frontend_path = Path(__file__).parent / "frontend"
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                "/ha_label_control",
                str(frontend_path),
                cache_headers=False
            )
        ])
    except RuntimeError:
        _LOGGER.debug("Static path already registered, skipping")

    # Register sidebar panel
    if PANEL_URL not in hass.data.get("frontend_panels", {}):
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=_get_panel_title(hass),
            sidebar_icon=PANEL_ICON,
            frontend_url_path=PANEL_URL,
            config={
                "_panel_custom": {
                    "name": "ha-label-control-panel",
                    "module_url": f"/ha_label_control/ha-label-control-panel.js?v={PANEL_VERSION}",
                }
            },
            require_admin=False,
        )

    # Only register standalone WebSocket commands if ha_permission_manager
    # is NOT loaded. When permission_manager is present, it provides
    # Store-based handlers for label_control/* commands that respect
    # centralized permissions. Registering here would overwrite those.
    if _has_permission_manager(hass):
        _LOGGER.info(
            "ha_permission_manager detected — skipping standalone WebSocket "
            "handler registration (permission_manager provides label_control/* handlers)"
        )
    else:
        _LOGGER.info(
            "ha_permission_manager not detected — registering standalone "
            "WebSocket handlers for label_control/*"
        )
        from .panel import async_register_websocket_commands
        await async_register_websocket_commands(hass)

    # Register sidebar-title.js as extra JS (runs on every page for title translation)
    cache_buster = int(time.time())
    add_extra_js_url(hass, f"/ha_label_control/sidebar-title.js?v={cache_buster}")

    _LOGGER.info("ha_label_control setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading ha_label_control")
    frontend.async_remove_panel(hass, PANEL_URL)
    return True
