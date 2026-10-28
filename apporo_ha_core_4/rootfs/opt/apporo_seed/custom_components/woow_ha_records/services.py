"""Service registration for all four Areas.

Each Area module exports a ``SERVICE_HANDLERS`` mapping of bare verb to
``(handler, response_type, schema)``. The Area prefix is applied here, in one
place: four verbs collided across the pre-merge domains (``export_csv``,
``create_category``, ``delete_category``, ``list_categories``), so every
service carries its Area.

Every service is registered *with* its schema. Without one, Home Assistant
passes ``call.data`` through untouched: an unknown field is dropped and the
call still reports success, and a missing required field surfaces as the
``KeyError`` the handler raises indexing ``call.data``. Issue #44.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .areas.asset.services import SERVICE_HANDLERS as ASSET_SERVICES
from .areas.finance.services import SERVICE_HANDLERS as FINANCE_SERVICES
from .areas.health.services import SERVICE_HANDLERS as HEALTH_SERVICES
from .areas.note.services import SERVICE_HANDLERS as NOTE_SERVICES
from .const import (
    AREA_ASSET,
    AREA_FINANCE,
    AREA_HEALTH,
    AREA_NOTE,
    DOMAIN,
    service_name,
)

_LOGGER = logging.getLogger(__name__)

_AREA_SERVICES = {
    AREA_FINANCE: FINANCE_SERVICES,
    AREA_ASSET: ASSET_SERVICES,
    AREA_HEALTH: HEALTH_SERVICES,
    AREA_NOTE: NOTE_SERVICES,
}


def async_register_services(hass: HomeAssistant) -> None:
    """Register every Area's services under the integration's domain."""
    count = 0
    for area, handlers in _AREA_SERVICES.items():
        for verb, (handler, response_type, schema) in handlers.items():
            hass.services.async_register(
                DOMAIN,
                service_name(area, verb),
                handler,
                schema=schema,
                supports_response=response_type,
            )
            count += 1
    _LOGGER.debug("Registered %d services for %s", count, DOMAIN)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove every service this integration registered."""
    for area, handlers in _AREA_SERVICES.items():
        for verb in handlers:
            hass.services.async_remove(DOMAIN, service_name(area, verb))
