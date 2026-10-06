"""Synthetic offline gate tests: not PHP/CODE/PG runtime acceptance."""
import ast
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
TOOL = BASE / 'qa/candidate_inventory.py'
spec = importlib.util.spec_from_file_location('candidate_inventory', TOOL)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def bundle():
    # Intentionally identical system/collation snapshots: this is a stub, NOT
    # a claim that a real bookworm -> trixie candidate has no locale drift.
    collation = dict(name='pg_catalog.en_US', provider='c', locale='en_US.UTF-8',
                     collate='en_US.UTF-8', ctype='en_US.UTF-8',
                     recorded_version='2.41', actual_version='2.41')
    database = dict(name='synthetic', provider='c', locale='en_US.UTF-8',
                    collate='en_US.UTF-8', ctype='en_US.UTF-8',
                    recorded_version='2.41', actual_version='2.41',
                    collations_complete=True, collations=[collation])
    pg = dict(version='16.15', libc_version='2.41', icu_version='76.1',
              locales=['C', 'C.UTF-8', 'en_US.UTF-8'],
              databases_complete=True, databases=[database])
    php = dict(version='8.4.24', modules=sorted(gate.REQUIRED_MODULES),
               ini=dict(memory_limit='1024M', upload_max_filesize='16G',
                        post_max_size='16G', **{'apc.enable_cli': '1'}))
    fpm = copy.deepcopy(php)
    fpm['ini'].pop('apc.enable_cli')
    fpm['ini']['opcache.enable'] = '1'
    return dict(
        schema_version=1, scope='isolated-synthetic', evidence_kind='stub',
        candidate_digest='sha256:' + 'a' * 64,
        source_digest='sha256:' + 'b' * 64,
        php=dict(cli=php, fpm=fpm),
        fpm=dict(binary='php-fpm8.4', socket='/run/php/php8.4-fpm.sock',
                 socket_is_unix=True, pid_file='/run/php/php8.4-fpm.pid',
                 pid=12345, master_pid=12345, process_alive=True,
                 config_test_exit=0),
        nginx=dict(config_test_exit=0, process_alive=True,
                   fastcgi_socket='/run/php/php8.4-fpm.sock'),
        code=dict(version='26.04.4.2', version_exit=0, process_alive=True,
                  discovery_http_status=200, discovery_xml_valid=True,
                  websocket_http_status=101, save_roundtrip=True,
                  jail_enabled=True),
        postgres=dict(source=copy.deepcopy(pg), candidate=copy.deepcopy(pg)))


class InventoryTests(unittest.TestCase):
    def blocked(self, doc, fragment):
        report = gate.evaluate(doc)
        self.assertEqual(report['status'], 'blocked', report)
        self.assertTrue(any(fragment in e for e in report['errors']), report)
        self.assertFalse(report['runtime_verified'])
        self.assertFalse(report['haos_verified'])
        self.assertFalse(report['production_authorized'])

    def test_stub_pass_is_only_input_consistency(self):
        report = gate.evaluate(bundle())
        self.assertEqual(report['status'], 'inventory_checks_passed')
        self.assertEqual(report['evidence_kind'], 'stub')
        self.assertFalse(report['runtime_verified'])
        self.assertFalse(report['haos_verified'])
        self.assertFalse(report['production_authorized'])
        self.assertIn('signed_build_and_artifact_lock', report['pending_gates'])

    def test_documented_stub_matches_contract_and_input_is_unchanged(self):
        fixture = json.loads((BASE / 'qa/fixtures/candidate-inventory.stub.json').read_text())
        self.assertEqual(fixture, bundle())
        before = copy.deepcopy(fixture)
        self.assertEqual(gate.evaluate(fixture)['status'], 'inventory_checks_passed')
        self.assertEqual(fixture, before)

    def test_every_top_level_field_is_required(self):
        for key in bundle():
            doc = bundle()
            del doc[key]
            with self.subTest(key=key):
                self.blocked(doc, key)

    def test_unknown_fields_and_types_fail_closed(self):
        for value in (None, [], True, 'yes', 1):
            with self.subTest(value=value):
                self.blocked(value, 'bundle')
        doc = bundle()
        doc['run_command'] = 'DO NOT EXECUTE'
        self.blocked(doc, 'unexpected')
        for section in ('php', 'fpm', 'nginx', 'code', 'postgres'):
            doc = bundle()
            doc[section] = []
            self.blocked(doc, section)

    def test_scope_and_digest_are_not_optional(self):
        for key, value in (('scope', 'production'), ('schema_version', True),
                           ('candidate_digest', 'debian:trixie-slim'),
                           ('source_digest', 'sha256:'),
                           ('evidence_kind', 'verified-by-agent')):
            doc = bundle()
            doc[key] = value
            self.blocked(doc, key)

    def test_php_module_and_ini_gates_for_both_sapis(self):
        for sapi in ('cli', 'fpm'):
            for module in gate.REQUIRED_MODULES:
                doc = bundle()
                doc['php'][sapi]['modules'].remove(module)
                with self.subTest(sapi=sapi, module=module):
                    self.blocked(doc, f'php.{sapi}.modules')
            doc = bundle()
            doc['php'][sapi]['version'] = '8.2.33'
            self.blocked(doc, f'php.{sapi}.version')
            for setting in doc['php'][sapi]['ini']:
                doc = bundle()
                doc['php'][sapi]['ini'][setting] = '0'
                self.blocked(doc, f'php.{sapi}.ini.{setting}')

    def test_cli_fpm_patch_versions_must_match(self):
        doc = bundle()
        doc['php']['fpm']['version'] = '8.4.23'
        self.blocked(doc, 'php.version')

    def test_duplicate_and_invalid_module_entries(self):
        for modules in (['curl', 'CURL'], ['curl', 0], [], 'curl'):
            doc = bundle()
            doc['php']['cli']['modules'] = modules
            self.blocked(doc, 'php.cli.modules')

    def test_all_service_gates(self):
        cases = {
            'fpm': dict(binary='php-fpm8.2', socket='/wrong',
                        socket_is_unix=False, pid_file='/wrong', pid=0,
                        master_pid=9999, process_alive=False,
                        config_test_exit=1),
            'nginx': dict(config_test_exit=1, process_alive=False,
                          fastcgi_socket='/wrong'),
            'code': dict(version='', version_exit=1, process_alive=False,
                         discovery_http_status=500, discovery_xml_valid=False,
                         websocket_http_status=200, save_roundtrip=False,
                         jail_enabled=False),
        }
        for section, changes in cases.items():
            for key, value in changes.items():
                doc = bundle()
                doc[section][key] = value
                with self.subTest(section=section, key=key):
                    self.blocked(doc, section)
                doc = bundle()
                del doc[section][key]
                self.blocked(doc, key)
        doc = bundle()
        doc['fpm']['config_test_exit'] = False  # bool is NOT exit code 0
        self.blocked(doc, 'config_test_exit')
        doc = bundle()
        doc['code']['process_alive'] = 'true'
        self.blocked(doc, 'process_alive')

    def test_pg_major_and_incomplete_inventories(self):
        for side in ('source', 'candidate'):
            for key, value in (('version', '17.0'), ('databases', []),
                               ('databases_complete', False), ('locales', [])):
                doc = bundle()
                doc['postgres'][side][key] = value
                self.blocked(doc, f'postgres.{side}.{key}')
            for key, value in (('collations', []), ('collations_complete', False)):
                doc = bundle()
                doc['postgres'][side]['databases'][0][key] = value
                self.blocked(doc, key)

    def test_system_locale_drift_is_not_waived(self):
        for key, value in (('libc_version', '2.36'), ('icu_version', '72.1'),
                           ('locales', ['C'])):
            doc = bundle()
            doc['postgres']['candidate'][key] = value
            self.blocked(doc, key)

    def test_database_and_collation_drift(self):
        for row_kind in ('database', 'collation'):
            for key, value in (('name', 'other'), ('provider', 'i'),
                               ('locale', 'en-GB'), ('collate', 'en_GB.UTF-8'),
                               ('ctype', 'en_GB.UTF-8'),
                               ('recorded_version', '2.36'),
                               ('actual_version', '2.36')):
                doc = bundle()
                row = doc['postgres']['candidate']['databases'][0]
                if row_kind == 'collation':
                    row = row['collations'][0]
                row[key] = value
                with self.subTest(row_kind=row_kind, key=key):
                    self.blocked(doc, 'postgres')

    def test_already_refreshed_versions_still_block_drift(self):
        doc = bundle()
        db = doc['postgres']['candidate']['databases'][0]
        for row in (db, db['collations'][0]):
            row['recorded_version'] = row['actual_version'] = '2.42'
        self.blocked(doc, 'drift')

    def test_null_version_is_only_allowed_for_c_locales(self):
        doc = bundle()
        for side in ('source', 'candidate'):
            db = doc['postgres'][side]['databases'][0]
            for row in (db, db['collations'][0]):
                row.update(locale='C', collate='C', ctype='C',
                           recorded_version=None, actual_version=None)
        self.assertEqual(gate.evaluate(doc)['status'], 'inventory_checks_passed')
        doc['postgres']['candidate']['databases'][0]['provider'] = 'i'
        self.blocked(doc, 'version')

    def test_default_collation_inherits_database_locale(self):
        doc = bundle()
        for side in ('source', 'candidate'):
            col = doc['postgres'][side]['databases'][0]['collations'][0]
            col.update(name='pg_catalog.default', provider='d',
                       recorded_version=None, actual_version=None)
        self.assertEqual(gate.evaluate(doc)['status'], 'inventory_checks_passed')
        doc['postgres']['candidate']['databases'][0]['collations'][0]['locale'] = 'other'
        self.blocked(doc, 'inherited')

    def test_missing_nested_fields_and_malformed_leaf_values(self):
        def objects(obj, path=()):
            if isinstance(obj, dict):
                yield path, obj
                for key, value in obj.items():
                    yield from objects(value, path + (key,))
            elif isinstance(obj, list):
                for index, value in enumerate(obj):
                    yield from objects(value, path + (index,))
        for path, obj in objects(bundle()):
            for key in obj:
                doc = bundle()
                target = doc
                for part in path:
                    target = target[part]
                del target[key]
                with self.subTest(path=path, missing=key):
                    self.blocked(doc, str(key))
        # Malformed JSON-compatible shapes may block, never crash or pass.
        for path, obj in objects(bundle()):
            for key, original in obj.items():
                for value in (None, [], {}, True, 0, ''):
                    if type(value) is type(original) and value == original:
                        continue
                    doc = bundle()
                    target = doc
                    for part in path:
                        target = target[part]
                    target[key] = value
                    with self.subTest(path=path, key=key, value=value):
                        self.assertEqual(gate.evaluate(doc)['status'], 'blocked')

    def test_duplicate_databases_or_collations_rejected(self):
        for key in ('databases', 'collations'):
            doc = bundle()
            rows = doc['postgres']['candidate']['databases']
            if key == 'collations':
                rows = rows[0]['collations']
            rows.append(copy.deepcopy(rows[0]))
            self.blocked(doc, 'duplicate')

    def test_collection_order_not_a_drift(self):
        doc = bundle()
        doc['postgres']['candidate']['locales'].reverse()
        self.assertEqual(gate.evaluate(doc)['status'], 'inventory_checks_passed')

    def cli(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic.json'
            path.write_text(content)
            return subprocess.run([sys.executable, str(TOOL), str(path)],
                                  capture_output=True, text=True, timeout=5)

    def test_cli_success_and_blocked_exit_codes(self):
        result = self.cli(json.dumps(bundle()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['runtime_verified'])
        result = self.cli('{}')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'blocked')

    def test_cli_rejects_bad_duplicate_nonfinite_or_oversized_json(self):
        for content in ('{', '{"scope":1,"scope":2}', '{"x":NaN}',
                        '{"x":1e999}', '{"x":-1e999}',
                        ' ' * (gate.MAX_BYTES + 1)):
            result = self.cli(content)
            with self.subTest(content=content[:40]):
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'invalid_input')
                self.assertFalse(json.loads(result.stdout)['runtime_verified'])

    def test_collected_label_does_not_authenticate_runtime(self):
        doc = bundle()
        doc['evidence_kind'] = 'collected'
        result = self.cli(json.dumps(doc))
        self.assertEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report['runtime_verified'])
        self.assertFalse(report['production_authorized'])

    def test_cli_missing_file_and_no_arguments(self):
        result = subprocess.run([sys.executable, str(TOOL), '/nonexistent/synthetic.json'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)['runtime_verified'])
        result = subprocess.run([sys.executable, str(TOOL)], capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 2)

    def test_evaluator_has_no_runtime_or_write_dependencies(self):
        tree = ast.parse(TOOL.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ('eval', 'exec', '__import__'))
        self.assertEqual(imports - {'argparse', 'json', 're', 'pathlib'}, set())
        for name in ('subprocess', 'socket', 'write_text', 'write_bytes', 'unlink'):
            self.assertNotIn(name, {n.attr for n in ast.walk(tree)
                                    if isinstance(n, ast.Attribute)})


if __name__ == '__main__':
    unittest.main()
