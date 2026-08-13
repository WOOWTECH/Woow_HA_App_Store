"""Base entity for Ha Note Record integration.

Provides the common base class for all note record entities (text and switch),
including shared device info and no-poll update pattern.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .store import Category, HaNoteRecordStore, Note


class HaNoteRecordEntity(Entity):
    """Base class for Ha Note Record entities.

    Provides ``has_entity_name = True`` and ``should_poll = False`` for the
    text and switch entity platforms.

    Each note category creates a device with
    ``identifiers = {(DOMAIN, category_id)}``, so every note entity that
    belongs to the same category is grouped under one device.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        store: HaNoteRecordStore,
        note: Note,
        category: Category,
    ) -> None:
        """Initialize the entity."""
        self._store = store
        self._note = note
        self._category = category
        self._note_exists = True

    @property
    def note_id(self) -> str:
        """Return the note ID."""
        return self._note.id

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return self._note_exists and self._store.get_note(self._note.id) is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._category.id)},
            name=self._category.name,
            manufacturer="Ha Note Record",
            model="Note Category",
        )

    def _refresh_note(self) -> bool:
        """Refresh note data from store.

        Returns True if note still exists, False otherwise.
        """
        note = self._store.get_note(self._note.id)
        if note:
            self._note = note
            self._note_exists = True
            return True
        self._note_exists = False
        return False
