"""The datetime platform, fanned out to the Areas that implement it.

Home Assistant discovers platforms at ``<domain>/datetime.py``, so one module has
to cover every Area exposing datetime entities: asset.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WoowHaRecordsConfigEntry
from .areas.asset.datetime import async_setup_area as _setup_asset


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WoowHaRecordsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up datetime entities for every Area that has them."""
    await _setup_asset(hass, entry.runtime_data.asset, async_add_entities)
