"""Panel registration for Ha Note Record."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "ha-note-record"
PANEL_COMPONENT_NAME = "ha-note-record-panel"
PANEL_TITLE = "Note Record"
PANEL_ICON = "mdi:note-text"
PANEL_VERSION = "1.0.0"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the panel."""
    frontend_dir = Path(__file__).parent / "frontend"

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}/frontend",
                str(frontend_dir),
                cache_headers=False,
            )
        ]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_COMPONENT_NAME,
        frontend_url_path=PANEL_URL_PATH,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"/{DOMAIN}/frontend/ha-note-record-panel.js?v={PANEL_VERSION}",
        require_admin=False,
        config={},
    )

    # Register sidebar title i18n script (runs on every page)
    cache_buster = int(time.time())
    frontend.add_extra_js_url(
        hass, f"/{DOMAIN}/frontend/sidebar-title.js?v={cache_buster}"
    )

    _LOGGER.info("Registered Ha Note Record panel")


async def async_unregister_panel(hass: HomeAssistant) -> bool:
    """Unregister the panel."""
    if PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        _LOGGER.info("Unregistered Ha Note Record panel")
        return True
    return False
