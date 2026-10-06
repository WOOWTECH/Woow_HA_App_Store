"""Synthetic declarations only. No image, signature, collector or runtime proof."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
TOOL = BASE / 'qa/artifact_lock.py'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ArtifactLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='artifact-lock-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.doc = dict(schema_version=1, scope='isolated-synthetic',
                        evidence_kind='collected', architecture='amd64',
                        observation='observations', images={}, artifacts=[])
        # Deliberately fabricated caller assertions for this unit test. NEVER
        # export this as collected evidence or reuse the checked-in stub as such.
        self.bundle = json.loads((BASE / 'qa/fixtures/candidate-inventory.stub.json').read_text())
        self.bundle['evidence_kind'] = 'collected'
        for side in ('source', 'candidate'):
            raw = json.dumps(dict(schemaVersion=2,
                mediaType='application/vnd.oci.image.manifest.v1+json',
                config=dict(mediaType='application/vnd.oci.image.config.v1+json',
                            digest='sha256:' + sha(side.encode()), size=100), layers=[])).encode()
            artifact = self.add(side + '-manifest', 'image-manifest', raw)
            self.bundle[side + '_digest'] = 'sha256:' + artifact['sha256']
            package = self.add(side + '-package', 'package', (side + ' package bytes').encode(),
                               name='php8.4-fpm', version='8.4.24-1', architecture='amd64')
            self.doc['images'][side] = dict(
                digest=self.bundle[side + '_digest'], source_commit=sha(side.encode())[:40],
                architecture='amd64', manifest=artifact['id'], inputs=[package['id']],
                receipt=side + '-receipt')
        observation = self.add('observations', 'observation', json.dumps(self.bundle).encode())
        for side, image in self.doc['images'].items():
            receipt = dict(schema_version=1, verification_status='verified',
                           image_digest=image['digest'], source_commit=image['source_commit'],
                           architecture=image['architecture'], observation_sha256=observation['sha256'],
                           inputs=[dict(id=aid, sha256=self.artifact(aid)['sha256']) for aid in image['inputs']])
            self.add(side + '-receipt', 'provenance', json.dumps(receipt).encode())

    def add(self, aid, kind, raw, **extra):
        (self.root / aid).write_bytes(raw)
        artifact = dict(id=aid, kind=kind, path=aid, sha256=sha(raw), size_bytes=len(raw), **extra)
        self.doc['artifacts'].append(artifact)
        return artifact

    def artifact(self, aid):
        return next(a for a in self.doc['artifacts'] if a['id'] == aid)

    def replace(self, aid, raw):
        artifact = self.artifact(aid)
        (self.root / artifact['path']).write_bytes(raw)
        artifact.update(sha256=sha(raw), size_bytes=len(raw))

    def run_cli(self, raw=None, root=None, manifest='lock.json'):
        (self.root / 'lock.json').write_text(json.dumps(self.doc) if raw is None else raw)
        result = subprocess.run([sys.executable, str(TOOL), '--public-root', str(root or self.root),
                                 '--manifest', manifest], capture_output=True, text=True, timeout=5)
        return result

    def assert_report(self, result, code):
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'offline_lock_consistent' if code == 0 else 'blocked')
        for key in ('signed_source_verified', 'image_build_verified', 'provenance_authenticated',
                    'runtime_verified', 'haos_verified', 'production_authorized'):
            self.assertIs(report[key], False)
        return report

    def test_consistent_declarations_are_not_trust_or_runtime_verification(self):
        report = self.assert_report(self.run_cli(), 0)
        self.assertEqual(report['artifact_count'], 7)
        self.assertIn('signed_dependency_resolution_and_build', report['pending_gates'])

    def edit_receipt(self, side, change):
        aid = side + '-receipt'
        receipt = json.loads((self.root / aid).read_text())
        change(receipt)
        self.replace(aid, json.dumps(receipt).encode())

    def test_placeholder_commit_and_unresolved_version_are_blocked(self):
        commit = self.doc['images']['source']['source_commit']
        for value in ('a' * 40, '0123456789' * 4):
            self.doc['images']['source']['source_commit'] = value
            self.edit_receipt('source', lambda r: r.update(source_commit=value))
            self.assert_report(self.run_cli(), 1)
        self.doc['images']['source']['source_commit'] = commit
        self.edit_receipt('source', lambda r: r.update(source_commit=commit))
        for value in ('latest', 'unknown', 'fixture-1', 'stub-8.4', 'TBD'):
            self.artifact('source-package')['version'] = value
            self.assert_report(self.run_cli(), 1)

    def test_every_manifest_field_required_and_unknown_fields_block(self):
        original = copy.deepcopy(self.doc)
        paths = [(), ('images',), ('images', 'source'), ('images', 'candidate')]
        paths += [('artifacts', i) for i in range(len(original['artifacts']))]
        for path in paths:
            target = original
            for part in path:
                target = target[part]
            for key in list(target) + ['unrecognized']:
                self.doc = copy.deepcopy(original)
                row = self.doc
                for part in path:
                    row = row[part]
                if key == 'unrecognized':
                    row[key] = 'never execute'
                else:
                    del row[key]
                with self.subTest(path=path, key=key):
                    self.assert_report(self.run_cli(), 1)

    def test_wrong_types_do_not_crash_or_pass(self):
        original = copy.deepcopy(self.doc)
        paths = [(), ('images', 'source'), ('artifacts', 0), ('artifacts', 1)]
        for path in paths:
            target = original
            for part in path:
                target = target[part]
            for key, old in target.items():
                for value in (None, [], {}, True, 0, ''):
                    if type(old) is type(value) and old == value:
                        continue
                    self.doc = copy.deepcopy(original)
                    row = self.doc
                    for part in path:
                        row = row[part]
                    row[key] = value
                    with self.subTest(path=path, key=key, value=value):
                        self.assert_report(self.run_cli(), 1)

    def test_mutated_missing_empty_or_size_mismatched_file(self):
        path = self.root / 'source-package'
        original = path.read_bytes()
        path.write_bytes(original.replace(b'package', b'PACKAGE'))
        self.assert_report(self.run_cli(), 1)
        path.write_bytes(b'')
        self.assert_report(self.run_cli(), 1)
        path.unlink()
        self.assert_report(self.run_cli(), 1)
        path.write_bytes(original)
        self.artifact('source-package')['size_bytes'] += 1
        self.assert_report(self.run_cli(), 1)

    def test_duplicate_ids_paths_references_and_unreferenced_artifacts(self):
        original = copy.deepcopy(self.doc)
        self.doc['artifacts'].append(copy.deepcopy(self.doc['artifacts'][0]))
        self.assert_report(self.run_cli(), 1)
        self.doc = copy.deepcopy(original)
        self.artifact('source-package')['path'] = 'source-manifest'
        self.assert_report(self.run_cli(), 1)
        self.doc = copy.deepcopy(original)
        self.doc['images']['source']['inputs'] *= 2
        self.assert_report(self.run_cli(), 1)
        self.doc = copy.deepcopy(original)
        self.add('unused', 'archive', b'unreferenced', name='nextcloud', version='33.0.0', architecture='all')
        self.assert_report(self.run_cli(), 1)

    def test_wrong_kind_missing_and_empty_references(self):
        original = copy.deepcopy(self.doc)
        for key, value in (('manifest', 'source-package'), ('receipt', 'source-manifest'),
                           ('inputs', ['observations']), ('inputs', ['missing']), ('inputs', [])):
            self.doc = copy.deepcopy(original)
            self.doc['images']['source'][key] = value
            self.assert_report(self.run_cli(), 1)

    def test_architecture_and_image_binding_mismatches(self):
        original = copy.deepcopy(self.doc)
        self.doc['architecture'] = 'arm64'
        self.assert_report(self.run_cli(), 1)
        self.doc = copy.deepcopy(original)
        self.doc['images']['source']['architecture'] = 'arm64'
        self.assert_report(self.run_cli(), 1)
        self.doc = copy.deepcopy(original)
        self.artifact('source-package')['architecture'] = 'arm64'
        self.assert_report(self.run_cli(), 1)
        self.doc = copy.deepcopy(original)
        self.doc['images']['source']['digest'] = self.doc['images']['candidate']['digest']
        self.assert_report(self.run_cli(), 1)

    def test_receipt_all_fields_hashes_and_statuses_bound(self):
        path = self.root / 'source-receipt'
        original = path.read_bytes()
        receipt = json.loads(original)
        for key in receipt:
            changed = copy.deepcopy(receipt)
            del changed[key]
            self.replace('source-receipt', json.dumps(changed).encode())
            self.assert_report(self.run_cli(), 1)
        for key, value in (('verification_status', 'pending'), ('verification_status', True),
                           ('schema_version', True), ('image_digest', 'sha256:' + sha(b'other')),
                           ('source_commit', sha(b'other')[:40]), ('architecture', 'arm64'),
                           ('observation_sha256', sha(b'other')), ('inputs', []),
                           ('inputs', receipt['inputs'] * 2), ('extra', 1),
                           ('inputs', [dict(id='source-package', sha256=sha(b'other'))])):
            changed = copy.deepcopy(receipt)
            changed[key] = value
            self.replace('source-receipt', json.dumps(changed).encode())
            self.assert_report(self.run_cli(), 1)
        self.replace('source-receipt', original)
        self.assert_report(self.run_cli(), 0)

    def rebind_observation(self):
        self.replace('observations', json.dumps(self.bundle).encode())
        for side in ('source', 'candidate'):
            self.edit_receipt(side, lambda r: r.update(observation_sha256=self.artifact('observations')['sha256']))

    def test_observation_stub_mismatch_and_inventory_drift_block_even_when_rehashed(self):
        original = copy.deepcopy(self.bundle)
        for mutation in ('stub', 'digest', 'drift'):
            self.bundle = copy.deepcopy(original)
            if mutation == 'stub':
                self.bundle['evidence_kind'] = 'stub'
            elif mutation == 'digest':
                self.bundle['source_digest'] = self.bundle['candidate_digest']
            else:
                self.bundle['postgres']['candidate']['libc_version'] = '2.36'
            self.rebind_observation()
            self.assert_report(self.run_cli(), 1)

    def test_raw_manifest_not_archive_or_index(self):
        for raw in (b'not a JSON manifest archive', b'{}',
                    b'{"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","config":{},"layers":[]}'):
            self.replace('source-manifest', raw)
            value = 'sha256:' + sha(raw)
            self.doc['images']['source']['digest'] = value
            self.bundle['source_digest'] = value
            self.edit_receipt('source', lambda r: r.update(image_digest=value))
            self.rebind_observation()
            self.assert_report(self.run_cli(), 1)

    def test_bad_duplicate_nonfinite_deep_and_oversize_json(self):
        for raw in ('{', '[]', '{"schema_version":1,"schema_version":1}',
                    '{"x":NaN}', '{"x":1e999}', '[' * 2000 + ']' * 2000,
                    ' ' * (1024 * 1024 + 1)):
            self.assert_report(self.run_cli(raw=raw), 1)
        for aid in ('source-receipt', 'observations', 'source-manifest'):
            original = (self.root / aid).read_bytes()
            self.replace(aid, b'{"x":1,"x":2}')
            self.assert_report(self.run_cli(), 1)
            self.replace(aid, original)

    def test_absolute_traversal_hidden_and_sensitive_paths_rejected(self):
        for path in ('/etc/passwd', '../outside', 'a/../outside', './source-package',
                     '.private/key', 'nested/.ssh/key', 'gnupg/key', 'PGDATA/file',
                     'a//b', 'a\\b', 'a\nb'):
            self.artifact('source-package')['path'] = path
            self.assert_report(self.run_cli(), 1)
        for path in ('../lock.json', '/etc/passwd', '.private/lock.json'):
            self.assert_report(self.run_cli(manifest=path), 1)
        for root in ('/', '/etc', '/proc', '/dev', str(self.root / '.private')):
            self.assert_report(self.run_cli(root=root), 1)

    def test_symlink_file_directory_manifest_and_root_are_rejected(self):
        original = self.root / 'source-package'
        raw = original.read_bytes()
        target = self.root / 'target'
        target.write_bytes(raw)
        original.unlink()
        original.symlink_to(target)
        self.assert_report(self.run_cli(), 1)
        original.unlink()
        original.write_bytes(raw)
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        self.artifact('source-package')['path'] = 'alias/source-package'
        self.assert_report(self.run_cli(), 1)
        self.artifact('source-package')['path'] = 'source-package'
        self.assert_report(self.run_cli(root=self.root / 'alias'), 1)
        (self.root / 'linked-manifest').symlink_to(self.root / 'lock.json')
        self.assert_report(self.run_cli(manifest='linked-manifest'), 1)

    def test_fifo_directory_and_hardlink_do_not_hang_or_pass(self):
        path = self.root / 'source-package'
        raw = path.read_bytes()
        path.unlink()
        os.mkfifo(path)
        self.assert_report(self.run_cli(), 1)
        path.unlink()
        path.mkdir()
        self.assert_report(self.run_cli(), 1)
        path.rmdir()
        path.write_bytes(raw)
        os.link(path, self.root / 'hardlink')
        self.assert_report(self.run_cli(), 1)

    def test_file_and_artifact_count_limits(self):
        path = self.root / 'source-package'
        with path.open('wb') as stream:
            stream.truncate(128 * 1024 * 1024 + 1)
        self.artifact('source-package')['size_bytes'] = path.stat().st_size
        self.assert_report(self.run_cli(), 1)
        self.doc['artifacts'] *= 40
        self.assert_report(self.run_cli(), 1)

    def test_declared_total_budget_blocks_before_artifact_reads(self):
        for i in range(5):
            row = self.add('extra-' + str(i), 'archive', b'bytes', name='nextcloud',
                           version='33.0.0', architecture='all')
            row['size_bytes'] = 128 * 1024 * 1024
            self.doc['images']['source']['inputs'].append(row['id'])
        result = self.assert_report(self.run_cli(), 1)
        self.assertIn('Total read limit exceeded.', result['errors'])
        self.assertLess(result['bytes_read'], 1024 * 1024)

    def test_cli_does_not_write_import_bytecode(self):
        runner = self.root / 'runner'
        runner.mkdir()
        for name in ('artifact_lock.py', 'candidate_inventory.py'):
            (runner / name).write_bytes((BASE / 'qa' / name).read_bytes())
        self.run_cli()  # create the lock input
        env = dict(os.environ)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        result = subprocess.run([sys.executable, str(runner / 'artifact_lock.py'),
                                 '--public-root', str(self.root), '--manifest', 'lock.json'],
                                env=env, capture_output=True, text=True, timeout=5)
        self.assert_report(result, 0)
        self.assertFalse((runner / '__pycache__').exists())

    def test_verifier_has_no_execution_network_or_write_dependencies(self):
        tree = ast.parse(TOOL.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ('eval', 'exec', '__import__'))
        self.assertEqual(imports - {'argparse', 'hashlib', 'json', 'os', 're', 'stat', 'sys', 'candidate_inventory'}, set())
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse(attributes & {'system', 'popen', 'spawn', 'execv', 'write', 'chmod',
                                       'unlink', 'mkdir', 'O_CREAT', 'O_TRUNC', 'O_WRONLY', 'O_RDWR'})

    def test_report_does_not_echo_untrusted_paths_or_fields(self):
        self.doc['DO_NOT_ECHO_SECRET'] = '/private/path/DO_NOT_ECHO_SECRET'
        result = self.run_cli()
        self.assert_report(result, 1)
        self.assertNotIn('DO_NOT_ECHO_SECRET', result.stdout + result.stderr)

    def test_package_all_arch_and_archive_are_supported(self):
        row = self.artifact('source-package')
        row.update(kind='archive', name='nextcloud', version='33.0.0', architecture='all')
        self.assert_report(self.run_cli(), 0)

    def test_checked_in_unresolved_template_stays_blocked(self):
        raw = (BASE / 'qa/fixtures/artifact-lock.unresolved.json').read_text()
        self.assert_report(self.run_cli(raw=raw), 1)

    def test_missing_file_and_arguments(self):
        self.assert_report(self.run_cli(manifest='absent.json'), 1)
        result = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
