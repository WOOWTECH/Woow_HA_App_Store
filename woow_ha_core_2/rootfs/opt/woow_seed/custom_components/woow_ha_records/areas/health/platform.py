"""Shared entity wiring for the health Area's four platforms.

Every health platform exposes the same thing: one entity per Record Type per
Member. Members and Record Types are created and deleted at runtime, so the
entity set has to be reconciled rather than built once at setup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ...const import signal_entities_changed
from .const import AREA

if TYPE_CHECKING:
    from .area import HealthArea
    from .coordinator import HealthRecordCoordinator


async def async_setup_record_entities(
    hass: HomeAssistant,
    area: HealthArea,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[HealthRecordCoordinator, str], Entity],
) -> None:
    """Add one entity per (Member, Record Type) and keep the set in step."""
    known: set[tuple[str, str]] = set()

    @callback
    def _reconcile() -> None:
        current = {
            (member_id, type_id)
            for member_id, coordinator in area.members.items()
            for type_id in coordinator.record_sets
        }
        added = [
            factory(area.members[member_id], type_id)
            for member_id, type_id in sorted(current - known)
        ]
        known.intersection_update(current)
        known.update(current)
        if added:
            async_add_entities(added)

    _reconcile()
    async_dispatcher_connect(hass, signal_entities_changed(AREA), _reconcile)
