"""Blueprint Manager - Auto-deploy blueprints and management panel."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL

_LOGGER = logging.getLogger(__name__)

BLUEPRINTS_AUTO_SOURCE = Path(__file__).parent / "blueprints" / "automation"
BLUEPRINTS_SCRIPT_SOURCE = Path(__file__).parent / "blueprints" / "script"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Blueprint Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Deploy blueprints (automation + script)
    await hass.async_add_executor_job(_deploy_blueprints, hass)

    # Register services
    from .services import async_register_services
    await async_register_services(hass)

    # Register frontend panel static path
    await hass.http.async_register_static_paths(
        [StaticPathConfig(
            url_path="/woow_blueprint_manager",
            path=str(Path(__file__).parent / "frontend"),
            cache_headers=False,
        )]
    )

    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL.lstrip("/"),
        config={
            "_panel_custom": {
                "name": "woow-blueprint-panel",
                "module_url": "/woow_blueprint_manager/woow-blueprint-panel.js",
            }
        },
        require_admin=False,
    )

    # Load sidebar-title.js on every page for dynamic i18n of sidebar title.
    # Cache buster ensures browsers pick up new versions after upgrades.
    cache_buster = int(time.time())
    frontend.add_extra_js_url(
        hass, f"/woow_blueprint_manager/sidebar-title.js?v={cache_buster}"
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    async_remove_panel(hass, PANEL_URL.lstrip("/"))

    # Unregister services
    from .services import async_unregister_services
    async_unregister_services(hass)

    hass.data.pop(DOMAIN, None)
    return True


def _deploy_blueprints(hass: HomeAssistant) -> None:
    """Deploy blueprint YAML files to HA config directory."""
    config_dir = Path(hass.config.path())

    sources = [
        (BLUEPRINTS_AUTO_SOURCE, config_dir / "blueprints" / "automation" / "woowtech"),
        (BLUEPRINTS_SCRIPT_SOURCE, config_dir / "blueprints" / "script" / "woowtech"),
    ]

    deployed = 0
    skipped = 0

    for src_dir, dest_dir in sources:
        if not src_dir.is_dir():
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)

        for src_file in src_dir.glob("*.yaml"):
            dest_file = dest_dir / src_file.name

            if dest_file.exists():
                if src_file.read_bytes() == dest_file.read_bytes():
                    skipped += 1
                    continue

            shutil.copy2(src_file, dest_file)
            deployed += 1

    _LOGGER.info(
        "Blueprint Manager: deployed %d blueprints, skipped %d (unchanged)",
        deployed,
        skipped,
    )
