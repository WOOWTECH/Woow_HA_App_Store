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
from .panel_policy import unroutable_panel_ids as _unroutable_panel_ids

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


def get_registered_panels(hass: HomeAssistant) -> dict:
    """Return the panels Home Assistant has registered, whatever it keeps them in."""
    # Method 1: frontend_panels (modern HA)
    if "frontend_panels" in hass.data:
        return hass.data["frontend_panels"]

    # Method 2: frontend -> panels
    if "frontend" in hass.data:
        frontend_data = hass.data["frontend"]
        if isinstance(frontend_data, dict):
            return frontend_data.get("panels", {})
        if hasattr(frontend_data, "panels"):
            return frontend_data.panels or {}

    return {}


def unroutable_panel_ids(hass: HomeAssistant) -> set[str]:
    """Panel ids that Home Assistant registers but never routes to.

    The Home Assistant adapter over panel_policy.unroutable_panel_ids, which
    holds the decision itself and is unit tested offline.
    """
    return _unroutable_panel_ids(get_registered_panels(hass))


def discover_panels(hass: HomeAssistant) -> list[Resource]:
    """Discover all sidebar panels."""
    resources = []

    panels = get_registered_panels(hass)
    unroutable = unroutable_panel_ids(hass)

    _LOGGER.debug("Found panels data: %s", list(panels.keys()) if panels else "None")
    if unroutable:
        _LOGGER.debug("Skipping panels Home Assistant does not route to: %s", unroutable)

    for panel_id, panel in panels.items():
        # Skip our own panel (we'll add it manually)
        if panel_id == "ha_permission_manager":
            continue

        # Never offer a Resource whose Permission level cannot be honoured
        if panel_id in unroutable:
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
