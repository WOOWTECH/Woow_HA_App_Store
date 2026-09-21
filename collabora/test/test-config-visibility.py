#!/usr/bin/env python3
"""Static TDD checks for Woow Collabora Home Assistant visibility.

These tests protect the UI contract that users care about:
- it must appear as a normal/stable installed app, not experimental;
- it must create a Home Assistant sidebar/Ingress panel;
- the sidebar must be available to non-admin HA users too;
- Nextcloud Office must use the direct WOPI port, not an ingress token URL.
"""
from pathlib import Path
import yaml

ADDON_DIR = Path(__file__).resolve().parents[1]
config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())

assert config["name"] == "Woow Collabora CODE"
assert config["slug"] == "woow-collabora"
assert config["stage"] == "stable", "Collabora must not show the experimental badge"
assert config.get("advanced") is not True, "App must be visible in the normal apps list"

assert config["ingress"] is True, "Admin GUI must be available through HA ingress"
assert config["ingress_panel"] is True, "Ingress panel must be enabled by default"
assert config["ingress_port"] == 9980
assert config["ingress_entry"] == "browser/dist/admin/admin.html"
assert config["ingress_stream"] is True, "Collabora admin websockets/events need ingress streaming"
assert config["panel_title"] == "Woow Collabora"
assert config["panel_icon"] == "mdi:file-document-edit-outline"
assert config["panel_admin"] is False, "Sidebar panel should be visible to all HA users"

ports = config["ports"]
assert ports["9980/tcp"] == 9981, "Direct WOPI endpoint should be exposed on HA port 9981"
assert config["webui"] == "[PROTO:ssl]://[HOST]:[PORT:9980]/browser/dist/admin/admin.html"
assert config["watchdog"] == "http://[HOST]:[PORT:9980]/hosting/capabilities"

options = config["options"]
assert options["aliasgroup1"] == "http://homeassistant:8000"
assert options["server_name"] == "homeassistant:9981"
assert options["ssl"] is False
assert options["ssl_termination"] is False
assert "ssl.enable=false" in options["extra_params"]
assert "ssl.termination=false" in options["extra_params"]

for doc in ["README.md", "DOCS.md", "TEST_REPORT.md"]:
    assert (ADDON_DIR / doc).exists(), f"missing operator documentation: {doc}"

print("Woow Collabora static visibility checks passed")
