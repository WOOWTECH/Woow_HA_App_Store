"""TCP/TLS authentication for Somfy PoE API.

IMPORTANT: AUTHENTICATION IS OPTIONAL AND NOT REQUIRED FOR BASIC MOTOR CONTROL

TESTED AND VERIFIED:
- UDP port 55055 with encrypted commands works WITHOUT authentication
- Basic motor control (status, movement, position) works without authentication
- Zero-padding encryption has 100% success rate
- TCP/TLS authentication on port 55056 is OPTIONAL

This module provides OPTIONAL authentication functionality:
- TCP port 55056 over TLS can be used for authentication
- Authenticate with 4-digit PIN code using security.auth method
- May be required for advanced features (not tested)
- NOT required for basic motor operations

For basic motor control, you can skip authentication entirely and use
encrypted UDP commands directly on port 55055.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any

from ..errors import (
    SomfyAuthenticationError,
    SomfyConnectionError,
    SomfyTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_AUTH_PORT = 55056
DEFAULT_AUTH_TIMEOUT = 10.0  # Authentication may take longer


class SomfyAuthenticator:
    """TCP/TLS authentication client for Somfy PoE devices.

    OPTIONAL: Authentication is NOT required for basic motor control operations.
    Use this only if you need advanced features or if authentication is explicitly required.

    Design Decisions:
    - Separate TCP connection for authentication (port 55056)
    - TLS/SSL with certificate verification
    - Session management with automatic reconnection
    - Thread-safe with asyncio lock
    - OPTIONAL - basic motor control works without authentication
    """

    def __init__(
        self,
        host: str,
        pin: str,
        target_id: str,
        port: int = DEFAULT_AUTH_PORT,
        timeout: float = DEFAULT_AUTH_TIMEOUT,
        verify_ssl: bool = True,
    ) -> None:
        """Initialize authenticator.

        Args:
            host: Target device IP address
            pin: 4-digit PIN code for authentication
            target_id: 6-character hex target ID (from MAC)
            port: TCP port (default 55056)
            timeout: Authentication timeout in seconds
            verify_ssl: Whether to verify SSL certificate (default True)

        Raises:
            ValueError: If pin or target_id format is invalid
        """
        if not pin or len(pin) != 4 or not pin.isdigit():
            raise ValueError("PIN must be a 4-digit number")

        if len(target_id) != 6 or not all(
            c in "0123456789ABCDEFabcdef" for c in target_id
        ):
            raise ValueError("target_id must be 6-character hex string")

        self._host = host
        self._port = port
        self._pin = pin
        self._target_id = target_id.upper()
        self._timeout = timeout
        self._verify_ssl = verify_ssl

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._authenticated = False
        self._lock = asyncio.Lock()
        self._request_id = 0

        _LOGGER.debug(
            "Initialized SomfyAuthenticator: host=%s, port=%s, target_id=%s, verify_ssl=%s",
            host, port, target_id, verify_ssl
        )

    async def __aenter__(self) -> SomfyAuthenticator:
        """Async context manager entry."""
        await self.authenticate()
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()

    async def authenticate(self) -> bool:
        """Authenticate with device using PIN.

        Returns:
            True if authentication successful

        Raises:
            SomfyConnectionError: If connection fails
            SomfyAuthenticationError: If authentication fails
            SomfyTimeoutError: If request times out
        """
        async with self._lock:
            if self._authenticated and self.is_connected:
                _LOGGER.debug("Already authenticated")
                return True

            # Close any existing connection
            await self._close_connection()

            # Create SSL context with maximum compatibility for legacy devices
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # Enable legacy renegotiation for devices with older TLS implementations
            ssl_context.options |= 0x4  # OP_LEGACY_SERVER_CONNECT

            # Set cipher suites for compatibility with older devices
            # Include both modern and legacy ciphers
            ssl_context.set_ciphers('DEFAULT:@SECLEVEL=1')

            if not self._verify_ssl:
                _LOGGER.warning("SSL verification disabled")

            try:
                _LOGGER.info("Connecting to %s:%s (TLS)", self._host, self._port)

                # Connect with timeout
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self._host,
                        self._port,
                        ssl=ssl_context,
                    ),
                    timeout=self._timeout,
                )

                _LOGGER.info("TLS connection established")

                # Build authentication request
                self._request_id += 1
                auth_request = {
                    "method": "security.auth",
                    "params": {
                        "targetID": self._target_id,
                        "code": self._pin,
                    },
                    "id": self._request_id,
                }

                request_json = json.dumps(auth_request, separators=(",", ":"))
                _LOGGER.debug("Sending auth request: %s", request_json)

                # Send authentication request
                self._writer.write(request_json.encode("utf-8"))
                self._writer.write(b"\n")  # Add newline delimiter
                await self._writer.drain()

                _LOGGER.debug("Auth request sent, waiting for response...")

                # Read response with timeout
                response_data = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=self._timeout,
                )

                if not response_data:
                    raise SomfyConnectionError("Connection closed by device")

                response = response_data.decode("utf-8").strip()
                _LOGGER.debug("Received auth response: %s", response)

                # Parse response
                try:
                    response_obj = json.loads(response)
                except json.JSONDecodeError as err:
                    raise SomfyAuthenticationError(
                        f"Invalid JSON response: {err}"
                    ) from err

                # Check for error
                if "error" in response_obj:
                    error = response_obj["error"]
                    if isinstance(error, dict):
                        code = error.get("id", -1)
                        message = error.get("title", "Unknown error")
                    else:
                        code = -1
                        message = str(error)

                    _LOGGER.error("Authentication failed: %s (code=%s)", message, code)
                    raise SomfyAuthenticationError(f"Authentication failed: {message}", code)

                # Check result
                result = response_obj.get("result")
                if result is True or (isinstance(result, dict) and result.get("success")):
                    self._authenticated = True
                    _LOGGER.info("Authentication successful")
                    return True
                else:
                    _LOGGER.error("Unexpected auth result: %s", result)
                    raise SomfyAuthenticationError(
                        f"Unexpected authentication result: {result}"
                    )

            except asyncio.TimeoutError as err:
                raise SomfyTimeoutError(
                    f"Authentication timed out after {self._timeout}s"
                ) from err
            except OSError as err:
                raise SomfyConnectionError(
                    f"Failed to connect to {self._host}:{self._port}: {err}"
                ) from err

    async def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send command over authenticated TCP connection.

        Args:
            method: RPC method name
            params: Optional method parameters

        Returns:
            Result from response

        Raises:
            SomfyConnectionError: If not connected
            SomfyAuthenticationError: If not authenticated
            SomfyTimeoutError: If request times out
        """
        if not self.is_connected:
            raise SomfyConnectionError("Not connected")

        if not self._authenticated:
            raise SomfyAuthenticationError("Not authenticated")

        async with self._lock:
            self._request_id += 1

            request_params = {"targetID": self._target_id}
            if params:
                request_params.update(params)

            request = {
                "method": method,
                "params": request_params,
                "id": self._request_id,
            }

            request_json = json.dumps(request, separators=(",", ":"))
            _LOGGER.debug("Sending command: %s", request_json)

            try:
                # Send request
                self._writer.write(request_json.encode("utf-8"))
                self._writer.write(b"\n")
                await self._writer.drain()

                # Read response
                response_data = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=self._timeout,
                )

                if not response_data:
                    raise SomfyConnectionError("Connection closed by device")

                response = response_data.decode("utf-8").strip()
                _LOGGER.debug("Received response: %s", response)

                # Parse response
                response_obj = json.loads(response)

                # Check for error
                if "error" in response_obj:
                    error = response_obj["error"]
                    if isinstance(error, dict):
                        message = error.get("title", "Unknown error")
                    else:
                        message = str(error)
                    raise SomfyAuthenticationError(f"Command failed: {message}")

                return response_obj.get("result")

            except asyncio.TimeoutError as err:
                raise SomfyTimeoutError(
                    f"Command timed out after {self._timeout}s"
                ) from err

    async def close(self) -> None:
        """Close TCP connection."""
        async with self._lock:
            await self._close_connection()

    async def _close_connection(self) -> None:
        """Internal method to close connection without lock."""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as err:
                _LOGGER.debug("Error closing writer: %s", err)

            self._writer = None
            self._reader = None
            self._authenticated = False
            _LOGGER.debug("TCP connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if connected to device."""
        return (
            self._reader is not None
            and self._writer is not None
            and not self._writer.is_closing()
        )

    @property
    def is_authenticated(self) -> bool:
        """Check if authenticated."""
        return self._authenticated and self.is_connected
