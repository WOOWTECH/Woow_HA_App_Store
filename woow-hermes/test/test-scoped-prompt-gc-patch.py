#!/usr/bin/env python3
"""Fail-closed build-patch checks; optional reviewed full-source directory."""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gc_patch", HERE.parent / "patches/scoped-prompt-gc.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class PatchTests(unittest.TestCase):
    temp_root = None
    source_dir = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_source_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            patcher.patch_directory(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unknown_and_marker_only_sources_are_rejected_without_write(self):
        for source in ("# unrelated upstream source\n", "# scoped prompt GC\n", ""):
            path = self.root / "hermes_state.py"
            path.write_text(source)
            for check in (False, True):
                with self.assertRaises(ValueError):
                    patcher.patch_directory(self.root, check)
                self.assertEqual(path.read_text(), source)

    def test_symlink_does_not_mutate_target_or_fall_back(self):
        target = self.root / "outside.py"
        target.write_text("untouched\n")
        path = self.root / "hermes_state_sessions.py"
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            patcher.patch_directory(self.root)
        self.assertEqual(target.read_text(), "untouched\n")
        target.unlink()
        with self.assertRaises(ValueError):
            patcher.patch_directory(self.root)
        self.assertFalse(target.exists())

    def test_split_source_never_falls_back_to_monolithic(self):
        (self.root / "hermes_state.py").write_text("monolithic untouched\n")
        (self.root / "hermes_state_sessions.py").write_text("unknown split\n")
        with self.assertRaises(ValueError):
            patcher.patch_directory(self.root)
        self.assertEqual((self.root / "hermes_state.py").read_text(), "monolithic untouched\n")

    def test_missing_or_duplicate_delete_method_rejected(self):
        source = (HERE / "fixtures/scoped-prompt-gc/monolithic.py").read_text()
        for changed in (source.replace("def delete_sessions(", "def renamed_delete_sessions("), source + "\n" + source):
            with self.assertRaises(ValueError):
                patcher.rewrite_methods(changed)

    def test_reviewed_full_file_apply_check_idempotence_and_drift(self):
        if self.source_dir is None:
            self.skipTest("full source pins verified by image build or --source-dir")
        files = [p for p in self.source_dir.iterdir() if p.name in patcher.SPECS]
        self.assertTrue(files)
        for source in files:
            with self.subTest(source=source.name):
                directory = self.root / source.stem
                directory.mkdir()
                target = directory / source.name
                original = source.read_bytes()
                target.write_bytes(original)
                with self.assertRaises(ValueError):
                    patcher.patch_directory(directory, check=True)
                self.assertEqual(target.read_bytes(), original)
                patcher.patch_directory(directory)
                changed = target.read_bytes()
                self.assertNotEqual(changed, original)
                patcher.patch_directory(directory, check=True)
                patcher.patch_directory(directory)
                self.assertEqual(target.read_bytes(), changed)
                for drifted in (original+b"\n", changed+b"\n", changed.replace(b"gc_roots =", b"gc_roots_drift =", 1)):
                    target.write_bytes(drifted)
                    with self.assertRaises(ValueError):
                        patcher.patch_directory(directory)
                    self.assertEqual(target.read_bytes(), drifted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--temp-root", type=Path)
    args = parser.parse_args()
    PatchTests.source_dir = args.source_dir
    PatchTests.temp_root = args.temp_root
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(PatchTests))
    print(json.dumps({"lane": "build-patch", "tests": result.testsRun, "skips": len(result.skipped),
                      "failures": [t.id() for t,_ in result.failures], "errors": [t.id() for t,_ in result.errors],
                      "passed": result.wasSuccessful()}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
