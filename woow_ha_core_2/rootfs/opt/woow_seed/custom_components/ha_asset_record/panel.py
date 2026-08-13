"""Panel registration for Ha Asset Record."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path


from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "ha-asset-record"
PANEL_COMPONENT_NAME = "ha-asset-panel"
PANEL_TITLE = "Asset Record"
PANEL_ICON = "mdi:devices"

# [M-13] Key to track whether the static path has already been registered
_DATA_STATIC_REGISTERED = f"{DOMAIN}_static_registered"


def _get_panel_version() -> str:
    """Derive panel version from manifest.json.

    [M-15] Read the version from manifest.json instead of hardcoding it.
    Falls back to "0.0.0" if the manifest cannot be read.

    Note: This is called at module-load time (not from the event loop)
    to avoid blocking I/O warnings.
    """
    manifest_path = Path(__file__).parent / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest.get("version", "0.0.0")
    except (FileNotFoundError, json.JSONDecodeError, OSError) as err:
        _LOGGER.warning("Could not read manifest.json for version: %s", err)
        return "0.0.0"


# Read version once at import time (synchronous I/O is fine here,
# outside the event loop).
_PANEL_VERSION = _get_panel_version()


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the panel."""
    # Get the frontend directory path
    frontend_dir = Path(__file__).parent / "frontend"

    # [M-15] Use pre-loaded version from module import
    panel_version = _PANEL_VERSION

    # [M-13] Guard static path registration for idempotency.
    # Registering the same static path twice would raise an error.
    if not hass.data.get(_DATA_STATIC_REGISTERED):
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                f"/{DOMAIN}/frontend",
                str(frontend_dir),
                cache_headers=False,
            )
        ])
        hass.data[_DATA_STATIC_REGISTERED] = True

    # Register the panel
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_COMPONENT_NAME,
        frontend_url_path=PANEL_URL_PATH,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"/{DOMAIN}/frontend/ha-asset-panel.js?v={panel_version}",
        require_admin=False,
        config={},
    )

    # Register sidebar title i18n script (runs on every page)
    cache_buster = int(time.time())
    frontend.add_extra_js_url(
        hass, f"/{DOMAIN}/frontend/sidebar-title.js?v={cache_buster}"
    )

    _LOGGER.info("Registered Ha Asset Record panel")


@callback
def unregister_panel(hass: HomeAssistant) -> bool:
    """Unregister the panel.

    [M-14] This function is synchronous because frontend.async_remove_panel
    is a @callback (no awaits). Renamed from async_unregister_panel to
    unregister_panel to reflect that it is not a coroutine.
    """
    if PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        # [M-13] Clean up static path registration tracking
        hass.data.pop(_DATA_STATIC_REGISTERED, None)
        _LOGGER.info("Unregistered Ha Asset Record panel")
        return True
    return False
