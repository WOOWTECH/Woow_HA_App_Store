"""Config flow for Somfy PoE Motor integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_TARGET_ID, CONF_KEY, DEFAULT_NAME
from .api.client import SomfyClient
from .errors import SomfyError

_LOGGER = logging.getLogger(__name__)

# Validation patterns
TARGET_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{6}$")
KEY_PATTERN = re.compile(r"^[0-9A-Fa-f]{32}$")

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_TARGET_ID): cv.string,
        vol.Required(CONF_KEY): cv.string,
    }
)


class SomfyPoeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Somfy PoE Motor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate target_id format
            if not TARGET_ID_PATTERN.match(user_input[CONF_TARGET_ID]):
                errors[CONF_TARGET_ID] = "invalid_target_id"

            # Validate key format
            if not KEY_PATTERN.match(user_input[CONF_KEY]):
                errors[CONF_KEY] = "invalid_key"

            # Test connection if inputs are valid
            if not errors:
                try:
                    await self._test_connection(user_input)
                except SomfyError as err:
                    _LOGGER.error("Connection test failed: %s", err)
                    errors["base"] = "cannot_connect"
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception: %s", err)
                    errors["base"] = "unknown"

            if not errors:
                # Create unique ID from target_id
                await self.async_set_unique_id(user_input[CONF_TARGET_ID])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_connection(self, config: dict[str, Any]) -> None:
        """Test if we can connect to the device.

        Args:
            config: Configuration dictionary

        Raises:
            SomfyError: If connection fails
        """
        client = SomfyClient(
            host=config[CONF_HOST],
            target_id=config[CONF_TARGET_ID],
            key=config[CONF_KEY],
        )

        async with client:
            # Test with encrypted communication (device doesn't respond to unencrypted ping)
            device_info = await client.get_device_info()
            _LOGGER.debug(
                "Successfully connected to device: %s (model: %s, firmware: %s)",
                device_info.name,
                device_info.model,
                device_info.firmware
            )
