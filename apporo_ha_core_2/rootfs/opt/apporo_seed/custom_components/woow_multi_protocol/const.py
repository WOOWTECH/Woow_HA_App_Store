"""Constants for the Woow Multi-Protocol Connect integration."""

from collections.abc import Mapping

DOMAIN = "woow_multi_protocol"

# The single sidebar panel.
PANEL_TITLE = "Woow Multi-Protocol Connect"
PANEL_ICON = "mdi:transit-connection-variant"
# The custom element defined by the frontend bundle and the bundle filename stem.
PANEL_COMPONENT_NAME = "woow-multi-protocol-panel"

# The protocols this integration fronts. Order defines the tab order in the panel
# and the parametrization order of the service / WebSocket seam.
PROTOCOLS = ("knx", "dmx", "modbus")

# Every file operation is sandboxed to <config>/woow_multi_protocol/<protocol>/.
# The base subdirectory is the domain itself, so all protocols live under one
# tree that a later cleanup can remove wholesale.
BASE_SUBDIR = DOMAIN

# `apply` targets the underlying stock/HACS integration that actually consumes
# each protocol's YAML — never this panel. Reload capability is discovered at
# call time (ADR-0002); this map only says *which* integration to target.
UNDERLYING_DOMAIN = {"knx": "knx", "dmx": "artnet", "modbus": "modbus"}

# Options flow: one enable toggle per protocol (e.g. "enable_knx"), all default on.
OPTION_ENABLE = {protocol: f"enable_{protocol}" for protocol in PROTOCOLS}


def enabled_protocols(options: Mapping[str, object]) -> list[str]:
    """Return the enabled protocols, in canonical order, from an entry's options.

    A protocol is enabled unless its toggle is explicitly ``False`` — so a fresh
    install (empty options) has all three on, matching the Options-flow defaults.
    """
    return [p for p in PROTOCOLS if options.get(OPTION_ENABLE[p], True)]
