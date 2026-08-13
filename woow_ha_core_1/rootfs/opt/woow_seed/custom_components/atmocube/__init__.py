"""The Atmocube Air Quality Sensor integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import AtmocubeCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type AtmocubeConfigEntry = ConfigEntry[AtmocubeCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AtmocubeConfigEntry) -> bool:
    """Set up Atmocube from a config entry."""
    coordinator = AtmocubeCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await coordinator.async_close()
        raise

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AtmocubeConfigEntry) -> bool:
    """Unload an Atmocube config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_close()
    return unload_ok
