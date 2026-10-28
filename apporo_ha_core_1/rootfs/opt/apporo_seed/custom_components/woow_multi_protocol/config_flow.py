"""Config flow for the Woow Multi-Protocol Connect integration.

A single, singleton entry: the first user step creates it; any later attempt
aborts as already-configured. An Options flow exposes one enable toggle per
protocol (``enable_knx`` / ``enable_dmx`` / ``enable_modbus``, all defaulting to
``true``); saving reloads the entry so the panel's tab set is rebuilt (ADR-0003).
"""

from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol

from .const import DOMAIN, OPTION_ENABLE, PANEL_TITLE, PROTOCOLS


class WoowMultiProtocolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a singleton config flow for Woow Multi-Protocol Connect."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step; only one entry is ever created."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(title=PANEL_TITLE, data={})

        return self.async_show_form(step_id="user", data_schema=None)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the Options flow that toggles which protocols are enabled."""
        return WoowMultiProtocolOptionsFlow()


class WoowMultiProtocolOptionsFlow(config_entries.OptionsFlow):
    """Toggle which protocols the single panel shows.

    One boolean per protocol, defaulting to the entry's current value (or ``true``
    on first open). Submitting stores the options; the entry's update listener
    reloads it so the panel rebuilds with the new tab set.
    """

    async def async_step_init(self, user_input=None):
        """Show the per-protocol toggles, then persist them."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    OPTION_ENABLE[protocol],
                    default=options.get(OPTION_ENABLE[protocol], True),
                ): bool
                for protocol in PROTOCOLS
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
