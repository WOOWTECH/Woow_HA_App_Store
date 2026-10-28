"""Sensor platform for Ha Health Record integration.

Creates one sensor entity per record type per member. Each sensor displays
the most recent recorded value for that metric (e.g., weight, blood pressure).
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ...const import unique_id
from .area import HealthArea
from .const import AREA
from .coordinator import (
    HealthRecordCoordinator,
    signal_record_updated,
)
from .platform import async_setup_record_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_area(
    hass: HomeAssistant,
    area: HealthArea,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one RecordSensor per Record Type per Member."""
    await async_setup_record_entities(
        hass,
        area,
        async_add_entities,
        lambda coordinator, type_id: RecordSensor(
            coordinator=coordinator, type_id=type_id
        ),
    )


class RecordSensor(SensorEntity):
    """Sensor showing the last record value.

    State
        Numeric value of the most recent record for this type.
        ``None`` if no records have been logged yet.

    Icon
        ``mdi:clipboard-text-clock``

    Unit
        Configurable per record type (e.g. ``"kg"``, ``"ml"``, ``"cm"``).

    Translation key
        ``"record"`` with placeholder ``{record_name}``.

    Extra state attributes
        * ``record_name`` (str) -- display name of the record type.
        * ``unit`` (str) -- unit of measurement.
        * ``note`` (str) -- free-text note attached to the record.
        * ``timestamp`` (str, ISO 8601) -- when the record was logged.

    Unique ID pattern
        ``{member_id}_{type_id}_record``

    Updates via dispatcher signal, not polling.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "record"

    def __init__(
        self,
        coordinator: HealthRecordCoordinator,
        type_id: str,
    ) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._type_id = type_id
        record_set = coordinator.get_record_set(type_id)

        self._attr_unique_id = unique_id(AREA, coordinator.member_id, type_id, "record")
        self._attr_translation_placeholders = {"record_name": record_set.name}
        self._attr_native_unit_of_measurement = record_set.unit
        self._attr_device_info = coordinator.get_device_info()
        self._attr_icon = "mdi:clipboard-text-clock"

    async def async_added_to_hass(self) -> None:
        """Subscribe to dispatcher signals when added to hass."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_record_updated(
                    self._coordinator.member_id, self._type_id
                ),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle update signal."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the last recorded value."""
        record_set = self._coordinator.get_record_set(self._type_id)
        if record_set and record_set.last_record:
            return record_set.last_record.value
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        record_set = self._coordinator.get_record_set(self._type_id)
        if not record_set or not record_set.last_record:
            return {}

        record = record_set.last_record
        attrs = {
            "record_name": record_set.name,
            "unit": record_set.unit,
            "note": record.note,
        }
        if record.timestamp:
            attrs["timestamp"] = record.timestamp.isoformat()

        return attrs
