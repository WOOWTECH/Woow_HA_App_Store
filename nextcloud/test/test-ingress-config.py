#!/usr/bin/env python3
"""Static regression checks for Woow Nextcloud HA Ingress support."""
from pathlib import Path
import yaml

ADDON_DIR = Path(__file__).resolve().parents[1]

config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
assert config["ingress"] is True
assert config["ingress_port"] == 8090
assert config["ingress_entry"] == "login"
assert config["ingress_stream"] is False
assert config["schema"]["NEXTCLOUD_PUBLIC_URL"] == "str?"
assert config["options"]["NEXTCLOUD_PUBLIC_URL"].startswith("https://")
assert config["panel_admin"] is False
assert config["panel_title"] == "Woow Nextcloud"
assert config["watchdog"] == "http://[HOST]:[PORT:8090]/healthz"
assert config["ports"]["80/tcp"] == 8000
assert "8090/tcp" not in (config.get("ports") or {}), "ingress port must not be directly exposed"

run_path = ADDON_DIR / "rootfs/etc/s6-overlay/s6-rc.d/init-nextcloud-ingress/run"
run = run_path.read_text()
required = [
    "listen 8090 default_server;",
    "allow 172.30.32.2;",
    "location = /healthz",
    "NEXTCLOUD_PUBLIC_URL",
    "window.top.location.replace(u)",
    "target=\"_top\"",
]
for needle in required:
    assert needle in run, f"missing sidebar launcher directive: {needle}"

for forbidden in [
    "proxy_pass http://127.0.0.1:80;",
    "proxy_cookie_path / $safe_ingress_path/;",
    "sub_filter 'href=\"/'",
]:
    assert forbidden not in run, f"ingress must not proxy full Nextcloud UI anymore: {forbidden}"

svc_dep = ADDON_DIR / "rootfs/etc/s6-overlay/s6-rc.d/svc-nginx/dependencies.d/init-nextcloud-ingress"
user_content = ADDON_DIR / "rootfs/etc/s6-overlay/s6-rc.d/user/contents.d/init-nextcloud-ingress"
assert svc_dep.exists(), "nginx must wait for ingress config generation"
assert user_content.exists(), "init-nextcloud-ingress must be in the user bundle"

print("Nextcloud ingress static checks passed")
