"""Config flow for WOOW ZHA Quirks.

The integration has no settings, so the flow is a single confirmation step. It is not a
formality: accepting it starts seven runtime hooks, three of which mutate data that is not
ours (``orphan_sweep`` deletes entity registry rows, ``presence_defaults`` writes device
settings, ``light_effects`` patches the ZHA ``Light`` class). The confirm step spells those
out, because this screen is the only place a user ever sees what the integration does.

``async_step_import`` exists **only** for the repair flow that migrates a 1.3.x install
(see ``repairs.py``); nothing calls it at startup. The 1.4.0 migration is deliberately a
hard cut in which a human accepts the change -- see docs/adr/0005-config-entry-setup.md.

This module must not import the package ``__init__``: that would register every quirk as a
side effect of Home Assistant merely listing the available integrations. Constants come
from ``const.py``.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

TITLE = "WOOW ZHA Quirks"


class WoowZhaQuirksConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the single-instance config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then create the one and only entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    async def async_step_import(
        self, import_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry on behalf of the YAML-migration repair flow.

        Reached only when a user confirms the repair issue raised for a leftover
        ``woow_zha_quirks:`` key. Never called from ``async_setup``.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title=TITLE, data={})
