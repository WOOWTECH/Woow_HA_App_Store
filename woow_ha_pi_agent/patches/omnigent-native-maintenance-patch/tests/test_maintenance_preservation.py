"""Owned source fixtures only; AST loading never imports the Omnigent runtime."""
from __future__ import annotations

import ast
import asyncio
import builtins
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
from types import SimpleNamespace
from unittest import mock
import unittest
from filelock import FileLock, Timeout as FileLockTimeout

HERE = Path(__file__).resolve().parents[1]
CAPTURED = HERE / "fixtures/captured"
OVERLAY = HERE / "overlay/omnigent/native/native_bridge_common.py"


def select_common_source(override=None):
    configured = os.environ.get("PI_NATIVE_MAINTENANCE_TEST_SOURCE")
    path = Path(override if override is not None else configured if configured is not None else OVERLAY)
    expected = json.loads((HERE / "source-lock.json").read_text())["files"][0]["afterSha256"]
    if not path.is_absolute() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("selected common source must match exact afterSha256 from source-lock.json")
    return path


# Validate an installed-source override before collecting any behavior tests.
# The suite AST-executes this selected file with controlled fixture dependencies,
# rather than importing the installed SDK or provider modules.
SELECTED_COMMON = select_common_source()


def ast_function(path, name):
    source = path.read_text()
    return ast.get_source_segment(source, next(n for n in ast.parse(source).body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name))


def load_common(path=None):
    path = SELECTED_COMMON if path is None else path
    # Isolated builtins for two lazy integration imports. No sys.modules edits,
    # SDK imports, monkeypatch of installed runtime, or provider calls.
    namespace = dict(os=os, stat=stat, Path=Path, contextlib=contextlib,
        contextmanager=contextlib.contextmanager, Iterator=object, Callable=object,
        FileLock=FileLock, FileLockTimeout=FileLockTimeout, shutil=shutil,
        _logger=logging.getLogger("owned-maintenance-tests"))
    live = dict(os=os, IS_WINDOWS=False)
    exec("from __future__ import annotations\n" + ast_function(CAPTURED / "inner/terminal.py", "_process_alive"), live)
    native = SimpleNamespace(attachment_cache_dir=lambda p: p.parent.parent / "caches" / p.name)
    terminal = SimpleNamespace(_process_alive=live["_process_alive"])
    real_import = builtins.__import__
    def fixture_import(name, *args, **kwargs):
        if name == "omnigent.inner.native_attachments": return native
        if name == "omnigent.inner.terminal": return terminal
        if name.startswith("omnigent"): raise AssertionError("Runtime import forbidden: " + name)
        return real_import(name, *args, **kwargs)
    namespace["__builtins__"] = dict(vars(builtins), __import__=fixture_import)
    source = path.read_text()
    selected = []
    for n in ast.parse(source).body:
        if isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) for t in n.targets):
            if any(t.id in {"OWNER_PID_FILENAME", "_LOCK_DIR_NAME"} or t.id.startswith("_MAINTENANCE_") for t in n.targets):
                selected.append(ast.get_source_segment(source, n))
        if isinstance(n, ast.FunctionDef) and n.name != "reap_orphaned_native_bridge_dirs":
            start = min([n.lineno] + [d.lineno for d in n.decorator_list])
            selected.append("\n".join(source.splitlines()[start-1:n.end_lineno]))
    exec("from __future__ import annotations\n" + "\n\n".join(selected), namespace)
    namespace["_fixture_terminal"] = terminal
    namespace["_fixture_attachments"] = native
    return SimpleNamespace(**namespace)


def age_predicate(common):
    namespace = dict(os=os, stat=stat, time=time, Path=Path,
        native_bridge_common=common, _ORPHAN_RETENTION_SECONDS=7*24*60*60)
    exec("from __future__ import annotations\n" + ast_function(CAPTURED / "harnesses/codex_native/bridge.py", "_codex_orphan_retention_expired"), namespace)
    return namespace["_codex_orphan_retention_expired"]


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="native-preservation-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "codex-native"
        self.root.mkdir(mode=0o700)
        self.bridge = self.root / ("a" * 32)
        self.bridge.mkdir(mode=0o700)
        self.owner = self.bridge / "owner.pid"
        self.owner.write_text("0")  # Captured POSIX predicate: nonpositive pid is dead.
        self.owner.chmod(0o600)
        self.old = time.time() - 8*24*60*60
        os.utime(self.owner, (self.old, self.old))
        self.common = load_common()

    def write(self, rel, data=b"private fixture only\n", mode=0o600):
        path = self.bridge / rel
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        path.chmod(mode)
        os.utime(path, (self.old, self.old))
        return path

    def prune(self, predicate=None):
        return self.common.prune_orphaned_dirs(self.root,
            should_prune=predicate if predicate is not None else age_predicate(self.common))

    def snapshot(self):
        result = {}
        for directory, dirs, files in os.walk(self.bridge, followlinks=False):
            for name in [".", *dirs, *files]:
                path = Path(directory) if name == "." else Path(directory) / name
                info = path.lstat()
                data = (os.readlink(path) if path.is_symlink() else
                    hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
                result[str(path.relative_to(self.bridge))] = (info.st_mode, info.st_uid,
                    info.st_gid, info.st_size, info.st_mtime_ns, info.st_ino, data)
        return result

    def assert_kept(self, predicate=None):
        before = self.snapshot()
        self.assertEqual(self.prune(predicate), 0)
        self.assertEqual(self.snapshot(), before)

    def test_marker_only_empty_bridge_is_eligible(self):
        self.assertTrue(self.common._maintenance_bridge_is_disposable(self.bridge))
        self.assertEqual(self.prune(), 1)
        self.assertFalse(self.bridge.exists())

    def test_nested_empty_sessions_is_eligible(self):
        (self.bridge / "codex-home/sessions/2026/10/01").mkdir(parents=True, mode=0o700)
        self.assertEqual(self.prune(), 1)
        self.assertFalse(self.bridge.exists())

    def test_every_nonmarker_leaf_is_retained_without_name_heuristics(self):
        for name in ["codex-home/sessions/opaque", "codex-home/archived_sessions/untitled.bin",
                "history", "unrecognized-extension.payload", "elsewhere/notes.jsonl", "state.sqlite",
                "owner.pid.bak", "dead_letter", "dead_letter.jsonl", "dead_letter.jsonl.1",
                "dead_letter.jsonl.999", "config.toml", "bridge.json", "auth.json"]:
            with self.subTest(name=name):
                path = self.write(name, b"fixture \x00\xff bytes\n")
                self.assert_kept(lambda _: True)
                path.unlink()

    def test_zero_byte_rollout_and_dead_letter_still_veto(self):
        for name in ["codex-home/sessions/rollout-empty.jsonl", "dead_letter.jsonl", "dead_letter.jsonl.1"]:
            with self.subTest(name=name):
                path = self.write(name, b"")
                self.assert_kept(lambda _: True)
                path.unlink()

    def test_generated_config_auth_and_exact_modes_remain_in_place(self):
        self.write("codex-home/sessions/native.bytes", bytes(range(256)), 0o640)
        self.write("codex-home/config.toml", b"fixture generated config", 0o600)
        self.write("codex-home/auth.json", b"fixture auth content only", 0o600)
        self.write("dead_letter.jsonl.1", b"fixture malformed\x00payload", 0o600)
        self.assert_kept(lambda _: True)
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["codex-native"])

    def test_auth_symlink_keeps_bridge_and_target_unchanged(self):
        outside = self.base / "global-fixture-auth.json"
        outside.write_bytes(b"owned noncredential fixture")
        outside.chmod(0o600)
        (self.bridge / "auth.json").symlink_to(outside)
        before = outside.stat()
        self.assert_kept(lambda _: True)
        after = outside.stat()
        self.assertEqual((before.st_ino, before.st_mode, before.st_mtime_ns, before.st_atime_ns),
                         (after.st_ino, after.st_mode, after.st_mtime_ns, after.st_atime_ns))
        self.assertEqual(outside.read_bytes(), b"owned noncredential fixture")

    def test_directory_and_dangling_symlinks_veto(self):
        outside = self.base / "outside"
        outside.mkdir()
        for name, target in [("alias", outside), ("dangling", self.base / "absent")]:
            with self.subTest(name=name):
                path = self.bridge / name
                path.symlink_to(target, target_is_directory=True)
                self.assert_kept(lambda _: True)
                path.unlink()

    def test_owner_symlink_never_read(self):
        original = self.owner.read_bytes()
        self.owner.unlink()
        outside = self.base / "marker-target"
        outside.write_bytes(original)
        self.owner.symlink_to(outside)
        self.assert_kept(lambda _: True)
        self.assertFalse((self.root / ".locks").exists())

    def test_symlink_bridge_path_is_not_followed(self):
        target = self.base / "outside-bridge"
        self.bridge.rename(target)
        self.bridge.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.prune(lambda _: True), 0)
        self.assertTrue((target / "owner.pid").exists())
        self.assertFalse((self.root / ".locks").exists())

    def test_symlink_root_and_ancestor_are_not_followed(self):
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.common.prune_orphaned_dirs(alias), 0)
        parent_alias = self.base / "parent-alias"
        parent_alias.symlink_to(self.base, target_is_directory=True)
        self.assertEqual(self.common.prune_orphaned_dirs(parent_alias / self.root.name), 0)
        self.assertTrue(self.owner.exists())
        self.assertFalse((self.root / ".locks").exists())

    def test_relative_and_parent_traversal_paths_veto(self):
        self.assertFalse(self.common._maintenance_bridge_is_disposable(Path("relative")))
        traversal = self.root / ".." / self.root.name / self.bridge.name
        self.assertFalse(self.common._maintenance_bridge_is_disposable(traversal))
        self.assertEqual(self.common.prune_orphaned_dirs(self.root / ".." / self.root.name), 0)
        self.assertTrue(self.owner.exists())

    def test_symlink_lock_directory_and_lockfile_veto(self):
        outside = self.base / "outside-locks"
        outside.mkdir()
        locks = self.root / ".locks"
        locks.symlink_to(outside, target_is_directory=True)
        self.assert_kept(lambda _: True)
        self.assertEqual(list(outside.iterdir()), [])
        locks.unlink()
        locks.mkdir()
        target = self.base / "outside-lock-file"
        target.write_bytes(b"keep exact fixture")
        (locks / (self.bridge.name + ".lock")).symlink_to(target)
        self.assert_kept(lambda _: True)
        self.assertEqual(target.read_bytes(), b"keep exact fixture")

    def test_live_owner_empty_bridge_is_kept(self):
        self.owner.write_text(str(os.getpid()))
        os.utime(self.owner, (self.old, self.old))
        self.assert_kept(lambda _: True)

    def test_new_owner_marker_keeps_seven_day_policy(self):
        self.owner.touch()
        self.assert_kept()

    def test_new_rollout_is_kept_even_if_predicate_permits(self):
        path = self.write("codex-home/sessions/rollout-new.jsonl")
        path.touch()
        self.assert_kept(lambda _: True)

    def test_no_harness_predicate_cannot_bypass_safety(self):
        self.write("dead_letter.jsonl")
        self.assertEqual(self.common.prune_orphaned_dirs(self.root), 0)
        self.assertTrue(self.bridge.exists())

    def test_predicate_false_or_error_keeps_empty_bridge(self):
        self.assert_kept(lambda _: False)
        def broken(_):
            raise RuntimeError("owned injected eligibility error")
        with self.assertLogs("owned-maintenance-tests", level="ERROR"):
            self.assert_kept(broken)

    def test_marker_missing_invalid_large_or_hardlinked_veto(self):
        for value in [None, b"", b"invalid", b"0" * 33]:
            with self.subTest(value=value):
                if self.owner.exists(): self.owner.unlink()
                if value is not None: self.owner.write_bytes(value)
                self.assert_kept(lambda _: True)
        self.owner.unlink()
        self.owner.write_text("0")
        os.link(self.owner, self.base / "marker-hardlink")
        self.assert_kept(lambda _: True)

    def test_special_fifo_veto(self):
        os.mkfifo(self.bridge / "native-pipe", mode=0o600)
        self.assertEqual(self.prune(lambda _: True), 0)
        self.assertTrue((self.bridge / "native-pipe").exists())

    def test_scan_failure_aborts_before_delete(self):
        fake_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        fake_os.scandir = mock.Mock(side_effect=PermissionError("owned fixture scan failure"))
        namespace = self.common._maintenance_bridge_is_disposable.__globals__
        with mock.patch.dict(namespace, os=fake_os):
            self.assert_kept(lambda _: True)
        fake_os.scandir.assert_called_once()

    def test_metadata_failure_aborts_before_delete(self):
        fake_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        fake_os.fstat = mock.Mock(side_effect=OSError("owned fixture metadata failure"))
        namespace = self.common._maintenance_bridge_is_disposable.__globals__
        with mock.patch.dict(namespace, os=fake_os):
            self.assert_kept(lambda _: True)

    def test_scan_entry_bound_holds(self):
        for i in range(self.common._MAINTENANCE_MAX_ENTRIES):
            (self.bridge / f"empty-{i}").mkdir()
        self.assertEqual(self.prune(lambda _: True), 0)
        self.assertTrue(self.owner.exists())

    def test_scan_depth_bound_holds(self):
        path = self.bridge
        for _ in range(self.common._MAINTENANCE_MAX_DEPTH + 1):
            path = path / "empty"
            path.mkdir()
        self.assert_kept(lambda _: True)

    def test_owner_changed_during_eligibility_is_kept(self):
        def changed(_):
            self.owner.write_text(str(os.getpid()))
            return True
        self.assertEqual(self.prune(changed), 0)
        self.assertTrue(self.owner.exists())

    def test_rollout_or_dead_letter_created_by_callback_vetoes_final_delete(self):
        for name in ["codex-home/sessions/new-opaque.bytes", "dead_letter.jsonl.1"]:
            with self.subTest(name=name):
                def added(_):
                    self.write(name)
                    return True
                self.assertEqual(self.prune(added), 0)
                self.assertTrue((self.bridge / name).exists())
                (self.bridge / name).unlink()

    def test_changed_snapshot_vetoes_delete(self):
        fake_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        scans = 0
        def changed(fd):
            nonlocal scans
            scans += 1
            if scans == 2:
                self.owner.write_text("00")
            return os.scandir(fd)
        fake_os.scandir = changed
        namespace = self.common._maintenance_bridge_is_disposable.__globals__
        with mock.patch.dict(namespace, os=fake_os):
            self.assertEqual(self.prune(lambda _: True), 0)
        self.assertEqual(self.owner.read_text(), "00")
        self.assertEqual(scans, 2)

    def test_data_created_during_descriptor_scan_is_kept(self):
        fake_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        created = False
        def changed(fd):
            nonlocal created
            if not created:
                self.write("dead_letter.jsonl")
                created = True
            return os.scandir(fd)
        fake_os.scandir = changed
        namespace = self.common._maintenance_bridge_is_disposable.__globals__
        with mock.patch.dict(namespace, os=fake_os):
            self.assertEqual(self.prune(lambda _: True), 0)
        self.assertTrue((self.bridge / "dead_letter.jsonl").exists())

    def test_preparation_lock_held_by_separate_filelock_skips(self):
        # Separate FileLock instance on the actual lockfile; same Linux flock
        # semantics as a separate process, no SDK or subprocess required.
        with self.common.bridge_dir_preparation_lock(self.bridge):
            self.assert_kept(lambda _: True)
        self.assertEqual(self.prune(lambda _: True), 1)

    def test_cache_exact_bytes_and_modes_survive_empty_bridge_removal(self):
        cache = self.common._fixture_attachments.attachment_cache_dir(self.bridge)
        cache.mkdir(parents=True, mode=0o700)
        cache.chmod(0o700)
        leaf = cache / "opaque-history-and-attachment.bin"
        leaf.write_bytes(bytes(range(256)))
        leaf.chmod(0o640)
        os.utime(leaf, (self.old, self.old))
        before = leaf.stat()
        cache_before = cache.stat()
        path = self.write("dead_letter.jsonl")
        self.assert_kept(lambda _: True)
        path.unlink()
        self.assertEqual(self.prune(lambda _: True), 1)
        self.assertFalse(self.bridge.exists())
        self.assertEqual(leaf.read_bytes(), bytes(range(256)))
        after = leaf.stat()
        self.assertEqual((before.st_ino, before.st_mode, before.st_uid, before.st_gid,
                          before.st_size, before.st_mtime_ns),
                         (after.st_ino, after.st_mode, after.st_uid, after.st_gid,
                          after.st_size, after.st_mtime_ns))
        self.assertEqual((cache.stat().st_ino, cache.stat().st_mode),
                         (cache_before.st_ino, cache_before.st_mode))

    def test_cache_path_symlink_is_never_followed_or_removed(self):
        cache = self.common._fixture_attachments.attachment_cache_dir(self.bridge)
        cache.parent.mkdir(parents=True)
        outside = self.base / "outside-fixture-cache"
        outside.mkdir()
        leaf = outside / "history.jsonl"
        leaf.write_bytes(b"owned cache symlink fixture")
        leaf.chmod(0o600)
        cache.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.prune(lambda _: True), 1)
        self.assertTrue(cache.is_symlink())
        self.assertEqual(leaf.read_bytes(), b"owned cache symlink fixture")
        self.assertEqual(stat.S_IMODE(leaf.stat().st_mode), 0o600)

    def test_unreadable_cache_is_untouched_without_even_resolving_it(self):
        cache = self.common._fixture_attachments.attachment_cache_dir(self.bridge)
        cache.mkdir(parents=True)
        leaf = cache / "history.jsonl"
        leaf.write_bytes(b"owned unreadable cache fixture")
        cache.chmod(0)
        self.addCleanup(cache.chmod, 0o700)
        # Resolver must not be invoked: no metadata/content access to the cache.
        self.common._fixture_attachments.attachment_cache_dir = mock.Mock(
            side_effect=AssertionError("maintenance must not resolve a cache"))
        self.assertEqual(self.prune(lambda _: True), 1)
        self.common._fixture_attachments.attachment_cache_dir.assert_not_called()
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0)
        cache.chmod(0o700)
        self.assertEqual(leaf.read_bytes(), b"owned unreadable cache fixture")

    def test_empty_attachment_cache_is_also_left_for_explicit_cleanup(self):
        cache = self.common._fixture_attachments.attachment_cache_dir(self.bridge)
        cache.mkdir(parents=True)
        self.assertEqual(self.prune(lambda _: True), 1)
        self.assertTrue(cache.is_dir())

    def test_dead_owner_is_rechecked_after_callback(self):
        calls = []
        def liveness(pid):
            calls.append(pid)
            return len(calls) > 1
        self.common._fixture_terminal._process_alive = liveness
        self.assert_kept(lambda _: True)
        self.assertEqual(calls, [0, 0])

    def test_explicit_session_delete_remains_destructive_without_archive(self):
        # Execute only the exact captured function with fixture path resolvers.
        # No runtime import, server request, provider or SDK is involved.
        families = ["antigravity", "claude", "codex", "cursor", "goose", "hermes",
                    "kimi", "kiro", "opencode", "pi", "qwen"]
        modules = {}
        for family in families:
            target = self.base / "explicit" / family / "owned-session"
            target.mkdir(parents=True)
            (target / "history.jsonl").write_bytes(b"owned deletion fixture")
            (target / "auth.json").write_bytes(b"owned auth fixture")
            cache = target.parent / "cache"
            cache.mkdir()
            (cache / "attachment").write_bytes(b"fixture")
            resolver = lambda _sid, p=target: p
            modules[f"omnigent.harnesses.{family}_native.bridge"] = SimpleNamespace(
                bridge_dir_for_bridge_id=resolver, bridge_dir_for_session_id=resolver,
                ANTIGRAVITY_NATIVE_BRIDGE_ID_LABEL_KEY="antigravity-label",
                BRIDGE_ID_LABEL_KEY="claude-label", CODEX_NATIVE_BRIDGE_ID_LABEL_KEY="codex-label",
                OPENCODE_NATIVE_BRIDGE_ID_LABEL_KEY="opencode-label")
        modules["omnigent.inner.native_attachments"] = SimpleNamespace(
            attachment_cache_dir=lambda p: p.parent / "cache")
        def imports(name, *args, **kwargs):
            if name in modules: return modules[name]
            if name == "__future__": return builtins.__import__(name, *args, **kwargs)
            raise AssertionError("unexpected explicit-delete import: " + name)
        namespace = dict(shutil=shutil, _logger=logging.getLogger("fixture-explicit"),
                         __builtins__=dict(vars(builtins), __import__=imports))
        fn = ast_function(CAPTURED / "runner/native/orchestration.py", "_delete_native_bridge_dirs")
        exec("from __future__ import annotations\n" + fn, namespace)
        asyncio.run(namespace["_delete_native_bridge_dirs"](server_client=None, session_id="owned-session"))
        for family in families:
            self.assertEqual(list((self.base / "explicit" / family).iterdir()), [])

    def test_old_rollout_is_preserved(self):
        path = self.write("codex-home/sessions/2026/10/01/rollout-old.jsonl")
        self.assertTrue(age_predicate(self.common)(self.bridge))
        self.assertEqual(self.prune(), 0)
        self.assertEqual(path.read_bytes(), b"private fixture only\n")

    def test_old_dead_letter_without_sessions_is_preserved(self):
        path = self.write("dead_letter.jsonl.1")
        self.assertTrue(age_predicate(self.common)(self.bridge))
        self.assertEqual(self.prune(), 0)
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
