"""Template Light Composer light platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_OFF
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound, TemplateError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.template import Template
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity

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
    LEVEL_TEMPLATE,
    STATE_TEMPLATE,
    STATE_ATTR_TEMPLATE,
    TEMPERATURE_TEMPLATE,
    AVAILABILITY_TEMPLATE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Template Light Composer light from a config entry."""
    config = config_entry.data

    light = TemplateComposerLight(
        hass=hass,
        config=config,
        unique_id=config[CONF_UNIQUE_ID],
    )

    async_add_entities([light])


class TemplateComposerLight(LightEntity, RestoreEntity):
    """Representation of a Template Light Composer light."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        unique_id: str,
    ) -> None:
        """Initialize the Template Light Composer light."""
        self.hass = hass
        self._config = config
        self._attr_unique_id = unique_id
        self._attr_name = config[CONF_NAME]
        self._attr_icon = config.get(CONF_ICON)

        # Initialize state
        self._attr_is_on = False
        self._attr_brightness = None
        self._attr_color_temp_kelvin = None
        self._attr_available = True

        # Setup templates
        self._level_template = None
        self._state_template = None
        self._temperature_template = None
        self._availability_template = None

        self._setup_templates()
        self._setup_features()

        # Track entities for state changes
        self._entities_to_track = set()
        self._collect_entities_to_track()

        # Unsub function for state tracking
        self._unsub_state_change = None

        # Debounce: cancel handle for pending state update
        self._debounce_cancel = None

    def _setup_templates(self) -> None:
        """Set up the templates."""
        # Level template
        if self._config.get(CONF_LEVEL_ENTITY):
            level_template_str = LEVEL_TEMPLATE.format(
                entity=self._config[CONF_LEVEL_ENTITY],
            )
            _LOGGER.debug("Generated level template: %s", level_template_str)
            self._level_template = Template(level_template_str, self.hass)

        # State template
        if self._config.get(CONF_STATE_ENTITY):
            state_entity = self._config[CONF_STATE_ENTITY]
            operator = self._config.get(CONF_STATE_OPERATOR, ">")
            threshold = self._config.get(CONF_STATE_THRESHOLD, 0)

            # For input_boolean, use states() directly
            if state_entity.startswith("input_boolean."):
                state_template_str = f"{{{{ states('{state_entity}') == 'on' }}}}"
            else:
                attribute = self._config.get(CONF_STATE_ATTRIBUTE, "state")
                if attribute == "state":
                    # Use states() for primary entity state
                    state_template_str = STATE_TEMPLATE.format(
                        entity=state_entity,
                        operator=operator,
                        threshold=threshold,
                    )
                else:
                    # Use state_attr() for actual entity attributes
                    state_template_str = STATE_ATTR_TEMPLATE.format(
                        entity=state_entity,
                        attribute=attribute,
                        operator=operator,
                        threshold=threshold,
                    )

            _LOGGER.debug("Generated state template: %s", state_template_str)
            self._state_template = Template(state_template_str, self.hass)

        # Temperature template
        if self._config.get(CONF_TEMPERATURE_ENTITY):
            temp_template_str = TEMPERATURE_TEMPLATE.format(
                entity=self._config[CONF_TEMPERATURE_ENTITY],
            )
            _LOGGER.debug("Generated temperature template: %s", temp_template_str)
            self._temperature_template = Template(temp_template_str, self.hass)

        # Availability template
        if self._config.get(CONF_AVAILABILITY_TEMPLATE):
            self._availability_template = Template(
                self._config[CONF_AVAILABILITY_TEMPLATE], self.hass
            )

    def _setup_features(self) -> None:
        """Set up the supported features and color modes."""
        features = LightEntityFeature(0)
        color_modes = set()

        # Check if color temperature is supported
        if self._temperature_template:
            color_modes.add(ColorMode.COLOR_TEMP)
        # Check if brightness is supported
        elif self._level_template:
            color_modes.add(ColorMode.BRIGHTNESS)
        else:
            # Only add ONOFF if no other modes are supported
            color_modes.add(ColorMode.ONOFF)

        # Check if transition is supported
        if self._config.get(CONF_SUPPORTS_TRANSITION, True):
            features |= LightEntityFeature.TRANSITION

        self._attr_supported_features = features
        self._attr_supported_color_modes = color_modes

        # Set color mode based on supported color modes
        if ColorMode.COLOR_TEMP in color_modes:
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif ColorMode.BRIGHTNESS in color_modes:
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_color_mode = ColorMode.ONOFF

        # Set temperature limits using kelvin attributes directly
        if self._temperature_template:
            # Use kelvin values directly
            self._attr_min_color_temp_kelvin = self._config.get(
                CONF_MIN_TEMPERATURE, 2500
            )
            self._attr_max_color_temp_kelvin = self._config.get(
                CONF_MAX_TEMPERATURE, 6500
            )

    def _collect_entities_to_track(self) -> None:
        """Collect all entities that need to be tracked for state changes."""
        if self._config.get(CONF_LEVEL_ENTITY):
            self._entities_to_track.add(self._config[CONF_LEVEL_ENTITY])

        if self._config.get(CONF_STATE_ENTITY):
            self._entities_to_track.add(self._config[CONF_STATE_ENTITY])

        if self._config.get(CONF_TEMPERATURE_ENTITY):
            self._entities_to_track.add(self._config[CONF_TEMPERATURE_ENTITY])

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Restore state
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == STATE_ON
            if last_state.attributes.get(ATTR_BRIGHTNESS):
                self._attr_brightness = last_state.attributes.get(ATTR_BRIGHTNESS)
            if last_state.attributes.get(ATTR_COLOR_TEMP_KELVIN):
                self._attr_color_temp_kelvin = last_state.attributes.get(
                    ATTR_COLOR_TEMP_KELVIN
                )

        # Start tracking state changes
        self._start_tracking()

        # Update initial state
        await self._async_update_state()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._unsub_state_change:
            self._unsub_state_change()
            self._unsub_state_change = None
        if self._debounce_cancel:
            self._debounce_cancel()
            self._debounce_cancel = None

    def _start_tracking(self) -> None:
        """Start tracking state changes."""
        if self._entities_to_track:
            self._unsub_state_change = async_track_state_change_event(
                self.hass,
                list(self._entities_to_track),
                self._async_state_changed,
            )

    @callback
    def _async_state_changed(self, event) -> None:
        """Handle state changes with debounce to avoid unbounded task creation."""
        if self._debounce_cancel:
            self._debounce_cancel()

        @callback
        def _debounced_update(_now) -> None:
            """Perform the debounced update."""
            self._debounce_cancel = None
            self.hass.async_create_task(
                self._async_update_state(),
                f"template_light_composer_update_{self._attr_unique_id}",
            )

        self._debounce_cancel = async_call_later(
            self.hass, 0.1, _debounced_update
        )

    async def _async_update_state(self) -> None:
        """Update the state based on templates."""
        try:
            # Update availability
            if self._availability_template:
                avail_result = self._availability_template.async_render(
                    parse_result=False
                )
                if isinstance(avail_result, str):
                    self._attr_available = avail_result.lower() in (
                        "true",
                        "1",
                        "on",
                        "yes",
                    )
                else:
                    self._attr_available = bool(avail_result)

            # Update on/off state
            if self._state_template:
                state_result = self._state_template.async_render(parse_result=False)
                _LOGGER.debug(
                    "State template result: %s (type: %s)",
                    state_result,
                    type(state_result),
                )

                # Handle the state result conversion more carefully
                if isinstance(state_result, str):
                    self._attr_is_on = state_result.lower() in (
                        "true",
                        "1",
                        "on",
                        "yes",
                    )
                else:
                    self._attr_is_on = bool(state_result)

                _LOGGER.debug("Set light is_on to: %s", self._attr_is_on)

            # Update brightness
            if self._level_template:
                try:
                    level_result = self._level_template.async_render(parse_result=False)
                    _LOGGER.debug("Level template result: %s", level_result)
                    brightness = int(level_result)
                    # Convert to Home Assistant brightness scale (0-255)
                    if brightness < 0:
                        brightness = 0
                    elif brightness > 255:
                        brightness = 255
                    self._attr_brightness = brightness
                    _LOGGER.debug("Set brightness to: %s", brightness)
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Invalid brightness value from template: %s", level_result
                    )

            # Update color temperature
            if self._temperature_template:
                try:
                    temp_result = self._temperature_template.async_render(
                        parse_result=False
                    )
                    color_temp_kelvin = int(temp_result)
                    # Ensure it's within limits
                    if color_temp_kelvin < self._attr_min_color_temp_kelvin:
                        color_temp_kelvin = self._attr_min_color_temp_kelvin
                    elif color_temp_kelvin > self._attr_max_color_temp_kelvin:
                        color_temp_kelvin = self._attr_max_color_temp_kelvin
                    self._attr_color_temp_kelvin = color_temp_kelvin
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Invalid color temperature value from template: %s", temp_result
                    )

            self.async_write_ha_state()

        except TemplateError as ex:
            _LOGGER.error("Error updating template light state: %s", ex)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        action_config = self._config.get(CONF_TURN_ON_ACTION)
        if not action_config:
            _LOGGER.warning("No turn on action configured")
            return

        # Handle brightness
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]

            # If we have a set level action, use it
            level_action = self._config.get(CONF_SET_LEVEL_ACTION)
            if level_action:
                await self._execute_action(
                    level_action,
                    action_key=CONF_SET_LEVEL_ACTION,
                    **kwargs,
                )

        # Handle color temperature
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]

            # If we have a set temperature action, use it
            temp_action = self._config.get(CONF_SET_TEMPERATURE_ACTION)
            if temp_action:
                await self._execute_action(
                    temp_action,
                    action_key=CONF_SET_TEMPERATURE_ACTION,
                    **kwargs,
                )

        # Always execute the turn on action to ensure the light turns on
        try:
            await self._execute_action(
                action_config, action_key=CONF_TURN_ON_ACTION, **kwargs
            )
            # Only update state if action succeeded
            self._attr_is_on = True
        except (ServiceNotFound, HomeAssistantError) as ex:
            _LOGGER.error("Failed to turn on light: %s", ex)

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        action_config = self._config.get(CONF_TURN_OFF_ACTION)
        if not action_config:
            _LOGGER.warning("No turn off action configured")
            return

        # Execute the turn off action
        try:
            await self._execute_action(
                action_config, action_key=CONF_TURN_OFF_ACTION, **kwargs
            )
            # Only update state if action succeeded
            self._attr_is_on = False
        except (ServiceNotFound, HomeAssistantError) as ex:
            _LOGGER.error("Failed to turn off light: %s", ex)

        self.async_write_ha_state()

    def _get_target_entity_for_action(
        self, action_key: str | None,
    ) -> str | None:
        """Determine the target entity_id for an action based on its role."""
        if action_key == CONF_TURN_ON_ACTION or action_key == CONF_TURN_OFF_ACTION:
            return self._config.get(CONF_STATE_ENTITY)
        if action_key == CONF_SET_LEVEL_ACTION:
            return self._config.get(CONF_LEVEL_ENTITY)
        if action_key == CONF_SET_TEMPERATURE_ACTION:
            return self._config.get(CONF_TEMPERATURE_ENTITY)
        return None

    async def _execute_action(
        self, action_config: dict[str, Any], action_key: str | None = None, **kwargs: Any
    ) -> None:
        """Execute an action with the given parameters."""
        action_type = action_config.get(CONF_ACTION_TYPE)
        action_target = action_config.get(CONF_ACTION_TARGET)
        parameter_mapping = action_config.get(CONF_PARAMETER_MAPPING, {})

        if not action_type or not action_target:
            _LOGGER.warning("Invalid action configuration")
            return

        # Build the service data
        service_data = {}

        # Add mapped parameters
        for param, mapping in parameter_mapping.items():
            template_str = mapping.get("template", "")
            default_value = mapping.get("default", "")

            if template_str:
                try:
                    template = Template(template_str, self.hass)
                    # Create context with kwargs
                    context = kwargs.copy()
                    context.update(
                        {
                            "brightness": kwargs.get(
                                ATTR_BRIGHTNESS, self._attr_brightness
                            ),
                            "color_temp_kelvin": kwargs.get(
                                ATTR_COLOR_TEMP_KELVIN, self._attr_color_temp_kelvin
                            ),
                            "transition": kwargs.get(ATTR_TRANSITION, 1),
                        }
                    )

                    value = template.async_render(variables=context, parse_result=False)
                    service_data[param] = value
                except TemplateError as ex:
                    _LOGGER.warning(
                        "Error rendering template for parameter %s: %s", param, ex
                    )
                    if default_value:
                        service_data[param] = default_value
            elif default_value:
                service_data[param] = default_value

        # Auto-populate entity_id if not set by parameter_mapping
        if "entity_id" not in service_data and action_type in (
            ACTION_TYPE_SERVICE,
            ACTION_TYPE_SCRIPT,
        ):
            target_entity = self._get_target_entity_for_action(action_key)
            if target_entity:
                service_data["entity_id"] = target_entity

        # Auto-populate value for input_number.set_value calls
        if (
            action_type == ACTION_TYPE_SERVICE
            and action_target == "input_number.set_value"
            and "value" not in service_data
        ):
            if action_key == CONF_SET_LEVEL_ACTION:
                value = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness)
                if value is not None:
                    service_data["value"] = value
            elif action_key == CONF_SET_TEMPERATURE_ACTION:
                value = kwargs.get(ATTR_COLOR_TEMP_KELVIN, self._attr_color_temp_kelvin)
                if value is not None:
                    service_data["value"] = value

        _LOGGER.debug(
            "Executing action: type=%s, target=%s, data=%s",
            action_type,
            action_target,
            service_data,
        )

        # Execute the action
        try:
            if action_type == ACTION_TYPE_SCRIPT:
                await self.hass.services.async_call(
                    "script",
                    action_target.split(".", 1)[1],
                    service_data,
                    context=self._context,
                )
            elif action_type == ACTION_TYPE_SERVICE:
                domain, service = action_target.split(".", 1)
                await self.hass.services.async_call(
                    domain,
                    service,
                    service_data,
                    context=self._context,
                )
            elif action_type == ACTION_TYPE_SCENE:
                await self.hass.services.async_call(
                    "scene",
                    "turn_on",
                    {"entity_id": action_target},
                    context=self._context,
                )
        except (ServiceNotFound, HomeAssistantError) as ex:
            _LOGGER.error("Error executing action %s: %s", action_target, ex)
            raise

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}

        # Add level unit if configured
        if self._config.get(CONF_LEVEL_UNIT):
            attrs["level_unit"] = self._config[CONF_LEVEL_UNIT]

        # Add template information
        if self._level_template:
            attrs["level_entity"] = self._config[CONF_LEVEL_ENTITY]

        if self._state_template:
            attrs["state_entity"] = self._config[CONF_STATE_ENTITY]

        if self._temperature_template:
            attrs["temperature_entity"] = self._config[CONF_TEMPERATURE_ENTITY]

        return attrs
