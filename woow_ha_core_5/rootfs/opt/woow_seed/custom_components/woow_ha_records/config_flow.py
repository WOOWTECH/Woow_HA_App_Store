"""Config flow for Woow HA Records.

There is one entry for the whole integration. Accounts and Members used to be
config entries of their own; they are records inside their Area's store now
(ADR-0001), created through services or the panels rather than through here.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class WoowHaRecordsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the single config flow for Woow HA Records."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then create the one entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Woow HA Records", data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
