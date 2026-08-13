"""Config flow for Template Light Composer integration."""

from __future__ import annotations

import logging
from typing import Any

import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry, selector

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_LEVEL_ENTITY,
    CONF_LEVEL_ATTRIBUTE,
    CONF_LEVEL_UNIT,
    CONF_STATE_ENTITY,
    CONF_STATE_ATTRIBUTE,
    CONF_STATE_OPERATOR,
    CONF_STATE_THRESHOLD,
    CONF_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_ATTRIBUTE,
    CONF_MIN_TEMPERATURE,
    CONF_MAX_TEMPERATURE,
    CONF_TURN_ON_ACTION,
    CONF_TURN_OFF_ACTION,
    CONF_SET_LEVEL_ACTION,
    CONF_SET_TEMPERATURE_ACTION,
    CONF_ACTION_TYPE,
    CONF_ACTION_TARGET,
    CONF_ACTION_PARAMETERS,
    CONF_PARAMETER_MAPPING,
    CONF_SUPPORTS_TRANSITION,
    CONF_ICON,
    CONF_AVAILABILITY_TEMPLATE,
    ACTION_TYPE_SCRIPT,
    ACTION_TYPE_SERVICE,
    ACTION_TYPE_SCENE,
    OPERATORS,
    DEFAULT_NAME,
    DEFAULT_MIN_TEMPERATURE,
    DEFAULT_MAX_TEMPERATURE,
    DEFAULT_SUPPORTS_TRANSITION,
    DEFAULT_ICON,
)

_LOGGER = logging.getLogger(__name__)


class TemplateComposerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Template Light Composer."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.config_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the basic configuration and template setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate name
            name = user_input.get(CONF_NAME, DEFAULT_NAME)
            if not name.strip():
                errors[CONF_NAME] = "name_required"
            else:
                # Generate unique ID using UUID for collision safety
                unique_id = str(uuid.uuid4())

                # Check if this unique ID already exists
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Validate entities exist
                level_entity = user_input.get(CONF_LEVEL_ENTITY)
                state_entity = user_input.get(CONF_STATE_ENTITY)
                temp_entity = user_input.get(CONF_TEMPERATURE_ENTITY)

                for entity_key, entity_id in [
                    (CONF_LEVEL_ENTITY, level_entity),
                    (CONF_STATE_ENTITY, state_entity),
                    (CONF_TEMPERATURE_ENTITY, temp_entity),
                ]:
                    if entity_id:
                        entity_registry_inst = entity_registry.async_get(self.hass)
                        if not entity_registry_inst.async_is_registered(entity_id):
                            state = self.hass.states.get(entity_id)
                            if not state:
                                errors[entity_key] = "entity_not_found"

                # Validate temperature range
                min_temp = user_input.get(CONF_MIN_TEMPERATURE, DEFAULT_MIN_TEMPERATURE)
                max_temp = user_input.get(CONF_MAX_TEMPERATURE, DEFAULT_MAX_TEMPERATURE)
                if min_temp >= max_temp:
                    errors[CONF_MIN_TEMPERATURE] = "min_temp_invalid"

                if not errors:
                    # Store basic and template configuration
                    self.config_data.update(
                        {
                            CONF_NAME: name,
                            CONF_UNIQUE_ID: unique_id,
                            CONF_LEVEL_ENTITY: level_entity,
                            CONF_LEVEL_ATTRIBUTE: user_input.get(
                                CONF_LEVEL_ATTRIBUTE, "state"
                            ),
                            CONF_LEVEL_UNIT: user_input.get(CONF_LEVEL_UNIT, ""),
                            CONF_STATE_ENTITY: state_entity,
                            CONF_STATE_ATTRIBUTE: user_input.get(
                                CONF_STATE_ATTRIBUTE, "state"
                            ),
                            CONF_STATE_OPERATOR: user_input.get(
                                CONF_STATE_OPERATOR, ">"
                            ),
                            CONF_STATE_THRESHOLD: user_input.get(
                                CONF_STATE_THRESHOLD, 0
                            ),
                            CONF_TEMPERATURE_ENTITY: temp_entity,
                            CONF_TEMPERATURE_ATTRIBUTE: user_input.get(
                                CONF_TEMPERATURE_ATTRIBUTE, "state"
                            ),
                            CONF_MIN_TEMPERATURE: min_temp,
                            CONF_MAX_TEMPERATURE: max_temp,
                        }
                    )

                    return await self.async_step_actions()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    # Basic Configuration
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    # Template Configuration
                    vol.Optional(CONF_LEVEL_ENTITY): selector.EntitySelector(),
                    vol.Optional(CONF_LEVEL_ATTRIBUTE, default="state"): str,
                    vol.Optional(CONF_LEVEL_UNIT, default=""): str,
                    vol.Optional(CONF_STATE_ENTITY): selector.EntitySelector(),
                    vol.Optional(CONF_STATE_ATTRIBUTE, default="state"): str,
                    vol.Optional(CONF_STATE_OPERATOR, default=">"): vol.In(
                        list(OPERATORS.keys())
                    ),
                    vol.Optional(CONF_STATE_THRESHOLD, default=0): vol.Coerce(float),
                    vol.Optional(CONF_TEMPERATURE_ENTITY): selector.EntitySelector(),
                    vol.Optional(CONF_TEMPERATURE_ATTRIBUTE, default="state"): str,
                    vol.Optional(
                        CONF_MIN_TEMPERATURE, default=DEFAULT_MIN_TEMPERATURE
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_MAX_TEMPERATURE, default=DEFAULT_MAX_TEMPERATURE
                    ): vol.Coerce(int),
                }
            ),
            errors=errors,
            description_placeholders={
                "step_title": "Basic Configuration & Templates",
                "step_description": "Configure the basic settings and template sources for your light.",
            },
        )

    async def async_step_actions(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the actions configuration step."""
        errors: dict[str, str] = {}

        # Get available actions for selectors
        action_selectors = await self._get_action_selectors()

        # Build a combined list of all available targets for the dropdown
        all_targets = []
        seen = set()
        for targets in action_selectors.values():
            for t in targets:
                if t not in seen:
                    all_targets.append(t)
                    seen.add(t)

        if user_input is not None:
            # Process all four actions
            actions_config = {}

            # Process each action type
            for action_key in [
                CONF_TURN_ON_ACTION,
                CONF_TURN_OFF_ACTION,
                CONF_SET_LEVEL_ACTION,
                CONF_SET_TEMPERATURE_ACTION,
            ]:
                action_type_key = f"{action_key}_type"
                action_target_key = f"{action_key}_target"

                action_type = user_input.get(action_type_key)
                action_target = user_input.get(action_target_key)

                if action_type and action_target:
                    # Validate action target based on type
                    if (
                        action_type == ACTION_TYPE_SCRIPT
                        and not action_target.startswith("script.")
                    ):
                        errors[action_target_key] = "script_prefix_required"
                    elif (
                        action_type == ACTION_TYPE_SCENE
                        and not action_target.startswith("scene.")
                    ):
                        errors[action_target_key] = "scene_prefix_required"

                    if not errors:
                        actions_config[action_key] = {
                            CONF_ACTION_TYPE: action_type,
                            CONF_ACTION_TARGET: action_target,
                            CONF_ACTION_PARAMETERS: [],
                            CONF_PARAMETER_MAPPING: {},
                        }

            if not errors:
                # Store actions configuration
                self.config_data.update(actions_config)
                return await self.async_step_advanced()

        # Build schema with type AND target shown together for each action
        schema_dict = {}

        action_labels = {
            CONF_TURN_ON_ACTION: "Turn On",
            CONF_TURN_OFF_ACTION: "Turn Off",
            CONF_SET_LEVEL_ACTION: "Set Brightness",
            CONF_SET_TEMPERATURE_ACTION: "Set Temperature",
        }

        for action_key, label in action_labels.items():
            action_type_key = f"{action_key}_type"
            action_target_key = f"{action_key}_target"

            # Action type selector
            schema_dict[vol.Optional(action_type_key)] = vol.In(
                [
                    ACTION_TYPE_SCRIPT,
                    ACTION_TYPE_SERVICE,
                    ACTION_TYPE_SCENE,
                ]
            )

            # Action target - use text input for flexibility
            schema_dict[vol.Optional(action_target_key, default="")] = str

        return self.async_show_form(
            step_id="actions",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "step_title": "Actions Configuration",
                "step_description": "Configure the actions for turn on, turn off, set brightness, and set temperature.",
            },
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the advanced options step."""
        if user_input is not None:
            # Store advanced configuration
            self.config_data.update(
                {
                    CONF_SUPPORTS_TRANSITION: user_input.get(
                        CONF_SUPPORTS_TRANSITION, DEFAULT_SUPPORTS_TRANSITION
                    ),
                    CONF_ICON: user_input.get(CONF_ICON, DEFAULT_ICON),
                    CONF_AVAILABILITY_TEMPLATE: user_input.get(
                        CONF_AVAILABILITY_TEMPLATE, ""
                    ),
                }
            )

            # Create the config entry
            return self.async_create_entry(
                title=self.config_data[CONF_NAME],
                data=self.config_data,
            )

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SUPPORTS_TRANSITION, default=DEFAULT_SUPPORTS_TRANSITION
                    ): bool,
                    vol.Optional(
                        CONF_ICON, default=DEFAULT_ICON
                    ): selector.IconSelector(),
                    vol.Optional(CONF_AVAILABILITY_TEMPLATE, default=""): str,
                }
            ),
            description_placeholders={
                "step_title": "Advanced Options",
                "step_description": "Configure advanced settings for your template light (optional).",
            },
        )

    async def _get_action_selectors(self) -> dict[str, list[str]]:
        """Get available actions for each action type."""
        selectors = {}

        # Get scripts
        scripts = []
        for entity_id in self.hass.states.async_entity_ids("script"):
            scripts.append(entity_id)
        selectors[ACTION_TYPE_SCRIPT] = scripts

        # Get scenes
        scenes = []
        for entity_id in self.hass.states.async_entity_ids("scene"):
            scenes.append(entity_id)
        selectors[ACTION_TYPE_SCENE] = scenes

        # Get common light services
        services = [
            "light.turn_on",
            "light.turn_off",
            "light.toggle",
            "input_number.set_value",
            "input_select.select_option",
            "input_boolean.turn_on",
            "input_boolean.turn_off",
            "input_boolean.toggle",
        ]
        selectors[ACTION_TYPE_SERVICE] = services

        return selectors

