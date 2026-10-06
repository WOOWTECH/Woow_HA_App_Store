"""Config flow for Ha Health Record integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
)

from .const import (
    CONF_MEMBER_ID,
    CONF_MEMBER_NAME,
    CONF_RECORD_SETS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _sanitize_id(name: str) -> str:
    """Sanitize a name to create a valid ID."""
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


class HaHealthRecordConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ha Health Record."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - add a family member."""
        errors: dict[str, str] = {}

        if user_input is not None:
            member_id = user_input.get(CONF_MEMBER_ID, "").strip()
            if not member_id:
                member_id = user_input[CONF_MEMBER_NAME]

            # Validate member_id produces a usable sanitized ID
            sanitized_id = _sanitize_id(member_id)
            if not sanitized_id:
                errors[CONF_MEMBER_ID] = "invalid_id"
            else:
                # Use the sanitized ID as the unique ID
                await self.async_set_unique_id(sanitized_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_MEMBER_NAME],
                    data={
                        CONF_MEMBER_ID: sanitized_id,
                        CONF_MEMBER_NAME: user_input[CONF_MEMBER_NAME],
                        "note": user_input.get("note", ""),
                    },
                    options={
                        CONF_RECORD_SETS: [],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MEMBER_NAME): str,
                    vol.Optional(CONF_MEMBER_ID, default=""): str,
                }
            ),
            errors=errors,
        )
