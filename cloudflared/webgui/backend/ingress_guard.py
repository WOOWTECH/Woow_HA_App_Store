"""Trust boundary for the Web GUI.

The GUI publishes no host port, so the only intended caller is the Home
Assistant Ingress proxy — which is the Supervisor itself. Everything else on
the internal ``hassio`` docker network (i.e. other add-ons) is rejected: they
could otherwise reach the API directly and rewrite this add-on's tunnel
configuration. Spoofed ``X-Ingress-Path`` / ``X-Hass-Source`` headers do not
help an attacker, because the decision is made on the peer address.

Two properties matter commercially:

- **It must not lock out real users.** Hard-coding 172.30.32.2 alone would
  break the whole product on any install where the Supervisor sits at a
  different address, so the Supervisor's actual address is resolved at
  startup and added to the allow-list.
- **A rejection must be diagnosable.** A bare 403 with nothing in the log is
  unsupportable, so the first rejection from each peer is logged together
  with the addresses that would have been accepted.
"""
from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlparse

_LOGGER = logging.getLogger(__name__)

# Well-known Supervisor address on the `hassio` network; kept as a fallback
# for the case where DNS resolution is unavailable at startup.
INGRESS_GATEWAY = "172.30.32.2"
LOOPBACK = ("127.0.0.1", "::1")

DEV_MODE = os.environ.get("WEBGUI_DEV", "") == "1"
SUPERVISOR_URL = os.environ.get("SUPERVISOR_API", "http://supervisor")


def _resolve_supervisor() -> set[str]:
    """Resolve the Supervisor's address(es); empty set if DNS is unavailable."""
    host = urlparse(SUPERVISOR_URL).hostname or "supervisor"
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError as exc:  # pragma: no cover - depends on the environment
        _LOGGER.warning("Could not resolve the Supervisor address (%s): %s", host, exc)
        return set()


class IngressGuard:
    def __init__(self) -> None:
        self.allowed: set[str] = {INGRESS_GATEWAY, *LOOPBACK} | _resolve_supervisor()
        self._reported: set[str] = set()

    def allows(self, client: str) -> bool:
        return DEV_MODE or client in self.allowed

    def reject(self, client: str, what: str) -> None:
        """Log the first rejection per peer, with enough context to debug."""
        if client in self._reported:
            return
        self._reported.add(client)
        _LOGGER.warning(
            "Blocked %s from %s: the Web GUI only accepts requests from the "
            "Home Assistant Ingress proxy (allowed: %s). If you are seeing "
            "this while opening the add-on's own Web UI, please report it "
            "with this line.",
            what,
            client or "<unknown peer>",
            ", ".join(sorted(self.allowed)),
        )


guard = IngressGuard()
