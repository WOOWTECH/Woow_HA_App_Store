"""Exercise strict image-build installation on owned fixture copies only."""
from __future__ import annotations
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from test_maintenance_preservation import CAPTURED, HERE, SELECTED_COMMON, load_common, select_common_source

spec = importlib.util.spec_from_file_location("owned_build_patch", HERE / "apply_maintenance_patch.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class StrictBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="native-preservation-build-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.sp = self.base / "site-packages"
        self.target = self.sp / installer.TARGET
        self.target.parent.mkdir(parents=True)
        self.original = (CAPTURED / "native/native_bridge_common.py").read_bytes()
        self.target.write_bytes(self.original)
        self.target.chmod(0o640)
        self.payload = (HERE / "overlay" / installer.TARGET).read_bytes()

    def test_installed_source_selector_accepts_only_exact_candidate(self):
        installer.apply(self.sp)
        self.assertEqual(select_common_source(self.target), self.target)

    def test_installed_source_selector_rejects_original_or_substitution(self):
        for data in (self.original, self.payload + b"\n# wrong installed source\n"):
            with self.subTest(data_size=len(data)):
                self.target.write_bytes(data)
                with self.assertRaisesRegex(RuntimeError, "exact afterSha256"):
                    select_common_source(self.target)

    def test_exact_source_install_preserves_mode_and_compiles_all_optimizations(self):
        before = self.target.stat()
        result = installer.apply(self.sp)
        after = self.target.stat()
        self.assertEqual(result["state"], "applied")
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual((before.st_mode, before.st_uid, before.st_gid),
                         (after.st_mode, after.st_uid, after.st_gid))
        for optimization in ("", 1, 2):
            pyc = Path(importlib.util.cache_from_source(str(self.target), optimization=optimization))
            self.assertTrue(pyc.is_file())
            self.assertEqual(int.from_bytes(pyc.read_bytes()[4:8], "little"), 3)
        self.assertTrue(load_common(self.target)._maintenance_bridge_is_disposable)

    def test_applied_source_is_hash_checked_idempotent(self):
        installer.apply(self.sp)
        ino = self.target.stat().st_ino
        self.assertEqual(installer.apply(self.sp)["state"], "already-applied")
        self.assertEqual(self.target.stat().st_ino, ino)

    def test_source_drift_refused_before_writes(self):
        drift = self.original + b"\n# fixture drift\n"
        self.target.write_bytes(drift)
        with self.assertRaisesRegex(installer.PatchRefused, "differs"):
            installer.apply(self.sp)
        self.assertEqual(self.target.read_bytes(), drift)
        self.assertEqual(sorted(p.name for p in self.target.parent.iterdir()), [self.target.name])

    def test_already_applied_but_modified_is_refused(self):
        self.target.write_bytes(self.payload + b"\n# drift\n")
        with self.assertRaises(installer.PatchRefused): installer.apply(self.sp)

    def test_check_only_does_not_write(self):
        self.assertEqual(installer.apply(self.sp, check_only=True)["state"], "checked")
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_target_symlink_is_refused(self):
        outside = self.base / "outside.py"
        outside.write_bytes(self.original)
        self.target.unlink()
        self.target.symlink_to(outside)
        with self.assertRaises((OSError, installer.PatchRefused)): installer.apply(self.sp)
        self.assertEqual(outside.read_bytes(), self.original)

    def test_ancestor_symlink_and_relative_paths_are_refused(self):
        alias = self.base / "alias"
        alias.symlink_to(self.sp, target_is_directory=True)
        for path in (alias, Path("relative"), self.sp / ".." / self.sp.name):
            with self.subTest(path=path):
                with self.assertRaises(installer.PatchRefused): installer.apply(path)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_hardlinked_target_is_refused(self):
        os.link(self.target, self.base / "alias.py")
        with self.assertRaises(installer.PatchRefused): installer.apply(self.sp)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_payload_hash_mismatch_aborts_before_target_write(self):
        package = self.base / "package"
        (package / "overlay" / installer.TARGET).parent.mkdir(parents=True)
        (package / "overlay" / installer.TARGET).write_bytes(self.payload + b"\n# substitution\n")
        shutil.copyfile(HERE / "source-lock.json", package / "source-lock.json")
        with mock.patch.object(installer, "HERE", package):
            with self.assertRaisesRegex(installer.PatchRefused, "payload hash"):
                installer.apply(self.sp)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_lock_target_substitution_aborts(self):
        package = self.base / "package"
        package.mkdir()
        lock = json.loads((HERE / "source-lock.json").read_text())
        lock["files"][0]["target"] = "other.py"
        (package / "source-lock.json").write_text(json.dumps(lock))
        with mock.patch.object(installer, "HERE", package):
            with self.assertRaisesRegex(installer.PatchRefused, "anchor"):
                installer.apply(self.sp)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_pycache_symlink_is_refused_before_source_write(self):
        outside = self.base / "outside-cache"
        outside.mkdir()
        (self.target.parent / "__pycache__").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(installer.PatchRefused): installer.apply(self.sp)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_pyc_symlink_is_refused_before_source_write(self):
        cache = self.target.parent / "__pycache__"
        cache.mkdir()
        outside = self.base / "outside-pyc"
        outside.write_bytes(b"keep bytes")
        Path(importlib.util.cache_from_source(str(self.target))).symlink_to(outside)
        with self.assertRaises(installer.PatchRefused): installer.apply(self.sp)
        self.assertEqual(outside.read_bytes(), b"keep bytes")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_installed_overlay_keeps_persisted_rollout(self):
        installer.apply(self.sp)
        common = load_common(self.target)
        root = self.base / "codex-native"
        bridge = root / ("c" * 32)
        bridge.mkdir(parents=True)
        (bridge / "owner.pid").write_text("0")
        history = bridge / "codex-home/sessions/old.jsonl"
        history.parent.mkdir(parents=True)
        history.write_bytes(b"fixture native rollout")
        self.assertEqual(common.prune_orphaned_dirs(root), 0)
        self.assertEqual(history.read_bytes(), b"fixture native rollout")


class SourceScopeTests(unittest.TestCase):
    @unittest.skipUnless((HERE.parent / "actual5164").is_dir(), "full 43-source audit is available in review workspace only")
    def test_all_43_captured_sources_unchanged(self):
        before = json.loads((HERE / "proof/original-43-before.json").read_text())
        self.assertEqual(len(before), 43)
        for rel, item in before.items():
            with self.subTest(rel=rel):
                self.assertEqual(hashlib.sha256((HERE.parent / rel).read_bytes()).hexdigest(), item["sha256"])

    def test_portable_fragments_match_recorded_source(self):
        fragments = json.loads((HERE / "fixtures/captured-fragments.json").read_text())
        for rel, item in fragments.items():
            fragment = (CAPTURED / rel).read_bytes()
            self.assertEqual(hashlib.sha256(fragment).hexdigest(), item["fragmentSha256"])
            original = HERE.parent / "actual5164" / rel
            if original.exists():
                source = original.read_bytes()
                self.assertEqual(hashlib.sha256(source).hexdigest(), item["sourceSha256"])
                if item["function"]:
                    text = source.decode()
                    node = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == item["function"])
                    self.assertEqual(fragment, (ast.get_source_segment(text, node) + "\n").encode())
                else:
                    self.assertEqual(fragment, source)

    def test_selected_source_hash_matches_lock(self):
        lock = json.loads((HERE / "source-lock.json").read_text())
        self.assertEqual(hashlib.sha256(SELECTED_COMMON.read_bytes()).hexdigest(), lock["files"][0]["afterSha256"])
        if "PI_NATIVE_MAINTENANCE_TEST_SOURCE" in os.environ:
            self.assertEqual(SELECTED_COMMON, Path(os.environ["PI_NATIVE_MAINTENANCE_TEST_SOURCE"]))

    def test_only_common_pruner_is_overlaid(self):
        actual = sorted(str(p.relative_to(HERE / "overlay")) for p in (HERE / "overlay").rglob("*.py"))
        self.assertEqual(actual, [installer.TARGET])

    def test_original_top_level_definitions_other_than_pruner_unchanged(self):
        original = ast.parse((CAPTURED / "native/native_bridge_common.py").read_text())
        patched = ast.parse((HERE / "overlay" / installer.TARGET).read_text())
        after = {n.name: n for n in patched.body if isinstance(n, ast.FunctionDef)}
        for n in original.body:
            if isinstance(n, ast.FunctionDef) and n.name != "prune_orphaned_dirs":
                self.assertEqual(ast.dump(n, include_attributes=False), ast.dump(after[n.name], include_attributes=False))

    def test_original_seven_day_predicate_and_explicit_routes_are_not_overlaid(self):
        for rel in ("harnesses/codex_native/bridge.py", "runner/native/orchestration.py", "runner/app.py"):
            self.assertFalse((HERE / "overlay/omnigent" / rel).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
