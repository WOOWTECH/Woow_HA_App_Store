"""High-level API client for Somfy PoE motors.

This client provides a simple interface for controlling Somfy motors via UDP.
Authentication is NOT required - the motor accepts encrypted UDP commands directly.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .encryption import SomfyEncryption
from .transport import SomfyTransport
from .protocol import SomfyProtocol
from .models import DeviceInfo, PositionStatus
from ..errors import SomfyError
from ..const import (
    METHOD_STATUS_INFO,
    METHOD_STATUS_POSITION,
    METHOD_MOVE_UP,
    METHOD_MOVE_DOWN,
    METHOD_MOVE_STOP,
    METHOD_MOVE_TO,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


class SomfyClient:
    """High-level async API client for Somfy PoE motors.

    Design Decisions:
    - Encapsulates all protocol/transport complexity
    - Context manager for resource management
    - Type-safe return values via models
    - UDP encryption with zero-padding (100% success rate)
    - No authentication required (motor accepts encrypted UDP directly)
    - Simple and reliable based on working test pattern
    """

    def __init__(
        self,
        host: str,
        target_id: str,
        key: str,
        port: int = 55055,
        timeout: float = 5.0,
    ) -> None:
        """Initialize API client.

        Args:
            host: Device IP address
            target_id: 6-character hex target ID (e.g., "160326")
            key: 32-character hex encryption key
            port: UDP port (default 55055 - REQUIRED for motor communication)
            timeout: Request timeout in seconds

        Raises:
            ValueError: If parameters are invalid

        Note:
            Motor control works via encrypted UDP on port 55055.
            No authentication is required - this is proven by the working test.
        """
        self._encryption = SomfyEncryption(key)
        self._protocol = SomfyProtocol(target_id)
        self._transport = SomfyTransport(
            host=host,
            encryption=self._encryption,
            port=port,
            default_timeout=timeout,
            target_id=target_id,  # Pass target_id for wake-up commands
        )
        self._host = host
        self._target_id = target_id

        _LOGGER.debug(
            "Initialized SomfyClient: host=%s, target_id=%s, port=%s, timeout=%s",
            host,
            target_id,
            port,
            timeout,
        )

    async def __aenter__(self) -> SomfyClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Connect to device.

        This verifies that we can bind to port 55055, which is required
        for the motor to accept commands. Also sends an initial wake-up
        command to ensure the motor is responsive for the first command.

        Raises:
            SomfyError: If connection fails
        """
        _LOGGER.debug("Connecting to device at %s", self._host)
        await self._transport.connect()
        _LOGGER.info("Connected to motor at %s (ready for encrypted UDP commands)", self._host)

    async def close(self) -> None:
        """Close connection."""
        _LOGGER.debug("Closing connection to %s", self._host)
        await self._transport.close()

    async def get_device_info(self) -> DeviceInfo:
        """Get device information.

        Returns:
            DeviceInfo model with device details

        Raises:
            SomfyError: If request fails
        """
        _LOGGER.debug("Requesting device info")
        request = self._protocol.build_request(METHOD_STATUS_INFO)
        response = await self._transport.send_encrypted(request)
        result = self._protocol.parse_response(response)

        _LOGGER.debug("Received device info response: %s", result)

        return DeviceInfo.from_api_response(result)

    async def get_position(self) -> PositionStatus:
        """Get current position and state.

        Returns:
            PositionStatus model with current state

        Raises:
            SomfyError: If request fails
        """
        _LOGGER.debug("Requesting position status from device")
        request = self._protocol.build_request(METHOD_STATUS_POSITION)
        response = await self._transport.send_encrypted(request)
        result = self._protocol.parse_response(response)

        _LOGGER.debug("Received position response: %s", result)

        return PositionStatus.from_api_response(result)

    async def move_up(self) -> None:
        """Start moving up (opening).

        Raises:
            SomfyError: If command fails
        """
        _LOGGER.info("Sending move UP command to motor %s", self._target_id)
        request = self._protocol.build_request(METHOD_MOVE_UP)
        response = await self._transport.send_encrypted(request)
        self._protocol.parse_response(response)
        _LOGGER.debug("Move up command sent successfully")

    async def move_down(self) -> None:
        """Start moving down (closing).

        Raises:
            SomfyError: If command fails
        """
        _LOGGER.info("Sending move DOWN command to motor %s", self._target_id)
        request = self._protocol.build_request(METHOD_MOVE_DOWN)
        response = await self._transport.send_encrypted(request)
        self._protocol.parse_response(response)
        _LOGGER.debug("Move down command sent successfully")

    async def stop(self) -> None:
        """Stop movement.

        Raises:
            SomfyError: If command fails
        """
        _LOGGER.info("Sending STOP command to motor %s", self._target_id)
        request = self._protocol.build_request(METHOD_MOVE_STOP)
        response = await self._transport.send_encrypted(request)
        self._protocol.parse_response(response)
        _LOGGER.debug("Stop command sent successfully")

    async def move_to_position(self, position: float) -> None:
        """Move to specific position.

        Args:
            position: Target position (0-100, up to 3 decimal places)
                     0 = fully open/up
                     100 = fully closed/down

        Raises:
            ValueError: If position is out of range
            SomfyError: If command fails
        """
        if not 0 <= position <= 100:
            raise ValueError(f"Position must be 0-100, got {position}")

        # Round to 3 decimal places as per API spec
        rounded_position = round(position, 3)

        _LOGGER.info(
            "Sending move to position command: position=%.3f, motor=%s",
            rounded_position,
            self._target_id,
        )
        params = {"position": rounded_position}
        request = self._protocol.build_request(METHOD_MOVE_TO, params)
        response = await self._transport.send_encrypted(request)
        self._protocol.parse_response(response)
        _LOGGER.debug("Move to position command sent successfully")

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._transport.is_connected

    @property
    def host(self) -> str:
        """Get device host."""
        return self._host

    @property
    def target_id(self) -> str:
        """Get target ID."""
        return self._target_id
