"""Run the real init shell control flow in a temp filesystem with stubbed services.
No live occ/database, host /data, or account is accessed. Not an image/HAOS test.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / 'rootfs/etc/s6-overlay/s6-rc.d/init-nextcloud-config/run'


class UpgradeGuardTests(unittest.TestCase):
    def run_init(self, existing=True, upgrade_exit=0, installed_check_exit=1):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / 'bin'
            bindir.mkdir()
            for command in ['pg_isready', 'redis-cli', 'chown']:
                p = bindir / command
                p.write_text('#!/bin/sh\nexit 0\n')
                p.chmod(0o700)
            # The interrupted-install check is the php call that reads $CONFIG["installed"];
            # INSTALLED_CHECK_EXIT is its result (0: config.php parses and is not installed).
            p = bindir / 'php'
            p.write_text('#!/bin/sh\ncase "$2" in *installed*) exit "$INSTALLED_CHECK_EXIT";; esac\n'
                         'case "$1" in *nextcloud-system-config.php) printf "system-config %s\\n" "$2" >> "$CALL_LOG";; esac\nexit 0\n')
            p.chmod(0o700)
            p = bindir / 'gosu'
            p.write_text('#!/bin/sh\nprintf "gosu %s\\n" "$*" >> "$CALL_LOG"\nprintf "1\\n"\n')
            p.chmod(0o700)
            p = bindir / 'occ'
            p.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\nif [ "$1" = upgrade ]; then exit "$UPGRADE_EXIT"; fi\nexit 0\n')
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
            (root / 'var/www/nextcloud').mkdir(parents=True)
            config = root / 'data/nextcloud/config'
            config.mkdir(parents=True)
            if existing:
                (config / 'config.php').write_text('<?php $CONFIG=["installed"=>true];\n')
            text = SCRIPT.read_text()
            for prefix in ['/var/www', '/data', '/run', '/share']:
                text = text.replace(prefix, str(root) + prefix)
            test_script = root / 'init.sh'
            test_script.write_text(text)
            log = root / 'calls'
            env = dict(os.environ, PATH=str(bindir) + ':/usr/bin:/bin', CALL_LOG=str(log), UPGRADE_EXIT=str(upgrade_exit),
                       INSTALLED_CHECK_EXIT=str(installed_check_exit))
            result = subprocess.run(['/bin/bash', str(test_script)], env=env, capture_output=True, text=True, timeout=10)
            calls = log.read_text().splitlines() if log.exists() else []
            self.config_left = (config / 'config.php').exists()
            self.config_path = str(config / 'config.php')
            # gosu calls are logged for the drop check; the occ assertions look at occ only
            self.gosu_calls = [c for c in calls if c.startswith('gosu ')]
            return result, [c for c in calls if not c.startswith('gosu ')]

    def test_upgrade_failure_stops_before_config_mutation(self):
        result, calls = self.run_init(upgrade_exit=17)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(calls, ['upgrade --no-interaction'])

    def test_upgrade_does_not_reset_existing_password(self):
        result, calls = self.run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('user:resetpassword' in c for c in calls))

    def test_successful_upgrade_continues_configuration(self):
        result, calls = self.run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        # System values are one write of config.php (pipeline #229), then the remaining occ calls.
        self.assertEqual(calls[:2], ['upgrade --no-interaction', 'system-config ' + self.config_path])
        self.assertIn('config:app:set password_policy minLength --value 7', calls)

    def test_initial_install_still_sets_initial_password(self):
        result, calls = self.run_init(existing=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        install = next(c for c in calls if c.startswith('maintenance:install'))
        self.assertIn('--admin-pass synthetic-initial-password', install)
        self.assertFalse(any(c.startswith('upgrade ') for c in calls))

    def test_interrupted_install_is_discarded_and_installed_again(self):
        result, calls = self.run_init(installed_check_exit=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('did not finish last time', result.stdout)
        self.assertTrue(any('dropdb -h' in c and c.endswith(' nextcloud') for c in self.gosu_calls), self.gosu_calls)
        self.assertTrue(any(c.startswith('maintenance:install') for c in calls))
        self.assertFalse(any(c.startswith('upgrade ') for c in calls))

    def test_installed_instance_is_never_dropped(self):
        for check in (1, 2, 255):  # installed, include threw, parse error
            result, calls = self.run_init(installed_check_exit=check)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(any('dropdb' in c for c in self.gosu_calls))
            self.assertTrue(self.config_left)
            self.assertEqual(calls[0], 'upgrade --no-interaction')

    def test_no_config_does_not_run_the_check_or_drop(self):
        result, calls = self.run_init(existing=False, installed_check_exit=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('dropdb' in c for c in self.gosu_calls))
        self.assertNotIn('did not finish last time', result.stdout)


if __name__ == '__main__':
    unittest.main()
