"""Data models for Somfy API responses."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MovementState(str, Enum):
    """Motor movement states from API."""

    STOPPED = "stopped"
    RUNNING = "running"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"

    @classmethod
    def from_api(cls, status: str | None, direction: str | None = None) -> MovementState:
        """Parse API state value.

        Args:
            status: Status from API ("stopped", "running", "blocked")
            direction: Direction from API ("up / open", "down / close")

        Returns:
            MovementState enum value
        """
        if status is None:
            return cls.UNKNOWN

        status_lower = status.lower()
        if "stopped" in status_lower:
            return cls.STOPPED
        elif "running" in status_lower:
            return cls.RUNNING
        elif "blocked" in status_lower:
            return cls.BLOCKED
        else:
            return cls.UNKNOWN

    @property
    def is_opening(self) -> bool:
        """Check if state represents opening movement."""
        return self == self.RUNNING  # Direction determined separately

    @property
    def is_closing(self) -> bool:
        """Check if state represents closing movement."""
        return self == self.RUNNING  # Direction determined separately


class Direction(str, Enum):
    """Movement direction."""

    UP_OPEN = "up"
    DOWN_CLOSE = "down"
    UNKNOWN = "unknown"

    @classmethod
    def from_api(cls, direction: str | None) -> Direction:
        """Parse API direction value."""
        if direction is None:
            return cls.UNKNOWN

        direction_lower = direction.lower()
        if "up" in direction_lower or "open" in direction_lower:
            return cls.UP_OPEN
        elif "down" in direction_lower or "close" in direction_lower:
            return cls.DOWN_CLOSE
        else:
            return cls.UNKNOWN


@dataclass(frozen=True)
class PositionStatus:
    """Current position and movement status.

    Attributes:
        position: Current position (0-100), None if unknown
        status: Current movement status
        direction: Current movement direction
        source: Source of last command
        cause: Cause of current state
    """

    position: float | None
    status: MovementState
    direction: Direction
    source: str | None = None
    cause: str | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> PositionStatus:
        """Create from API response.

        Args:
            data: Parsed JSON response data

        Returns:
            PositionStatus instance
        """
        # Extract position data
        position_data = data.get("position", {})
        if isinstance(position_data, dict):
            position_value = position_data.get("value")
            status_value = position_data.get("status")
            direction_value = position_data.get("direction")
            source_value = position_data.get("source")
            cause_value = position_data.get("cause")
        else:
            # Fallback if position is just a number
            position_value = position_data if isinstance(position_data, (int, float)) else None
            status_value = None
            direction_value = None
            source_value = None
            cause_value = None

        # Parse position
        position = float(position_value) if position_value is not None else None

        # Parse state and direction
        status = MovementState.from_api(status_value)
        direction = Direction.from_api(direction_value)

        return cls(
            position=position,
            status=status,
            direction=direction,
            source=source_value,
            cause=cause_value,
        )

    @property
    def is_moving(self) -> bool:
        """Check if motor is currently moving."""
        return self.status == MovementState.RUNNING

    @property
    def is_stopped(self) -> bool:
        """Check if motor is stopped."""
        return self.status == MovementState.STOPPED

    @property
    def is_opening(self) -> bool:
        """Check if motor is opening."""
        return self.is_moving and self.direction == Direction.UP_OPEN

    @property
    def is_closing(self) -> bool:
        """Check if motor is closing."""
        return self.is_moving and self.direction == Direction.DOWN_CLOSE


@dataclass(frozen=True)
class DeviceInfo:
    """Device information from status.info.

    Attributes:
        name: Device name
        model: Device model name
        hostname: Device hostname
        synergy_version: Synergy protocol version
        target_id: Target ID
        firmware: Firmware version string
        hardware: Hardware version string
        mac_address: Device MAC address
    """

    name: str
    model: str
    hostname: str
    synergy_version: str
    target_id: str
    firmware: str
    hardware: str
    mac_address: str

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> DeviceInfo:
        """Create from API response.

        Args:
            data: Parsed JSON response data

        Returns:
            DeviceInfo instance
        """
        info = data.get("info", {})

        return cls(
            name=info.get("name", "Unknown"),
            model=info.get("model", "Unknown"),
            hostname=info.get("hostname", ""),
            synergy_version=str(info.get("synergy_version", "")),
            target_id=data.get("targetID", ""),
            firmware=info.get("firmware", "Unknown"),
            hardware=info.get("hardware", "Unknown"),
            mac_address=info.get("mac", ""),
        )
