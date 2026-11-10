"""Native histories survive real pinned orphan pruning; disposable dirs do not."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('history_patch_builder', ROOT / 'patch-native-resume.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class HistoryRetention(unittest.TestCase):
    def setUp(self):
        fixture = os.environ.get('OMNIGENT_TEST_SITE_PACKAGES')
        if not fixture:
            self.skipTest('Pinned Omnigent 0.16 fixture required')
        self.fixture = Path(fixture)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.site = self.directory / 'site'
        for name in builder.HASHES:
            destination = self.site / 'omnigent' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.fixture / 'omnigent' / name, destination)
        metadata = self.site / 'omnigent-0.16.0.dist-info/METADATA'
        metadata.parent.mkdir(parents=True)
        metadata.write_text('Name: omnigent\nVersion: 0.16.0\n')
        common_path = self.fixture / 'omnigent/native/native_bridge_common.py'
        self.assertEqual(hashlib.sha256(common_path.read_bytes()).hexdigest(),
                         '2a80d492f6f844a8da0e7dbb3e8aaec396a2bbd525f6d042ddc3cf2eed6bccc6')
        common_spec = importlib.util.spec_from_file_location('pinned_bridge_lifecycle', common_path)
        self.common = importlib.util.module_from_spec(common_spec)
        common_spec.loader.exec_module(self.common)
        attachments = types.ModuleType('omnigent.inner.native_attachments')
        attachments.attachment_cache_dir = lambda path: self.directory / 'cache' / path.name
        terminal = types.ModuleType('omnigent.inner.terminal')
        terminal._process_alive = lambda pid: pid == os.getpid()
        modules = patch.dict(sys.modules, {'omnigent.inner.native_attachments': attachments,
                                          'omnigent.inner.terminal': terminal})
        modules.start()
        self.addCleanup(modules.stop)
        self.root = self.directory / 'bridges'
        self.root.mkdir()
        original = (self.site / 'omnigent/harnesses/pi_native/bridge.py').read_text()
        transformed = builder.transformed('harnesses/pi_native/bridge.py', original)
        tree = ast.parse(transformed)
        # Execute the actual two patched functions with the actual pinned
        # lifecycle module; substitute only external process liveness/cache.
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and
                    node.name in ('_woow_pi_bridge_has_no_native_history', 'prune_orphaned_bridge_dirs')]
        self.assertEqual(len(selected), 2)
        namespace = {'Path': Path, '_SESSIONS_DIR': 'sessions',
                     'native_bridge_common': self.common, 'bridge_root': lambda: self.root}
        exec(compile(ast.Module(body=selected, type_ignores=[]), '<actual-pinned-pi-pruner>', 'exec'), namespace)
        self.prune = namespace['prune_orphaned_bridge_dirs']
        self.eligible = namespace['_woow_pi_bridge_has_no_native_history']

    def bridge(self, name, *, alive=False, history=None):
        directory = self.root / name
        directory.mkdir()
        (directory / 'owner.pid').write_text(str(os.getpid() if alive else 99999999))
        (directory / 'sessions').mkdir()
        if history is not None:
            (directory / 'sessions/original.jsonl').write_bytes(history)
        return directory

    def test_dead_owner_history_survives_while_empty_bridge_is_pruned(self):
        raw = b'{"type":"session","id":"original","version":3}\n'
        original = self.bridge('original', history=raw)
        empty = self.bridge('empty')
        self.assertEqual(self.prune(), 1)
        self.assertFalse(empty.exists())
        self.assertEqual((original / 'sessions/original.jsonl').read_bytes(), raw)
        self.assertEqual(self.prune(), 0)

    def test_empty_or_partial_jsonl_is_not_discarded(self):
        empty = self.bridge('empty-record', history=b'')
        partial = self.bridge('partial-record', history=b'{"type":')
        self.assertEqual(self.prune(), 0)
        self.assertTrue(empty.exists() and partial.exists())

    def test_live_owner_and_held_sdk_lock_remain_protected(self):
        alive = self.bridge('alive', alive=True)
        held = self.bridge('held')
        with self.common.bridge_dir_preparation_lock(held):
            self.assertEqual(self.prune(), 0)
        self.assertTrue(alive.exists() and held.exists())
        self.assertEqual(self.prune(), 1)
        self.assertTrue(alive.exists())

    def test_missing_history_is_disposable_but_symlink_is_retained(self):
        missing = self.bridge('missing')
        (missing / 'sessions').rmdir()
        linked = self.bridge('linked')
        (linked / 'sessions').rmdir()
        outside = self.directory / 'outside'
        outside.mkdir()
        (outside / 'private.jsonl').write_text('preserve')
        (linked / 'sessions').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.prune(), 1)
        self.assertFalse(missing.exists())
        self.assertTrue(linked.exists())
        self.assertEqual((outside / 'private.jsonl').read_text(), 'preserve')

    def test_unreadable_history_is_retained(self):
        directory = self.bridge('unreadable')
        with patch.object(Path, 'iterdir', side_effect=PermissionError):
            self.assertFalse(self.eligible(directory))

    def install_previous_hot_patch(self):
        targets = {}
        for name, expected in builder.HASHES.items():
            target = self.site / 'omnigent' / name
            anchor, hook = builder.HOOKS[name]
            source = target.read_text().replace(anchor, anchor + hook, 1)
            if name.endswith('.js'):
                source = builder.JS_PREAMBLE + source
            target.write_text(source)
            targets[name] = {'original': expected, 'patched': builder.digest(target.read_bytes())}
        helper = (ROOT / 'pi_mcp_refresh.cjs').read_bytes()
        (self.site / 'omnigent' / builder.HELPER).write_bytes(helper)
        (self.site / 'omnigent' / builder.RECEIPT).write_text(json.dumps({
            'version': builder.VERSION, 'marker': builder.MARKER, 'targets': targets,
            'helper': builder.digest(helper)}))

    def files(self):
        return {str(path.relative_to(self.site)): path.read_bytes()
                for path in self.site.rglob('*') if path.is_file()}

    def test_validated_previous_patch_upgrades_without_touching_native_data(self):
        self.install_previous_hot_patch()
        before = self.files()
        self.assertEqual(builder.patch(self.site, check=True)['state'], 'verified')
        self.assertEqual(before, self.files())
        self.assertEqual(builder.patch(self.site)['state'], 'applied')
        after = self.files()
        self.assertEqual({key for key in before if before[key] != after[key]},
                         {'omnigent/harnesses/pi_native/bridge.py', 'omnigent/' + builder.RECEIPT})
        self.assertEqual(builder.patch(self.site)['state'], 'already-applied')
        self.assertEqual(after, self.files())

    def test_retention_drift_refused_even_with_forged_receipt(self):
        builder.patch(self.site)
        relative = 'harnesses/pi_native/bridge.py'
        target = self.site / 'omnigent' / relative
        target.write_text(target.read_text().replace('except OSError:\n        return False',
                                                    'except OSError:\n        return True'))
        receipt = self.site / 'omnigent' / builder.RECEIPT
        document = json.loads(receipt.read_text())
        document['targets'][relative]['patched'] = builder.digest(target.read_bytes())
        receipt.write_text(json.dumps(document))
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'MCP_NATIVE_PATCH_SOURCE_MISMATCH'):
            builder.patch(self.site)
        self.assertEqual(before, self.files())


if __name__ == '__main__':
    unittest.main()
