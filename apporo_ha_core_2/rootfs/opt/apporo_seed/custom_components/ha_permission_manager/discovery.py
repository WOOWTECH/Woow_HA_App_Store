"""Resource discovery for ha_permission_manager."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import label_registry as lr

from .const import (
    PREFIX_AREA,
    PREFIX_LABEL,
    PREFIX_PANEL,
    SELF_PANEL_ID,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class Resource:
    """Represents a protectable resource."""
    id: str
    name: str
    type: str  # "area" | "label" | "panel"


def discover_areas(hass: HomeAssistant) -> list[Resource]:
    """Discover all areas."""
    registry = ar.async_get(hass)
    resources = []
    for area in registry.async_list_areas():
        resources.append(
            Resource(
                id=f"{PREFIX_AREA}{area.id}",
                name=area.name,
                type="area",
            )
        )
    _LOGGER.debug("Discovered %d areas", len(resources))
    return resources


def discover_labels(hass: HomeAssistant) -> list[Resource]:
    """Discover all labels."""
    registry = lr.async_get(hass)
    resources = []
    for label in registry.async_list_labels():
        resources.append(
            Resource(
                id=f"{PREFIX_LABEL}{label.label_id}",
                name=label.name,
                type="label",
            )
        )
    _LOGGER.debug("Discovered %d labels", len(resources))
    return resources


def discover_panels(hass: HomeAssistant) -> list[Resource]:
    """Discover all sidebar panels."""
    resources = []

    # Try multiple locations where panels might be stored
    panels = {}

    # Method 1: frontend_panels (modern HA)
    if "frontend_panels" in hass.data:
        panels = hass.data["frontend_panels"]
    # Method 2: frontend -> panels
    elif "frontend" in hass.data:
        frontend_data = hass.data["frontend"]
        if isinstance(frontend_data, dict):
            panels = frontend_data.get("panels", {})
        elif hasattr(frontend_data, "panels"):
            panels = frontend_data.panels or {}

    _LOGGER.debug("Found panels data: %s", list(panels.keys()) if panels else "None")

    for panel_id, panel in panels.items():
        # Skip our own panel (we'll add it manually)
        if panel_id == "ha_permission_manager":
            continue

        # Get panel title
        title = panel_id
        if isinstance(panel, dict):
            title = panel.get("title") or panel.get("sidebar_title") or panel_id
        elif hasattr(panel, "title"):
            title = panel.title or panel_id
        elif hasattr(panel, "sidebar_title"):
            title = panel.sidebar_title or panel_id

        resources.append(
            Resource(
                id=f"{PREFIX_PANEL}{panel_id}",
                name=str(title),
                type="panel",
            )
        )

    # Always add self-reference
    resources.append(
        Resource(
            id=SELF_PANEL_ID,
            name="Permission Manager",
            type="panel",
        )
    )

    _LOGGER.debug("Discovered %d panels (including self)", len(resources))
    return resources


def discover_all_resources(hass: HomeAssistant) -> dict[str, list[Resource]]:
    """Discover all protectable resources grouped by type."""
    return {
        "areas": discover_areas(hass),
        "labels": discover_labels(hass),
        "panels": discover_panels(hass),
    }
