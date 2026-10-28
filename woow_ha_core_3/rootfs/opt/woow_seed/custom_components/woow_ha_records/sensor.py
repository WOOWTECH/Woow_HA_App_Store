"""The sensor platform, fanned out to the Areas that implement it.

Home Assistant discovers platforms at ``<domain>/sensor.py``, so one module has
to cover every Area exposing sensor entities: finance, health.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WoowHaRecordsConfigEntry
from .areas.finance.sensor import async_setup_area as _setup_finance
from .areas.health.sensor import async_setup_area as _setup_health


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WoowHaRecordsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities for every Area that has them."""
    await _setup_finance(hass, entry.runtime_data.finance, async_add_entities)
    await _setup_health(hass, entry.runtime_data.health, async_add_entities)
