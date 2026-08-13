"""Config flow for Ha Finance Record integration."""
from __future__ import annotations

import hashlib
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_NAME,
    CONF_INITIAL_BALANCE,
    DOMAIN,
)


def generate_account_id(name: str) -> str:
    """Generate a valid account ID from the name."""
    # Convert to lowercase and replace spaces/special chars with underscore
    account_id = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower())
    account_id = re.sub(r"_+", "_", account_id).strip("_")
    if not account_id:
        account_id = hashlib.md5(name.encode()).hexdigest()[:8]
    return account_id or "account"


class HaFinanceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ha Finance."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            account_name = user_input[CONF_ACCOUNT_NAME]
            account_id = user_input.get(CONF_ACCOUNT_ID) or generate_account_id(
                account_name
            )
            initial_balance = user_input.get(CONF_INITIAL_BALANCE, 0.0)

            # Check for duplicate account ID
            await self.async_set_unique_id(account_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=account_name,
                data={
                    CONF_ACCOUNT_ID: account_id,
                    CONF_ACCOUNT_NAME: account_name,
                    CONF_INITIAL_BALANCE: initial_balance,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_NAME): cv.string,
                    vol.Optional(CONF_ACCOUNT_ID): cv.string,
                    vol.Optional(CONF_INITIAL_BALANCE, default=0.0): vol.Coerce(float),
                }
            ),
            errors=errors,
        )

    async def async_step_ws_panel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle account creation from WebSocket panel."""
        if user_input is None:
            return self.async_abort(reason="invalid_input")

        account_name = user_input.get("name", "")
        account_id = user_input.get("account_id") or generate_account_id(account_name)
        initial_balance = user_input.get("initial_balance", 0.0)

        await self.async_set_unique_id(account_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=account_name,
            data={
                CONF_ACCOUNT_ID: account_id,
                CONF_ACCOUNT_NAME: account_name,
                CONF_INITIAL_BALANCE: initial_balance,
            },
        )

