"""WebSocket command registration for all four Areas.

Commands are named ``woow_ha_records/<area>/<verb>``. The verbs are unchanged
from before the merge — normalising them (asset says ``list`` where health says
``get_members``) would have meant reading four compiled panel bundles rather
than re-prefixing strings in them, and is tracked separately.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback

from .areas.asset.websocket import (
    async_register_websocket_commands as register_asset,
)
from .areas.finance.websocket import (
    async_register_websocket_commands as register_finance,
)
from .areas.health.websocket import register_websocket_commands as register_health
from .areas.note.websocket_api import async_register_websocket_api as register_note

_LOGGER = logging.getLogger(__name__)


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register every Area's WebSocket commands."""
    register_finance(hass)
    register_asset(hass)
    register_health(hass)
    register_note(hass)
    _LOGGER.debug("Registered WebSocket commands for all Areas")
