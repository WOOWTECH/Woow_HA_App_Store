#!/usr/bin/env python3
"""Manifest, config-script and nginx gateway contracts.

Ported from the former tests/test-dual-gateway.sh. Every assertion here is a
contract about the shipped files; nothing needs a live Odoo.
"""
import re
import subprocess
from pathlib import Path

import yaml

from conftest import require_tool

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
DOCKERFILE = ROOT / "Dockerfile"
CONFIG_SCRIPT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"
POSTGRES_INIT = ROOT / "rootfs/etc/cont-init.d/00-postgres-init.sh"
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
BOOTSTRAP = ROOT / "rootfs/usr/local/bin/odoo-maintenance-bootstrap"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_manifest_contract() -> None:
    c = yaml.safe_load(read(CONFIG))
    assert c["ingress"] is True
    assert c["ingress_port"] == 5691
    assert c["ingress_entry"] == "odoo"
    assert c["ingress_stream"] is True
    # The origin ports are published so the LAN can reach Odoo directly; the
    # privilege split is enforced by source address inside nginx, not by
    # hiding the ports.
    assert c["ports"]["8069/tcp"] == 8069
    assert c["ports"]["8072/tcp"] == 8072
    assert c["schema"]["lan_networks"] == "str?"
    assert c["options"]["lan_networks"] == "192.168.0.0/16 10.0.0.0/8 172.16.0.0/12"
    # 8072 only carries the gevent WebSocket while Odoo runs multi-process.
    assert c["options"]["workers"] > 0
    assert not c.get("hassio_api", False)
    assert all("backup" not in str(x) for x in c["map"])
    assert c["schema"]["public_url"] == "url?"
    assert "public_url" not in c["options"]


def test_dockerfile_pins() -> None:
    d = read(DOCKERFILE)
    assert re.search(r'ARG ODOO_DEB_VERSION="18\.0\.\d{8}"', d)
    assert re.search(r'ARG ODOO_DEB_SHA256="[0-9a-f]{64}"', d)
    assert re.search(r'ARG WOOW_ADDONS_REF="[0-9a-f]{40}"', d)
    assert "odoo-jsonrpc-filter" in d


def test_config_script_contract() -> None:
    s = read(CONFIG_SCRIPT)
    # gevent must not sit on 8072: nginx owns that port so the gate applies there.
    assert "gevent_port = 8073" in s
    assert "WS_PORT=8073" in s
    assert "gevent_port = 8072" not in s
    assert "http_interface = 127.0.0.1" in s
    assert "http_port = 8070" in s
    assert "proxy_mode = True" in s
    # Operator-supplied CIDRs are rendered straight into an nginx geo block, so
    # anything malformed has to fail start-up rather than inject a directive.
    assert "lan_networks entry is not an IPv4/IPv6 CIDR" in s
    assert "exit 1" in s
    for placeholder in ["%%LAN_NETWORKS%%", "%%PUBLIC_HOST_MAP%%", "%%DENY_STATUS%%"]:
        assert placeholder in s, placeholder
    # Without public_url no Host may reach the public tier, and off-LAN is 503.
    assert "PUBLIC_HOST_MAP=''" in s
    assert "DENY_STATUS='503'" in s
    assert "DENY_STATUS='444'" in s


def test_nginx_template_contract() -> None:
    n = read(TEMPLATE)
    for text in [
        "listen 8069",
        "listen 5691",
        "server 127.0.0.1:%%WS_PORT%%",
        "/web/database/",
        "http_x_ingress_path",
        "HTMLFormElement",
    ]:
        assert text in n, text

    # --- 8069 origin: LAN tier vs Cloudflare tunnel ---
    # The tunnel reaches this listener from the add-on network, and the default
    # LAN list (172.16.0.0/12) contains that network. This single carve-out is
    # what keeps the tunnel off the LAN tier, so assert it literally.
    assert "172.30.32.0/23      0;" in n, "hassio IPv4 carve-out missing"
    assert "fd0c:ac1e:2100::/48 0;" in n, "hassio IPv6 carve-out missing"
    # The bridge address must never be promoted back into the LAN tier: the
    # Cloudflare tunnel is host-networked on real deployments and arrives from
    # it, which would publish the database manager to the internet.
    geo = n.split("geo $woow_lan_src")[1].split("}")[0]
    lan_entries = re.findall(r"^\s*([0-9a-fA-F.:]+/\d+)\s+1;", geo, re.M)
    assert not any(
        e.startswith("172.30.32.") or e.startswith("172.30.33.") for e in lan_entries
    ), f"bridge/add-on network must not be LAN: {lan_entries}"
    assert "%%LAN_NETWORKS%%" in n

    # Database lifecycle is LAN-only; every entry point must be gated.
    for loc in ["location ^~ /web/database/", "location = /xmlrpc/db", "location = /xmlrpc/2/db"]:
        i = n.index(loc)
        assert 'if ($woow_origin_gate != "lan") { return 404; }' in n[i : i + 220], loc

    # Off-LAN callers that present no recognised Host are dropped outright, on
    # the WebSocket origin as well as the HTTP one.
    assert n.count('if ($woow_origin_gate = "deny") { return %%DENY_STATUS%%; }') == 2
    # Odoo binds gevent to loopback, so nginx has to own the published 8072
    # port and the worker has to sit on an internal one.
    assert "listen 8072 default_server;" in n
    # An unset public_url must not leave a Host that maps to the public tier.
    assert "map $http_host $woow_public_host" in n
    assert "%%PUBLIC_HOST_MAP%%" in n
    # The LAN talks to Odoo directly; the tunnel keeps the RPC policy filter.
    assert '"lan"   "127.0.0.1:8070";' in n
    assert 'default "127.0.0.1:8071";' in n
    assert "proxy_pass http://$woow_jsonrpc_upstream;" in n
    # A Secure cookie over plain LAN http is never returned by the browser.
    assert "proxy_cookie_flags session_id $woow_origin_cookie_secure" in n
    assert "proxy_set_header X-Forwarded-Proto $woow_origin_proto;" in n
    # The old unconditional guard must be gone, not merely bypassed.
    assert "%%PUBLIC_HOST_GUARD%%" not in n
    assert "location ^~ /web/database/ { return 404; }" not in n
    for placeholder in ["%%DENY_STATUS%%", "%%PUBLIC_HOST_MAP%%", "%%PUBLIC_PROTO%%"]:
        assert placeholder in n

    # --- ingress adapter ---
    assert "while(q.indexOf(P+P)===0)" in n
    assert "absolute_redirect off;" in n
    assert "(?<odoo_redirect>/.*)" in n
    assert "window.SharedWorker=function" in n
    assert 'Object.defineProperty(navigator.serviceWorker,"controller"' in n
    assert "sub_filter '&#39;/web/login&#39;'" in n
    assert "sub_filter '<head>'" in n
    assert "u instanceof URL" in n
    assert "location ^~ /web/assets/" in n
    assert "translationURL" in n
    assert 'browser.location.origin+"$safe_ingress_path"+router.stateToUrl' in n
    assert "params.serverURL}$safe_ingress_path/bus/websocket_worker_bundle" in n
    assert 'serverURL.replace("http", "ws")}$safe_ingress_path/websocket' in n
    assert 'serverURL:window.origin+"$safe_ingress_path"' not in n
    assert "odoo:websocket_shared_worker_%%INGRESS_CACHE_VERSION%%" in n
    assert "websocket_worker_bundle?woow_ingress=%%INGRESS_CACHE_VERSION%%&v=" in n
    assert "%%INGRESS_CACHE_VERSION%%" in n
    assert 'Cache-Control "no-store, no-cache, must-revalidate"' in n
    assert "navigator.serviceWorker.getRegistrations" in n
    assert 'r.scope.indexOf("/odoo")' in n
    assert "woow-odoo-sw-clean-%%INGRESS_CACHE_VERSION%%" in n
    assert "sub_filter '\"src\": \"/'" in n
    assert "sub_filter '\"/my/'" in n
    assert "sub_filter '\"/calendar/'" in n
    assert "sub_filter '\"/base_setup/'" in n
    assert "sub_filter '\"icon\":\"/'" in n
    assert "sub_filter '\"imgurl\":\"/'" in n
    assert ".settings_tab a.tab" not in n
    assert 'if(u.charAt(0)==="#")return u' in n
    assert "href^='#'" not in n
    assert 'HTMLImageElement.prototype,"srcset"' in n
    assert "return 302 $safe_ingress_path/odoo" not in n
    assert n.count("proxy_set_header X-Forwarded-Proto $ingress_proto;") >= 3
    assert "proxy_set_header Origin $ingress_proto://$http_host;" in n
    assert "map $ingress_proto $ingress_cookie_secure" in n
    assert "proxy_cookie_flags session_id $ingress_cookie_secure" in n
    assert "proxy_hide_header X-Frame-Options;" in n
    assert "location = /xmlrpc/2/db" in n
    assert "window.WebSocket.OPEN=W.OPEN" in n
    assert "$request_method $uri $server_protocol" in n
    assert "$http_referer" not in n
    assert "$sent_http_x_frame_options" in n
    assert "$upstream_http_x_frame_options" in n
    assert (ROOT / "tests/e2e_adversarial.py").is_file()


def test_maintenance_bootstrap_contract() -> None:
    m = read(BOOTSTRAP)
    assert "web.base.url.freeze" in m
    assert "bootstrap-user.json" in m
    assert "base.group_system" in m
    assert "base.group_erp_manager" in m
    assert "root:600" in m
    assert "must contain at least 20 characters" in m


def test_postgres_init_contract() -> None:
    pg = read(POSTGRES_INIT)
    assert "local   all       all                  peer" in pg
    assert "--auth-local=peer" in pg


def runtime_shim_source() -> str:
    source = read(TEMPLATE)
    map_start = source.index("map $upstream_http_content_type $ingress_runtime_shim {")
    map_end = source.index("\n    }", map_start)
    runtime_shim = source[map_start:map_end]
    assert '"~*^text/html(?:;|$)"' in runtime_shim, "runtime shim must be limited to HTML upstream responses"
    match = re.search(r"<script>(.*?)</script>';", runtime_shim, re.S)
    assert match, "HTML runtime shim not found"
    return match.group(1).replace("$safe_ingress_path", "/P").replace("%%INGRESS_CACHE_VERSION%%", "V")


def test_runtime_shim_is_valid_javascript(tmp_path: Path) -> None:
    node = require_tool("node")
    shim = tmp_path / "shim.js"
    shim.write_text(runtime_shim_source(), encoding="utf-8")
    result = subprocess.run([node, "--check", str(shim)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def render_scenarios(test_dir: Path) -> dict:
    """Render the template for both real-world shapes: public_url set and unset."""
    template = read(TEMPLATE)
    common = {
        "%%WS_PORT%%": "8070",
        "%%PUBLIC_PROTO%%": "https",
        "%%LAN_NETWORKS%%": "192.168.0.0/16 1; 10.0.0.0/8 1; 172.16.0.0/12 1;",
        "%%INGRESS_CACHE_VERSION%%": "test",
    }
    scenarios = {
        "public": dict(common, **{
            "%%PUBLIC_HOST_MAP%%": '"odoo-test.invalid" 1; "odoo-test.invalid:443" 1;',
            "%%DENY_STATUS%%": "444",
        }),
        # public_url unset: the host map is empty, so no Host reaches the
        # public tier and every off-LAN caller falls through to the deny status.
        "lanonly": dict(common, **{"%%PUBLIC_HOST_MAP%%": "", "%%DENY_STATUS%%": "503"}),
    }
    rendered = {}
    for name, replacements in scenarios.items():
        config = template
        for placeholder, value in replacements.items():
            assert placeholder in template, f"missing template placeholder: {placeholder}"
            config = config.replace(placeholder, value)
        assert "%%" not in config, f"unrendered placeholder remains in {name}"
        config = config.replace("pid /var/run/nginx.pid;", f"pid {test_dir}/{name}.pid;")
        config = config.replace("error_log /dev/stderr info;", f"error_log {test_dir}/{name}-error.log info;")
        config = config.replace("access_log /dev/stdout safe;", f"access_log {test_dir}/{name}-access.log safe;")
        # nginx -t opens listener sockets. Use paths inside the unique temporary
        # directory rather than probing and releasing TCP ports, which has a
        # TOCTOU race with other processes.
        for original, replacement in [
            ("listen 8069 default_server;", f"listen unix:{test_dir}/{name}-public.sock default_server;"),
            ("listen 8072 default_server;", f"listen unix:{test_dir}/{name}-ws.sock default_server;"),
            ("listen 5691;", f"listen unix:{test_dir}/{name}-ingress.sock;"),
        ]:
            assert config.count(original) == 1, f"expected one listener to replace: {original}"
            config = config.replace(original, replacement)
        path = test_dir / f"nginx-{name}.conf"
        path.write_text(config, encoding="utf-8")
        rendered[name] = path
    return rendered


def test_rendered_gateway_configs_are_valid_nginx(tmp_path: Path) -> None:
    nginx = require_tool("nginx")
    for name, config in render_scenarios(tmp_path).items():
        result = subprocess.run(
            [nginx, "-t", "-p", str(tmp_path), "-c", str(config)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"
