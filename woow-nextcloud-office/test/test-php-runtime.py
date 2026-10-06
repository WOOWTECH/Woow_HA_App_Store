"""PHP8.4 packaging contract + real shell flow with temp paths/stub services.
No PHP/nginx/CODE/DB daemon runs. This is not image or HAOS acceptance.
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SERVICES = BASE / 'rootfs/etc/s6-overlay/s6-rc.d'


class PhpRuntimeTests(unittest.TestCase):
    def test_official_trixie_packages_preserve_pg16_and_nc33(self):
        docker = (BASE / 'Dockerfile').read_text()
        self.assertIn('FROM debian:trixie-slim', docker)
        self.assertIn('https://apt.postgresql.org/pub/repos/apt trixie-pgdg main', docker)
        self.assertIn('postgresql-16 postgresql-client-16', docker)
        # Still the Nextcloud 33 series here (patch releases allowed); majors are released one at a time.
        self.assertRegex(docker, r'ARG NEXTCLOUD_VERSION=33\.\d+\.\d+\n')
        expected = {f'php8.4-{suffix}' for suffix in (
            'fpm', 'cli', 'common', 'pgsql', 'curl', 'gd', 'intl', 'mbstring',
            'xml', 'zip', 'bcmath', 'gmp', 'imagick', 'redis', 'apcu', 'bz2',
        )}
        self.assertEqual(set(re.findall(r'\bphp8\.\d+-[a-z0-9]+', docker)), expected)
        self.assertNotIn('sury', docker.lower())
        self.assertIn('libsmbclient0', docker)

    def test_ini_settings_target_both_php84_sapis(self):
        docker = (BASE / 'Dockerfile').read_text()
        for sapi in ('cli', 'fpm'):
            lines = [line for line in docker.splitlines()
                     if f'> /etc/php/8.4/{sapi}/conf.d/99-woow-nextcloud-office.ini' in line]
            self.assertEqual(len(lines), 1, sapi)
            for setting in ('memory_limit=1024M', 'upload_max_filesize=16G', 'post_max_size=16G'):
                self.assertIn(setting, lines[0])
            self.assertIn('apc.enable_cli=1' if sapi == 'cli' else 'opcache.enable=1', lines[0])

    def test_no_stale_php82_runtime_paths(self):
        paths = [BASE / 'Dockerfile', *[p for p in (BASE / 'rootfs').rglob('*') if p.is_file()]]
        for path in paths:
            with self.subTest(path=path.relative_to(BASE)):
                self.assertNotRegex(path.read_text(), r'php(?:-fpm)?8\.2|/etc/php/8\.2/')

    def run_service(self, service, enabled=True):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / 'bin'
            bindir.mkdir()
            log = root / 'calls'
            # Block the old binary explicitly, even if installed on the test host.
            stubs = {
                'php-fpm8.2': 'exit 127',
                'php-fpm8.4': 'printf "fpm:%s\\n" "$*" >> "$CALL_LOG"',
                'nginx': 'printf "nginx:%s\\n" "$*" >> "$CALL_LOG"',
                'php': 'exit 0', 'curl': 'exit 0', 'occ': 'exit 0',
            }
            for name, body in stubs.items():
                path = bindir / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o700)
            envdir = root / 'run/woow-office'
            envdir.mkdir(parents=True)
            (envdir / 'env').write_text('\n'.join([
                f'ENABLE_COLLABORA={str(enabled).lower()}',
                'PUBLIC_URL=https://cloud.example.invalid',
                'HA_PUBLIC_URL=https://ha.example.invalid',
                'COLLABORA_ADMIN_USER=synthetic', 'COLLABORA_ADMIN_PASS=synthetic', '',
            ]))
            phpdir = root / 'run/php'
            phpdir.mkdir()
            (phpdir / 'php8.4-fpm.pid').write_text('424242\n')
            text = (SERVICES / service / 'run').read_text()
            for prefix in ('/run', '/etc/nginx', '/var/lib/nginx', '/var/www'):
                text = text.replace(prefix, str(root) + prefix)
            # Stub the shell builtin: never signal a real PID, even on a regression.
            text = ('kill() { printf "kill:%s\\n" "$*" >> "$CALL_LOG"; };\n'
                    'sleep() { :; };\n' + text)
            script = root / 'service.sh'
            script.write_text(text)
            result = subprocess.run(
                ['/bin/bash', str(script)], capture_output=True, text=True, timeout=10,
                env=dict(os.environ, PATH=str(bindir) + ':/usr/bin:/bin', CALL_LOG=str(log)),
            )
            nginx = root / 'etc/nginx/conf.d/nextcloud-office.conf'
            return (result, log.read_text().splitlines() if log.exists() else [],
                    nginx.read_text() if nginx.exists() else '', str(root))

    def test_fpm_executes_php84_in_foreground(self):
        result, calls, _, _ = self.run_service('svc-php-fpm')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['fpm:-F'])

    def test_generated_nginx_uses_php84_socket(self):
        result, calls, config, root = self.run_service('init-nginx-config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['nginx:-t'])
        self.assertIn(f'fastcgi_pass unix:{root}/run/php/php8.4-fpm.sock;', config)
        self.assertNotIn('php8.2', config)

    def test_office_restart_uses_php84_pid(self):
        result, calls, _, _ = self.run_service('init-richdocuments-config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['kill:-TERM 424242'])

    def test_disabled_office_does_not_signal_fpm(self):
        result, calls, _, _ = self.run_service('init-richdocuments-config', enabled=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
