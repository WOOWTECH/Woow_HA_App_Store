"""Ha Asset Record - Home Assistant Custom Component for asset management.

Purpose
-------
Manage household assets with warranty tracking, purchase dates,
brand/category classification, and monetary value inside Home Assistant.

Architecture
------------
Single config entry (``single_config_entry: true`` in manifest).  The sole
``AssetCoordinator`` instance is stored in ``hass.data[DOMAIN]`` following
the standard HA singleton pattern (similar to *shopping_list*).

Platforms
~~~~~~~~~
Five entity platforms are forwarded for each tracked asset:
  * **datetime** -- ``purchase_at`` and ``warranty_until``
  * **text**     -- ``brand`` and ``category``
  * **number**   -- ``value`` (monetary worth)

Storage
~~~~~~~
Assets are persisted in ``.storage/ha_asset_record`` via the coordinator's
internal ``Store`` instance.

WebSocket API
~~~~~~~~~~~~~
4 commands are registered in ``websocket.py``:
  * list, create, update, delete

Panel
~~~~~
A custom sidebar panel is registered once per HA instance, guarded by the
``DATA_PANEL_REGISTERED`` flag in ``hass.data``.

Device removal
~~~~~~~~~~~~~~
``async_remove_config_entry_device`` is implemented so that orphaned device
entries (whose underlying asset no longer exists in the coordinator) can be
removed from the *Devices & Services* UI.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import AssetCoordinator
from .panel import async_register_panel, unregister_panel
from .services import async_register_services, async_unregister_services
from .websocket import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

type AssetConfigEntry = ConfigEntry[AssetCoordinator]

# Track if panel and websocket are registered (only once per HA instance)
DATA_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"


async def async_setup_entry(hass: HomeAssistant, entry: AssetConfigEntry) -> bool:
    """Set up Ha Asset Record from a config entry."""
    coordinator = AssetCoordinator(hass, entry)

    # [C-01] The coordinator's async_load handles internal errors gracefully
    # (logs and continues with empty data). However, if an unexpected exception
    # propagates, raise ConfigEntryNotReady so HA will retry setup later.
    try:
        await coordinator.async_load()
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Failed to load asset data: {err}"
        ) from err

    # [H-12] Store coordinator in hass.data[DOMAIN] following standard HA
    # pattern (see shopping_list). This is a single-instance integration.
    hass.data[DOMAIN] = coordinator

    entry.runtime_data = coordinator

    # Register websocket commands, services, and panel (only once)
    if not hass.data.get(DATA_PANEL_REGISTERED):
        async_register_websocket_commands(hass)
        async_register_services(hass)
        await async_register_panel(hass)
        hass.data[DATA_PANEL_REGISTERED] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AssetConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Unregister panel if this is the last entry
    if unload_ok:
        remaining_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining_entries:
            if hass.data.get(DATA_PANEL_REGISTERED):
                # [M-14] unregister_panel is synchronous (no awaits)
                unregister_panel(hass)
                async_unregister_services(hass)
            # [L-04] Clean up tracking keys from hass.data
            hass.data.pop(DATA_PANEL_REGISTERED, None)
            hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: AssetConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow device removal from Device & Services UI for orphaned devices.

    Returns True (allow removal) when the asset no longer exists in the
    coordinator, enabling users to clean up stale device entries manually.
    """
    coordinator: AssetCoordinator = config_entry.runtime_data
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            asset_id = identifier[1]
            if coordinator.get_asset(asset_id) is not None:
                return False
    return True


async def async_update_options(hass: HomeAssistant, entry: AssetConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
