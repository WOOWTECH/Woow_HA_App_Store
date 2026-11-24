"""Per-boot work of init-nextcloud-config stays short (pipeline unattended-pipeline/229).

s6-overlay's stop waits for a start transition that is still running, so every second this
oneshot runs is a second in which a stop ends in SIGKILL (exit 137). On an N2840 it took about
3 minutes on every boot: a recursive chown of the Nextcloud tree, the add-on data and the data
directory, then about 20 occ calls (each one boots Nextcloud, about 1.3 s there).

- Ownership: only entries that are not www-data:www-data are changed. When everything is already
  owned correctly nothing is written (a chown of the image's tree makes overlayfs copy it up).
- System values: written to config.php in one pass by nextcloud-system-config.php, with the same
  result as the former `occ config:system:set` calls followed by the trusted_proxies/overwritehost
  edit.

The shell flow runs with stubbed services in a temp directory. The PHP tests need `php` on PATH
(the CI runner has it); without it they are skipped, except under CI where they fail.
"""
import grp
import json
import os
import pwd
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / 'rootfs/etc/s6-overlay/s6-rc.d/init-nextcloud-config/run'
SYSTEM_CONFIG = BASE / 'rootfs/usr/local/share/woow-office/nextcloud-system-config.php'
ME = pwd.getpwuid(os.getuid()).pw_name
MY_GROUP = grp.getgrgid(os.getgid()).gr_name


class ShellFlow(unittest.TestCase):
    def run_init(self, user, group):
        """Run the real run script; user:group replace www-data:www-data as the owner the tree must have."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / 'bin'
            bindir.mkdir()
            stubs = {
                'pg_isready': 'exit 0',
                'redis-cli': 'exit 0',
                'gosu': 'printf "1\\n"',
                'chown': 'printf "chown %s\\n" "$*" >> "$CALL_LOG"',
                # The interrupted-install check reads $CONFIG["installed"]; 1 = installed.
                'php': 'case "$2" in *installed*) exit 1;; esac\n'
                       'printf "php %s PUBLIC_HOST=%s PUBLIC_URL=%s DEFAULT_PHONE_REGION=%s DB_PASS=%s\\n" '
                       '"$*" "$PUBLIC_HOST" "$PUBLIC_URL" "$DEFAULT_PHONE_REGION" "$DB_PASS" >> "$CALL_LOG"',
                'occ': 'printf "occ %s\\n" "$*" >> "$CALL_LOG"',
            }
            for name, body in stubs.items():
                p = bindir / name
                p.write_text(f'#!/bin/sh\n{body}\nexit 0\n')
                p.chmod(0o700)
            envdir = root / 'run/woow-office'
            envdir.mkdir(parents=True)
            (envdir / 'env').write_text('\n'.join([
                'DB_PASS=synthetic-db-password', 'ADMIN_USER=synthetic-admin',
                'ADMIN_PASS=synthetic-initial-password',
                f'NEXTCLOUD_DATADIR={root}/share/nextcloud',
                'PUBLIC_HOST=cloud.example.invalid', 'PUBLIC_URL=https://cloud.example.invalid',
                'DEFAULT_PHONE_REGION=TW', '',
            ]))
            (root / 'var/www/nextcloud/apps/files').mkdir(parents=True)
            (root / 'var/www/nextcloud/index.php').write_text('')
            (root / 'share/nextcloud/admin/files').mkdir(parents=True)
            (root / 'share/nextcloud/admin/files/a.txt').write_text('a')
            config = root / 'data/nextcloud/config'
            config.mkdir(parents=True)
            (config / 'config.php').write_text('<?php $CONFIG=["installed"=>true];\n')
            text = SCRIPT.read_text()
            for prefix in ['/var/www', '/data', '/run', '/share']:
                text = text.replace(prefix, str(root) + prefix)
            # Only the ownership the tree must have is replaced; this user cannot create www-data files.
            text = text.replace('www-data:www-data', f'{user}:{group}')
            text = text.replace('-user www-data', f'-user {user}').replace('-group www-data', f'-group {group}')
            test_script = root / 'init.sh'
            test_script.write_text(text)
            log = root / 'calls'
            env = dict(os.environ, PATH=f'{bindir}:/usr/bin:/bin', CALL_LOG=str(log))
            result = subprocess.run(['/bin/bash', str(test_script)], env=env, capture_output=True, text=True, timeout=20)
            calls = log.read_text().splitlines() if log.exists() else []
            return result, [c.replace(str(root), '') for c in calls]

    def test_nothing_is_chowned_when_owners_are_already_right(self):
        result, calls = self.run_init(ME, MY_GROUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c for c in calls if c.startswith('chown')], [])

    def test_wrong_owners_are_still_fixed(self):
        # A restore can leave files with other owners; those are still changed, without following links.
        result, calls = self.run_init('root', 'root')
        self.assertEqual(result.returncode, 0, result.stderr)
        chowned = ' '.join(c for c in calls if c.startswith('chown'))
        self.assertIn('chown -h root:root', chowned)
        for path in ['/data/nextcloud/config/config.php', '/share/nextcloud/admin/files/a.txt',
                     '/var/www/nextcloud/apps/files', '/var/www/nextcloud/index.php']:
            self.assertIn(path, chowned)
        self.assertNotIn('chown -R', chowned)

    def test_system_values_are_written_in_one_pass(self):
        result, calls = self.run_init('root', 'root')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c for c in calls if c.startswith('occ config:system:set')], [])
        writes = [c for c in calls if 'nextcloud-system-config.php' in c]
        self.assertEqual(writes, [
            'php /usr/local/share/woow-office/nextcloud-system-config.php /data/nextcloud/config/config.php '
            'PUBLIC_HOST=cloud.example.invalid PUBLIC_URL=https://cloud.example.invalid '
            'DEFAULT_PHONE_REGION=TW DB_PASS=synthetic-db-password'])
        # Everything else occ did on a normal boot is unchanged.
        self.assertEqual([c for c in calls if c.startswith('occ')], [
            'occ upgrade --no-interaction',
            'occ config:app:set password_policy minLength --value 7',
            'occ app:disable firstrunwizard',
            'occ app:disable notify_push',
        ])


def find_php():
    php = shutil.which('php')
    if php is None and os.environ.get('CI'):
        raise AssertionError('php is required on the CI runner for test-init-config.py')
    return php


@unittest.skipIf(find_php() is None, 'php not on PATH')
class SystemConfigWriter(unittest.TestCase):
    ENV = {
        'PUBLIC_HOST': 'cloud.example.invalid', 'PUBLIC_URL': 'https://cloud.example.invalid',
        'DEFAULT_PHONE_REGION': 'TW', 'DB_PASS': 'new-db-password',
    }

    def write(self, config, extra=None, env=None):
        """Run the writer on config (a PHP array literal); return (config.php text, $CONFIG as JSON)."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            f = d / 'config.php'
            f.write_text(f'<?php\n$CONFIG = {config};\n')
            for name, text in (extra or {}).items():
                (d / name).write_text(f'<?php\n$CONFIG = {text};\n')
            result = subprocess.run(
                [find_php(), str(SYSTEM_CONFIG), str(f)], env=dict(os.environ, **(env or self.ENV)),
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = f.read_text()
            dump = subprocess.run(
                [find_php(), '-r', 'include $argv[1]; echo json_encode($CONFIG);', '--', str(f)],
                capture_output=True, text=True, timeout=20, check=True)
            return text, json.loads(dump.stdout)

    def test_fresh_install_gets_every_value_in_occ_order(self):
        # What maintenance:install leaves (shortened); apps.config.php is merged in, as occ does.
        text, c = self.write(
            "['instanceid' => 'oc1', 'trusted_domains' => [0 => 'localhost'], 'datadirectory' => '/share/nextcloud', "
            "'dbtype' => 'pgsql', 'version' => '35.0.1.2', 'overwrite.cli.url' => 'http://localhost', "
            "'dbpassword' => 'install-pw', 'installed' => true]",
            extra={'apps.config.php': "['apps_paths' => [['path' => '/var/www/nextcloud/apps', 'url' => '/apps', 'writable' => false]]]"})
        self.assertEqual(list(c), [
            'instanceid', 'trusted_domains', 'datadirectory', 'dbtype', 'version', 'overwrite.cli.url',
            'dbpassword', 'installed', 'apps_paths', 'overwriteprotocol', 'default_phone_region',
            'memcache.local', 'memcache.locking', 'redis', 'maintenance_window_start',
            'trusted_proxies', 'overwritehost'])
        self.assertEqual(c['trusted_domains'], ['cloud.example.invalid', 'localhost', '127.0.0.1', 'homeassistant'])
        self.assertEqual(c['overwrite.cli.url'], 'https://cloud.example.invalid')
        self.assertEqual(c['overwriteprotocol'], 'https')
        self.assertEqual(c['default_phone_region'], 'TW')
        self.assertEqual(c['dbpassword'], 'new-db-password')
        self.assertEqual(c['memcache.local'], '\\OC\\Memcache\\APCu')
        self.assertEqual(c['memcache.locking'], '\\OC\\Memcache\\Redis')
        self.assertEqual(c['redis'], {'host': '/run/redis/redis.sock', 'port': 0})
        self.assertEqual(c['maintenance_window_start'], 1)
        self.assertEqual(c['trusted_proxies'], ['127.0.0.1', '172.30.32.2'])
        self.assertEqual(c['overwritehost'], 'cloud.example.invalid')
        self.assertTrue(text.startswith("<?php\n$CONFIG = array (\n"), text[:40])
        self.assertIn("'port' => 0,", text)
        self.assertIn("'maintenance_window_start' => 1,", text)

    def test_other_values_are_kept(self):
        _, c = self.write(
            "['version' => '35.0.1.2', 'trusted_domains' => [0 => 'old.example', 4 => 'extra.example'], "
            "'redis' => ['host' => 'x', 'timeout' => 1.5], 'trusted_proxies' => ['10.0.0.1', '127.0.0.1'], "
            "'mail_smtphost' => 'smtp.example']")
        self.assertEqual(c['trusted_domains'], {'0': 'cloud.example.invalid', '4': 'extra.example', '1': 'localhost',
                                                '2': '127.0.0.1', '3': 'homeassistant'})
        self.assertEqual(c['redis'], {'host': '/run/redis/redis.sock', 'timeout': 1.5, 'port': 0})
        self.assertEqual(c['trusted_proxies'], ['10.0.0.1', '127.0.0.1', '172.30.32.2'])
        self.assertEqual(c['mail_smtphost'], 'smtp.example')

    def test_string_trusted_proxies_becomes_a_list(self):
        _, c = self.write("['version' => '1', 'trusted_proxies' => '10.0.0.1']")
        self.assertEqual(c['trusted_proxies'], ['10.0.0.1', '127.0.0.1', '172.30.32.2'])

    def test_values_already_set_leave_config_php_alone_apart_from_proxies(self):
        # occ writes nothing when no value changes, so the other config files are not merged in.
        own = ("['version' => '1', 'trusted_domains' => [0 => 'cloud.example.invalid', 1 => 'localhost', 2 => '127.0.0.1', "
               "3 => 'homeassistant'], 'overwrite.cli.url' => 'https://cloud.example.invalid', 'overwriteprotocol' => 'https', "
               "'default_phone_region' => 'TW', 'dbpassword' => 'new-db-password', "
               "'memcache.local' => '\\\\OC\\\\Memcache\\\\APCu', 'memcache.locking' => '\\\\OC\\\\Memcache\\\\Redis', "
               "'redis' => ['host' => '/run/redis/redis.sock', 'port' => 0], 'maintenance_window_start' => 1]")
        _, c = self.write(own, extra={'apps.config.php': "['apps_paths' => []]"})
        self.assertNotIn('apps_paths', c)
        self.assertEqual(c['trusted_proxies'], ['127.0.0.1', '172.30.32.2'])
        # One changed value: occ writes the merged values, so they end up in config.php.
        _, c = self.write(own, extra={'apps.config.php': "['apps_paths' => []]"}, env=dict(self.ENV, DB_PASS='other'))
        self.assertEqual(c['apps_paths'], [])
        self.assertEqual(c['dbpassword'], 'other')

    def test_types_match_occ(self):
        # occ without --type stores strings; port and maintenance_window_start are --type integer.
        _, c = self.write("['version' => '1', 'redis' => ['port' => '0'], 'maintenance_window_start' => '1']",
                          env=dict(self.ENV, DEFAULT_PHONE_REGION=''))
        self.assertEqual(c['redis']['port'], 0)
        self.assertEqual(c['maintenance_window_start'], 1)
        self.assertEqual(c['default_phone_region'], '')


if __name__ == '__main__':
    unittest.main()
