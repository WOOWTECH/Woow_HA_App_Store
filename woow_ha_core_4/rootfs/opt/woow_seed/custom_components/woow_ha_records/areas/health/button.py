"""Button platform for Ha Health Record integration.

Creates one button entity per record type per member. Pressing the button
logs the current value and note to persistent storage.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ...const import unique_id
from .area import HealthArea
from .const import AREA, EVENT_RECORD_LOGGED
from .coordinator import HealthRecordCoordinator
from .platform import async_setup_record_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_area(
    hass: HomeAssistant,
    area: HealthArea,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one RecordLogButton per Record Type per Member."""
    await async_setup_record_entities(
        hass,
        area,
        async_add_entities,
        lambda coordinator, type_id: RecordLogButton(
            coordinator=coordinator, type_id=type_id
        ),
    )


class RecordLogButton(ButtonEntity):
    """Button to log a record.

    Pressing this button logs the current value (from ``RecordValueNumber``)
    and note (from ``RecordNoteText``) as a new record entry in storage.

    Icon
        ``mdi:content-save``

    Entity category
        ``CONFIG``

    Translation key
        ``"record_log"`` with placeholder ``{record_name}``.

    Unique ID pattern
        ``{member_id}_{type_id}_log``

    Side effects
        Fires the ``ha_health_record_record_logged`` event with the following
        data: ``member_id``, ``member_name``, ``record_type``,
        ``record_name``, ``value``, ``unit``, ``note``, ``timestamp``.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_translation_key = "record_log"

    def __init__(
        self,
        coordinator: HealthRecordCoordinator,
        type_id: str,
    ) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._type_id = type_id
        record_set = coordinator.get_record_set(type_id)

        self._attr_unique_id = unique_id(AREA, coordinator.member_id, type_id, "log")
        self._attr_translation_placeholders = {"record_name": record_set.name}
        self._attr_device_info = coordinator.get_device_info()
        self._attr_icon = "mdi:content-save"

    async def async_press(self) -> None:
        """Handle the button press."""
        record = self._coordinator.log_record(self._type_id)

        if record is None:
            _LOGGER.warning("Failed to log record: %s", self._type_id)
            return

        record_set = self._coordinator.get_record_set(self._type_id)

        # Fire event
        self.hass.bus.async_fire(
            EVENT_RECORD_LOGGED,
            {
                "member_id": self._coordinator.member_id,
                "member_name": self._coordinator.member_name,
                "record_type": self._type_id,
                "record_name": record_set.name,
                "value": record.value,
                "unit": record_set.unit,
                "note": record.note,
                "timestamp": record.timestamp.isoformat() if record.timestamp else None,
            },
        )

        _LOGGER.info(
            "Record logged: %s - %s %s (note: %s)",
            record_set.name,
            record.value,
            record_set.unit,
            record.note,
        )
