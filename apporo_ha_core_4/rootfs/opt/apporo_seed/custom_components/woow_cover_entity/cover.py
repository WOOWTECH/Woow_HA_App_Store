"""Support for WoowTech Cover Entity."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_utc_time_change,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.script import Script

from .const import (
    CONF_CLOSE_COVER_ACTION,
    CONF_CLOSE_TILT_ACTION,
    CONF_CLOSE_TIME,
    CONF_DEVICE_CLASS,
    CONF_ENABLE_TILT,
    CONF_OPEN_COVER_ACTION,
    CONF_OPEN_TIME,
    CONF_OPEN_TILT_ACTION,
    CONF_POSITION_ENTITY,
    CONF_SET_POSITION_ACTION,
    CONF_SET_TILT_POSITION_ACTION,
    CONF_STOP_COVER_ACTION,
    CONF_STOP_TILT_ACTION,
    CONF_TILT_CLOSE_TIME,
    CONF_TILT_OPEN_TIME,
    CONF_TILT_POSITION_ENTITY,
    DEFAULT_NAME,
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
    """Set up WoowTech Cover Entity from a config entry."""
    options = config_entry.options

    _LOGGER.debug(
        "Setting up SimpleCover from config entry: %s",
        config_entry.entry_id,
    )

    name = options.get(CONF_NAME, DEFAULT_NAME)
    device_class_str = options.get(CONF_DEVICE_CLASS)
    enable_tilt = options.get(CONF_ENABLE_TILT, False)

    # Entity selectors for TX/RX targets
    position_entity_id = options.get(CONF_POSITION_ENTITY)
    tilt_position_entity_id = options.get(CONF_TILT_POSITION_ENTITY)

    # Action scripts
    def _make_script(action_data: list[dict]) -> Script:
        validated = cv.SCRIPT_SCHEMA(action_data)
        return Script(hass, validated, name, DOMAIN)

    set_position_script = None
    if action := options.get(CONF_SET_POSITION_ACTION):
        set_position_script = _make_script(action)

    set_tilt_position_script = None
    if action := options.get(CONF_SET_TILT_POSITION_ACTION):
        set_tilt_position_script = _make_script(action)

    open_cover_script = None
    if action := options.get(CONF_OPEN_COVER_ACTION):
        open_cover_script = _make_script(action)

    close_cover_script = None
    if action := options.get(CONF_CLOSE_COVER_ACTION):
        close_cover_script = _make_script(action)

    stop_cover_script = None
    if action := options.get(CONF_STOP_COVER_ACTION):
        stop_cover_script = _make_script(action)

    open_tilt_script = None
    if action := options.get(CONF_OPEN_TILT_ACTION):
        open_tilt_script = _make_script(action)

    close_tilt_script = None
    if action := options.get(CONF_CLOSE_TILT_ACTION):
        close_tilt_script = _make_script(action)

    stop_tilt_script = None
    if action := options.get(CONF_STOP_TILT_ACTION):
        stop_tilt_script = _make_script(action)

    # Time-based position estimation
    open_time = options.get(CONF_OPEN_TIME)
    close_time = options.get(CONF_CLOSE_TIME)
    tilt_open_time = options.get(CONF_TILT_OPEN_TIME)
    tilt_close_time = options.get(CONF_TILT_CLOSE_TIME)

    # Validate: both open_time and close_time must be set together
    if (open_time is None) != (close_time is None):
        _LOGGER.warning(
            "Both open_time and close_time must be configured for time-based "
            "estimation. Ignoring partial configuration"
        )
        open_time = None
        close_time = None

    if (tilt_open_time is None) != (tilt_close_time is None):
        _LOGGER.warning(
            "Both tilt_open_time and tilt_close_time must be configured. "
            "Ignoring partial configuration"
        )
        tilt_open_time = None
        tilt_close_time = None

    # Parse device class
    device_class = None
    if device_class_str:
        try:
            device_class = CoverDeviceClass(device_class_str)
        except ValueError:
            _LOGGER.warning("Invalid device class: %s", device_class_str)

    entity = SimpleCover(
        hass=hass,
        name=name,
        device_class=device_class,
        enable_tilt=enable_tilt,
        unique_id=config_entry.entry_id,
        position_entity_id=position_entity_id,
        tilt_position_entity_id=tilt_position_entity_id,
        set_position_script=set_position_script,
        set_tilt_position_script=set_tilt_position_script,
        open_cover_script=open_cover_script,
        close_cover_script=close_cover_script,
        stop_cover_script=stop_cover_script,
        open_tilt_script=open_tilt_script,
        close_tilt_script=close_tilt_script,
        stop_tilt_script=stop_tilt_script,
        open_time=open_time,
        close_time=close_time,
        tilt_open_time=tilt_open_time,
        tilt_close_time=tilt_close_time,
    )

    async_add_entities([entity])

    _LOGGER.info(
        "Created SimpleCover entity '%s' (device_class=%s, tilt=%s)",
        name,
        device_class_str or "none",
        enable_tilt,
    )


# ============================================================================
# SimpleCover Entity
# ============================================================================


class SimpleCover(CoverEntity, RestoreEntity):
    """A cover entity with TX/RX support for entity selectors and action scripts."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        device_class: CoverDeviceClass | None,
        enable_tilt: bool,
        unique_id: str,
        # TX/RX entity selectors
        position_entity_id: str | None = None,
        tilt_position_entity_id: str | None = None,
        # Action script overrides
        set_position_script: Script | None = None,
        set_tilt_position_script: Script | None = None,
        open_cover_script: Script | None = None,
        close_cover_script: Script | None = None,
        stop_cover_script: Script | None = None,
        open_tilt_script: Script | None = None,
        close_tilt_script: Script | None = None,
        stop_tilt_script: Script | None = None,
        # Time-based position estimation
        open_time: float | None = None,
        close_time: float | None = None,
        tilt_open_time: float | None = None,
        tilt_close_time: float | None = None,
    ) -> None:
        """Initialize the cover entity."""
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_device_class = device_class
        self._enable_tilt = enable_tilt

        # TX/RX entity selectors
        self._position_entity_id = position_entity_id
        self._tilt_position_entity_id = tilt_position_entity_id

        # Action script overrides
        self._set_position_script = set_position_script
        self._set_tilt_position_script = set_tilt_position_script
        self._open_cover_script = open_cover_script
        self._close_cover_script = close_cover_script
        self._stop_cover_script = stop_cover_script
        self._open_tilt_script = open_tilt_script
        self._close_tilt_script = close_tilt_script
        self._stop_tilt_script = stop_tilt_script

        # Time-based position estimation
        self._open_time = open_time
        self._close_time = close_time
        self._tilt_open_time = tilt_open_time
        self._tilt_close_time = tilt_close_time

        # Timer state
        self._unsub_listener_cover: CALLBACK_TYPE | None = None
        self._target_position: int | None = None
        self._unsub_listener_tilt: CALLBACK_TYPE | None = None
        self._target_tilt_position: int | None = None

        # State variables
        self._attr_current_cover_position: int | None = None
        self._attr_current_cover_tilt_position: int | None = None
        self._attr_is_opening: bool | None = False
        self._attr_is_closing: bool | None = False

        # Separate tilt movement tracking to avoid overwriting cover flags
        self._tilt_is_opening: bool = False
        self._tilt_is_closing: bool = False

        # Supported features
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        )

        if position_entity_id or set_position_script:
            self._attr_supported_features |= CoverEntityFeature.SET_POSITION

        if stop_cover_script:
            self._attr_supported_features |= CoverEntityFeature.STOP

        if enable_tilt:
            self._attr_supported_features |= (
                CoverEntityFeature.OPEN_TILT | CoverEntityFeature.CLOSE_TILT
            )
            if tilt_position_entity_id or set_tilt_position_script:
                self._attr_supported_features |= (
                    CoverEntityFeature.SET_TILT_POSITION
                )
            if stop_tilt_script:
                self._attr_supported_features |= CoverEntityFeature.STOP_TILT

        # Time-based mode auto-enables SET_POSITION and STOP
        if self._time_based_mode:
            self._attr_supported_features |= (
                CoverEntityFeature.SET_POSITION | CoverEntityFeature.STOP
            )
        if self._time_based_tilt_mode and enable_tilt:
            self._attr_supported_features |= (
                CoverEntityFeature.SET_TILT_POSITION
                | CoverEntityFeature.STOP_TILT
            )

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed."""
        if self._attr_current_cover_position is not None:
            return self._attr_current_cover_position == 0
        return None

    # ------------------------------------------------------------------
    # Time-Based Position Estimation
    # ------------------------------------------------------------------

    @property
    def _time_based_mode(self) -> bool:
        """Return True if time-based position estimation is enabled."""
        return self._open_time is not None and self._close_time is not None

    @property
    def _time_based_tilt_mode(self) -> bool:
        """Return True if time-based tilt estimation is enabled."""
        return (
            self._tilt_open_time is not None
            and self._tilt_close_time is not None
        )

    @callback
    def _start_position_timer(self, target: int) -> None:
        """Start time-based position movement toward target."""
        current = self._attr_current_cover_position
        if current is None:
            current = 0  # Assume closed if unknown
            self._attr_current_cover_position = current

        if current == target:
            return  # Already at target

        # Cancel any existing timer
        self._cancel_position_timer()

        # Record target and set direction flags
        self._target_position = target
        if target > current:
            self._attr_is_opening = True
            self._attr_is_closing = False
        else:
            self._attr_is_closing = True
            self._attr_is_opening = False

        # Start 1-second interval timer
        self._unsub_listener_cover = async_track_utc_time_change(
            self.hass, self._async_position_tick
        )

    async def _async_position_tick(self, now: datetime) -> None:
        """Update position by one tick (called every ~1 second)."""
        current = self._attr_current_cover_position
        target = self._target_position

        if current is None or target is None:
            self._cancel_position_timer()
            return

        current_f = float(current)

        # Calculate step size based on direction
        if target > current:
            travel_time = self._open_time or 1.0
            step = 100.0 / travel_time
            new_pos = min(current_f + step, float(target))
        else:
            travel_time = self._close_time or 1.0
            step = 100.0 / travel_time
            new_pos = max(current_f - step, float(target))

        # Clamp and set
        new_pos_int = max(0, min(100, round(new_pos)))
        self._attr_current_cover_position = new_pos_int

        # Check if target reached
        if new_pos_int == target:
            self._cancel_position_timer()
            self._attr_is_opening = False
            self._attr_is_closing = False
            self._target_position = None

        self.async_write_ha_state()

    @callback
    def _cancel_position_timer(self) -> None:
        """Cancel the position movement timer."""
        if self._unsub_listener_cover is not None:
            self._unsub_listener_cover()
            self._unsub_listener_cover = None

    @callback
    def _start_tilt_timer(self, target: int) -> None:
        """Start time-based tilt movement toward target."""
        current = self._attr_current_cover_tilt_position
        if current is None:
            current = 0
            self._attr_current_cover_tilt_position = current

        if current == target:
            return

        self._cancel_tilt_timer()
        self._target_tilt_position = target

        # Use separate tilt movement flags to avoid overwriting cover position flags
        if target > current:
            self._tilt_is_opening = True
            self._tilt_is_closing = False
        else:
            self._tilt_is_closing = True
            self._tilt_is_opening = False

        self._unsub_listener_tilt = async_track_utc_time_change(
            self.hass, self._async_tilt_tick
        )

    async def _async_tilt_tick(self, now: datetime) -> None:
        """Update tilt position by one tick (called every ~1 second)."""
        current = self._attr_current_cover_tilt_position
        target = self._target_tilt_position

        if current is None or target is None:
            self._cancel_tilt_timer()
            return

        current_f = float(current)

        if target > current:
            travel_time = self._tilt_open_time or 1.0
            step = 100.0 / travel_time
            new_pos = min(current_f + step, float(target))
        else:
            travel_time = self._tilt_close_time or 1.0
            step = 100.0 / travel_time
            new_pos = max(current_f - step, float(target))

        new_pos_int = max(0, min(100, round(new_pos)))
        self._attr_current_cover_tilt_position = new_pos_int

        if new_pos_int == target:
            self._cancel_tilt_timer()
            self._tilt_is_opening = False
            self._tilt_is_closing = False
            self._target_tilt_position = None

        self.async_write_ha_state()

    @callback
    def _cancel_tilt_timer(self) -> None:
        """Cancel the tilt movement timer."""
        if self._unsub_listener_tilt is not None:
            self._unsub_listener_tilt()
            self._unsub_listener_tilt = None

    async def async_added_to_hass(self) -> None:
        """Register listeners and restore state."""
        await super().async_added_to_hass()

        # Restore previous state first (lowest priority)
        if (old_state := await self.async_get_last_state()) is not None:
            # Restore position
            if (
                pos := old_state.attributes.get("current_position")
            ) is not None:
                self._attr_current_cover_position = int(pos)

            # Restore tilt position
            if self._enable_tilt and (
                tilt := old_state.attributes.get("current_tilt_position")
            ) is not None:
                self._attr_current_cover_tilt_position = int(tilt)

        # RX: Listen to position entity (takes precedence over restored state)
        if self._position_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._position_entity_id],
                    self._async_position_entity_changed,
                )
            )
            # Sync initial state from live entity (overrides restored state)
            pos_state = self.hass.states.get(self._position_entity_id)
            if pos_state and pos_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                try:
                    self._attr_current_cover_position = int(
                        float(pos_state.state)
                    )
                except (ValueError, TypeError):
                    pass

        # RX: Listen to tilt position entity (takes precedence over restored state)
        if self._tilt_position_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._tilt_position_entity_id],
                    self._async_tilt_entity_changed,
                )
            )
            # Sync initial state from live entity (overrides restored state)
            tilt_state = self.hass.states.get(self._tilt_position_entity_id)
            if tilt_state and tilt_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                try:
                    self._attr_current_cover_tilt_position = int(
                        float(tilt_state.state)
                    )
                except (ValueError, TypeError):
                    pass

        # Register timer cleanup
        if self._time_based_mode:
            self.async_on_remove(self._cancel_position_timer)
        if self._time_based_tilt_mode:
            self.async_on_remove(self._cancel_tilt_timer)

    # ------------------------------------------------------------------
    # TX Helper
    # ------------------------------------------------------------------

    async def _async_set_entity_state(
        self, entity_id: str, value: float
    ) -> None:
        """TX helper: send a numeric value to an external entity."""
        domain = entity_id.split(".")[0]
        if domain in ("input_number", "number"):
            await self.hass.services.async_call(
                domain,
                "set_value",
                {ATTR_ENTITY_ID: entity_id, "value": value},
                blocking=True,
                context=self._context,
            )
        else:
            _LOGGER.warning("Unsupported entity domain for TX: %s", domain)

    # ------------------------------------------------------------------
    # RX Callbacks
    # ------------------------------------------------------------------

    @callback
    def _async_position_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle position entity state changes."""
        if self._time_based_mode:
            return  # Timer is authoritative; ignore external position updates
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            try:
                pos = int(float(new_state.state))
                if 0 <= pos <= 100:
                    self._attr_current_cover_position = pos
                    # Clear opening/closing flags when position arrives
                    self._attr_is_opening = False
                    self._attr_is_closing = False
                    self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    @callback
    def _async_tilt_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """RX: handle tilt position entity state changes."""
        if self._time_based_tilt_mode:
            return  # Timer is authoritative; ignore external tilt updates
        new_state = event.data["new_state"]
        if new_state and new_state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            try:
                tilt = int(float(new_state.state))
                if 0 <= tilt <= 100:
                    self._attr_current_cover_tilt_position = tilt
                    self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    # ------------------------------------------------------------------
    # Cover Control Methods (TX)
    # ------------------------------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        if self._time_based_mode:
            # Fire action script to command the motor
            try:
                if self._open_cover_script:
                    await self._open_cover_script.async_run(
                        context=self._context,
                    )
                elif self._set_position_script:
                    await self._set_position_script.async_run(
                        run_variables={"position": 100},
                        context=self._context,
                    )
            except Exception:
                _LOGGER.exception("Error executing open cover script")
            # Start timer to estimate position
            self._start_position_timer(100)
            self.async_write_ha_state()
            return

        self._attr_is_opening = True
        self._attr_is_closing = False

        try:
            if self._open_cover_script:
                await self._open_cover_script.async_run(
                    context=self._context,
                )
            elif self._set_position_script:
                await self._set_position_script.async_run(
                    run_variables={"position": 100},
                    context=self._context,
                )
            elif self._position_entity_id:
                await self._async_set_entity_state(
                    self._position_entity_id, 100
                )
            else:
                # No TX target: just set position directly
                self._attr_current_cover_position = 100
                self._attr_is_opening = False
        except Exception:
            _LOGGER.exception("Error executing open cover action")
            self._attr_is_opening = False

        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        if self._time_based_mode:
            try:
                if self._close_cover_script:
                    await self._close_cover_script.async_run(
                        context=self._context,
                    )
                elif self._set_position_script:
                    await self._set_position_script.async_run(
                        run_variables={"position": 0},
                        context=self._context,
                    )
            except Exception:
                _LOGGER.exception("Error executing close cover script")
            self._start_position_timer(0)
            self.async_write_ha_state()
            return

        self._attr_is_closing = True
        self._attr_is_opening = False

        try:
            if self._close_cover_script:
                await self._close_cover_script.async_run(
                    context=self._context,
                )
            elif self._set_position_script:
                await self._set_position_script.async_run(
                    run_variables={"position": 0},
                    context=self._context,
                )
            elif self._position_entity_id:
                await self._async_set_entity_state(
                    self._position_entity_id, 0
                )
            else:
                # No TX target: just set position directly
                self._attr_current_cover_position = 0
                self._attr_is_closing = False
        except Exception:
            _LOGGER.exception("Error executing close cover action")
            self._attr_is_closing = False

        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        if self._time_based_mode:
            self._cancel_position_timer()
            self._target_position = None

        self._attr_is_opening = False
        self._attr_is_closing = False

        if self._stop_cover_script:
            await self._stop_cover_script.async_run(
                context=self._context,
            )

        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            return

        if self._time_based_mode:
            if self._set_position_script:
                await self._set_position_script.async_run(
                    run_variables={"position": position},
                    context=self._context,
                )
            self._start_position_timer(position)
            self.async_write_ha_state()
            return

        old_position = self._attr_current_cover_position
        if old_position is not None:
            if position > old_position:
                self._attr_is_opening = True
                self._attr_is_closing = False
            elif position < old_position:
                self._attr_is_closing = True
                self._attr_is_opening = False

        # TX: action script > entity selector
        if self._set_position_script:
            await self._set_position_script.async_run(
                run_variables={"position": position},
                context=self._context,
            )
        elif self._position_entity_id:
            await self._async_set_entity_state(
                self._position_entity_id, position
            )
        else:
            # No TX target: set directly
            self._attr_current_cover_position = position
            self._attr_is_opening = False
            self._attr_is_closing = False

        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Tilt Control Methods (TX)
    # ------------------------------------------------------------------

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open the cover tilt."""
        if self._time_based_tilt_mode:
            if self._open_tilt_script:
                await self._open_tilt_script.async_run(
                    context=self._context,
                )
            elif self._set_tilt_position_script:
                await self._set_tilt_position_script.async_run(
                    run_variables={"tilt_position": 100},
                    context=self._context,
                )
            self._start_tilt_timer(100)
            self.async_write_ha_state()
            return

        if self._open_tilt_script:
            await self._open_tilt_script.async_run(
                context=self._context,
            )
        elif self._set_tilt_position_script:
            await self._set_tilt_position_script.async_run(
                run_variables={"tilt_position": 100},
                context=self._context,
            )
        elif self._tilt_position_entity_id:
            await self._async_set_entity_state(
                self._tilt_position_entity_id, 100
            )
        else:
            self._attr_current_cover_tilt_position = 100

        self.async_write_ha_state()

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the cover tilt."""
        if self._time_based_tilt_mode:
            if self._close_tilt_script:
                await self._close_tilt_script.async_run(
                    context=self._context,
                )
            elif self._set_tilt_position_script:
                await self._set_tilt_position_script.async_run(
                    run_variables={"tilt_position": 0},
                    context=self._context,
                )
            self._start_tilt_timer(0)
            self.async_write_ha_state()
            return

        if self._close_tilt_script:
            await self._close_tilt_script.async_run(
                context=self._context,
            )
        elif self._set_tilt_position_script:
            await self._set_tilt_position_script.async_run(
                run_variables={"tilt_position": 0},
                context=self._context,
            )
        elif self._tilt_position_entity_id:
            await self._async_set_entity_state(
                self._tilt_position_entity_id, 0
            )
        else:
            self._attr_current_cover_tilt_position = 0

        self.async_write_ha_state()

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop the cover tilt."""
        if self._time_based_tilt_mode:
            self._cancel_tilt_timer()
            self._target_tilt_position = None

        if self._stop_tilt_script:
            await self._stop_tilt_script.async_run(
                context=self._context,
            )

        self.async_write_ha_state()

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Set the cover tilt position."""
        tilt_position = kwargs.get(ATTR_TILT_POSITION)
        if tilt_position is None:
            return

        if self._time_based_tilt_mode:
            if self._set_tilt_position_script:
                await self._set_tilt_position_script.async_run(
                    run_variables={"tilt_position": tilt_position},
                    context=self._context,
                )
            self._start_tilt_timer(tilt_position)
            self.async_write_ha_state()
            return

        # TX: action script > entity selector
        if self._set_tilt_position_script:
            await self._set_tilt_position_script.async_run(
                run_variables={"tilt_position": tilt_position},
                context=self._context,
            )
        elif self._tilt_position_entity_id:
            await self._async_set_entity_state(
                self._tilt_position_entity_id, tilt_position
            )
        else:
            self._attr_current_cover_tilt_position = tilt_position

        self.async_write_ha_state()
