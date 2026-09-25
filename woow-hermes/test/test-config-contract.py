"""Static contract checks for the add-on manifest, translations and ingress adapter."""
import pathlib
import re
import sys

import yaml

ADDON = pathlib.Path(__file__).resolve().parent.parent
config = yaml.safe_load((ADDON / "config.yaml").read_text())
nginx = (ADDON / "rootfs/etc/nginx/nginx.conf").read_text()
common = (ADDON / "rootfs/etc/nginx/woow/proxy-common.conf").read_text()
dockerfile = (ADDON / "Dockerfile").read_text()

# s6-overlay in the base image only starts when it is PID 1.
assert config["init"] is False
assert re.fullmatch(r"\d+\.\d+\.\d+", config["version"]), "plain X.Y.Z only"
assert config["arch"] == ["amd64"]
assert config["ingress"] is True and config["ingress_port"] == 9120 and config["ingress_stream"] is True
assert config["ports"] == {"8642/tcp": 8642, "9119/tcp": 9119, "8644/tcp": 8644}
assert "8642" not in config["watchdog"], "the gateway can be stopped from the dashboard"
assert config["panel_title"] == "Hermes"
assert "homeassistant_api" not in config
assert {"type": "addon_config", "path": "/opt/data", "read_only": False} in config["map"]
# Supervisor's backup filter only prunes a directory when the directory itself matches.
assert all(not p.endswith("/**") for p in config["backup_exclude"])

for lang in ("en", "zh-Hant"):
    tr = yaml.safe_load((ADDON / f"translations/{lang}.yaml").read_text())
    assert set(tr["configuration"]) == set(config["schema"]), lang
    assert set(tr["network"]) == set(config["ports"]), lang

# Hermes prefixes Location headers itself; proxy_redirect would double-prefix.
assert not re.search(r"^\s*proxy_redirect\b", nginx, re.M)
assert "allow 172.30.32.2;" in nginx and "deny all;" in nginx
assert "X-Forwarded-Prefix $safe_ingress_path" in common
# A location with its own proxy_set_header does not inherit the server's, so every
# proxied location must include the shared set.
for block in re.findall(r"location[^{]*\{(.*?)\n        \}", nginx, re.S):
    if "proxy_pass" in block:
        assert "include /etc/nginx/woow/proxy-common.conf;" in block, block[:80]

# Every rewritten anchor is proven in the image at build time.
for anchor in re.findall(r"sub_filter\s+(['\"])(.*?)\1\s", nginx):
    text = anchor[1]
    # Generated at runtime by FastAPI; run-local-parity.sh checks them.
    if text in ("</head>", "url: '/openapi.json'", '{"openapi":'):
        continue
    assert text in dockerfile.replace("\\", ""), f"no build proof for anchor {text!r}"

# The relay behind ingress WebSockets runs as an s6 service, and nginx routes
# WebSocket upgrades on /api/ to it.
s6 = ADDON / "rootfs/etc/s6-overlay/s6-rc.d"
assert (s6 / "woow-wsrelay/type").read_text().strip() == "longrun"
assert (s6 / "user/contents.d/woow-wsrelay").exists()
assert "/opt/woow/ws_relay.py 9121" in (s6 / "woow-wsrelay/run").read_text()
assert '"~*^websocket$" 127.0.0.1:9121;' in nginx
assert "location = /__woow/wsclose" in nginx

# The agent runs with upstream's approval defaults (user decision, 2026-09-25):
# the podman stack's sed policy never matched the v2026.8.31 config and must
# not come back looking as if it did.
provision = "\n".join(line for line in (ADDON / "rootfs/usr/local/bin/woow-provision").read_text().splitlines()
                      if not line.lstrip().startswith("#"))
for text in ("cron_mode: yolo", "mode: off", "hooks_auto_accept: true", "sed -i"):
    assert text not in provision, f"woow-provision still carries the approval policy: {text!r}"

# Home Assistant pulls the prebuilt image the publish workflow pushes.
workflow = (ADDON.parent / ".github/workflows/publish-hermes-addon-images.yml").read_text()
assert config["image"] == "ghcr.io/woowtech/woow-ha-hermes-{arch}"
assert "ghcr.io/woowtech/woow-ha-hermes-amd64:${{ steps.addon.outputs.version }}" in workflow
assert config["arch"] == ["amd64"] and "linux/amd64" in workflow

# Store listing artwork: the official Hermes app icon.
from PIL import Image
assert Image.open(ADDON / "icon.png").size == (128, 128)
assert Image.open(ADDON / "logo.png").size == (400, 400)

# Swagger's server comes from the ingress path (P4k).
assert "location = /openapi.json" in nginx and "$openapi_head" in nginx

# Unattended runs follow cron_mode / unattended_mode (own patch, proven at build).
assert (ADDON / "patches/approval-unattended.py").exists()
assert "woow: unattended runs ignore HERMES_EXEC_ASK" in dockerfile

# Defaults the add-on writes while the keys are empty.
provision_run = (ADDON / "rootfs/etc/s6-overlay/s6-rc.d/woow-provision/run").read_text()
for default in ("set_default web.search_backend ddgs", "set_default web.extract_backend parallel",
                "set_default browser.backend off", "set_default platforms.webhook.enabled true"):
    assert default in provision_run, default

print("config contract: ok")
