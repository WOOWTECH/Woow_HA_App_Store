"""Switch entity for Ha Note Record integration.

Creates one switch entity per note to control its pinned status.
Turning on pins the note; turning off unpins it.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import ENTITY_ID_FORMAT, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTR_NOTE_ID, ICON_PINNED, ICON_UNPINNED
from .entity import HaNoteRecordEntity, note_unique_id
from .store import Category, HaNoteRecordStore, Note

_LOGGER = logging.getLogger(__name__)


async def async_setup_area(
    hass: HomeAssistant,
    store: HaNoteRecordStore,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities from a config entry."""

    # Track entity IDs to avoid duplicates
    known_note_ids: set[str] = set()
    entities: list[HaNoteRecordSwitchEntity] = []

    for note in store.notes:
        category = store.get_category(note.category_id)
        if category:
            entity = HaNoteRecordSwitchEntity(store, note, category)
            entity.async_repair_registry_entity_id(hass)
            entities.append(entity)
            known_note_ids.add(note.id)

    async_add_entities(entities)

    @callback
    def async_add_new_entities() -> None:
        """Add entities for newly created notes."""
        new_entities: list[HaNoteRecordSwitchEntity] = []

        # Reconcile known_note_ids — remove deleted notes
        current_ids = {n.id for n in store.notes}
        known_note_ids.intersection_update(current_ids)

        for note in store.notes:
            if note.id not in known_note_ids:
                category = store.get_category(note.category_id)
                if category:
                    entity = HaNoteRecordSwitchEntity(store, note, category)
                    new_entities.append(entity)
                    known_note_ids.add(note.id)

        if new_entities:
            async_add_entities(new_entities)

    store.entry.async_on_unload(store.async_add_listener(async_add_new_entities))


class HaNoteRecordSwitchEntity(HaNoteRecordEntity, SwitchEntity):
    """Switch entity controlling note pinned status.

    State
        ON when the note is pinned, OFF when unpinned.

    Icon
        ``mdi:pin`` (``ICON_PINNED``) when pinned,
        ``mdi:pin-off`` (``ICON_UNPINNED``) when unpinned.

    Extra state attributes
        * ``note_id`` (str) -- unique note identifier

    Unique ID pattern
        ``note_{note_id}_pinned`` -- category-free, so the note can move
        between categories without changing identity (ADR-0003).

    Entity ID
        Suggested via ``_apply_entity_id`` so a long note title cannot push the
        object_id past Home Assistant's 255-character limit.

    Name
        ``"{note_title} Pinned"`` (set directly, not via translation key).

    Methods
        * ``async_turn_on`` -- pins the note
        * ``async_turn_off`` -- unpins the note
    """

    def __init__(
        self,
        store: HaNoteRecordStore,
        note: Note,
        category: Category,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(store, note, category)
        self._attr_unique_id = note_unique_id(note.id, "pinned")
        self._attr_name = f"{note.title} Pinned"
        self._apply_entity_id(ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool | None:
        """Return True if the note is pinned."""
        if not self._refresh_note():
            return None
        return self._note.pinned

    @property
    def icon(self) -> str:
        """Return the icon based on pinned status."""
        return ICON_PINNED if self.is_on else ICON_UNPINNED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            ATTR_NOTE_ID: self._note.id,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pin the note."""
        await self._store.async_update_note_pinned(self._note.id, True)
        if self._refresh_note():
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unpin the note."""
        await self._store.async_update_note_pinned(self._note.id, False)
        if self._refresh_note():
            self.async_write_ha_state()
