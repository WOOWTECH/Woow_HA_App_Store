"""Sidebar panels for the four Areas.

The four integrations each registered their own panel with near-identical code.
One table drives all four now. The sidebar paths are deliberately unchanged
across the merge — users bookmark them and dashboards link to them.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import AREAS, DOMAIN, FRONTEND_BASE_URL

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PanelSpec:
    """One Area's sidebar panel."""

    area: str
    url_path: str
    component: str
    bundle: str
    title: str
    icon: str


PANELS: tuple[PanelSpec, ...] = (
    PanelSpec(
        area="finance",
        url_path="ha-finance",
        component="ha-finance-panel",
        bundle="ha-finance-panel.js",
        title="Finance Record",
        icon="mdi:finance",
    ),
    PanelSpec(
        area="asset",
        url_path="ha-asset-record",
        component="ha-asset-panel",
        bundle="ha-asset-panel.js",
        title="Asset Record",
        icon="mdi:package-variant-closed",
    ),
    PanelSpec(
        area="health",
        url_path="ha-health-record",
        component="ha-health-record-panel",
        bundle="ha-health-record-panel.js",
        title="Health Record",
        icon="mdi:heart-pulse",
    ),
    PanelSpec(
        area="note",
        url_path="ha-note-record",
        component="ha-note-record-panel",
        bundle="ha-note-record-panel.js",
        title="Note Record",
        icon="mdi:note-text",
    ),
)


async def async_setup_panels(hass: HomeAssistant) -> None:
    """Serve each Area's bundle and register its sidebar entry."""
    frontend_root = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"{FRONTEND_BASE_URL}/{area}",
                str(frontend_root / area),
                cache_headers=False,
            )
            for area in AREAS
        ]
    )

    # Bust the browser cache so a redeployed bundle is actually fetched.
    cache_buster = int(time.time())

    for spec in PANELS:
        base = f"{FRONTEND_BASE_URL}/{spec.area}"
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name=spec.component,
            frontend_url_path=spec.url_path,
            sidebar_title=spec.title,
            sidebar_icon=spec.icon,
            module_url=f"{base}/{spec.bundle}?v={cache_buster}",
            require_admin=False,
            config={},
        )
        frontend.add_extra_js_url(
            hass, f"{base}/sidebar-title.js?v={cache_buster}"
        )

    _LOGGER.debug("Registered %d panels for %s", len(PANELS), DOMAIN)


def async_unload_panels(hass: HomeAssistant) -> None:
    """Remove every sidebar entry this integration registered."""
    registered = hass.data.get(frontend.DATA_PANELS, {})
    for spec in PANELS:
        if spec.url_path in registered:
            frontend.async_remove_panel(hass, spec.url_path)
