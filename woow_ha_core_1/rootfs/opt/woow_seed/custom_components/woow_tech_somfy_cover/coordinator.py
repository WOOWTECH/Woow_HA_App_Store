"""Data update coordinator for Somfy PoE."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import SomfyClient
from .api.models import PositionStatus, DeviceInfo as SomfyDeviceInfo
from .const import DOMAIN, CONF_HOST, CONF_TARGET_ID, CONF_NAME
from .errors import SomfyError

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=30)
FAST_UPDATE_INTERVAL = timedelta(seconds=2)


class SomfyDataUpdateCoordinator(DataUpdateCoordinator[PositionStatus]):
    """Coordinator for fetching Somfy motor state.

    Design Decisions:
    - Normal polling: 30 seconds
    - Fast polling during movement: 2 seconds
    - Automatic transition between polling modes
    - Maintains persistent client connection
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SomfyClient,
        entry_data: dict[str, Any],
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_data[CONF_NAME]}",
            update_interval=UPDATE_INTERVAL,
        )

        self.client = client
        self._entry_data = entry_data
        self._device_info_cache: SomfyDeviceInfo | None = None
        self._fast_poll_mode = False

        _LOGGER.debug(
            "Initialized coordinator: name=%s, update_interval=%s, host=%s",
            f"{DOMAIN}_{entry_data[CONF_NAME]}",
            UPDATE_INTERVAL,
            entry_data[CONF_HOST]
        )

    async def _async_update_data(self) -> PositionStatus:
        """Fetch data from API.

        Returns:
            Current position status

        Raises:
            UpdateFailed: If update fails
        """
        _LOGGER.debug("Starting coordinator update cycle")

        try:
            status = await self.client.get_position()

            _LOGGER.debug(
                "Position status retrieved: position=%s, status=%s, direction=%s, source=%s, cause=%s",
                status.position,
                status.status.value,
                status.direction.value,
                status.source,
                status.cause
            )

            # Adjust polling interval based on movement
            await self._adjust_polling_interval(status)

            return status

        except SomfyError as err:
            _LOGGER.error(
                "Failed to update position status: %s (type: %s)",
                err,
                type(err).__name__,
                exc_info=True
            )
            raise UpdateFailed(f"Error communicating with device: {err}") from err

    async def _adjust_polling_interval(self, status: PositionStatus) -> None:
        """Adjust polling interval based on movement state."""
        is_moving = status.is_moving

        if is_moving and not self._fast_poll_mode:
            # Switch to fast polling
            self._fast_poll_mode = True
            self.update_interval = FAST_UPDATE_INTERVAL
            _LOGGER.debug("Switched to fast polling (moving)")

        elif not is_moving and self._fast_poll_mode:
            # Switch back to normal polling
            self._fast_poll_mode = False
            self.update_interval = UPDATE_INTERVAL
            _LOGGER.debug("Switched to normal polling (stopped)")

    async def async_move_up(self) -> None:
        """Send move up command."""
        _LOGGER.debug("Coordinator executing move_up command")
        await self.client.move_up()

    async def async_move_down(self) -> None:
        """Send move down command."""
        _LOGGER.debug("Coordinator executing move_down command")
        await self.client.move_down()

    async def async_stop(self) -> None:
        """Send stop command."""
        _LOGGER.debug("Coordinator executing stop command")
        await self.client.stop()

    async def async_move_to_position(self, position: float) -> None:
        """Send move to position command."""
        _LOGGER.debug("Coordinator executing move_to_position: target=%s", position)
        await self.client.move_to_position(position)

    async def async_get_device_info(self) -> SomfyDeviceInfo:
        """Get device information (cached)."""
        if self._device_info_cache is None:
            _LOGGER.debug("Fetching device info (cache miss)")
            self._device_info_cache = await self.client.get_device_info()
            _LOGGER.debug(
                "Device info cached: model=%s, firmware=%s, mac=%s",
                self._device_info_cache.model,
                self._device_info_cache.firmware,
                self._device_info_cache.mac_address
            )
        else:
            _LOGGER.debug("Using cached device info")

        return self._device_info_cache

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for entity registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_data[CONF_TARGET_ID])},
            name=self._entry_data[CONF_NAME],
            manufacturer="Somfy",
            model=self._device_info_cache.model
            if self._device_info_cache
            else "PoE Motor",
            sw_version=self._device_info_cache.firmware
            if self._device_info_cache
            else None,
        )
