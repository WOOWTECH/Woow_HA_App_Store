"""Sensor platform for the Atmocube integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AtmocubeConfigEntry
from .const import DOMAIN, AtmocubeSensorDefinition, SENSOR_DEFINITIONS
from .coordinator import AtmocubeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtmocubeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Atmocube sensors from a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        AtmocubeSensor(coordinator, sensor_def, entry)
        for sensor_def in SENSOR_DEFINITIONS
    )


class AtmocubeSensor(CoordinatorEntity[AtmocubeCoordinator], SensorEntity):
    """Representation of an Atmocube sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AtmocubeCoordinator,
        sensor_def: AtmocubeSensorDefinition,
        entry: AtmocubeConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_def = sensor_def
        self._attr_unique_id = f"{entry.entry_id}_{sensor_def.key}"
        self._attr_translation_key = sensor_def.key
        self._attr_native_unit_of_measurement = sensor_def.unit
        self._attr_device_class = sensor_def.device_class
        self._attr_state_class = sensor_def.state_class
        self._attr_suggested_display_precision = sensor_def.precision
        if sensor_def.icon:
            self._attr_icon = sensor_def.icon

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to group all sensors under one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.host)},
            name="Atmocube",
            manufacturer="Atmotube",
            model="Atmocube",
        )

    @property
    def native_value(self) -> float | None:
        """Return the sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._sensor_def.key)
