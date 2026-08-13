"""Config flow for Ha Asset Record integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    ACTION_CREATE_ASSET,
    ACTION_DELETE_ASSET,
    DOMAIN,
)
from .coordinator import AssetCoordinator

_LOGGER = logging.getLogger(__name__)


class HaAssetRecordConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ha Asset Record."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Only allow one instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Ha Asset Record",
                data={},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        # [H-03] Modern OptionsFlow: no need to pass config_entry to __init__.
        # The base class provides self.config_entry as a property that looks up
        # the entry by handler key after initialisation.
        return HaAssetRecordOptionsFlow()


class HaAssetRecordOptionsFlow(OptionsFlow):
    """Handle options flow for Ha Asset Record.

    [H-03] No __init__ override needed. The modern OptionsFlow base class
    provides self.config_entry via a property (available after init, not
    during __init__). See config_entries.py OptionsFlow.config_entry.
    """

    @property
    def coordinator(self) -> AssetCoordinator:
        """Get the coordinator."""
        return self.config_entry.runtime_data

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            action = user_input.get("action")
            if action == ACTION_CREATE_ASSET:
                return await self.async_step_create_asset()
            if action == ACTION_DELETE_ASSET:
                return await self.async_step_delete_asset()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): vol.In(
                        {
                            ACTION_CREATE_ASSET: "Create Asset",
                            ACTION_DELETE_ASSET: "Delete Asset",
                        }
                    ),
                }
            ),
        )

    async def async_step_create_asset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle create asset step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.get("name", "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                await self.coordinator.async_create_asset(name)
                # [L-03] Preserve existing options by merging, not overwriting
                return self.async_create_entry(
                    data={**self.config_entry.options},
                )

        return self.async_show_form(
            step_id="create_asset",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_delete_asset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle delete asset step."""
        errors: dict[str, str] = {}
        assets = self.coordinator.assets

        if not assets:
            errors["base"] = "no_assets"
            return self.async_show_form(
                step_id="delete_asset",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        if user_input is not None:
            asset_id = user_input.get("asset_id")
            if asset_id:
                await self.coordinator.async_delete_asset(asset_id)
                # [L-03] Preserve existing options by merging, not overwriting
                return self.async_create_entry(
                    data={**self.config_entry.options},
                )

        asset_options = {
            asset.id: asset.name for asset in assets.values()
        }

        return self.async_show_form(
            step_id="delete_asset",
            data_schema=vol.Schema(
                {
                    vol.Required("asset_id"): vol.In(asset_options),
                }
            ),
            errors=errors,
        )
