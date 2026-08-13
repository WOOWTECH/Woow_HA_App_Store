"""Config flow for the Atmocube integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import (
    CONF_SLAVE_ID,
    DEFAULT_PORT,
    DEFAULT_SLAVE_ID,
    DOMAIN,
    REGISTER_START,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        vol.Required(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID): vol.Coerce(int),
    }
)


class AtmocubeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Atmocube."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            slave_id = user_input[CONF_SLAVE_ID]

            await self.async_set_unique_id(f"atmocube_{host}")
            self._abort_if_unique_id_configured()

            error = await self._async_validate_connection(host, port, slave_id)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Atmocube ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _async_validate_connection(
        self, host: str, port: int, slave_id: int
    ) -> str | None:
        """Validate the Modbus TCP connection by reading a register."""
        client = AsyncModbusTcpClient(host, port=port, timeout=5)
        try:
            connected = await client.connect()
            if not connected:
                return "cannot_connect"

            result = await client.read_input_registers(
                address=REGISTER_START, count=1, device_id=slave_id
            )
            if result.isError():
                return "cannot_connect"

        except (ModbusException, OSError):
            return "cannot_connect"
        finally:
            client.close()

        return None
