"""Data coordinator for the Atmocube integration."""

from __future__ import annotations

import logging
import struct
from datetime import timedelta

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_SLAVE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    REGISTER_COUNT,
    REGISTER_START,
    SENSOR_DEFINITIONS,
)

_LOGGER = logging.getLogger(__name__)


class AtmocubeCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Coordinator to poll Atmocube sensor via Modbus TCP."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.host: str = config_entry.data[CONF_HOST]
        self.port: int = config_entry.data[CONF_PORT]
        self.slave_id: int = config_entry.data[CONF_SLAVE_ID]
        self.client = AsyncModbusTcpClient(self.host, port=self.port, timeout=10)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, float]:
        """Fetch all 20 sensor registers in a single batch read."""
        try:
            if not self.client.connected:
                connected = await self.client.connect()
                if not connected:
                    raise UpdateFailed(
                        f"Cannot connect to Atmocube at {self.host}:{self.port}"
                    )

            result = await self.client.read_input_registers(
                address=REGISTER_START,
                count=REGISTER_COUNT,
                device_id=self.slave_id,
            )

            if result.isError():
                raise UpdateFailed(f"Modbus read error: {result}")

            data: dict[str, float] = {}
            for sensor_def in SENSOR_DEFINITIONS:
                raw = result.registers[sensor_def.register_offset]
                if sensor_def.is_signed:
                    raw = struct.unpack("h", struct.pack("H", raw))[0]
                data[sensor_def.key] = round(
                    raw * sensor_def.scale, sensor_def.precision
                )

            return data

        except ModbusException as err:
            raise UpdateFailed(f"Modbus communication error: {err}") from err

    async def async_close(self) -> None:
        """Close the Modbus TCP connection."""
        self.client.close()
