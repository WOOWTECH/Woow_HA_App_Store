"""s6 startup must not wait for the richdocuments (Office) configuration (pipeline unattended-pipeline/224).

s6-overlay's stop waits for a start transition that is still running, so a slow oneshot in the
`user` bundle makes every stop during it end in SIGKILL (exit 137). The richdocuments
configuration waits for coolwsd and runs a dozen occ calls, so it runs as a longrun: s6 startup
finishes as soon as it is spawned. A longrun that exits is restarted by s6-supervise, so its run
script must stay up (exec sleep infinity) on every path, including when the configuration fails.
The docker counterpart is test-s6-stop.sh.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RC = BASE / 'rootfs/etc/s6-overlay/s6-rc.d'
SVC = 'svc-richdocuments-config'
RUN = RC / SVC / 'run'


class Layout(unittest.TestCase):
    def test_richdocuments_configuration_is_a_longrun_in_the_user_bundle(self):
        self.assertEqual((RC / SVC / 'type').read_text().strip(), 'longrun')
        self.assertTrue((RC / 'user/contents.d' / SVC).exists())
        deps = sorted(p.name for p in (RC / SVC / 'dependencies.d').iterdir())
        self.assertEqual(deps, ['svc-coolwsd', 'svc-nginx'])

    def test_no_oneshot_configures_richdocuments(self):
        self.assertFalse((RC / 'init-richdocuments-config').exists())
        self.assertFalse((RC / 'user/contents.d/init-richdocuments-config').exists())
        for svc in RC.iterdir():
            if (svc / 'type').exists() and (svc / 'type').read_text().strip() == 'oneshot':
                self.assertNotIn('richdocuments', (svc / 'run').read_text(), svc.name)

    def test_nothing_waits_for_the_richdocuments_configuration(self):
        for dep in RC.glob('*/dependencies.d/*'):
            self.assertNotIn('richdocuments', dep.name, str(dep))


class RunScript(unittest.TestCase):
    """Run the real run script with stubbed commands in a temp directory."""

    def run_service(self, enable_collabora, config_exit=0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / 'bin'
            bindir.mkdir()
            log = root / 'calls'
            stubs = {
                'woow-richdocuments-config': f'echo config >> "$CALL_LOG"; exit {config_exit}',
                'sleep': 'echo "sleep $*" >> "$CALL_LOG"; exit 0',
            }
            for name, body in stubs.items():
                p = bindir / name
                p.write_text(f'#!/bin/sh\n{body}\n')
                p.chmod(0o700)
            (root / 'env').write_text(f"ENABLE_COLLABORA='{enable_collabora}'\n")
            script = root / 'run'
            script.write_text(RUN.read_text().replace('/run/woow-office/env', str(root / 'env')))
            env = dict(os.environ, PATH=f'{bindir}:/usr/bin:/bin', CALL_LOG=str(log))
            result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True, timeout=10)
            return result, log.read_text().splitlines() if log.exists() else []

    def test_configures_then_stays_up(self):
        result, calls = self.run_service('true')
        self.assertEqual(calls, ['config', 'sleep infinity'], result.stderr)

    def test_stays_up_when_the_configuration_fails(self):
        result, calls = self.run_service('true', config_exit=3)
        self.assertEqual(calls, ['config', 'sleep infinity'], result.stderr)
        self.assertNotIn('ERROR', result.stderr)

    def test_collabora_disabled_skips_configuration_and_stays_up(self):
        result, calls = self.run_service('false')
        self.assertEqual(calls, ['sleep infinity'], result.stderr)


if __name__ == '__main__':
    unittest.main()
