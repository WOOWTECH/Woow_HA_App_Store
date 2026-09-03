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
assert c['ports']['8069/tcp'] is None
assert c['ports']['8072/tcp'] is None
assert not c.get('hassio_api', False)
assert all('backup' not in str(x) for x in c['map'])
assert c['schema']['public_url']=='url?'
assert 'public_url' not in c['options']

d=(root/'Dockerfile').read_text()
assert '18.0.20260806' in d
assert '60def7fca9f7005be9575f70f17e7db4e4e43190b36d0f34832fb0248beb6ba5' in d

s=(root/'rootfs/etc/cont-init.d/10-odoo-config.sh').read_text()
assert 'http_interface = 127.0.0.1' in s
assert 'http_port = 8070' in s
assert 'proxy_mode = True' in s

n=(root/'rootfs/etc/nginx/nginx.conf.template').read_text()
for text in ['listen 8069','listen 5691','server 127.0.0.1:%%WS_PORT%%','/web/database/','http_x_ingress_path','HTMLFormElement']:
    assert text in n, text

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
assert '%%PUBLIC_HOST_GUARD%%' in n
assert '%%PUBLIC_PROTO%%' in n
assert 'window.WebSocket.OPEN=W.OPEN' in n
assert '$request_method $uri $server_protocol' in n
assert '$http_referer' not in n
assert '$sent_http_x_frame_options' in n
assert '$upstream_http_x_frame_options' in n
assert 'proxy_pass http://127.0.0.1:8071' in n
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
match=re.search(r"sub_filter '<head>' '<head><script>(.*?)</script>';", source, re.S)
assert match, 'ingress shim not found'
open(sys.argv[2], 'w', encoding='utf-8').write(match.group(1).replace('$safe_ingress_path','/P').replace('%%INGRESS_CACHE_VERSION%%','V'))
PY
node --check "${shim}"
python3 "${ADDON}/tests/test-ingress-router-rewrite.py"

if ! command -v nginx >/dev/null 2>&1; then
    printf '%s\n' 'nginx is required for rendered gateway configuration tests' >&2
    exit 1
fi
rendered_nginx="${nginx_test_dir}/nginx.conf"
python3 - "${ADDON}/rootfs/etc/nginx/nginx.conf.template" "${rendered_nginx}" "${nginx_test_dir}" <<'PY'
from pathlib import Path
import sys
source, output, test_dir = map(Path, sys.argv[1:])
config = source.read_text(encoding='utf-8')
replacements = {
    '%%WS_PORT%%': '8070',
    '%%PUBLIC_PROTO%%': 'https',
    '%%PUBLIC_HOST_GUARD%%': 'if ($http_host != "odoo-test.invalid") { return 444; }',
    '%%INGRESS_CACHE_VERSION%%': 'test',
}
for placeholder, value in replacements.items():
    assert placeholder in config, f'missing template placeholder: {placeholder}'
    config = config.replace(placeholder, value)
assert '%%' not in config, 'unrendered nginx template placeholder remains'
config = config.replace('pid /var/run/nginx.pid;', f'pid {test_dir}/nginx.pid;')
config = config.replace('error_log /dev/stderr info;', f'error_log {test_dir}/error.log info;')
config = config.replace('access_log /dev/stdout safe;', f'access_log {test_dir}/access.log safe;')

# nginx -t opens listener sockets. Use paths within this unique temporary
# directory rather than probing and releasing TCP ports, which has a TOCTOU
# race with other processes.
public_socket = test_dir / 'public.sock'
ingress_socket = test_dir / 'ingress.sock'
for socket_path in (public_socket, ingress_socket):
    assert not socket_path.exists(), f'unexpected pre-existing socket: {socket_path}'
for original, replacement in [
    ('listen 8069 default_server;', f'listen unix:{public_socket} default_server;'),
    ('listen 5691;', f'listen unix:{ingress_socket};'),
]:
    assert config.count(original) == 1, f'expected one listener to replace: {original}'
    config = config.replace(original, replacement)
output.write_text(config, encoding='utf-8')
PY
nginx -t -p "${nginx_test_dir}" -c "${rendered_nginx}"
printf '%s\n' 'dual gateway tests passed'
