"""Custom exceptions for Somfy PoE integration."""
from __future__ import annotations


class SomfyError(Exception):
    """Base exception for Somfy integration."""


class SomfyConnectionError(SomfyError):
    """Error connecting to device."""


class SomfyTimeoutError(SomfyError):
    """Request timeout."""


class SomfyProtocolError(SomfyError):
    """Protocol-level error (malformed JSON, etc)."""


class SomfyAPIError(SomfyError):
    """API returned error response.

    Attributes:
        message: Error message from API
        code: Error code from API
    """

    def __init__(self, message: str, code: int) -> None:
        """Initialize API error."""
        super().__init__(f"API error {code}: {message}")
        self.message = message
        self.code = code

    @property
    def is_device_busy(self) -> bool:
        """Check if error indicates device is busy."""
        from .const import ERROR_BUSY
        return self.code == ERROR_BUSY

    @property
    def is_device_locked(self) -> bool:
        """Check if error indicates device is locked."""
        from .const import ERROR_DEVICE_LOCKED
        return self.code == ERROR_DEVICE_LOCKED

    @property
    def is_end_limits_not_set(self) -> bool:
        """Check if error indicates end limits not set."""
        from .const import ERROR_END_LIMITS_NOT_SET
        return self.code == ERROR_END_LIMITS_NOT_SET


class SomfyAuthenticationError(SomfyError):
    """Authentication error.

    Attributes:
        message: Error message
        code: Optional error code
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        """Initialize authentication error."""
        if code is not None:
            super().__init__(f"Auth error {code}: {message}")
        else:
            super().__init__(f"Auth error: {message}")
        self.message = message
        self.code = code
