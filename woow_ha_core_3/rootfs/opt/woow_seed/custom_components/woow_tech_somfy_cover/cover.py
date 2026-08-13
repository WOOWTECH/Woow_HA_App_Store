"""Somfy PoE cover platform."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
    ATTR_POSITION,
    PLATFORM_SCHEMA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, STATE_CLOSED, STATE_CLOSING, STATE_OPEN, STATE_OPENING
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.client import SomfyClient
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_TARGET_ID,
    CONF_KEY,
    DEFAULT_NAME,
)
from .coordinator import SomfyDataUpdateCoordinator
from .api.models import MovementState, Direction

_LOGGER = logging.getLogger(__name__)

# YAML platform schema for validation
# Note: Using vol.Coerce(str) allows users to specify target_id and key
# with or without quotes in YAML (e.g., both 160326 and "160326" work)
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_TARGET_ID): vol.Coerce(str),
        vol.Required(CONF_KEY): vol.Coerce(str),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Somfy cover from YAML configuration.

    This function creates a cover entity from YAML configuration in configuration.yaml.
    It creates its own coordinator and client, independent of Config Flow entries.

    Args:
        hass: Home Assistant instance
        config: Platform configuration from YAML
        async_add_entities: Callback to add entities
        discovery_info: Discovery information (not used)

    Example YAML configuration:
        cover:
          - platform: woow_tech_somfy_cover
            name: Living Room Shade
            host: 192.168.1.77
            target_id: "160326"
            key: "FBE90399BA25B4B67DC1B23BE0D9C084"

    Note:
        Each YAML-configured cover gets its own coordinator and client instance.
        This allows YAML and Config Flow covers to coexist without conflicts.
    """
    name = config[CONF_NAME]
    host = config[CONF_HOST]
    target_id = config[CONF_TARGET_ID]
    key = config[CONF_KEY]

    _LOGGER.info(
        "Setting up YAML-configured Somfy cover: name=%s, host=%s, target_id=%s",
        name,
        host,
        target_id,
    )

    # Create API client for this YAML cover
    client = SomfyClient(
        host=host,
        target_id=target_id,
        key=key,
    )

    # Connect to device
    try:
        await client.connect()
        _LOGGER.info(
            "Successfully connected to YAML-configured Somfy motor at %s (ID: %s)",
            host,
            target_id,
        )
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error(
            "Failed to connect to YAML-configured Somfy motor at %s: %s",
            host,
            err,
        )
        # Don't raise - allow HA to continue startup
        # The entity will be unavailable until connection succeeds
        return

    # Create coordinator for this YAML cover
    # Note: We use a unique identifier to avoid conflicts with Config Flow entries
    coordinator = SomfyDataUpdateCoordinator(
        hass=hass,
        client=client,
        entry_data={
            CONF_NAME: name,
            CONF_HOST: host,
            CONF_TARGET_ID: target_id,
            CONF_KEY: key,
        },
    )

    # Fetch initial data
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning(
            "Failed to fetch initial data for YAML-configured cover %s: %s",
            name,
            err,
        )
        # Continue anyway - coordinator will retry

    # Fetch device info for better entity identification
    try:
        await coordinator.async_get_device_info()
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning(
            "Failed to fetch device info for YAML-configured cover %s: %s",
            name,
            err,
        )

    # Create and add the cover entity
    # We use a special unique_id format to distinguish YAML covers from Config Flow
    cover = SomfyYAMLCover(coordinator, config)
    async_add_entities([cover])

    _LOGGER.debug(
        "YAML-configured Somfy cover setup completed: name=%s, host=%s",
        name,
        host,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Somfy cover from config entry."""
    coordinator: SomfyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([SomfyCover(coordinator, entry)])


class SomfyCover(CoordinatorEntity[SomfyDataUpdateCoordinator], CoverEntity):
    """Somfy PoE motor cover entity.

    Design Decisions:
    - Uses coordinator pattern for state updates
    - Supports position, open/close, and stop
    - Maps API states to HA states
    - Handles null positions gracefully
    - Position 0 = fully closed, 100 = fully open
    """

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_has_entity_name = True
    _attr_name = None  # Use device name

    def __init__(
        self,
        coordinator: SomfyDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize cover entity."""
        super().__init__(coordinator)

        self._attr_unique_id = f"{entry.entry_id}_cover"
        self._attr_device_info = coordinator.device_info

        # Determine supported features
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

        _LOGGER.debug(
            "Initialized cover entity: unique_id=%s, features=%s",
            self._attr_unique_id,
            self._attr_supported_features
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (0 closed - 100 open).

        Note: Somfy API uses 0=open/up, 100=closed/down
        We need to invert this for HA (0=closed, 100=open)
        """
        if self.coordinator.data is None:
            _LOGGER.debug("Position unknown: coordinator data is None")
            return None

        position = self.coordinator.data.position
        if position is None:
            _LOGGER.debug("Position unknown: API returned None")
            return None

        # Invert position: Somfy 0=open/up, 100=closed/down
        # HA expects: 0=closed, 100=open
        inverted = 100 - position
        rounded = round(inverted)

        _LOGGER.debug(
            "Position conversion: somfy=%s, inverted=%s, rounded=%s",
            position,
            inverted,
            rounded
        )

        # Convert to integer for HA (0-100)
        return rounded

    @property
    def is_closed(self) -> bool | None:
        """Return if cover is closed.

        Returns None if position is unknown.
        """
        position = self.current_cover_position
        if position is None:
            return None

        return position == 0

    @property
    def is_opening(self) -> bool:
        """Return if cover is opening."""
        if self.coordinator.data is None:
            return False

        return self.coordinator.data.is_opening

    @property
    def is_closing(self) -> bool:
        """Return if cover is closing."""
        if self.coordinator.data is None:
            return False

        return self.coordinator.data.is_closing

    @property
    def state(self) -> str:
        """Return the state of the cover."""
        if self.coordinator.data is None:
            _LOGGER.debug("State defaulting to OPEN (no coordinator data)")
            return STATE_OPEN

        # Check movement state
        if self.coordinator.data.is_opening:
            _LOGGER.debug("State: OPENING (moving up)")
            return STATE_OPENING
        elif self.coordinator.data.is_closing:
            _LOGGER.debug("State: CLOSING (moving down)")
            return STATE_CLOSING

        # If stopped, determine open/closed from position
        position = self.current_cover_position
        if position is not None and position == 0:
            _LOGGER.debug("State: CLOSED (position=0)")
            return STATE_CLOSED

        _LOGGER.debug("State: OPEN (default)")
        return STATE_OPEN

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug("Opening cover")
        await self.coordinator.async_move_up()

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug("Closing cover")
        await self.coordinator.async_move_down()

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug("Stopping cover")
        await self.coordinator.async_stop()

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move cover to a specific position."""
        position = kwargs[ATTR_POSITION]

        # Invert position for Somfy API
        # HA: 0=closed, 100=open
        # Somfy: 0=open/up, 100=closed/down
        somfy_position = 100 - position

        _LOGGER.debug(
            "Setting cover position: ha_position=%s, somfy_position=%s, current=%s",
            position,
            somfy_position,
            self.current_cover_position
        )
        await self.coordinator.async_move_to_position(float(somfy_position))

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        _LOGGER.debug(
            "Coordinator update received: position=%s, state=%s, available=%s",
            self.current_cover_position,
            self.state,
            self.available
        )
        self.async_write_ha_state()


class SomfyYAMLCover(CoordinatorEntity[SomfyDataUpdateCoordinator], CoverEntity):
    """Somfy PoE motor cover entity configured via YAML.

    This class is similar to SomfyCover but designed for YAML configuration.
    It doesn't require a config entry and generates unique_id from YAML config.

    Design Decisions:
    - Standalone class (not inheriting from SomfyCover to avoid entry dependency)
    - Uses target_id-based unique_id for YAML covers
    - Provides device info directly from coordinator
    - Allows multiple YAML covers with same target_id but different names
    """

    _attr_device_class = CoverDeviceClass.SHADE

    def __init__(
        self,
        coordinator: SomfyDataUpdateCoordinator,
        config: ConfigType,
    ) -> None:
        """Initialize YAML-configured cover entity."""
        super().__init__(coordinator)

        # Generate unique_id for YAML cover
        # Format: yaml_<target_id>_<sanitized_name>
        # This allows multiple YAML covers with same target_id but different names
        name = config[CONF_NAME]
        target_id = config[CONF_TARGET_ID]
        sanitized_name = name.lower().replace(" ", "_")
        self._attr_unique_id = f"yaml_{target_id}_{sanitized_name}"

        # Set the entity name (will be used as the entity_id base)
        self._attr_name = name
        self._attr_has_entity_name = False  # Use the name directly

        # Set device info
        self._attr_device_info = coordinator.device_info

        # Determine supported features
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

        _LOGGER.debug(
            "Initialized YAML cover entity: unique_id=%s, name=%s, target_id=%s, features=%s",
            self._attr_unique_id,
            name,
            target_id,
            self._attr_supported_features,
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (0 closed - 100 open).

        Note: Somfy API uses 0=open/up, 100=closed/down
        We need to invert this for HA (0=closed, 100=open)
        """
        if self.coordinator.data is None:
            _LOGGER.debug("Position unknown: coordinator data is None")
            return None

        position = self.coordinator.data.position
        if position is None:
            _LOGGER.debug("Position unknown: API returned None")
            return None

        # Invert position: Somfy 0=open/up, 100=closed/down
        # HA expects: 0=closed, 100=open
        inverted = 100 - position
        rounded = round(inverted)

        _LOGGER.debug(
            "Position conversion: somfy=%s, inverted=%s, rounded=%s",
            position,
            inverted,
            rounded
        )

        # Convert to integer for HA (0-100)
        return rounded

    @property
    def is_closed(self) -> bool | None:
        """Return if cover is closed.

        Returns None if position is unknown.
        """
        position = self.current_cover_position
        if position is None:
            return None

        return position == 0

    @property
    def is_opening(self) -> bool:
        """Return if cover is opening."""
        if self.coordinator.data is None:
            return False

        return self.coordinator.data.is_opening

    @property
    def is_closing(self) -> bool:
        """Return if cover is closing."""
        if self.coordinator.data is None:
            return False

        return self.coordinator.data.is_closing

    @property
    def state(self) -> str:
        """Return the state of the cover."""
        if self.coordinator.data is None:
            _LOGGER.debug("State defaulting to OPEN (no coordinator data)")
            return STATE_OPEN

        # Check movement state
        if self.coordinator.data.is_opening:
            _LOGGER.debug("State: OPENING (moving up)")
            return STATE_OPENING
        elif self.coordinator.data.is_closing:
            _LOGGER.debug("State: CLOSING (moving down)")
            return STATE_CLOSING

        # If stopped, determine open/closed from position
        position = self.current_cover_position
        if position is not None and position == 0:
            _LOGGER.debug("State: CLOSED (position=0)")
            return STATE_CLOSED

        _LOGGER.debug("State: OPEN (default)")
        return STATE_OPEN

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.debug("Opening cover")
        await self.coordinator.async_move_up()

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.debug("Closing cover")
        await self.coordinator.async_move_down()

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.debug("Stopping cover")
        await self.coordinator.async_stop()

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move cover to a specific position."""
        position = kwargs[ATTR_POSITION]

        # Invert position for Somfy API
        # HA: 0=closed, 100=open
        # Somfy: 0=open/up, 100=closed/down
        somfy_position = 100 - position

        _LOGGER.debug(
            "Setting cover position: ha_position=%s, somfy_position=%s, current=%s",
            position,
            somfy_position,
            self.current_cover_position
        )
        await self.coordinator.async_move_to_position(float(somfy_position))

        # Request immediate refresh
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        _LOGGER.debug(
            "Coordinator update received: position=%s, state=%s, available=%s",
            self.current_cover_position,
            self.state,
            self.available
        )
        self.async_write_ha_state()
