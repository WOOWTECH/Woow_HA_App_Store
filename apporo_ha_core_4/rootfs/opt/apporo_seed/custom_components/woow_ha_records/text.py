"""The text platform, fanned out to the Areas that implement it.

Home Assistant discovers platforms at ``<domain>/text.py``, so one module has
to cover every Area exposing text entities: asset, health, note.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WoowHaRecordsConfigEntry
from .areas.asset.text import async_setup_area as _setup_asset
from .areas.health.text import async_setup_area as _setup_health
from .areas.note.text import async_setup_area as _setup_note


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WoowHaRecordsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up text entities for every Area that has them."""
    await _setup_asset(hass, entry.runtime_data.asset, async_add_entities)
    await _setup_health(hass, entry.runtime_data.health, async_add_entities)
    await _setup_note(hass, entry.runtime_data.note, async_add_entities)
