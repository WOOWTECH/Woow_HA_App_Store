"""Repair flow that migrates a 1.3.x YAML install to a config entry.

1.4.0 removed YAML setup outright. A machine that upgrades and does nothing therefore has
no config entry, and Home Assistant never sets the component up: the seven runtime hooks
and the climate entities are gone until somebody adds the integration from the UI. A log
warning does not reach that person; a repair issue on the dashboard does.

So ``__init__.async_setup`` raises a *fixable* issue whenever the obsolete
``woow_zha_quirks:`` key is still in configuration.yaml, and confirming it here creates the
entry. Two clicks, no file editing, and the migration still requires a human -- which is
the whole point of the hard cut (docs/adr/0005-config-entry-setup.md).

Note what remains true while the issue is unfixed: the leftover YAML key is what makes
Home Assistant import this package at all, and the quirks register at import time. So such
an install keeps working quirks; only the hooks and the climate entities are missing.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, ISSUE_YAML_REMOVED


class YamlRemovedRepairFlow(RepairsFlow):
    """Confirm, then create the config entry the YAML key used to stand in for."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        if user_input is not None:
            await self.hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}
            )
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix flow for our one repairable issue."""
    if issue_id == ISSUE_YAML_REMOVED:
        return YamlRemovedRepairFlow()

    raise ValueError(f"{DOMAIN}: unknown repair issue {issue_id}")
