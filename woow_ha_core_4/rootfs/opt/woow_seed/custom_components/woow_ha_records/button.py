"""The button platform, fanned out to the Areas that implement it.

Home Assistant discovers platforms at ``<domain>/button.py``, so one module has
to cover every Area exposing button entities: health.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WoowHaRecordsConfigEntry
from .areas.health.button import async_setup_area as _setup_health


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WoowHaRecordsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up button entities for every Area that has them."""
    await _setup_health(hass, entry.runtime_data.health, async_add_entities)
