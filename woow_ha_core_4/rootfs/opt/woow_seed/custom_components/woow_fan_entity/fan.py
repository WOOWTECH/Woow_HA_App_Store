"""Support for WoowTech Fan Entity."""

from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    DOMAIN as HOMEASSISTANT_DOMAIN,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.script import Script

from homeassistant.helpers.template import Template, TemplateError

from .const import (
    CONF_DIRECTION_ENTITY,
    CONF_DIRECTION_RECEIVE_TEMPLATE,
    CONF_ENABLE_DIRECTION,
    CONF_ENABLE_OSCILLATION,
    CONF_OSCILLATING_ENTITY,
    CONF_PERCENTAGE_ENTITY,
    CONF_PERCENTAGE_INPUT_MAX,
    CONF_PERCENTAGE_INPUT_MIN,
    CONF_PERCENTAGE_OUTPUT_MAX,
    CONF_PERCENTAGE_OUTPUT_MIN,
    CONF_PERCENTAGE_RECEIVE_TEMPLATE,
    CONF_PRESET_MODE_ENTITY,
    CONF_PRESET_MODE_RECEIVE_TEMPLATE,
    CONF_PRESET_MODES,
    CONF_SET_DIRECTION_ACTION,
    CONF_SET_OSCILLATING_ACTION,
    CONF_SET_PERCENTAGE_ACTION,
    CONF_SET_PRESET_MODE_ACTION,
    CONF_SPEED_COUNT,
    CONF_SWITCH_ENTITY,
    DEFAULT_NAME,
    DEFAULT_SPEED_COUNT,
    DIRECTION_FORWARD,
    DIRECTION_REVERSE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


# ============================================================================
# Config Entry Setup
# ============================================================================


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WoowTech Fan Entity from a config entry."""
    options = config_entry.options

    _LOGGER.debug(
        "Setting up SimpleFan from config entry: %s",
        config_entry.entry_id,
    )

    name = options.get(CONF_NAME, DEFAULT_NAME)
    switch_entity_id = options.get(CONF_SWITCH_ENTITY)
    speed_count = int(options.get(CONF_SPEED_COUNT, DEFAULT_SPEED_COUNT))
    preset_modes = options.get(CONF_PRESET_MODES)
    enable_oscillation = options.get(CONF_ENABLE_OSCILLATION, False)
    enable_direction = options.get(CONF_ENABLE_DIRECTION, False)

    # Entity selectors for TX/RX targets
    percentage_entity_id = options.get(CONF_PERCENTAGE_ENTITY)
    preset_mode_entity_id = options.get(CONF_PRESET_MODE_ENTITY)
    oscillating_entity_id = options.get(CONF_OSCILLATING_ENTITY)
    direction_entity_id = options.get(CONF_DIRECTION_ENTITY)

    # Receive templates
    percentage_receive_template = options.get(CONF_PERCENTAGE_RECEIVE_TEMPLATE)
    preset_mode_receive_template = options.get(CONF_PRESET_MODE_RECEIVE_TEMPLATE)
    direction_receive_template = options.get(CONF_DIRECTION_RECEIVE_TEMPLATE)

    # Linear interpolation (percentage only)
    percentage_input_min = options.get(CONF_PERCENTAGE_INPUT_MIN)
    percentage_input_max = options.get(CONF_PERCENTAGE_INPUT_MAX)
    percentage_output_min = options.get(CONF_PERCENTAGE_OUTPUT_MIN)
    percentage_output_max = options.get(CONF_PERCENTAGE_OUTPUT_MAX)

    # Action scripts
    def _make_script(action_data: list[dict]) -> Script:
        validated = cv.SCRIPT_SCHEMA(action_data)
        return Script(hass, validated, name, DOMAIN)

    set_percentage_script = None
    if action := options.get(CONF_SET_PERCENTAGE_ACTION):
        set_percentage_script = _make_script(action)

    set_preset_mode_script = None
    if action := options.get(CONF_SET_PRESET_MODE_ACTION):
        set_preset_mode_script = _make_script(action)

    set_oscillating_script = None
    if action := options.get(CONF_SET_OSCILLATING_ACTION):
        set_oscillating_script = _make_script(action)

    set_direction_script = None
    if action := options.get(CONF_SET_DIRECTION_ACTION):
        set_direction_script = _make_script(action)

    entity = SimpleFan(
        hass=hass,
        name=name,
        switch_entity_id=switch_entity_id,
        speed_count=speed_count,
        preset_modes=preset_modes,
        enable_oscillation=enable_oscillation,
        enable_direction=enable_direction,
        unique_id=config_entry.entry_id,
        percentage_entity_id=percentage_entity_id,
        preset_mode_entity_id=preset_mode_entity_id,
        oscillating_entity_id=oscillating_entity_id,
        direction_entity_id=direction_entity_id,
        set_percentage_script=set_percentage_script,
        set_preset_mode_script=set_preset_mode_script,
        set_oscillating_script=set_oscillating_script,
        set_direction_script=set_direction_script,
        percentage_receive_template=percentage_receive_template,
        preset_mode_receive_template=preset_mode_receive_template,
        direction_receive_template=direction_receive_template,
        percentage_input_min=percentage_input_min,
        percentage_input_max=percentage_input_max,
        percentage_output_min=percentage_output_min,
        percentage_output_max=percentage_output_max,
    )

    async_add_entities([entity])

    _LOGGER.info(
        "Created SimpleFan entity '%s' with speed_count=%d",
        name,
        speed_count,
    )


# ============================================================================
# SimpleFan Entity
# ============================================================================


class SimpleFan(FanEntity, RestoreEntity):
    """A fan entity with TX/RX support for entity selectors and action scripts."""

    _attr_should_poll = False
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        switch_entity_id: str | None,
        speed_count: int,
        preset_modes: list[str] | None,
        enable_oscillation: bool,
        enable_direction: bool,
        unique_id: str,
        # TX/RX entity selectors
        percentage_entity_id: str | None = None,
        preset_mode_entity_id: str | None = None,
        oscillating_entity_id: str | None = None,
        direction_entity_id: str | None = None,
        # Action script overrides
        set_percentage_script: Script | None = None,
        set_preset_mode_script: Script | None = None,
        set_oscillating_script: Script | None = None,
        set_direction_script: Script | None = None,
        # Receive templates
        percentage_receive_template: str | None = None,
        preset_mode_receive_template: str | None = None,
        direction_receive_template: str | None = None,
        # Linear interpolation (percentage only)
        percentage_input_min: float | None = None,
        percentage_input_max: float | None = None,
        percentage_output_min: float | None = None,
        percentage_output_max: float | None = None,
    ) -> None:
        """Initialize the fan entity."""
        self._attr_name = name
        self._attr_unique_id = unique_id

        # Switch entity for on/off control
        self._switch_entity_id = switch_entity_id

        # Fan settings
        self._attr_speed_count = speed_count

        # TX/RX entity selectors
        self._percentage_entity_id = percentage_entity_id
        self._preset_mode_entity_id = preset_mode_entity_id
        self._oscillating_entity_id = oscillating_entity_id
        self._direction_entity_id = direction_entity_id

        # Action script overrides
        self._set_percentage_script = set_percentage_script
        self._set_preset_mode_script = set_preset_mode_script
        self._set_oscillating_script = set_oscillating_script
        self._set_direction_script = set_direction_script

        # Receive templates
        self._percentage_receive_template = percentage_receive_template
        self._preset_mode_receive_template = preset_mode_receive_template
        self._direction_receive_template = direction_receive_template

        # Linear interpolation (percentage only)
        self._percentage_input_min = percentage_input_min
        self._percentage_input_max = percentage_input_max
        self._percentage_output_min = percentage_output_min
        self._percentage_output_max = percentage_output_max
        self._has_percentage_linear = all(
            x is not None for x in [
                percentage_input_min, percentage_input_max,
                percentage_output_min, percentage_output_max,
            ]
        )

        # Preset modes
        self._attr_preset_modes = preset_modes if preset_modes else None

        # State variables
        self._attr_percentage: int | None = None
        self._attr_preset_mode: str | None = None
        self._attr_oscillating: bool | None = False if enable_oscillation else None
        self._attr_current_direction: str | None = (
            DIRECTION_FORWARD if enable_direction else None
        )

        # Supported features
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.TURN_ON
        )

        if preset_modes:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE

        if enable_oscillation:
            self._attr_supported_features |= FanEntityFeature.OSCILLATE

        if enable_direction:
            self._attr_supported_features |= FanEntityFeature.DIRECTION

    async def async_added_to_hass(self) -> None:
        """Register listeners and restore state.

        Order: restore saved state first, then sync from live RX entities.
        This ensures live entity state always takes precedence over stale
        restored state after a restart.
        """
        await super().async_added_to_hass()

        # 1. Restore previous state (lowest priority — may be stale)
        if (old_state := await self.async_get_last_state()) is not None:
            if (pct := old_state.attributes.get("percentage")) is not None:
                self._attr_percentage = int(pct)

            if self._attr_preset_modes:
                if (preset := old_state.attributes.get("preset_mode")) in (
                    self._attr_preset_modes or []
                ):
                    self._attr_preset_mode = preset

            if self._attr_oscillating is not None:
                if (osc := old_state.attributes.get("oscillating")) is not None:
                    self._attr_oscillating = bool(osc)

            if self._attr_current_direction is not None:
                if (
                    direction := old_state.attributes.get("current_direction")
                ) in (DIRECTION_FORWARD, DIRECTION_REVERSE):
                    self._attr_current_direction = direction

        # 2. RX: Register listeners and sync from live entities (overrides restored state)

        # RX: Listen to switch entity for on/off
        if self._switch_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._switch_entity_id],
                    self._async_switch_changed,
                )
            )

        # RX: Listen to percentage entity
        if self._percentage_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._percentage_entity_id],
                    self._async_percentage_entity_changed,
                )
            )
            pct_state = self.hass.states.get(self._percentage_entity_id)
            if pct_state and pct_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                result = self._apply_receive_transform(
                    pct_state.state,
                    self._percentage_receive_template,
                    self._percentage_input_min,
                    self._percentage_input_max,
                    self._percentage_output_min,
                    self._percentage_output_max,
                )
                if result is not None:
                    try:
                        pct = max(0, min(100, int(float(result))))
                        self._attr_percentage = pct
                    except (ValueError, TypeError):
                        pass

        # RX: Listen to preset mode entity
        if self._preset_mode_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._preset_mode_entity_id],
                    self._async_preset_mode_entity_changed,
                )
            )
            preset_state = self.hass.states.get(self._preset_mode_entity_id)
            if preset_state and preset_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                raw = preset_state.state
                if self._preset_mode_receive_template:
                    result = self._render_receive_template(
                        self._preset_mode_receive_template, raw
                    )
                    if result is not None:
                        raw = result
                if raw in (self._attr_preset_modes or []):
                    self._attr_preset_mode = raw

        # RX: Listen to oscillating entity
        if self._oscillating_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._oscillating_entity_id],
                    self._async_oscillating_entity_changed,
                )
            )
            osc_state = self.hass.states.get(self._oscillating_entity_id)
            if osc_state and osc_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._attr_oscillating = osc_state.state == STATE_ON

        # RX: Listen to direction entity
        if self._direction_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._direction_entity_id],
                    self._async_direction_entity_changed,
                )
            )
            dir_state = self.hass.states.get(self._direction_entity_id)
            if dir_state and dir_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                raw = dir_state.state
                if self._direction_receive_template:
                    result = self._render_receive_template(
                        self._direction_receive_template, raw
                    )
                    if result is not None:
                        raw = result
                if raw in (DIRECTION_FORWARD, DIRECTION_REVERSE):
                    self._attr_current_direction = raw

        # 3. Sync switch state
        if self._switch_entity_id:
            sw_state = self.hass.states.get(self._switch_entity_id)
            if sw_state is not None:
                is_on = sw_state.state == STATE_ON
                if is_on and (self._attr_percentage or 0) == 0:
                    self._attr_percentage = self._default_percentage()
                elif not is_on and (self._attr_percentage or 0) > 0:
                    self._attr_percentage = 0

    def _default_percentage(self) -> int:
        """Return a sensible default percentage when turning on."""
        step = 100 / self._attr_speed_count
        return int(step)

    # ------------------------------------------------------------------
    # Receive Transform Helpers
    # ------------------------------------------------------------------

    def _render_receive_template(
        self, template_str: str, value: str
    ) -> str | None:
        """Render a Jinja2 receive template with {{ value }} variable.

        Returns the rendered string, or None on error (caller skips update).
        """
        try:
            # Cache Template objects to avoid recreation on every render
            if not hasattr(self, "_template_cache"):
                self._template_cache: dict[str, Template] = {}
            tpl = self._template_cache.get(template_str)
            if tpl is None:
                tpl = Template(template_str, self.hass)
                tpl.hass = self.hass
                self._template_cache[template_str] = tpl
            result = tpl.async_render({"value": value})
            return str(result)
        except TemplateError:
            _LOGGER.warning(
                "Receive template render failed for value=%s, template=%s",
                value,
                template_str,
            )
            return None

    @staticmethod
    def _apply_linear_interpolation(
        value: float,
        in_min: float,
        in_max: float,
        out_min: float,
        out_max: float,
    ) -> float:
        """Compute y = (value - in_min) / (in_max - in_min) * (out_max - out_min) + out_min.

        Division-by-zero guard: returns out_min if in_min == in_max.
        """
        if in_max == in_min:
            return out_min
        return (value - in_min) / (in_max - in_min) * (out_max - out_min) + out_min

    @staticmethod
    def _apply_reverse_interpolation(
        value: float,
        in_min: float,
        in_max: float,
        out_min: float,
        out_max: float,
    ) -> float:
        """Reverse linear interpolation: map internal (out) back to external (in)."""
        if out_max == out_min:
            return in_min
        return (value - out_min) / (out_max - out_min) * (in_max - in_min) + in_min

    def _apply_receive_transform(
        self,
        value: str,
        template: str | None,
        in_min: float | None,
        in_max: float | None,
        out_min: float | None,
        out_max: float | None,
    ) -> str | None:
        """Apply receive transform: linear interpolation > template > passthrough.

        Returns transformed string, or None on error (caller skips update).
        """
        # Priority 1: Linear interpolation (all 4 fields must be set)
        if (
            in_min is not None
            and in_max is not None
            and out_min is not None
            and out_max is not None
        ):
            try:
                raw = float(value)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Linear interpolation: non-numeric value=%s", value
                )
                return None
            result = self._apply_linear_interpolation(
                raw, in_min, in_max, out_min, out_max
            )
            return str(result)

        # Priority 2: Receive template (Jinja2)
        if template:
            return self._render_receive_template(template, value)

        # Priority 3: Raw passthrough
        return value

    # ------------------------------------------------------------------
    # TX Helper
    # ------------------------------------------------------------------

    async def _async_set_entity_state(
        self, entity_id: str, value: str
    ) -> None:
        """TX helper: send a value to an external entity based on its domain."""
        domain = entity_id.split(".")[0]
        if domain in ("input_select", "select"):
            await self.hass.services.async_call(
                domain,
                "select_option",
                {ATTR_ENTITY_ID: entity_id, "option": value},
                blocking=True,
                context=self._context,
            )
        elif domain in ("switch", "input_boolean"):
            service = (
                SERVICE_TURN_ON if value in (STATE_ON, "on", "True", "true") else SERVICE_TURN_OFF
            )
            await self.hass.services.async_call(
                HOMEASSISTANT_DOMAIN,
                service,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
                context=self._context,
            )
        elif domain in ("input_number", "number"):
            await self.hass.services.async_call(
                domain,
                "set_value",
                {ATTR_ENTITY_ID: entity_id, "value": float(value)},
                blocking=True,
                context=self._context,
            )
        else:
            _LOGGER.warning("Unsupported entity domain for TX: %s", domain)

    # ------------------------------------------------------------------
    # RX Callbacks
    # ------------------------------------------------------------------

    @callback
    def _async_switch_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle switch entity state changes (on/off)."""
        new_state = event.data["new_state"]
        if new_state is None:
            return
        is_on = new_state.state == STATE_ON
        if is_on and (self._attr_percentage or 0) == 0:
            self._attr_percentage = self._default_percentage()
        elif not is_on and (self._attr_percentage or 0) > 0:
            self._attr_percentage = 0
        self.async_write_ha_state()

    @callback
    def _async_percentage_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle percentage entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            result = self._apply_receive_transform(
                new_state.state,
                self._percentage_receive_template,
                self._percentage_input_min,
                self._percentage_input_max,
                self._percentage_output_min,
                self._percentage_output_max,
            )
            if result is None:
                return
            try:
                pct = max(0, min(100, int(float(result))))
                if self._attr_percentage != pct:
                    self._attr_percentage = pct
                    if pct > 0:
                        self._attr_preset_mode = None
                    self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    @callback
    def _async_preset_mode_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle preset mode entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raw = new_state.state
            if self._preset_mode_receive_template:
                result = self._render_receive_template(
                    self._preset_mode_receive_template, raw
                )
                if result is None:
                    return
                raw = result
            if raw in (self._attr_preset_modes or []):
                if self._attr_preset_mode != raw:
                    self._attr_preset_mode = raw
                    self.async_write_ha_state()

    @callback
    def _async_oscillating_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle oscillating entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            osc = new_state.state == STATE_ON
            if self._attr_oscillating != osc:
                self._attr_oscillating = osc
                self.async_write_ha_state()

    @callback
    def _async_direction_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle direction entity state changes."""
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raw = new_state.state
            if self._direction_receive_template:
                result = self._render_receive_template(
                    self._direction_receive_template, raw
                )
                if result is None:
                    return
                raw = result
            if raw in (DIRECTION_FORWARD, DIRECTION_REVERSE):
                if self._attr_current_direction != raw:
                    self._attr_current_direction = raw
                    self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Fan Control Methods (TX)
    # ------------------------------------------------------------------

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
            return

        if percentage is not None:
            await self.async_set_percentage(percentage)
            return

        # Default: turn on at default speed
        self._attr_percentage = self._default_percentage()
        self._attr_preset_mode = None

        # TX: turn on switch entity
        if self._switch_entity_id:
            await self.hass.services.async_call(
                HOMEASSISTANT_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: self._switch_entity_id},
                blocking=True,
                context=self._context,
            )

        # TX: send percentage
        if self._set_percentage_script:
            await self._set_percentage_script.async_run(
                run_variables={"percentage": self._attr_percentage},
                context=self._context,
            )
        elif self._percentage_entity_id:
            tx_value = self._attr_percentage
            if self._has_percentage_linear and tx_value is not None:
                tx_value = self._apply_reverse_interpolation(
                    tx_value,
                    self._percentage_input_min,
                    self._percentage_input_max,
                    self._percentage_output_min,
                    self._percentage_output_max,
                )
            await self._async_set_entity_state(
                self._percentage_entity_id, str(tx_value)
            )

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        self._attr_percentage = 0
        self._attr_preset_mode = None

        # TX: turn off switch entity
        if self._switch_entity_id:
            await self.hass.services.async_call(
                HOMEASSISTANT_DOMAIN,
                SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self._switch_entity_id},
                blocking=True,
                context=self._context,
            )

        # TX: send percentage 0
        if self._set_percentage_script:
            await self._set_percentage_script.async_run(
                run_variables={"percentage": 0},
                context=self._context,
            )
        elif self._percentage_entity_id:
            tx_value = 0
            if self._has_percentage_linear:
                tx_value = self._apply_reverse_interpolation(
                    0,
                    self._percentage_input_min,
                    self._percentage_input_max,
                    self._percentage_output_min,
                    self._percentage_output_max,
                )
            await self._async_set_entity_state(
                self._percentage_entity_id, str(tx_value)
            )

        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the fan speed percentage."""
        if percentage == 0:
            await self.async_turn_off()
            return

        self._attr_percentage = percentage
        self._attr_preset_mode = None  # Clear preset when setting speed

        # TX: turn on switch if off
        if self._switch_entity_id:
            sw_state = self.hass.states.get(self._switch_entity_id)
            if sw_state and sw_state.state != STATE_ON:
                await self.hass.services.async_call(
                    HOMEASSISTANT_DOMAIN,
                    SERVICE_TURN_ON,
                    {ATTR_ENTITY_ID: self._switch_entity_id},
                    context=self._context,
                )

        # TX: action script > entity selector
        if self._set_percentage_script:
            await self._set_percentage_script.async_run(
                run_variables={"percentage": percentage},
                context=self._context,
            )
        elif self._percentage_entity_id:
            tx_value = percentage
            if self._has_percentage_linear:
                tx_value = self._apply_reverse_interpolation(
                    percentage,
                    self._percentage_input_min,
                    self._percentage_input_max,
                    self._percentage_output_min,
                    self._percentage_output_max,
                )
            await self._async_set_entity_state(
                self._percentage_entity_id, str(tx_value)
            )

        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the fan preset mode."""
        if self._attr_preset_modes and preset_mode in self._attr_preset_modes:
            self._attr_preset_mode = preset_mode
            self._attr_percentage = None  # Clear percentage when in preset

            # TX: action script > entity selector
            if self._set_preset_mode_script:
                await self._set_preset_mode_script.async_run(
                    run_variables={"preset_mode": preset_mode},
                    context=self._context,
                )
            elif self._preset_mode_entity_id:
                await self._async_set_entity_state(
                    self._preset_mode_entity_id, preset_mode
                )

            self.async_write_ha_state()
        else:
            _LOGGER.error("Invalid preset mode: %s", preset_mode)

    async def async_oscillate(self, oscillating: bool) -> None:
        """Set fan oscillation."""
        self._attr_oscillating = oscillating

        # TX: action script > entity selector
        if self._set_oscillating_script:
            await self._set_oscillating_script.async_run(
                run_variables={"oscillating": oscillating},
                context=self._context,
            )
        elif self._oscillating_entity_id:
            await self._async_set_entity_state(
                self._oscillating_entity_id,
                STATE_ON if oscillating else "off",
            )

        self.async_write_ha_state()

    async def async_set_direction(self, direction: str) -> None:
        """Set fan direction."""
        if direction not in (DIRECTION_FORWARD, DIRECTION_REVERSE):
            _LOGGER.error("Invalid direction: %s", direction)
            return

        self._attr_current_direction = direction

        # TX: action script > entity selector
        if self._set_direction_script:
            await self._set_direction_script.async_run(
                run_variables={"direction": direction},
                context=self._context,
            )
        elif self._direction_entity_id:
            await self._async_set_entity_state(
                self._direction_entity_id, direction
            )

        self.async_write_ha_state()
