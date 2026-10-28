"""The health Area: Members, their Record Types, and their Records.

A Member used to be a Home Assistant config entry backed by a store file of its
own. Since the merge (ADR-0001) a Member is a record inside this Area's single
store, which is what lets `health_add_member` be an ordinary write rather than a
config-flow round trip.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from ...const import signal_entities_changed
from .const import AREA, STORAGE_KEY, STORAGE_VERSION
from .coordinator import HealthRecordCoordinator

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 1  # seconds -- batches rapid operations into a single write


class HealthArea:
    """Owns the health store and every Member coordinator in it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Area."""
        self.hass = hass
        self.entry = entry
        self.members: dict[str, HealthRecordCoordinator] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY, atomic_writes=True
        )

    async def async_load(self) -> None:
        """Load every Member from the store."""
        data = await self._store.async_load() or {}
        for member_id, member_data in data.get("members", {}).items():
            coordinator = HealthRecordCoordinator(
                self.hass,
                self,
                member_id,
                member_data.get("name", member_id),
                member_data.get("note", ""),
            )
            coordinator.load_from_dict(member_data)
            self.members[member_id] = coordinator
        _LOGGER.debug("Loaded health Area: %d members", len(self.members))

    @callback
    def async_schedule_save(self) -> None:
        """Schedule a delayed write covering every Member."""
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        """Return the whole Area as stored."""
        return {
            "members": {
                member_id: coordinator.to_dict()
                for member_id, coordinator in self.members.items()
            }
        }

    async def async_save_now(self) -> None:
        """Flush pending changes immediately.

        Call before anything that re-reads the store; the delayed save batches
        rapid edits and would otherwise still be pending.
        """
        await self._store.async_save(self._data_to_save())

    @callback
    def async_notify_entities_changed(self) -> None:
        """Tell the health platforms to reconcile their entities."""
        async_dispatcher_send(self.hass, signal_entities_changed(AREA))

    async def async_remove(self) -> None:
        """Delete the Area's store file."""
        await self._store.async_remove()

    # ── Members ──────────────────────────────────────────────────────

    def get(self, member_id: str) -> HealthRecordCoordinator | None:
        """Return one Member's coordinator, or None if there is no such Member."""
        return self.members.get(member_id)

    def add_member(
        self, member_id: str, member_name: str, note: str = ""
    ) -> HealthRecordCoordinator:
        """Create a Member and persist it."""
        coordinator = HealthRecordCoordinator(
            self.hass, self, member_id, member_name, note
        )
        self.members[member_id] = coordinator
        self.async_schedule_save()
        self.async_notify_entities_changed()
        return coordinator

    def remove_member(self, member_id: str) -> bool:
        """Delete a Member and everything recorded against them."""
        if self.members.pop(member_id, None) is None:
            return False
        self.async_schedule_save()
        self.async_notify_entities_changed()
        return True
