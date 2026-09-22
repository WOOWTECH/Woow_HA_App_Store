from pathlib import Path
import yaml
BASE = Path(__file__).resolve().parents[1]
config = yaml.safe_load((BASE / 'config.yaml').read_text())
assert config['slug'] == 'woow-nextcloud-office'
assert config['ingress'] is True
assert config['panel_admin'] is False
assert 'amd64' in config['arch']
assert 'aarch64' in config['arch']
assert config['backup'] == 'cold'
text = (BASE / 'rootfs/etc/s6-overlay/s6-rc.d/init-nginx-config/run').read_text()
for route in ['/hosting/', '/browser/', '/cool/']:
    assert route in text
assert 'X-Forwarded-For 127.0.0.1' in text
assert "frame-ancestors 'self'" in text
collabora = (BASE / 'rootfs/etc/s6-overlay/s6-rc.d/init-collabora-config/run').read_text()
assert 'storage.wopi.host' in collabora
assert 'coolconfig set ssl.termination true' in collabora
rich = (BASE / 'rootfs/etc/s6-overlay/s6-rc.d/init-richdocuments-config/run').read_text()
assert 'config:app:set --value "http://127.0.0.1:9980" richdocuments wopi_url' in rich
assert 'richdocuments:activate-config' in rich
