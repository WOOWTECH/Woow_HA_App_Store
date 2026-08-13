"""The Climate Template integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONF_HEATER, CONF_TEMPERATURE_SENSOR, DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Climate Template component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Climate Template from a config entry.

    This is called when the integration is set up via the UI config flow.
    """
    _LOGGER.debug(
        "Setting up Climate Template entry: %s (%s)",
        entry.title,
        entry.entry_id,
    )

    # Store entry data for the climate platform to use
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.options

    # Forward setup to the climate platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info(
        "Climate Template '%s' set up successfully with sensor '%s' and heater '%s'",
        entry.options.get(CONF_NAME, entry.title),
        entry.options.get(CONF_TEMPERATURE_SENSOR),
        entry.options.get(CONF_HEATER),
    )

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Called when the user modifies the integration options.
    """
    _LOGGER.debug("Updating Climate Template options for: %s", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Called when the integration is removed or reloaded.
    """
    _LOGGER.debug("Unloading Climate Template entry: %s", entry.title)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Clean up stored data
    if unload_ok and entry.entry_id in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry.

    Called when the integration needs to be reloaded.
    """
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
