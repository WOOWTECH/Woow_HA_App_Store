"""Ha Health Record integration for Home Assistant.

Purpose
-------
Track health metrics (weight, blood pressure, exercise, etc.) for family
members inside Home Assistant.

Architecture
------------
Multi-config-entry model -- each config entry represents one family member.
Every entry creates its own ``HealthRecordCoordinator`` that owns the
member's data and persists it independently.

Platforms
~~~~~~~~~
Four entity platforms are forwarded per config entry:
  * **button**  -- trigger a new record log
  * **number**  -- numeric metric value input
  * **text**    -- free-text annotation
  * **sensor**  -- read-only latest-value / statistics

Each record type configured for a member produces one entity on each
platform, so the total entity count is ``4 * len(record_sets)`` per member.

Storage
~~~~~~~
Records are stored in ``.storage/ha_health_record_{member_id}`` via each
coordinator's internal ``Store`` instance.

Migration
~~~~~~~~~
Config-entry version 1 -> 2: the legacy ``activity_sets`` and
``growth_sets`` option keys are merged into a single ``record_sets`` list
(see ``async_migrate_entry``).

Coordinator map
~~~~~~~~~~~~~~~
``hass.data[f"{DOMAIN}_coordinator_map"]`` holds a ``dict[str,
HealthRecordCoordinator]`` keyed by ``member_id``, giving O(1) lookup from
the WebSocket API without scanning all config entries.

WebSocket API
~~~~~~~~~~~~~
12 commands are registered once in ``panel.py`` via
``register_websocket_commands()``.

Panel
~~~~~
A custom sidebar panel is served at ``/ha-health-record``.

Events
~~~~~~
* ``ha_health_record_record_logged``   -- fired after a record is persisted
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_MEMBER_ID,
    CONF_RECORD_NAME,
    CONF_RECORD_SETS,
    CONF_RECORD_TYPE,
    CONF_RECORD_UNIT,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import HealthRecordCoordinator
from .panel import async_setup_panel, async_unload_panel, register_websocket_commands
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

type HaHealthRecordConfigEntry = ConfigEntry[HealthRecordCoordinator]

PLATFORMS_LIST: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.TEXT,
    Platform.SENSOR,
]

# Keys for tracking one-time setup state in hass.data
_KEY_WS_REGISTERED = f"{DOMAIN}_ws_registered"
_KEY_SERVICES_REGISTERED = f"{DOMAIN}_services_registered"
_KEY_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"
KEY_COORDINATOR_MAP = f"{DOMAIN}_coordinator_map"


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrate config entry from v1 to v2."""
    if config_entry.version == 1:
        _LOGGER.info(
            "Migrating config entry %s from version 1 to 2", config_entry.title
        )
        record_sets: list[dict[str, str]] = []

        for act in config_entry.options.get("activity_sets", []):
            record_sets.append(
                {
                    CONF_RECORD_TYPE: act.get("activity_type", ""),
                    CONF_RECORD_NAME: act.get("activity_name", ""),
                    CONF_RECORD_UNIT: act.get("activity_unit", ""),
                }
            )
        for grw in config_entry.options.get("growth_sets", []):
            record_sets.append(
                {
                    CONF_RECORD_TYPE: grw.get("growth_type", ""),
                    CONF_RECORD_NAME: grw.get("growth_name", ""),
                    CONF_RECORD_UNIT: grw.get("growth_unit", ""),
                }
            )

        hass.config_entries.async_update_entry(
            config_entry,
            options={CONF_RECORD_SETS: record_sets},
            version=2,
        )
        _LOGGER.info(
            "Migration complete for %s: %d record sets",
            config_entry.title,
            len(record_sets),
        )

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: HaHealthRecordConfigEntry
) -> bool:
    """Set up Ha Health Record from a config entry."""
    coordinator = HealthRecordCoordinator(hass, entry)
    try:
        await coordinator.async_load()
    except Exception:
        _LOGGER.exception("Failed to load health record data for %s", entry.title)
        return False

    entry.runtime_data = coordinator

    # Register coordinator in lookup dict for O(1) access from WebSocket API
    if KEY_COORDINATOR_MAP not in hass.data:
        hass.data[KEY_COORDINATOR_MAP] = {}
    hass.data[KEY_COORDINATOR_MAP][coordinator.member_id] = coordinator

    # Register WS commands once (they persist across entry reloads)
    if not hass.data.get(_KEY_WS_REGISTERED):
        register_websocket_commands(hass)
        hass.data[_KEY_WS_REGISTERED] = True

    # Register HA services once
    if not hass.data.get(_KEY_SERVICES_REGISTERED):
        async_register_services(hass)
        hass.data[_KEY_SERVICES_REGISTERED] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_LIST)

    # Set up panel only once (for the first entry).
    # Set flag before awaiting to prevent concurrent entries from double-registering.
    if not hass.data.get(_KEY_PANEL_REGISTERED):
        hass.data[_KEY_PANEL_REGISTERED] = True
        try:
            await async_setup_panel(hass)
        except Exception:
            hass.data[_KEY_PANEL_REGISTERED] = False
            raise

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(
    hass: HomeAssistant, entry: HaHealthRecordConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: HaHealthRecordConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS_LIST)

    if unload_ok:
        # Remove coordinator from lookup dict
        coord_map = hass.data.get(KEY_COORDINATOR_MAP, {})
        member_id = entry.data.get(CONF_MEMBER_ID)
        coord_map.pop(member_id, None)

        # Check if any other loaded entries remain
        remaining = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
            and e.state is ConfigEntryState.LOADED
        ]

        # Unload panel and services if no more entries
        if not remaining:
            if hass.data.get(_KEY_PANEL_REGISTERED):
                await async_unload_panel(hass)
                hass.data[_KEY_PANEL_REGISTERED] = False
            if hass.data.get(_KEY_SERVICES_REGISTERED):
                async_unregister_services(hass)
                hass.data[_KEY_SERVICES_REGISTERED] = False

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a config entry and clean up its storage file."""
    member_id = entry.data.get(CONF_MEMBER_ID)
    if member_id:
        store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}_{member_id}"
        )
        await store.async_remove()
