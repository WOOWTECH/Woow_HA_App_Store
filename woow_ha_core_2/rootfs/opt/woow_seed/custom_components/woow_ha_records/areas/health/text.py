"""Text platform for Ha Health Record integration.

Creates one text entity per record type per member for entering
free-text notes to attach to each logged record.
"""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ...const import unique_id
from .area import HealthArea
from .const import AREA
from .coordinator import HealthRecordCoordinator
from .platform import async_setup_record_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_area(
    hass: HomeAssistant,
    area: HealthArea,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one RecordNoteText per Record Type per Member."""
    await async_setup_record_entities(
        hass,
        area,
        async_add_entities,
        lambda coordinator, type_id: RecordNoteText(
            coordinator=coordinator, type_id=type_id
        ),
    )


class RecordNoteText(TextEntity):
    """Text entity for record note input.

    State
        The note text to be attached on the next log, or an empty string.

    Max length
        255 characters.

    Mode
        ``TEXT``

    Icon
        ``mdi:note-text``

    Entity category
        ``CONFIG``

    Translation key
        ``"record_note"`` with placeholder ``{record_name}``.

    Unique ID pattern
        ``{member_id}_{type_id}_note``

    Updates via dispatcher signal, not polling.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_mode = TextMode.TEXT
    _attr_native_max = 255
    _attr_translation_key = "record_note"

    def __init__(
        self,
        coordinator: HealthRecordCoordinator,
        type_id: str,
    ) -> None:
        """Initialize the text entity."""
        self._coordinator = coordinator
        self._type_id = type_id
        record_set = coordinator.get_record_set(type_id)

        self._attr_unique_id = unique_id(AREA, coordinator.member_id, type_id, "note")
        self._attr_translation_placeholders = {"record_name": record_set.name}
        self._attr_device_info = coordinator.get_device_info()
        self._attr_icon = "mdi:note-text"

    @property
    def native_value(self) -> str | None:
        """Return the current value."""
        record_set = self._coordinator.get_record_set(self._type_id)
        return record_set.current_note if record_set else None

    async def async_set_value(self, value: str) -> None:
        """Set the value."""
        self._coordinator.set_record_note(self._type_id, value)
        self.async_write_ha_state()
