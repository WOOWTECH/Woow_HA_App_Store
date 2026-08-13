"""Config flow for Blueprint Manager."""

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class WoowBlueprintManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Blueprint Manager."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            # Prevent multiple instances
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Blueprint Manager", data={})

        return self.async_show_form(step_id="user")
