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
assert 'while(q.indexOf(P+P)===0)' in n
PY
printf '%s\n' 'dual gateway tests passed'
