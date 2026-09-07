#!/usr/bin/env bash
set -euo pipefail
ADDON="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$ADDON" <<'PY'
import sys, yaml
from pathlib import Path
root=Path(sys.argv[1]); c=yaml.safe_load((root/'config.yaml').read_text())
assert c['ingress'] is True
assert c['ingress_port']==5691
assert c['ingress_entry']=='odoo'
assert c['ingress_stream'] is True
# The origin ports are published so the LAN can reach Odoo directly; the
# privilege split is enforced by source address inside nginx, not by hiding
# the ports.
assert c['ports']['8069/tcp']==8069
assert c['ports']['8072/tcp']==8072
assert c['schema']['lan_networks']=='str?'
assert c['options']['lan_networks']=='192.168.0.0/16 10.0.0.0/8 172.16.0.0/12'
# 8072 only carries the gevent WebSocket while Odoo runs multi-process.
assert c['options']['workers']>0
assert not c.get('hassio_api', False)
assert all('backup' not in str(x) for x in c['map'])
assert c['schema']['public_url']=='url?'
assert 'public_url' not in c['options']

d=(root/'Dockerfile').read_text()
assert '18.0.20260806' in d
assert '60def7fca9f7005be9575f70f17e7db4e4e43190b36d0f34832fb0248beb6ba5' in d

s=(root/'rootfs/etc/cont-init.d/10-odoo-config.sh').read_text()
# gevent must not sit on 8072: nginx owns that port so the gate applies there.
assert 'gevent_port = 8073' in s
assert 'WS_PORT=8073' in s
assert 'gevent_port = 8072' not in s
assert 'http_interface = 127.0.0.1' in s
assert 'http_port = 8070' in s
assert 'proxy_mode = True' in s
# Operator-supplied CIDRs are rendered straight into an nginx geo block, so
# anything malformed has to fail start-up rather than inject a directive.
assert 'lan_networks entry is not an IPv4/IPv6 CIDR' in s
assert "exit 1" in s
for ph in ['%%LAN_NETWORKS%%','%%PUBLIC_HOST_MAP%%','%%DENY_STATUS%%']:
    assert ph in s, ph
# Without public_url no Host may reach the public tier, and off-LAN is 503.
assert "PUBLIC_HOST_MAP=''" in s
assert "DENY_STATUS='503'" in s
assert "DENY_STATUS='444'" in s

n=(root/'rootfs/etc/nginx/nginx.conf.template').read_text()
for text in ['listen 8069','listen 5691','server 127.0.0.1:%%WS_PORT%%','/web/database/','http_x_ingress_path','HTMLFormElement']:
    assert text in n, text

# --- 8069 origin: LAN tier vs Cloudflare tunnel ---
# The tunnel reaches this listener from the add-on network, and the default
# LAN list (172.16.0.0/12) contains that network. This single carve-out is
# what keeps the tunnel off the LAN tier, so assert it literally.
assert '172.30.32.0/23      0;' in n, 'hassio IPv4 carve-out missing'
assert 'fd0c:ac1e:2100::/48 0;' in n, 'hassio IPv6 carve-out missing'
# The bridge address must never be promoted back into the LAN tier: the
# Cloudflare tunnel is host-networked on real deployments and arrives from it,
# which would publish the database manager to the internet.
import re as _re
_geo = n.split('geo $woow_lan_src')[1].split('}')[0]
_lan_entries = _re.findall(r'^\s*([0-9a-fA-F.:]+/\d+)\s+1;', _geo, _re.M)
assert not any(e.startswith('172.30.32.') or e.startswith('172.30.33.')
               for e in _lan_entries), f'bridge/add-on network must not be LAN: {_lan_entries}'
assert 'geo $woow_lan_src' in n
assert '%%LAN_NETWORKS%%' in n

# Database lifecycle is LAN-only; every entry point must be gated.
for loc in ['location ^~ /web/database/','location = /xmlrpc/db','location = /xmlrpc/2/db']:
    i=n.index(loc)
    assert 'if ($woow_origin_gate != "lan") { return 404; }' in n[i:i+220], loc

# Off-LAN callers that present no recognised Host are dropped outright, on
# the WebSocket origin as well as the HTTP one.
assert n.count('if ($woow_origin_gate = "deny") { return %%DENY_STATUS%%; }') == 2
# Odoo binds gevent to loopback, so nginx has to own the published 8072 port
# and the worker has to sit on an internal one.
assert 'listen 8072 default_server;' in n
# An unset public_url must not leave a Host that maps to the public tier.
assert 'map $http_host $woow_public_host' in n
assert '%%PUBLIC_HOST_MAP%%' in n
# The LAN talks to Odoo directly; the tunnel keeps the RPC policy filter.
assert '"lan"   "127.0.0.1:8070";' in n
assert 'default "127.0.0.1:8071";' in n
# A Secure cookie over plain LAN http is never returned by the browser.
assert 'proxy_cookie_flags session_id $woow_origin_cookie_secure' in n
assert 'proxy_set_header X-Forwarded-Proto $woow_origin_proto;' in n
# The old unconditional guard must be gone, not merely bypassed.
assert '%%PUBLIC_HOST_GUARD%%' not in n
assert 'location ^~ /web/database/ { return 404; }' not in n

m=(root/'rootfs/usr/local/bin/odoo-maintenance-bootstrap').read_text()
assert 'web.base.url.freeze' in m
assert 'bootstrap-user.json' in m
assert 'base.group_system' in m
assert 'base.group_erp_manager' in m
assert "root:600" in m
assert 'must contain at least 20 characters' in m

pg=(root/'rootfs/etc/cont-init.d/00-postgres-init.sh').read_text()
assert 'local   all       all                  peer' in pg
assert '--auth-local=peer' in pg
assert '51856b0abbce68848b2b024a00191cac5eeead3f' in d
assert 'odoo-jsonrpc-filter' in d
assert 'while(q.indexOf(P+P)===0)' in n
assert 'absolute_redirect off;' in n
assert '(?<odoo_redirect>/.*)' in n
assert 'window.SharedWorker=function' in n
assert 'Object.defineProperty(navigator.serviceWorker,"controller"' in n
assert "sub_filter '&#39;/web/login&#39;'" in n
assert "sub_filter '<head>'" in n
assert 'u instanceof URL' in n
assert 'location ^~ /web/assets/' in n
assert 'translationURL' in n
assert 'browser.location.origin+"$safe_ingress_path"+router.stateToUrl' in n
assert 'params.serverURL}$safe_ingress_path/bus/websocket_worker_bundle' in n
assert 'serverURL.replace("http", "ws")}$safe_ingress_path/websocket' in n
assert 'serverURL:window.origin+"$safe_ingress_path"' not in n
assert 'odoo:websocket_shared_worker_%%INGRESS_CACHE_VERSION%%' in n
assert 'websocket_worker_bundle?woow_ingress=%%INGRESS_CACHE_VERSION%%&v=' in n
assert '%%INGRESS_CACHE_VERSION%%' in n
assert 'Cache-Control "no-store, no-cache, must-revalidate"' in n
assert 'navigator.serviceWorker.getRegistrations' in n
assert 'r.scope.indexOf("/odoo")' in n
assert 'woow-odoo-sw-clean-%%INGRESS_CACHE_VERSION%%' in n
assert "sub_filter '\"src\": \"/'" in n
assert "sub_filter '\"/my/'" in n
assert "sub_filter '\"/calendar/'" in n
assert "sub_filter '\"/base_setup/'" in n
assert "sub_filter '\"icon\":\"/'" in n
assert "sub_filter '\"imgurl\":\"/'" in n
assert '.settings_tab a.tab' not in n
assert 'if(u.charAt(0)==="#")return u' in n
assert "href^='#'" not in n
assert 'HTMLImageElement.prototype,"srcset"' in n
assert 'return 302 $safe_ingress_path/odoo' not in n
assert n.count('proxy_set_header X-Forwarded-Proto $ingress_proto;') >= 3
assert 'proxy_set_header Origin $ingress_proto://$http_host;' in n
assert 'map $ingress_proto $ingress_cookie_secure' in n
assert 'proxy_cookie_flags session_id $ingress_cookie_secure' in n
assert 'proxy_hide_header X-Frame-Options;' in n
assert (root/'tests/e2e_adversarial.py').is_file()
assert 'location = /xmlrpc/2/db' in n
# %%PUBLIC_HOST_GUARD%% was a single unconditional guard on the whole
# listener. It is replaced by the source-address gate, which has to
# distinguish LAN from tunnel rather than allow or refuse everyone.
assert '%%DENY_STATUS%%' in n
assert '%%PUBLIC_HOST_MAP%%' in n
assert '%%PUBLIC_PROTO%%' in n
assert 'window.WebSocket.OPEN=W.OPEN' in n
assert '$request_method $uri $server_protocol' in n
assert '$http_referer' not in n
assert '$sent_http_x_frame_options' in n
assert '$upstream_http_x_frame_options' in n
# The RPC policy filter is no longer a fixed upstream: it stays the default
# target and only the LAN tier is routed past it.
assert 'proxy_pass http://$woow_jsonrpc_upstream;' in n
PY
if ! command -v node >/dev/null 2>&1; then
    printf '%s\n' 'node is required for ingress gateway contract tests' >&2
    exit 1
fi
shim="$(mktemp --suffix=.js)"
nginx_test_dir="$(mktemp -d)"
trap 'rm -f "${shim}"; rm -rf "${nginx_test_dir}"' EXIT
python3 - "${ADDON}/rootfs/etc/nginx/nginx.conf.template" "${shim}" <<'PY'
import re, sys
source=open(sys.argv[1], encoding='utf-8').read()
map_start=source.index('map $upstream_http_content_type $ingress_runtime_shim {')
map_end=source.index('\n    }', map_start)
runtime_shim=source[map_start:map_end]
assert '"~*^text/html(?:;|$)"' in runtime_shim, 'runtime shim must be limited to HTML upstream responses'
match=re.search(r"<script>(.*?)</script>';", runtime_shim, re.S)
assert match, 'HTML runtime shim not found'
open(sys.argv[2], 'w', encoding='utf-8').write(match.group(1).replace('$safe_ingress_path','/P').replace('%%INGRESS_CACHE_VERSION%%','V'))
PY
node --check "${shim}"
python3 "${ADDON}/tests/test-ingress-router-rewrite.py"
python3 "${ADDON}/tests/test-ingress-content-type-filter.py"
python3 "${ADDON}/tests/test-settings-icon-rewrite.py"
python3 "${ADDON}/tests/e2e_settings_controls.py" --self-test

if ! command -v nginx >/dev/null 2>&1; then
    printf '%s\n' 'nginx is required for rendered gateway configuration tests' >&2
    exit 1
fi
# Both render paths have to be valid nginx: with public_url configured, and
# without it -- which is what an add-on serving only the LAN actually runs.
python3 - "${ADDON}/rootfs/etc/nginx/nginx.conf.template" "${nginx_test_dir}" <<'RENDER'
from pathlib import Path
import sys
source, test_dir = map(Path, sys.argv[1:])
template = source.read_text(encoding="utf-8")

common = {
    "%%WS_PORT%%": "8070",
    "%%PUBLIC_PROTO%%": "https",
    "%%LAN_NETWORKS%%": "192.168.0.0/16 1; 10.0.0.0/8 1; 172.16.0.0/12 1;",
    "%%INGRESS_CACHE_VERSION%%": "test",
}
scenarios = {
    "public": dict(common, **{
        "%%PUBLIC_HOST_MAP%%": '"odoo-test.invalid" 1; "odoo-test.invalid:443" 1;',
        "%%DENY_STATUS%%": "444"}),
    # public_url unset: the host map is empty, so no Host reaches the public
    # tier and every off-LAN caller falls through to the deny status.
    "lanonly": dict(common, **{"%%PUBLIC_HOST_MAP%%": "", "%%DENY_STATUS%%": "503"}),
}

for name, replacements in scenarios.items():
    config = template
    for placeholder, value in replacements.items():
        assert placeholder in template, f"missing template placeholder: {placeholder}"
        config = config.replace(placeholder, value)
    assert "%%" not in config, f"unrendered placeholder remains in {name}"
    config = config.replace("pid /var/run/nginx.pid;", f"pid {test_dir}/{name}.pid;")
    config = config.replace("error_log /dev/stderr info;", f"error_log {test_dir}/{name}-error.log info;")
    config = config.replace("access_log /dev/stdout safe;", f"access_log {test_dir}/{name}-access.log safe;")

    # nginx -t opens listener sockets. Use paths inside this unique temporary
    # directory rather than probing and releasing TCP ports, which has a
    # TOCTOU race with other processes.
    public_socket = test_dir / f"{name}-public.sock"
    websocket_socket = test_dir / f"{name}-ws.sock"
    ingress_socket = test_dir / f"{name}-ingress.sock"
    for socket_path in (public_socket, websocket_socket, ingress_socket):
        assert not socket_path.exists(), f"unexpected pre-existing socket: {socket_path}"
    for original, replacement in [
        ("listen 8069 default_server;", f"listen unix:{public_socket} default_server;"),
        ("listen 8072 default_server;", f"listen unix:{websocket_socket} default_server;"),
        ("listen 5691;", f"listen unix:{ingress_socket};"),
    ]:
        assert config.count(original) == 1, f"expected one listener to replace: {original}"
        config = config.replace(original, replacement)
    (test_dir / f"nginx-{name}.conf").write_text(config, encoding="utf-8")
RENDER
for scenario in public lanonly; do
    nginx -t -p "${nginx_test_dir}" -c "${nginx_test_dir}/nginx-${scenario}.conf"
done
printf '%s\n' 'dual gateway tests passed'
