"""Text entity for Ha Note Record integration.

Creates one text entity per note to expose the note content. Content is
stored as markdown and can be up to 100,000 characters via the WebSocket API,
but the HA text entity state is capped at 255 characters by HA core.
"""

from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CATEGORY,
    ATTR_CREATED_AT,
    ATTR_NOTE_ID,
    ATTR_RAW_CONTENT,
    ATTR_TITLE,
    ATTR_UPDATED_AT,
    DOMAIN,
    ICON_NOTE,
    MAX_NOTE_CONTENT_LENGTH,
)
from .entity import HaNoteRecordEntity
from .store import Category, HaNoteRecordStore, Note

_LOGGER = logging.getLogger(__name__)

# Maximum length for state value (HA limit is 255)
MAX_STATE_LENGTH = 200


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up text entities from a config entry."""
    store: HaNoteRecordStore = entry.runtime_data

    # Track entity IDs to avoid duplicates
    known_note_ids: set[str] = set()
    entities: list[HaNoteRecordTextEntity] = []

    for note in store.notes:
        category = store.get_category(note.category_id)
        if category:
            entities.append(HaNoteRecordTextEntity(store, note, category))
            known_note_ids.add(note.id)

    async_add_entities(entities)

    @callback
    def async_add_new_entities() -> None:
        """Add entities for newly created notes."""
        new_entities: list[HaNoteRecordTextEntity] = []

        # Reconcile known_note_ids — remove deleted notes
        current_ids = {n.id for n in store.notes}
        known_note_ids.intersection_update(current_ids)

        for note in store.notes:
            if note.id not in known_note_ids:
                category = store.get_category(note.category_id)
                if category:
                    entity = HaNoteRecordTextEntity(store, note, category)
                    new_entities.append(entity)
                    known_note_ids.add(note.id)

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(store.async_add_listener(async_add_new_entities))


class HaNoteRecordTextEntity(HaNoteRecordEntity, TextEntity):
    """Text entity exposing note content.

    State
        The note's content text, truncated to 255 characters by HA core.
        Full content is available via the ``raw_content`` extra state
        attribute.

    Mode
        ``TextMode.TEXT`` (plain text input).

    Icon
        ``mdi:note-text`` (the ``ICON_NOTE`` constant).

    Extra state attributes
        * ``raw_content`` (str) -- full markdown content of the note
        * ``title`` (str) -- note title
        * ``category`` (str) -- category name
        * ``created_at`` (str) -- ISO-8601 creation timestamp
        * ``updated_at`` (str) -- ISO-8601 last-update timestamp
        * ``note_id`` (str) -- unique note identifier
        * ``category_id`` (str) -- unique category identifier

    Unique ID pattern
        ``{DOMAIN}_{category_id}_{note_id}_content``

    Name
        The note title, set directly (not via translation key).
    """

    _attr_mode = TextMode.TEXT
    _attr_icon = ICON_NOTE

    def __init__(
        self,
        store: HaNoteRecordStore,
        note: Note,
        category: Category,
    ) -> None:
        """Initialize the text entity."""
        super().__init__(store, note, category)
        self._attr_unique_id = f"{DOMAIN}_{category.id}_{note.id}_content"
        self._attr_name = note.title

    @property
    def native_value(self) -> str | None:
        """Return the state value (truncated if needed)."""
        if not self._refresh_note():
            return None
        content = self._note.content
        if len(content) > MAX_STATE_LENGTH:
            return content[:MAX_STATE_LENGTH] + "..."
        return content

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return extra state attributes."""
        self._refresh_note()
        return {
            ATTR_RAW_CONTENT: self._note.content,
            ATTR_TITLE: self._note.title,
            ATTR_NOTE_ID: self._note.id,
            ATTR_CATEGORY: self._category.name,
            ATTR_CREATED_AT: self._note.created_at,
            ATTR_UPDATED_AT: self._note.updated_at,
        }

    async def async_set_value(self, value: str) -> None:
        """Set the note content."""
        if len(value) > MAX_NOTE_CONTENT_LENGTH:
            _LOGGER.warning(
                "Content exceeds maximum length of %d characters",
                MAX_NOTE_CONTENT_LENGTH,
            )
            return
        await self._store.async_update_note_content(self._note.id, value)
        if self._refresh_note():
            self.async_write_ha_state()
