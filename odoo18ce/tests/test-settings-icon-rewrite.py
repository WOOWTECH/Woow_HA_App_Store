#!/usr/bin/env python3
"""Contracts for the narrow ingress rewrites used by Settings icons."""
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
DYNAMIC_SOURCE = 'imgurl:el.getAttribute("logo")||"/"+el.getAttribute("name")+"/static/description/icon.png"'
DYNAMIC_TARGET = 'imgurl:el.getAttribute("logo")||"$safe_ingress_path/"+el.getAttribute("name")+"/static/description/icon.png"'
BASE_ICON_SOURCE = "/base/static/description/settings.png"
BASE_ICON_TARGET = "$safe_ingress_path/base/static/description/settings.png"


def rule(source: str, target: str) -> str:
    return f"sub_filter '{source}' '{target}';"


def assert_actual_nginx_literal_rewrite() -> None:
    """Prove nginx rewrites the path in direct and JSON-escaped payloads."""
    nginx = shutil.which("nginx")
    if not nginx:
        raise AssertionError("nginx is required for Settings icon response tests")

    direct = '<app_settings_block logo="/base/static/description/settings.png">'
    escaped = r'{"arch":"<app_settings_block logo=\"/base/static/description/settings.png\">"}'
    with tempfile.TemporaryDirectory(prefix="odoo-icon-nginx-") as directory:
        root = Path(directory)
        socket = root / "filter.sock"
        config = root / "nginx.conf"
        (root / "direct.txt").write_text(direct, encoding="utf-8")
        (root / "escaped.json").write_text(escaped, encoding="utf-8")
        config.write_text(
            "\n".join(
                (
                    "daemon off;",
                    "master_process off;",
                    f"pid {root / 'nginx.pid'};",
                    f"error_log {root / 'error.log'} notice;",
                    "events {}",
                    "http {",
                    "  access_log off;",
                    "  sub_filter_once off;",
                    "  sub_filter_types *;",
                    f"  server {{ listen unix:{socket};",
                    f"    sub_filter '{BASE_ICON_SOURCE}' '/P{BASE_ICON_SOURCE}';",
                    f"    location = /direct {{ default_type text/plain; alias {root / 'direct.txt'}; }}",
                    f"    location = /escaped {{ default_type application/json; alias {root / 'escaped.json'}; }}",
                    "  }",
                    "}",
                )
            ),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [nginx, "-p", str(root), "-c", str(config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            for _ in range(100):
                if socket.exists():
                    break
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    raise AssertionError(f"nginx response harness exited: {stdout}{stderr}")
                time.sleep(0.02)
            else:
                raise AssertionError("nginx response harness socket did not become ready")

            for route, payload in (("direct", direct), ("escaped", escaped)):
                response = subprocess.run(
                    ["curl", "--fail", "--silent", "--unix-socket", str(socket), f"http://localhost/{route}"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                expected = payload.replace(BASE_ICON_SOURCE, f"/P{BASE_ICON_SOURCE}")
                assert response == expected, {"route": route, "expected": expected, "actual": response}
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    public_start = template.index("# Internal public origin.")
    ingress_start = template.index("# HA Supervisor Ingress adapter.")
    public = template[public_start:ingress_start]
    ingress = template[ingress_start:]
    assets_start = ingress.index("location ^~ /web/assets/ {")
    generic_start = ingress.index("\n        location / {", assets_start)
    assets = ingress[assets_start:generic_start]
    generic = ingress[generic_start:]

    dynamic_rule = rule(DYNAMIC_SOURCE, DYNAMIC_TARGET)
    assert dynamic_rule in assets, "missing exact SettingsViewCompiler fallback icon rewrite"
    assert dynamic_rule not in generic
    assert dynamic_rule not in public, "Settings asset rewrite must not affect public origin"

    base_icon_rule = rule(BASE_ICON_SOURCE, BASE_ICON_TARGET)
    assert base_icon_rule in generic, "missing exact General Settings icon path rewrite"
    assert base_icon_rule not in assets
    assert base_icon_rule not in public, "General Settings icon rewrite must not affect public origin"
    assert "sub_filter 'logo=\"/'" not in generic
    assert "sub_filter 'logo=\\\"/'" not in generic

    # The rule matches only the path bytes, independently of surrounding quote
    # encoding. Actual nginx response filtering is verified below.
    assert BASE_ICON_SOURCE in '<app_settings_block logo="/base/static/description/settings.png">'
    assert BASE_ICON_SOURCE in r'{"arch":"<app_settings_block logo=\"/base/static/description/settings.png\">"}'
    assert_actual_nginx_literal_rewrite()


if __name__ == "__main__":
    main()
