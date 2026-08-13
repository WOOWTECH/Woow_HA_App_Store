"""JSON-RPC protocol implementation for Somfy PoE API."""
from __future__ import annotations

import json
import logging
from typing import Any

from ..errors import SomfyProtocolError, SomfyAPIError

_LOGGER = logging.getLogger(__name__)


class SomfyProtocol:
    """JSON-RPC message builder and parser.

    Design Decisions:
    - Stateless design (no request ID tracking)
    - Simple incremental ID generation
    - Comprehensive error code mapping
    - Type-safe result extraction
    """

    def __init__(self, target_id: str) -> None:
        """Initialize protocol.

        Args:
            target_id: 6-character hex target ID (from MAC)

        Raises:
            ValueError: If target_id format is invalid
        """
        if len(target_id) != 6 or not all(
            c in "0123456789ABCDEFabcdef" for c in target_id
        ):
            raise ValueError("target_id must be 6-character hex string")

        self._target_id = target_id.upper()
        self._request_id = 0
        _LOGGER.debug("Initialized SomfyProtocol with target_id=%s", self._target_id)

    def build_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Build JSON-RPC request.

        Args:
            method: RPC method name (e.g., "status.position")
            params: Optional method parameters

        Returns:
            JSON string ready for transmission
        """
        self._request_id += 1

        request_params = {"targetID": self._target_id}
        if params:
            request_params.update(params)

        request = {
            "method": method,
            "params": request_params,
            "id": self._request_id,
        }

        json_str = json.dumps(request, separators=(",", ":"))
        _LOGGER.debug(
            "Built JSON-RPC request #%d: method=%s, params=%s, full_payload=%s",
            self._request_id,
            method,
            request_params,
            json_str
        )
        return json_str  # Compact JSON

    def parse_response(self, response: str) -> Any:
        """Parse JSON-RPC response.

        Args:
            response: JSON response string

        Returns:
            Result data from response

        Raises:
            SomfyProtocolError: If response is malformed
            SomfyAPIError: If response contains error
        """
        _LOGGER.debug("Parsing JSON-RPC response: %s", response)

        try:
            data = json.loads(response)
        except json.JSONDecodeError as err:
            raise SomfyProtocolError(f"Invalid JSON response: {err}") from err

        _LOGGER.debug("Parsed response structure: %s", data)

        # Validate JSON-RPC structure
        if not isinstance(data, dict):
            raise SomfyProtocolError("Response must be JSON object")

        # Check for error response
        if "error" in data:
            error = data["error"]
            if isinstance(error, dict):
                code = error.get("id", -1)
                message = error.get("title", "Unknown error")
            else:
                code = -1
                message = str(error)

            _LOGGER.debug(
                "API returned error response: code=%s, message=%s, full_error=%s",
                code,
                message,
                error
            )
            raise SomfyAPIError(message, code)

        # Extract result
        if "result" not in data:
            raise SomfyProtocolError("Response missing 'result' field")

        _LOGGER.debug("Extracted result from response: %s", data.get("result"))
        return data

    @property
    def target_id(self) -> str:
        """Get target ID."""
        return self._target_id
