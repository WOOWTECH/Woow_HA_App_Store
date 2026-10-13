#!/usr/bin/env python3
"""SQLite regressions on reviewed upstream excerpts, or a complete image SessionDB.

Default: narrow fixtures with an explicit SQLite transaction/guard harness.
--runtime-root: real SessionDB, schema, transactions, guards and file cleanup.
Both modes use only newly created synthetic databases under --temp-root.
"""
import argparse
import hashlib
import importlib.util
import inspect
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gc_patch", HERE.parent / "patches/scoped-prompt-gc.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class MetadataResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_types = []

    def addError(self, test, err):
        self.error_types.append({"case": test.id(), "type": err[0].__name__, "name": getattr(err[1], "name", None)})
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err and not issubclass(err[0], test.failureException):
            self.error_types.append({"case": subtest.id(), "type": err[0].__name__, "name": getattr(err[1], "name", None)})
        super().addSubTest(test, subtest, err)


class FixtureDB:
    """Only connection/schema/guard adapters are doubles; deletion SQL is upstream."""
    def __init__(self, path):
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript('''
            CREATE TABLE system_prompts(hash TEXT PRIMARY KEY, prompt TEXT NOT NULL);
            CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, session_key TEXT, started_at REAL,
                ended_at REAL, end_reason TEXT, model_config TEXT, tool_names TEXT,
                parent_session_id TEXT REFERENCES sessions(id), system_prompt_hash TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT REFERENCES sessions(id),
                role TEXT, content TEXT, timestamp REAL);
        ''')
        self.guarded = set()

    def _execute_write(self, callback):
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            value = callback(self._conn)
            self._conn.commit()
            return value
        except BaseException:
            self._conn.rollback()
            raise

    def _guarded_ids(self, conn, ids):
        return self.guarded.intersection(ids)

    def close(self):
        self._conn.close()


class DeletionCases(unittest.TestCase):
    factory = None
    split = False
    runtime = False
    root = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.db"
        self.files = Path(self.temp.name) / "transcripts"
        self.files.mkdir()
        self.db = self.factory(self.path)
        self.addCleanup(self.db.close)
        self.orphan = self.prompt("unrelated-orphan")
        self.orphan2 = self.prompt("other-orphan")
        self.add("unrelated", "referenced-control")

    def write(self, sql, values=()):
        return self.db._execute_write(lambda conn: conn.execute(sql, values).rowcount)

    def prompt(self, text):
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.write("INSERT OR IGNORE INTO system_prompts(hash,prompt) VALUES(?,?)", (digest, text))
        return digest

    def add(self, sid, prompt=None, parent=None, reason="done", config=None, source="cli"):
        digest = self.prompt(prompt) if prompt is not None else None
        self.write("INSERT INTO sessions(id,source,started_at,ended_at,end_reason,model_config,parent_session_id,system_prompt_hash) VALUES(?,?,1,2,?,?,?,?)",
                   (sid, source, reason, json.dumps(config or {}), parent, digest))
        self.write("INSERT INTO messages(session_id,role,content,timestamp) VALUES(?,'user','synthetic',1)", (sid,))
        (self.files / (sid + ".json")).write_text("synthetic")
        return digest

    def rows(self, table):
        with sqlite3.connect(self.path) as conn:
            return conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()

    def snapshot(self):
        return {table: self.rows(table) for table in ("sessions", "messages", "system_prompts")}

    def hashes(self):
        return {row[0] for row in self.rows("system_prompts")}

    def ids(self):
        return {row[0] for row in self.rows("sessions")}

    def assert_preserved(self):
        self.assertTrue({self.orphan, self.orphan2} <= self.hashes())
        self.assertIn("unrelated", self.ids())
        self.assertTrue((self.files / "unrelated.json").exists())
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def delete(self, ids, batch=False, **kwargs):
        if batch:
            return self.db.delete_sessions(ids, sessions_dir=self.files, **kwargs)
        return self.db.delete_session(ids[0], sessions_dir=self.files, **kwargs)

    def guard(self, sid):
        if self.runtime:
            self.assertTrue(self.db.try_acquire_compression_lock(sid, "synthetic-guard"))
        else:
            self.db.guarded.add(sid)

    def test_single_reclaims_only_owned_prompt(self):
        owned = self.add("owned", "owned-only")
        control = self.snapshot()["messages"]
        self.assertIs(self.delete(["owned"]), True)
        self.assertNotIn(owned, self.hashes())
        self.assertEqual(self.ids(), {"unrelated"})
        self.assertEqual(self.rows("messages"), [row for row in control if row[1] == "unrelated"])
        self.assertFalse((self.files / "owned.json").exists())
        self.assert_preserved()

    def test_no_prompt_does_not_collect_orphans(self):
        self.add("owned")
        before = self.hashes()
        self.assertIs(self.delete(["owned"]), True)
        self.assertEqual(self.hashes(), before)

    def test_shared_prompt_survives_until_last_reference(self):
        shared = self.add("owned", "shared")
        self.add("survivor", "shared")
        self.delete(["owned"])
        self.assertIn(shared, self.hashes())
        self.assertIn("survivor", self.ids())
        self.delete(["survivor"])
        self.assertNotIn(shared, self.hashes())
        self.assert_preserved()

    def test_batch_counts_deduplicates_and_preserves_controls(self):
        owned = self.add("one", "owned-only")
        shared = self.add("two", "shared")
        self.add("survivor", "shared")
        self.assertEqual(self.delete(["one", "two", "one", "missing", None, 7, ""], batch=True), 2)
        self.assertNotIn(owned, self.hashes())
        self.assertIn(shared, self.hashes())
        self.assertEqual(self.ids(), {"survivor", "unrelated"})
        self.assert_preserved()

    def test_delegate_cascade_and_branch_preservation(self):
        for batch in (False, True):
            with self.subTest(batch=batch):
                prefix = "batch" if batch else "single"
                owned = self.add(prefix, prefix)
                delegate = self.add(prefix+"-delegate", prefix+"-delegate", parent=prefix, config={"_delegate_from": prefix})
                nested = self.add(prefix+"-nested", prefix+"-nested", config={"_delegate_from": prefix+"-delegate"})
                branch = self.add(prefix+"-branch", "surviving-branch", parent=prefix+"-delegate", config={"_branched_from": prefix+"-delegate"})
                self.delete([prefix], batch=batch)
                self.assertTrue({owned, delegate, nested}.isdisjoint(self.hashes()))
                self.assertIn(branch, self.hashes())
                with sqlite3.connect(self.path) as conn:
                    self.assertIsNone(conn.execute("SELECT parent_session_id FROM sessions WHERE id=?", (prefix+"-branch",)).fetchone()[0])
                self.assert_preserved()

    def test_absent_empty_invalid_and_repeat_are_noops(self):
        before = self.snapshot()
        self.assertIs(self.delete(["missing"]), False)
        for ids in ([], ["missing"], ["", None, 5]):
            self.assertEqual(self.delete(ids, batch=True), 0)
        self.assertEqual(self.snapshot(), before)
        self.add("owned", "owned-only")
        self.delete(["owned"])
        after = self.snapshot()
        self.assertIs(self.delete(["owned"]), False)
        self.assertEqual(self.snapshot(), after)
        self.assert_preserved()

    def test_expected_delete_set_mismatch_changes_nothing(self):
        self.add("owned", "owned-only")
        self.add("delegate", "delegate-only", config={"_delegate_from": "owned"})
        before = self.snapshot()
        self.assertIs(self.delete(["owned"], expected_delete_ids=["owned"]), False)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.files / "owned.json").exists())
        self.assertIs(self.delete(["owned"], expected_delete_ids=["owned", "delegate"]), True)
        self.assert_preserved()

    def test_gc_failure_rolls_back_sessions_messages_prompts_and_files(self):
        for batch in (False, True):
            with self.subTest(batch=batch):
                prefix = "batch" if batch else "single"
                self.add(prefix, prefix)
                self.add(prefix+"-delegate", prefix+"-delegate", config={"_delegate_from": prefix})
                self.write("CREATE TABLE gc_counter(value INTEGER)")
                self.write("INSERT INTO gc_counter VALUES(0)")
                # Fail after two prompt deletions, proving partial GC also rolls back.
                self.write("CREATE TRIGGER fail_gc AFTER DELETE ON system_prompts BEGIN UPDATE gc_counter SET value=value+1; SELECT CASE WHEN (SELECT value FROM gc_counter)=2 THEN RAISE(ABORT,'synthetic failure') END; END")
                before = self.snapshot()
                with self.assertRaises(sqlite3.IntegrityError):
                    self.delete([prefix], batch=batch)
                self.assertEqual(self.snapshot(), before)
                self.assertTrue((self.files / (prefix+".json")).exists())
                self.assertTrue((self.files / (prefix+"-delegate.json")).exists())
                self.assertEqual(self.rows("gc_counter"), [(0,)])
                self.write("DROP TRIGGER fail_gc")
                self.write("DROP TABLE gc_counter")
                self.assert_preserved()

    def test_prompt_capture_and_reclaim_share_transaction(self):
        self.add("owned", "owned-only")
        traces = []
        self.db._conn.set_trace_callback(traces.append)
        self.delete(["owned"])
        self.db._conn.set_trace_callback(None)
        statements = [s.strip().upper() for s in traces]
        captures = [i for i,s in enumerate(statements) if s.startswith("SELECT SYSTEM_PROMPT_HASH")]
        self.assertTrue(captures, "prompt roots must be captured before deletion")
        capture = captures[0]
        deletes = [i for i,s in enumerate(statements) if s.startswith("DELETE FROM SYSTEM_PROMPTS")]
        begin = max(i for i,s in enumerate(statements[:capture]) if s.startswith("BEGIN"))
        commit = next(i for i,s in enumerate(statements) if i > capture and s.startswith("COMMIT"))
        self.assertTrue(deletes and all(begin < capture < i < commit for i in deletes))

    def chain(self, prefix="chain"):
        root = self.add(prefix+"-root", prefix+"-root", reason="compression")
        mid = self.add(prefix+"-mid", prefix+"-mid", parent=prefix+"-root", reason="compression")
        tip = self.add(prefix+"-tip", "chain-shared", parent=prefix+"-mid")
        sibling = self.add(prefix+"-sibling", prefix+"-sibling", parent=prefix+"-root")
        delegate = self.add(prefix+"-delegate", prefix+"-delegate", config={"_delegate_from": prefix+"-mid"})
        self.add(prefix+"-branch", "chain-shared", parent=prefix+"-root", config={"_branched_from": prefix+"-root"})
        self.add(prefix+"-reset", prefix+"-reset", parent=prefix+"-root", config={"_reset_from": prefix+"-root"})
        self.add(prefix+"-tool", prefix+"-tool", parent=prefix+"-root", source="tool")
        return {root, mid, sibling, delegate}, tip

    def require_split(self):
        if not self.split:
            self.skipTest("pinned monolithic image has no compression-chain API")

    def test_chain_from_tip_single_and_batch_reclaims_expanded_set(self):
        self.require_split()
        for batch in (False, True):
            with self.subTest(batch=batch):
                prefix = "batch" if batch else "single"
                owned, shared = self.chain(prefix)
                result = self.delete([prefix+"-tip"], batch=batch, include_compression_chain=True)
                self.assertEqual(result, 1)
                self.assertTrue(owned.isdisjoint(self.hashes()))
                self.assertIn(shared, self.hashes())
                self.assertTrue({prefix+suffix for suffix in ("-root", "-mid", "-tip", "-sibling", "-delegate")}.isdisjoint(self.ids()))
                self.assertTrue({prefix+suffix for suffix in ("-branch", "-reset", "-tool")} <= self.ids())
                self.assert_preserved()

    def test_tool_names_reference_preserves_shared_prompt(self):
        self.require_split()
        shared = self.add("owned", "shared-tool-reference")
        self.add("survivor")
        self.write("UPDATE sessions SET tool_names=? WHERE id='survivor'", (shared,))
        self.delete(["owned"])
        self.assertIn(shared, self.hashes())
        self.delete(["survivor"])
        self.assertNotIn(shared, self.hashes())
        self.assert_preserved()

    def test_owned_tool_names_reclaimed_single_and_batch(self):
        self.require_split()
        for batch in (False, True):
            with self.subTest(batch=batch):
                sid = "batch-tools" if batch else "single-tools"
                self.add(sid)
                tools = self.prompt(sid)
                self.write("UPDATE sessions SET tool_names=? WHERE id=?", (tools, sid))
                self.delete([sid], batch=batch)
                self.assertNotIn(tools, self.hashes())
                self.assert_preserved()

    def test_chain_preserves_external_tool_names_reference(self):
        self.require_split()
        self.chain()
        shared = self.prompt("chain-root")
        self.write("UPDATE sessions SET tool_names=? WHERE id='unrelated'", (shared,))
        self.assertIs(self.delete(["chain-tip"], include_compression_chain=True), True)
        self.assertIn(shared, self.hashes())
        self.assert_preserved()

    def test_default_single_does_not_expand_compression(self):
        self.require_split()
        self.chain()
        self.assertIs(self.delete(["chain-root"]), True)
        self.assertTrue({"chain-mid", "chain-tip", "chain-sibling"} <= self.ids())
        self.assert_preserved()

    def test_chain_guard_filter_preserves_skipped_chain(self):
        self.require_split()
        self.chain()
        self.guard("chain-delegate")
        own = self.add("owned", "owned-only")
        before = self.hashes()
        skipped = []
        self.assertEqual(self.delete(["chain-tip", "owned"], batch=True, include_compression_chain=True,
                                     exclude_active_write_guards=True, skipped_ids=skipped), 1)
        self.assertEqual(skipped, ["chain-tip"])
        self.assertEqual(self.hashes(), before - {own})
        self.assertIn("chain-root", self.ids())
        self.assert_preserved()

    def test_all_guarded_and_absent_chain_are_noops(self):
        self.require_split()
        self.chain()
        self.guard("chain-mid")
        before = self.snapshot()
        self.assertIs(self.delete(["chain-tip"], include_compression_chain=True, exclude_active_write_guards=True), False)
        self.assertIs(self.delete(["absent"], include_compression_chain=True), False)
        self.assertEqual(self.snapshot(), before)

    def test_single_active_guard_raises_without_mutation(self):
        self.require_split()
        self.add("owned", "owned-only")
        self.guard("owned")
        before = self.snapshot()
        with self.assertRaises(self.guard_error):
            self.delete(["owned"], exclude_active_write_guards=True)
        self.assertEqual(self.snapshot(), before)

    def test_chain_gc_error_rolls_back_entire_expansion(self):
        self.require_split()
        self.chain()
        self.write("CREATE TRIGGER fail_gc BEFORE DELETE ON system_prompts BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.delete(["chain-tip"], include_compression_chain=True)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.files / "chain-root.json").exists())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unpatched", action="store_true", help="negative control; expect failures")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--overlay-root", type=Path)
    parser.add_argument("--temp-root", type=Path)
    args = parser.parse_args()
    suite = unittest.TestSuite()
    bindings = {}
    module_hashes = {}
    with tempfile.TemporaryDirectory(dir=args.temp_root) as root:
        os.environ["HERMES_HOME"] = str(Path(root) / "home")
        logging.disable(logging.CRITICAL)
        if args.runtime_root:
            sys.path.insert(0, str(args.runtime_root))
            if args.overlay_root:
                sys.path.insert(0, str(args.overlay_root))
            from hermes_state import SessionDB
            split = "include_compression_chain" in inspect.signature(SessionDB.delete_session).parameters
            source = Path(inspect.getmodule(SessionDB.delete_session).__file__)
            bindings[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
            expected = patcher.SPECS[source.name][0 if args.unpatched else 1]
            if bindings[source.name] != expected:
                raise SystemExit("runtime source differs from reviewed pin")
            if split:
                from hermes_state_errors import SessionActiveWriteGuardError
            else:
                SessionActiveWriteGuardError = RuntimeError
            cls = type("RuntimeDeletionCases", (DeletionCases,), dict(factory=staticmethod(SessionDB), split=split,
                       runtime=True, root=root, guard_error=SessionActiveWriteGuardError))
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
        else:
            provenance = json.loads((HERE / "fixtures/scoped-prompt-gc/provenance.json").read_text())
            for variant in ("monolithic", "split"):
                path = HERE / "fixtures/scoped-prompt-gc" / (variant+".py")
                source = path.read_text()
                digest = hashlib.sha256(source.encode()).hexdigest()
                if digest != provenance[variant]["fixture_sha256"]:
                    raise SystemExit("fixture differs from provenance")
                bindings[variant] = digest
                if not args.unpatched:
                    source = patcher.rewrite_methods(source)
                namespace = {"SessionActiveWriteGuardError": RuntimeError}
                exec(compile(source, str(path), "exec"), namespace)
                factory = type("FixtureSessionDB", (namespace["Methods"], FixtureDB), {})
                cls = type(variant.title()+"DeletionCases", (DeletionCases,), dict(factory=staticmethod(factory),
                           split=variant=="split", root=root, guard_error=RuntimeError))
                suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=MetadataResult).run(suite)
        if args.runtime_root:
            for name, module in tuple(sys.modules.items()):
                filename = getattr(module, "__file__", None)
                if not filename:
                    continue
                path = Path(filename).resolve()
                roots = [args.runtime_root.resolve()] + ([args.overlay_root.resolve()] if args.overlay_root else [])
                if path.suffix == ".py" and any(path.is_relative_to(r) for r in roots):
                    module_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        print(json.dumps({"lane": "full-module" if args.runtime_root else "upstream-excerpts",
                          "unpatched": args.unpatched, "tests": result.testsRun,
                          "failures": [t.id() for t,_ in result.failures], "errors": [t.id() for t,_ in result.errors],
                          "error_types": result.error_types, "skips": len(result.skipped), "passed": result.wasSuccessful(),
                          "source_bindings": bindings, "runtime_module_hashes": module_hashes,
                          "sqlite_version": sqlite3.sqlite_version, "ha_access": False}, sort_keys=True))
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
