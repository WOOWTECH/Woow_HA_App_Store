"""Config flow for ha_permission_manager."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class HaPermissionManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Permission Manager."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Prevent multiple instances
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            # User confirmed, create the entry
            return self.async_create_entry(
                title="Permission Manager",
                data={},
            )

        # Show confirmation form
        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "info": "This will set up permission management for all users and resources."
            },
        )
