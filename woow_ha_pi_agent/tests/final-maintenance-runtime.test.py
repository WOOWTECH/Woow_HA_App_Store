"""Pure verifier fixtures and CI source contract; never builds/runs an image."""
import importlib.util
import json
import marshal
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('owned_final_verifier', ROOT / 'tests/verify-final-maintenance.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class FinalReadbackTests(unittest.TestCase):
    source = b'"fixture docstring"\nVALUE = 7\ndef fixture():\n    assert VALUE\n    return VALUE\n'
    filename = '/owned/fixture.py'

    def blob(self, optimization=0, source=None, filename=None):
        source = self.source if source is None else source
        filename = self.filename if filename is None else filename
        return (importlib.util.MAGIC_NUMBER + (3).to_bytes(4, 'little') +
                importlib.util.source_hash(self.source) +
                marshal.dumps(compile(source, filename, 'exec', dont_inherit=True, optimize=optimization)))

    def validate(self, blob, optimization=0):
        return verifier.verify_pyc(blob, self.source, self.filename, optimization)

    def test_all_three_checked_hash_code_variants(self):
        for optimization in (0, 1, 2):
            result = self.validate(self.blob(optimization), optimization)
            self.assertTrue(result['marshalMatchesCompiledSource'])
            self.assertEqual(result['flags'], 3)

    def test_wrong_magic_flags_or_source_hash_fail(self):
        original = self.blob()
        for altered in [b'xxxx' + original[4:], original[:4] + (1).to_bytes(4, 'little') + original[8:],
                        original[:8] + b'xxxxxxxx' + original[16:]]:
            with self.assertRaises(RuntimeError):
                self.validate(altered)

    def test_wrong_marshal_code_or_optimization_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'code_differs'):
            self.validate(self.blob(source=self.source.replace(b'7', b'8')))
        with self.assertRaisesRegex(RuntimeError, 'code_differs'):
            self.validate(self.blob(2), 0)

    def test_foreign_filename_and_trailing_payload_fail(self):
        with self.assertRaises(RuntimeError):
            self.validate(self.blob(filename='/foreign/fixture.py'))
        with self.assertRaisesRegex(RuntimeError, 'marshal_boundary'):
            self.validate(self.blob() + b'extra')

    def test_runtime_requires_exact_python_native_arch_and_uid(self):
        for arch, machine in [('amd64', 'x86_64'), ('aarch64', 'aarch64')]:
            verifier.runtime_identity((3, 12, 12), machine, 1000, 1000, arch)
        for version, machine, uid, gid, arch in [((3, 12, 14), 'x86_64', 1000, 1000, 'amd64'),
                ((3, 12, 12), 'aarch64', 1000, 1000, 'amd64'),
                ((3, 12, 12), 'x86_64', 0, 0, 'amd64')]:
            with self.assertRaises(RuntimeError):
                verifier.runtime_identity(version, machine, uid, gid, arch)

    def mounts(self):
        return {'/': {'options': ['ro'], 'type': 'overlay'},
                '/ha-final-verification': {'options': ['ro'], 'type': 'ext4'},
                '/tmp': {'options': ['rw', 'nosuid', 'nodev', 'noexec'], 'type': 'tmpfs'}}

    def test_sandbox_requires_root_and_payload_ro_tmpfs_networknone(self):
        verifier.sandbox_identity(self.mounts(), ['lo'], '00000000', '1')
        altered = self.mounts(); altered['/']['options'] = ['rw']
        with self.assertRaises(RuntimeError): verifier.sandbox_identity(altered, ['lo'], '0', '1')
        altered = self.mounts(); altered['/ha-final-verification']['options'] = ['rw']
        with self.assertRaises(RuntimeError): verifier.sandbox_identity(altered, ['lo'], '0', '1')
        with self.assertRaises(RuntimeError): verifier.sandbox_identity(self.mounts(), ['lo', 'eth0'], '0', '1')
        with self.assertRaises(RuntimeError): verifier.sandbox_identity(self.mounts(), ['lo'], '1', '1')
        with self.assertRaises(RuntimeError): verifier.sandbox_identity(self.mounts(), ['lo'], '0', '0')

    def test_file_links_oversize_and_image_identity_fail(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'fixture'
            path.write_bytes(b'owned fixture')
            self.assertEqual(verifier.plain_file(path, 100)[0], b'owned fixture')
            with self.assertRaises(RuntimeError): verifier.plain_file(path, 1)
            path.chmod(0o600)
            with self.assertRaises(RuntimeError): verifier.plain_file(path, 100, image=True)
            link = Path(d) / 'link'; link.symlink_to(path)
            with self.assertRaises(RuntimeError): verifier.plain_file(link, 100)

    def result(self, **changes):
        result = SimpleNamespace(testsRun=57, wasSuccessful=lambda: True, failures=[], errors=[],
            skipped=[(SimpleNamespace(id=lambda: verifier.EXPECTED_SKIP),
                      'full 43-source audit is available in review workspace only')])
        for key, value in changes.items(): setattr(result, key, value)
        return result

    def test_only_exact_57_suite_and_one_known_skip_accept(self):
        self.assertEqual(verifier.suite_result(self.result())['pass'], 56)
        for changed in [self.result(testsRun=56), self.result(wasSuccessful=lambda: False),
                        self.result(skipped=[]), self.result(skipped=[(SimpleNamespace(id=lambda: 'other'), '43')])]:
            with self.assertRaises(RuntimeError): verifier.suite_result(changed)

    def test_workflow_loads_both_and_final_gate_blocks_artifacts(self):
        text = (ROOT / '.github/workflows/build.yml').read_text()
        self.assertIn("load: ${{ github.event_name == 'pull_request' }}", text)
        free = text.split('- name: Free disk space', 1)[1].split('- name: Set up Buildx', 1)[0]
        self.assertNotIn('matrix.arch ==', free)
        self.assertIn('20 * 1024 * 1024 * 1024', free)
        final = text.split('- name: Verify final installed maintenance on the native image', 1)[1].split('# The SBOM', 1)[0]
        self.assertNotIn('continue-on-error', final)
        self.assertNotIn('matrix.arch ==', final)
        self.assertIn('ha-final-image-maintenance-${{ matrix.arch }}', final)
        self.assertLess(text.index('- name: Verify final installed maintenance'), text.index('- name: SBOM for'))
        self.assertIn('python3 -B tests/final-maintenance-runtime.test.py', text)

    def test_host_command_is_bounded_native_final_image_not_sdk_entrypoint(self):
        source = (ROOT / 'tests/verify-final-maintenance.sh').read_text()
        for literal in ['--network none', '--read-only', '--user 1000:1000', '--cap-drop ALL',
                        '--security-opt no-new-privileges', '--tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m',
                        'target=/ha-final-verification,readonly', '"$image_id" -I -B', 'timeout 300s']:
            self.assertIn(literal, source)
        result = subprocess.run(['bash', '-n', str(ROOT / 'tests/verify-final-maintenance.sh')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class BuildImageBindingShellTests(unittest.TestCase):
    """Controlled argv fixture only: the Docker replacement runs no image."""
    config_id = 'sha256:' + 'a' * 64
    manifest_digest = 'sha256:' + 'c' * 64

    def test_python_binding_defense_rejects_missing_invalid_or_mismatched_config(self):
        verifier.image_identity(self.config_id, self.config_id, 'd' * 40)
        for action_id in ['', 'sha256:' + 'A' * 64, 'sha256:' + 'b' * 64]:
            with self.subTest(action_id=action_id), self.assertRaises(RuntimeError):
                verifier.image_identity(self.config_id, action_id, 'd' * 40)

    def wrapper(self, action_id):
        with tempfile.TemporaryDirectory(prefix='ha-build-binding-fixture-') as owned:
            base = Path(owned)
            bin_dir = base / 'bin'
            bin_dir.mkdir()
            calls = base / 'docker-calls.jsonl'
            docker = bin_dir / 'docker'
            docker.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with Path(os.environ['OWNED_DOCKER_CALLS']).open('a') as log: log.write(json.dumps(args)+'\\n')
if args[:2]==['image','inspect']:
    fields={'{{.Id}}':'sha256:'+'a'*64,'{{.Architecture}}':'amd64','{{.Os}}':'linux','{{.Size}}':'1024'}
    print(fields[args[3]])
elif args[0]=='run':
    print(json.dumps({'success':True,'fixtureOnly':True,
        'imageId':args[args.index('--image-id')+1],
        'buildActionImageId':args[args.index('--build-action-image-id')+1],
        'buildActionDigest':args[args.index('--build-action-digest')+1]}))
else: raise SystemExit(2)
''')
            docker.chmod(0o755)
            df = bin_dir / 'df'
            df.write_text('#!/bin/sh\nprintf "Avail\\n100000000000\\n"\n')
            df.chmod(0o755)
            context = base / 'context'
            for name, raw in [('patches/omnigent-native-maintenance-patch/owned.txt', b'fixture only'),
                              ('cli-runtime/versions.json', b'{}'),
                              ('tests/verify-final-maintenance.py', b'# fixture payload; never executed\n')]:
                path = context / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            runner_temp = base / 'runner-temp'
            runner_temp.mkdir()
            env = {'PATH': str(bin_dir) + ':/usr/bin:/bin', 'RUNNER_TEMP': str(runner_temp),
                   'OWNED_DOCKER_CALLS': str(calls)}
            result = subprocess.run(['bash', str(ROOT / 'tests/verify-final-maintenance.sh'), str(context),
                                     'amd64', 'owned-fixture:image', action_id, self.manifest_digest, 'd' * 40],
                                    env=env, text=True, capture_output=True, timeout=10)
            seen = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            receipt = json.loads((runner_temp / 'ha-final-image-maintenance-amd64.json').read_text())
            return result, seen, receipt

    def refused_before_run(self, action_id):
        result, calls, receipt = self.wrapper(action_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] == 'run' for call in calls), calls)
        self.assertIs(receipt['success'], False)

    def test_missing_action_config_refuses_before_docker_run(self):
        self.refused_before_run('')

    def test_malformed_action_config_refuses_before_docker_run(self):
        for action_id in ['sha256:' + 'A' * 64, 'sha256:' + 'a' * 63, 'sha512:' + 'a' * 64,
                          self.config_id + '\n']:
            with self.subTest(action_id=action_id):
                self.refused_before_run(action_id)

    def test_mismatched_action_config_refuses_before_docker_run(self):
        self.refused_before_run('sha256:' + 'b' * 64)

    def test_matching_config_proceeds_with_distinct_manifest_digest(self):
        result, calls, receipt = self.wrapper(self.config_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [call for call in calls if call[0] == 'run']
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][runs[0].index('--entrypoint') + 2], self.config_id)
        self.assertEqual(receipt['loadedImageId'], self.config_id)
        self.assertEqual(receipt['buildActionImageId'], self.config_id)
        self.assertEqual(receipt['buildActionDigest'], self.manifest_digest)
        self.assertNotEqual(receipt['buildActionDigest'], receipt['loadedImageId'])
        self.assertIs(receipt['fixtureOnly'], True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
