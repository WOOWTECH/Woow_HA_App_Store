"""WoowTech Somfy Cover integration for Home Assistant.

This integration provides local control of Somfy PoE motors through encrypted UDP communication.
It supports position control, status monitoring, and automatic motor wake-up handling.

For more information about this integration, please refer to the documentation at
https://github.com/woowtech/somfy-cover
"""
from __future__ import annotations

import logging
from typing import Any

# Allow importing API modules for testing without Home Assistant installed
try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .api.client import SomfyClient
    from .const import DOMAIN, CONF_HOST, CONF_TARGET_ID, CONF_KEY
    from .coordinator import SomfyDataUpdateCoordinator

    PLATFORMS: list[Platform] = [Platform.COVER]
except ImportError:
    # Running in test mode without Home Assistant
    pass

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the WoowTech Somfy Cover component from YAML configuration.

    This function enables YAML configuration support for the integration.
    The actual platform setup is handled by async_setup_platform in cover.py.

    Args:
        hass: Home Assistant instance
        config: Full Home Assistant configuration dict

    Returns:
        True if setup was successful

    Note:
        This function coexists with async_setup_entry for Config Flow support.
        Users can configure covers via YAML, Config Flow, or both simultaneously.
    """
    _LOGGER.debug("YAML configuration setup initiated")

    # Initialize domain storage if not already done
    hass.data.setdefault(DOMAIN, {})

    # Platform setup will be handled by async_setup_platform in cover.py
    # when Home Assistant processes the cover platform configuration
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WoowTech Somfy Cover from a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry containing motor connection details

    Returns:
        True if setup was successful, False otherwise
    """
    _LOGGER.debug(
        "Setting up WoowTech Somfy Cover integration for %s",
        entry.data.get(CONF_HOST),
    )

    # Create API client
    client = SomfyClient(
        host=entry.data[CONF_HOST],
        target_id=entry.data[CONF_TARGET_ID],
        key=entry.data[CONF_KEY],
    )

    # Connect to device
    try:
        await client.connect()
        _LOGGER.info(
            "Successfully connected to Somfy motor at %s (ID: %s)",
            entry.data[CONF_HOST],
            entry.data[CONF_TARGET_ID],
        )
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error(
            "Failed to connect to Somfy motor at %s: %s",
            entry.data[CONF_HOST],
            err,
        )
        return False

    # Create coordinator for position polling
    coordinator = SomfyDataUpdateCoordinator(
        hass=hass,
        client=client,
        entry_data=entry.data,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Fetch device info for device registry
    try:
        await coordinator.async_get_device_info()
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning("Failed to fetch device info: %s", err)

    # Store coordinator in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Setup cover platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug("WoowTech Somfy Cover setup completed for %s", entry.data[CONF_HOST])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a WoowTech Somfy Cover config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry to unload

    Returns:
        True if unload was successful, False otherwise
    """
    _LOGGER.debug("Unloading WoowTech Somfy Cover integration for %s", entry.data[CONF_HOST])

    # Unload platforms
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Close client connection
        coordinator: SomfyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.client.close()

        # Remove coordinator from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)

        _LOGGER.info("Successfully unloaded WoowTech Somfy Cover for %s", entry.data[CONF_HOST])

    return unload_ok
