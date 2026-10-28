"""Woow HA Records — household records across four Areas.

One Home Assistant domain, one config entry, four Areas that share a runtime
and nothing else. Before version 2.0 these were four separate integrations;
HACS installs one integration per repository, so distribution meant mirroring
each into its own publish repo. See ADR-0001.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .areas.asset.coordinator import AssetCoordinator
from .areas.finance.area import FinanceArea
from .areas.health.area import HealthArea
from .areas.note.store import HaNoteRecordStore
from .const import DOMAIN, PLATFORMS
from .panel import async_setup_panels, async_unload_panels
from .runtime import WoowRecordsData
from .services import async_register_services, async_unregister_services
from .websocket import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

type WoowHaRecordsConfigEntry = ConfigEntry[WoowRecordsData]


async def async_setup_entry(
    hass: HomeAssistant, entry: WoowHaRecordsConfigEntry
) -> bool:
    """Bring up all four Areas."""
    finance = FinanceArea(hass, entry)
    asset = AssetCoordinator(hass, entry)
    health = HealthArea(hass, entry)
    note = HaNoteRecordStore(hass, entry)

    await finance.async_load()
    await asset.async_load()
    await health.async_load()
    await note.async_load()

    data = WoowRecordsData(finance=finance, asset=asset, health=health, note=note)
    entry.runtime_data = data
    # Service and WebSocket handlers only receive `hass`, so mirror it here.
    hass.data[DOMAIN] = data

    async_register_services(hass)
    async_register_websocket_commands(hass)
    await async_setup_panels(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: WoowHaRecordsConfigEntry
) -> bool:
    """Tear all four Areas down."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    await entry.runtime_data.finance.async_shutdown()

    async_unregister_services(hass)
    async_unload_panels(hass)
    hass.data.pop(DOMAIN, None)

    return True
