"""Config flow for Label Control integration."""
from homeassistant import config_entries

from .const import DOMAIN


class LabelControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Label Control."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        # Prevent multiple instances
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Label Control", data={})

        return self.async_show_form(step_id="user")
