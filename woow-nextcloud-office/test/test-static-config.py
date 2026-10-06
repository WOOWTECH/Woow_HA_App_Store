from pathlib import Path
import yaml
BASE = Path(__file__).resolve().parents[1]
config = yaml.safe_load((BASE / 'config.yaml').read_text())
assert config['slug'] == 'woow-nextcloud-office'
assert config['ingress'] is True
assert config['panel_admin'] is False
assert 'amd64' in config['arch']
# Prebuilt GHCR image, amd64 only until an aarch64 image (incl. CODE) is built and verified.
assert config['arch'] == ['amd64']
assert config['image'] == 'ghcr.io/woowtech/woow-ha-nextcloud-office-{arch}'
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
# Repository authenticity is an independent gate from successful package install.
dockerfile = (BASE / 'Dockerfile').read_text()
assert '[trusted=yes]' not in dockerfile
assert 'signed-by=/etc/apt/keyrings/collabora.gpg' in dockerfile
assert 'COLLABORA_KEYRING_SHA256' in dockerfile
assert 'sha256sum -c -' in dockerfile
# Nextcloud server archive: pinned SHA256 and signature by the pinned release key.
assert 'ARG NEXTCLOUD_SHA256=' in dockerfile and 'ARG NEXTCLOUD_KEY_FPR=28806A878AE423A28372792ED75899B9A724937A' in dockerfile
assert 'verify-nextcloud.sh /tmp/nextcloud.tar.bz2 /tmp/nextcloud.tar.bz2.asc' in dockerfile
assert dockerfile.index('verify-nextcloud.sh /tmp/nextcloud.tar.bz2') < dockerfile.index('tar -xjf /tmp/nextcloud.tar.bz2')
# App store apps (richdocuments) must live in the persistent custom_apps, not the image's apps/.
init_nc = (BASE / 'rootfs/etc/s6-overlay/s6-rc.d/init-nextcloud-config/run').read_text()
assert 'apps.config.php' in init_nc and "'writable' => true" in init_nc and '/var/www/nextcloud/custom_apps' in init_nc
assert init_nc.index('apps.config.php') < init_nc.index('occ maintenance:install') and init_nc.index('apps.config.php') < init_nc.index('occ upgrade')
# No unconditional re-download on every boot; update only when the enabled check fails.
assert 'occ app:install richdocuments || true' not in rich
assert 'occ app:update richdocuments' in rich and 'app:getpath richdocuments' in rich
# Version ARGs come after the OS package layer so a Nextcloud version bump keeps that cache.
assert dockerfile.index('ARG NEXTCLOUD_VERSION=') > dockerfile.index('apt-get install -y --no-install-recommends \\\n      nginx')
# HA backup/restore does not preserve file modes: every boot re-asserts the secret-bearing config modes.
assert 'chmod 0640' in init_nc and 'chmod 0750 /data/nextcloud/config' in init_nc and 'chmod 0770 "$NEXTCLOUD_DATADIR"' in init_nc
assert init_nc.rindex('chmod 0640') > init_nc.index('file_put_contents($f,$out)')
