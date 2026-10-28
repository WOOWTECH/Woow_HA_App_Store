"""The switch platform, fanned out to the Areas that implement it.

Home Assistant discovers platforms at ``<domain>/switch.py``, so one module has
to cover every Area exposing switch entities: note.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WoowHaRecordsConfigEntry
from .areas.note.switch import async_setup_area as _setup_note


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WoowHaRecordsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities for every Area that has them."""
    await _setup_note(hass, entry.runtime_data.note, async_add_entities)
