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
printf '%s\n' 'dual gateway tests passed'
