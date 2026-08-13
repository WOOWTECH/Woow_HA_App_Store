"""Ha Note Record integration for Home Assistant.

Purpose
-------
Organize markdown notes into categories within Home Assistant, providing a
lightweight personal knowledge-base accessible from the sidebar.

Architecture
------------
Single config entry.  The ``HaNoteRecordStore`` instance is created during
``async_setup_entry`` and placed in ``hass.data[DOMAIN]["store"]`` so that
both the entity platforms and the WebSocket API can access the same data.

Platforms
~~~~~~~~~
Two entity platforms are forwarded per config entry:
  * **text**   -- note content (markdown body)
  * **switch** -- pinned status (on/off)

Storage
~~~~~~~
Categories and notes are persisted in ``.storage/ha_note_record`` via the
``HaNoteRecordStore`` class.

WebSocket API
~~~~~~~~~~~~~
6 commands are registered in ``websocket_api.py`` via
``async_register_websocket_api()``.

Panel
~~~~~
A custom panel is served via ``panel_custom`` and registered once per HA
instance, guarded by the ``DATA_PANEL_REGISTERED`` flag in ``hass.data``.

Validation limits
~~~~~~~~~~~~~~~~~
* ``MAX_CATEGORY_NAME_LENGTH`` = 100
* ``MAX_NOTE_TITLE_LENGTH``    = 200
* ``MAX_NOTE_CONTENT_LENGTH``  = 100 000
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .panel import async_register_panel, async_unregister_panel
from .services import async_register_services, async_unregister_services
from .store import HaNoteRecordStore
from .websocket_api import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)

type HaNoteRecordConfigEntry = ConfigEntry[HaNoteRecordStore]

DATA_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"
DATA_WS_REGISTERED = f"{DOMAIN}_ws_registered"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Ha Note Record component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HaNoteRecordConfigEntry) -> bool:
    """Set up Ha Note Record from a config entry."""
    store = HaNoteRecordStore(hass)
    await store.async_load()

    entry.runtime_data = store
    hass.data[DOMAIN]["store"] = store

    # Register WebSocket API and services (once, idempotent)
    if not hass.data.get(DATA_WS_REGISTERED):
        async_register_websocket_api(hass)
        async_register_services(hass)
        hass.data[DATA_WS_REGISTERED] = True

    # Register panel (only once) — set flag before await to prevent race
    if not hass.data.get(DATA_PANEL_REGISTERED):
        hass.data[DATA_PANEL_REGISTERED] = True
        await async_register_panel(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaNoteRecordConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Unregister panel and services if this is the last entry
    if unload_ok:
        remaining_entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining_entries:
            if hass.data.get(DATA_PANEL_REGISTERED):
                await async_unregister_panel(hass)
                hass.data[DATA_PANEL_REGISTERED] = False
            async_unregister_services(hass)

    # Clean up hass.data
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop("store", None)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: HaNoteRecordConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
