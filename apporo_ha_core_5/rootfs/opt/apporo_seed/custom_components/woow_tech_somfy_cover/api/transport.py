"""UDP transport with encryption for Somfy PoE API.

This module uses synchronous sockets wrapped in async executors to ensure
compatibility with the Somfy motor's requirements:
- Must bind to port 55055
- Must use SO_REUSEADDR
- Simple send/receive pattern works best

Design based on working test_decrypt_responses.py pattern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import TYPE_CHECKING

from ..errors import SomfyConnectionError, SomfyTimeoutError

if TYPE_CHECKING:
    from .encryption import SomfyEncryption

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0  # seconds


class SomfyTransport:
    """UDP transport with AES encryption using synchronous sockets.

    Design Decisions:
    - Uses synchronous socket operations (proven to work with Somfy motor)
    - Wraps blocking operations in asyncio executor for async compatibility
    - Binds to port 55055 with SO_REUSEADDR (required by motor)
    - Creates new socket for each request (like working test)
    - Automatic encryption/decryption
    - Thread-safe with asyncio lock
    - Motor wake-up mechanism to handle hibernation
    """

    def __init__(
        self,
        host: str,
        encryption: SomfyEncryption | None,
        port: int = 55055,
        default_timeout: float = DEFAULT_TIMEOUT,
        target_id: str | None = None,
    ) -> None:
        """Initialize transport.

        Args:
            host: Target device IP address
            encryption: SomfyEncryption instance (None for unencrypted)
            port: UDP port (default 55055)
            default_timeout: Default request timeout in seconds
            target_id: Target ID for wake-up commands (optional)
        """
        self._host = host
        self._port = port
        self._encryption = encryption
        self._default_timeout = default_timeout
        self._target_id = target_id or ""
        self._lock = asyncio.Lock()
        self._closed = False
        self._needs_wakeup = True  # Motor needs wake-up on first command
        self._last_timeout = False  # Track if last request timed out

        _LOGGER.debug(
            "Initialized SomfyTransport: host=%s, port=%s, timeout=%s, target_id=%s",
            host,
            port,
            default_timeout,
            target_id,
        )

    async def __aenter__(self) -> SomfyTransport:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Verify connection capability.

        Note: This doesn't create a persistent socket. Each request creates
        its own socket (like the working test pattern).

        Raises:
            SomfyConnectionError: If connection test fails
        """
        if self._closed:
            raise SomfyConnectionError("Transport is closed")

        # Test that we can create and bind a socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self._port))
            sock.close()
            _LOGGER.info("Transport ready: can bind to port %s", self._port)
        except OSError as err:
            raise SomfyConnectionError(
                f"Cannot bind to port {self._port} (required for motor): {err}"
            ) from err

    async def close(self) -> None:
        """Close transport.

        Note: Since we don't keep persistent sockets, this just marks
        the transport as closed to prevent new requests.
        """
        self._closed = True
        _LOGGER.debug("Transport closed")

    async def send_encrypted(
        self,
        plaintext: str,
        timeout: float | None = None,
        retry_on_timeout: bool = True,
        skip_wakeup: bool = False,
    ) -> str:
        """Send encrypted message and receive encrypted response.

        This method follows the working pattern from test_decrypt_responses.py:
        1. Wake up motor if needed (after connection or timeout)
        2. Create fresh socket with SO_REUSEADDR
        3. Bind to port 55055
        4. Encrypt and send data
        5. Receive response
        6. Close socket
        7. Decrypt response

        Motor Wake-up Strategy:
        The motor enters hibernation/sleep mode after inactivity. When sleeping:
        - First command gets NO response (motor wakes but doesn't reply)
        - Subsequent commands work perfectly

        To solve this, we send a wake-up command (move.stop) before the actual
        command when the motor might be sleeping (after connection or timeout).
        The wake-up command uses a short timeout and ignores no-response errors.

        If the first request times out, it will automatically retry once after
        a brief delay. This handles cases where the motor is in a busy state.

        Args:
            plaintext: Unencrypted JSON-RPC message
            timeout: Request timeout (uses default if None)
            retry_on_timeout: Retry once if timeout occurs (default: True)
            skip_wakeup: Skip wake-up logic (internal use only)

        Returns:
            Decrypted response string

        Raises:
            SomfyConnectionError: If send/receive fails
            SomfyTimeoutError: If request times out after retry
        """
        if self._closed:
            raise SomfyConnectionError("Transport is closed")

        if self._encryption is None:
            raise SomfyConnectionError("Encryption not configured")

        timeout = timeout if timeout is not None else self._default_timeout
        _LOGGER.debug("Sending encrypted request with timeout: %s seconds", timeout)

        async with self._lock:  # Serialize requests
            # Wake up motor if needed (before actual command)
            _LOGGER.debug(
                "Wake-up check: skip_wakeup=%s, needs_wakeup=%s, last_timeout=%s",
                skip_wakeup,
                self._needs_wakeup,
                self._last_timeout,
            )
            if not skip_wakeup and (self._needs_wakeup or self._last_timeout):
                await self._send_wakeup_command()
                self._needs_wakeup = False  # Don't wake up again until needed

            last_error = None

            for attempt in range(2 if retry_on_timeout else 1):
                try:
                    if attempt > 0:
                        # Motor may have been busy, wait briefly before retry
                        _LOGGER.debug(
                            "Retrying request after timeout (attempt %d/2)", attempt + 1
                        )
                        await asyncio.sleep(0.3)

                    # Log plaintext before encryption
                    _LOGGER.debug("Outgoing plaintext payload: %s", plaintext)

                    # Encrypt outgoing message
                    encrypted_data = self._encryption.encrypt(plaintext)

                    _LOGGER.debug(
                        "Encrypted payload: %s (IV: %s, ciphertext: %d bytes)",
                        encrypted_data[:32].hex() + "...",
                        encrypted_data[:16].hex(),
                        len(encrypted_data) - 16,
                    )

                    # Send and receive using synchronous socket (proven pattern)
                    encrypted_response = await asyncio.to_thread(
                        self._send_receive_sync,
                        encrypted_data,
                        timeout,
                    )

                    _LOGGER.debug(
                        "Received encrypted response: %s... (%d bytes)",
                        encrypted_response[:32].hex(),
                        len(encrypted_response),
                    )

                    # Decrypt response
                    response = self._encryption.decrypt(encrypted_response)
                    _LOGGER.debug("Decrypted response: %s", response)

                    # Success - reset timeout flag
                    self._last_timeout = False

                    if attempt > 0:
                        _LOGGER.info("Request succeeded on retry")

                    return response

                except socket.timeout as err:
                    last_error = err
                    self._last_timeout = True  # Mark that we had a timeout
                    if not retry_on_timeout or attempt >= 1:
                        # No retry, or already retried
                        raise SomfyTimeoutError(
                            f"Request timed out after {timeout}s"
                        ) from err
                    # Will retry
                    _LOGGER.warning(
                        "Request timed out, will retry (motor may be busy)"
                    )
                    continue

                except OSError as err:
                    raise SomfyConnectionError(f"Send/receive failed: {err}") from err

            # Should not reach here, but just in case
            if last_error:
                raise SomfyTimeoutError(
                    f"Request timed out after {timeout}s and retry"
                ) from last_error

    async def _send_wakeup_command(self) -> None:
        """Send wake-up command to motor that might be sleeping.

        The motor enters hibernation after inactivity. When sleeping:
        - First command gets NO response (motor wakes but doesn't reply)
        - Subsequent commands work perfectly

        This method sends a harmless "move.stop" command with a short timeout
        to wake the motor. We ignore timeout/no-response since the goal is just
        to wake the motor, not get a response.

        This is called automatically before commands when:
        - First command after connection
        - First command after a previous timeout (motor may have slept again)
        """
        if self._encryption is None:
            # Can't wake up without encryption
            return

        _LOGGER.debug("Sending wake-up command to potentially sleeping motor")

        # Build simple move.stop command (harmless, just wakes motor)
        # Use JSON-RPC format with proper target_id
        wakeup_request = json.dumps({
            "method": "move.stop",
            "params": {"targetID": self._target_id},
            "id": 0
        }, separators=(",", ":"))

        try:
            # Encrypt the wake-up command
            encrypted_data = self._encryption.encrypt(wakeup_request)

            # Send with very short timeout - we don't care about the response
            await asyncio.to_thread(
                self._send_receive_sync,
                encrypted_data,
                0.8,  # Short timeout - motor wakes but may not respond
            )

            _LOGGER.debug("Wake-up command received response (motor was awake)")

        except socket.timeout:
            # Expected - motor woke up but didn't respond, that's fine
            _LOGGER.debug("Wake-up command timed out (expected - motor is now awake)")

        except OSError as err:
            # Log but don't fail - wake-up is best-effort
            _LOGGER.debug("Wake-up command failed (non-critical): %s", err)

        # Brief pause to let motor stabilize after wake-up
        await asyncio.sleep(0.2)

    async def send_unencrypted(
        self,
        message: str,
        timeout: float | None = None,
    ) -> str:
        """Send unencrypted message (for ping/testing).

        Args:
            message: Unencrypted message
            timeout: Request timeout

        Returns:
            Unencrypted response

        Raises:
            SomfyConnectionError: If send/receive fails
            SomfyTimeoutError: If request times out
        """
        if self._closed:
            raise SomfyConnectionError("Transport is closed")

        timeout = timeout if timeout is not None else self._default_timeout
        _LOGGER.debug("Sending unencrypted request")

        async with self._lock:
            try:
                data = message.encode("utf-8")
                _LOGGER.debug("Outgoing unencrypted data: %s", message)

                # Send and receive using synchronous socket
                loop = asyncio.get_running_loop()
                response_data = await loop.run_in_executor(
                    None,
                    self._send_receive_sync,
                    data,
                    timeout,
                )

                response = response_data.decode("utf-8")
                _LOGGER.debug("Received unencrypted response: %s", response)

                return response

            except socket.timeout as err:
                raise SomfyTimeoutError(
                    f"Request timed out after {timeout}s"
                ) from err
            except OSError as err:
                raise SomfyConnectionError(f"Send/receive failed: {err}") from err

    def _send_receive_sync(self, data: bytes, timeout: float) -> bytes:
        """Synchronous send/receive operation.

        This follows the exact pattern from test_decrypt_responses.py that works:
        1. Create socket
        2. Enable SO_REUSEADDR (CRITICAL)
        3. Bind to port 55055 (CRITICAL)
        4. Set timeout
        5. Send data
        6. Receive response
        7. Close socket

        Args:
            data: Data to send (encrypted or unencrypted)
            timeout: Socket timeout in seconds

        Returns:
            Response data (encrypted or unencrypted)

        Raises:
            socket.timeout: If no response within timeout
            OSError: If send/receive fails
        """
        sock = None
        try:
            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # CRITICAL: Enable SO_REUSEADDR (required for motor communication)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Try SO_REUSEPORT if available (helps on macOS/BSD)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                _LOGGER.debug("SO_REUSEPORT enabled")
            except (AttributeError, OSError):
                # Not available on all platforms
                pass

            # CRITICAL: Bind to port 55055 (motor only responds when bound)
            sock.bind(("", self._port))
            _LOGGER.debug("Socket bound to port %s", self._port)

            # Set timeout
            sock.settimeout(timeout)

            # Send data
            sock.sendto(data, (self._host, self._port))
            _LOGGER.debug(
                "Sent %d bytes to %s:%s",
                len(data),
                self._host,
                self._port,
            )

            # Receive response
            response, addr = sock.recvfrom(4096)
            _LOGGER.debug(
                "Received %d bytes from %s",
                len(response),
                addr,
            )

            return response

        finally:
            if sock:
                sock.close()

    @property
    def is_connected(self) -> bool:
        """Check if transport is ready (not closed)."""
        return not self._closed
