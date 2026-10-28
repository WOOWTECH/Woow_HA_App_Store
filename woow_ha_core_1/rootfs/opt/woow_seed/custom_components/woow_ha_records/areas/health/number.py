"""Number platform for Ha Health Record integration.

Creates one number entity per record type per member for entering
measurement values before logging.
"""
from __future__ import annotations

import logging
import math

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up one RecordValueNumber per Record Type per Member."""
    await async_setup_record_entities(
        hass,
        area,
        async_add_entities,
        lambda coordinator, type_id: RecordValueNumber(
            coordinator=coordinator, type_id=type_id
        ),
    )


class RecordValueNumber(NumberEntity):
    """Number entity for record value input.

    State
        The value to be logged on the next button press, or the
        ``default_value`` configured for this record type.

    Range
        0 to 10 000, step 0.1.

    Mode
        ``BOX`` (free numeric input).

    Icon
        ``mdi:numeric``

    Entity category
        ``CONFIG``

    Translation key
        ``"record_value"`` with placeholder ``{record_name}``.

    Unique ID pattern
        ``{member_id}_{type_id}_value``

    Updates via dispatcher signal, not polling.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 10000
    _attr_native_step = 0.1
    _attr_translation_key = "record_value"

    def __init__(
        self,
        coordinator: HealthRecordCoordinator,
        type_id: str,
    ) -> None:
        """Initialize the number entity."""
        self._coordinator = coordinator
        self._type_id = type_id
        record_set = coordinator.get_record_set(type_id)

        self._attr_unique_id = unique_id(AREA, coordinator.member_id, type_id, "value")
        self._attr_translation_placeholders = {"record_name": record_set.name}
        self._attr_native_unit_of_measurement = record_set.unit
        self._attr_device_info = coordinator.get_device_info()
        self._attr_icon = "mdi:numeric"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        record_set = self._coordinator.get_record_set(self._type_id)
        return record_set.current_value if record_set else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"Invalid value: {value} (NaN/Infinity not allowed)")
        self._coordinator.set_record_value(self._type_id, value)
        self.async_write_ha_state()
