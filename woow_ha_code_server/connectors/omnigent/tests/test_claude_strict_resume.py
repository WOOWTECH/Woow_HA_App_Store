import ast
import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).parents[1]
SID = "original_session_0123456789"
NID = "01234567-89ab-4cde-8f01-23456789abcd"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


native = load("claude_strict_test_native", "claude_strict_resume.py")
patcher = load("claude_strict_test_patch", "patch-claude-strict-resume.py")
cold = load("native_strict_test_bootstrap", "native_strict_bootstrap.py")


class Fixture:
    def setup_fixture(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "claude"
        self.root.mkdir()
        self.workspace = self.base / "work"
        self.workspace.mkdir()
        self.path = native.transcript_path(self.root, self.workspace, NID)
        self.path.parent.mkdir(parents=True)
        self.raw = b"".join((json.dumps({"sessionId": NID, "type": typ, "cwd": str(self.workspace / child),
            "message": {"content": content}}) + "\n").encode() for typ, child, content in [
                ("user", "", "original prompt"), ("assistant", "projects", "original reply")])
        self.path.write_bytes(self.raw)
        self.trust = self.root / ".claude.json"
        self.trust.write_text(json.dumps({"hasCompletedOnboarding": True,
            "projects": {str(self.workspace): {"hasTrustDialogAccepted": True}}, "unrelated": "preserve"}))
        self.body = {"woow_strict_claude_resume": True, "ensure_native_terminal": True,
            "terminal": "claude", "session_key": "main", "expected_external_session_id": NID,
            "expected_workspace": str(self.workspace)}
        self.info = {"id": SID, "harness": "claude-native", "status": "idle",
            "external_session_id": NID, "workspace": str(self.workspace), "labels": {}}
        self.busy = False
        self.epoch = 3
        empty_proc = self.base / "empty-proc"
        empty_proc.mkdir()
        original = native.assert_no_matching_process
        proc_patch = patch.object(native, "assert_no_matching_process", side_effect=lambda sid, cwd, **kw:
            original(sid, cwd, proc_root=kw.get("proc_root", empty_proc)))
        proc_patch.start()
        self.addCleanup(proc_patch.stop)

    def plan(self):
        return native.prepare_plan(SID, self.body, self.info, busy=lambda: self.busy,
            epoch=lambda: self.epoch, root=self.root)

    def code(self, code, fn):
        with self.assertRaisesRegex(native.StrictResumeError, "^" + code + "$"):
            fn()


class Validation(Fixture, unittest.TestCase):
    def setUp(self):
        self.setup_fixture()

    def test_exact_existing_bytes_id_workspace_and_trust_never_written(self):
        before = self.trust.read_bytes()
        plan = self.plan()
        self.assertEqual(plan.resume_existing(NID, None, False), self.path)
        plan.before_launch("claude", ("--resume", NID, "--model", "opus"), self.workspace, False)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(self.trust.read_bytes(), before)
        self.assertEqual(plan.sha256, hashlib.sha256(self.raw).hexdigest())

    def test_missing_empty_partial_json_and_foreign_native_id_refuse(self):
        self.path.unlink()
        self.code("STRICT_NATIVE_FILE_UNAVAILABLE", self.plan)
        self.path.write_bytes(b"")
        self.code("STRICT_NATIVE_FILE_INVALID", self.plan)
        self.path.write_bytes(self.raw[:-1])
        self.code("STRICT_NATIVE_FILE_INVALID", self.plan)
        self.path.write_bytes(self.raw.replace(NID.encode(), b"different-id"))
        self.code("STRICT_NATIVE_ID_CHANGED", self.plan)

    def test_symlink_or_world_writable_transcript_refused(self):
        self.path.chmod(0o666)
        self.code("STRICT_NATIVE_FILE_UNSAFE", self.plan)
        self.path.chmod(0o600)
        other = self.path.with_suffix(".original")
        self.path.rename(other)
        self.path.symlink_to(other)
        self.code("STRICT_NATIVE_FILE_UNAVAILABLE", self.plan)

    def test_parent_symlink_refused(self):
        parent = self.path.parent
        original = parent.with_name(parent.name + "-original")
        parent.rename(original)
        parent.symlink_to(original, target_is_directory=True)
        self.code("STRICT_NATIVE_FILE_UNSAFE", self.plan)

    def test_no_auto_accept_trust(self):
        self.trust.write_text("{}")
        self.code("STRICT_EXISTING_TRUST_REQUIRED", self.plan)
        self.assertEqual(self.trust.read_text(), "{}")

    def test_authoritative_bindings_and_shape(self):
        self.body["expected_external_session_id"] = "other"
        self.code("STRICT_NATIVE_ID_CHANGED", self.plan)
        self.body["expected_external_session_id"] = NID
        self.info["workspace"] = "/"
        self.code("STRICT_WORKSPACE_MISMATCH", self.plan)
        self.info["workspace"] = str(self.workspace)
        self.body["ensure_native_terminal"] = False
        self.code("STRICT_REQUEST_INVALID", self.plan)

    def test_active_turn_and_changed_epoch_prevent_launch(self):
        plan = self.plan()
        self.busy = True
        self.code("SESSION_BUSY", plan.check_cold)
        self.busy = False
        self.epoch += 1
        self.code("SESSION_BUSY", plan.check_cold)

    def test_append_only_after_launch_and_original_prefix_immutable(self):
        plan = self.plan()
        self.path.write_bytes(self.raw + b'{"type":"progress"}\n')
        self.code("STRICT_NATIVE_FILE_CHANGED", plan.check_cold)
        plan.check_prefix(allow_append=True)
        self.path.write_bytes(b"changed" + self.raw[7:])
        self.code("STRICT_NATIVE_FILE_CHANGED", lambda: plan.check_prefix(allow_append=True))

    def test_file_replacement_even_same_bytes_refused(self):
        plan = self.plan()
        self.path.rename(self.path.with_suffix(".old"))
        self.path.write_bytes(self.raw)
        self.code("STRICT_NATIVE_FILE_CHANGED", plan.check_cold)

    def test_no_fresh_fork_rewind_or_ambiguous_argv(self):
        plan = self.plan()
        self.code("STRICT_NATIVE_ID_CHANGED", lambda: plan.resume_existing(NID, "fork", False))
        for forbidden in ["--fork-session", "--session-id=x", "--continue", "-p", "--resume=" + NID, "--rewind-files=x", "-r"]:
            with self.subTest(arg=forbidden):
                self.code("STRICT_LAUNCH_CONFIG_CHANGED", lambda: plan.before_launch("claude", ("--resume", NID, forbidden), self.workspace, False))
        self.code("STRICT_NATIVE_ID_CHANGED", lambda: plan.before_launch("claude", ("--resume",), self.workspace, False))
        self.code("STRICT_LAUNCH_CONFIG_CHANGED", lambda: plan.before_launch("custom-wrapper", ("--resume", NID), self.workspace, False))
        self.code("STRICT_LAUNCH_CONFIG_CHANGED", lambda: plan.before_launch("claude", ("--resume", NID), self.workspace, True))
        plan.before_launch("/home/coder/.local/share/claude/versions/2.1.285", ("--resume", NID), self.workspace, False)

    def test_collision_guard_all_observed_and_installer_launch_forms(self):
        proc = self.base / "proc"
        proc.mkdir()
        entry = proc / "12345678"
        entry.mkdir()
        (entry / "cwd").symlink_to(self.workspace, target_is_directory=True)
        examples = [
            ([b"claude", b"--resume", NID.encode()], "/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"),
            ([b"2.1.285", b"--resume=" + NID.encode()], "/home/coder/.local/share/claude/versions/2.1.285"),
            ([b"/home/coder/.local/share/claude/versions/2.1.285"], "/home/coder/.local/share/claude/versions/2.1.285"),
            ([b"node", b"/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"], "/usr/bin/node"),
            ([b"claude-native"], "/usr/local/bin/claude-native"),
        ]
        for args, executable in examples:
            with self.subTest(args=args):
                (entry / "cmdline").write_bytes(b"\0".join(args) + b"\0")
                (entry / "exe").unlink(missing_ok=True)
                (entry / "exe").symlink_to(executable)
                self.code("STRICT_NATIVE_ALREADY_RUNNING", lambda: native.assert_no_matching_process(NID, self.workspace, proc_root=proc))
        (entry / "cmdline").write_bytes(b"node\0project-server.mjs\0")
        (entry / "exe").unlink()
        (entry / "exe").symlink_to("/usr/bin/node")
        native.assert_no_matching_process(NID, self.workspace, proc_root=proc)

    def test_native_reservation_blocks_second_owner(self):
        plan = self.plan()
        with native.reserve_native(plan):
            with self.assertRaisesRegex(native.StrictResumeError, "SESSION_BUSY"):
                with native.reserve_native(plan):
                    self.fail("second reservation admitted")

    def test_cleared_authoritative_bridge_is_bound(self):
        self.info["labels"]["omnigent.claude_native.bridge_id"] = SID + "-cleared"
        plan = self.plan()
        self.assertEqual(plan.bridge_id, SID + "-cleared")
        plan.bind_bridge(SID + "-cleared")
        self.code("STRICT_BRIDGE_ID_CHANGED", lambda: plan.bind_bridge(SID))


def extract(source, names, namespace):
    """Execute actual pinned function bodies without importing unrelated SDKs."""
    parsed = ast.parse(source)
    nodes = []
    for name in names:
        matches = [n for n in ast.walk(parsed) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name]
        if len(matches) != 1:
            raise AssertionError("pinned source seam changed: " + name)
        nodes.append(matches[0])
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), "actual-pinned-omnigent-0.16", "exec"), namespace)


class PinnedComposition(Fixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_fixture()
        fixture = os.environ.get("OMNIGENT_TEST_SITE_PACKAGES")
        if not fixture:
            self.skipTest("Set OMNIGENT_TEST_SITE_PACKAGES to pristine 0.16.0 source fixture")
        self.site = self.base / "vendor"
        for name in patcher.HASHES:
            p = self.site / "omnigent" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(fixture) / "omnigent" / name, p)
        meta = self.site / "omnigent-0.16.0.dist-info/METADATA"
        meta.parent.mkdir()
        meta.write_text("Name: omnigent\nVersion: 0.16.0\n")
        patcher.patch(self.site)
        self.app = (self.site / "omnigent/runner/app.py").read_text()
        self.orch = (self.site / "omnigent/runner/native/orchestration.py").read_text()
        self.ns = {"dataclasses": dataclasses, "asyncio": asyncio, "_logger": Mock(), "debug_event": lambda *a, **kw: kw}
        extract(self.orch, ["NativeLaunchContext", "PreLaunchResult"], self.ns)
        self.registry = Mock()
        self.registry.get_terminal_resource = AsyncMock(return_value=None)
        self.registry.terminal_registry.get.return_value = None
        self.registry.terminal_registry.cleanup_conversation = AsyncMock()
        self.ctx = self.ns["NativeLaunchContext"](SID, self.registry, Mock(), server_client=Mock())
        self.modules = patch.dict(sys.modules, {"omnigent.runner.native.woow_claude_strict_resume": native})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    async def test_actual_ensure_build_context_and_adapter_preserve_plan(self):
        plan = self.plan()
        spec = types.SimpleNamespace(name="existing-agent", skills_filter="all")
        self.ns.update({"session_id": SID, "_resolve_session_spec_entry": AsyncMock(return_value=spec),
            "_unwrap_resolved_spec": lambda obj: obj, "_resolved_spec_workdir": lambda obj: self.workspace,
            "auth_token_factory": Mock(), "_record_session_claude_launch_config": Mock(),
            "_auto_create_claude_terminal": AsyncMock(return_value="terminal"),
            "_resolve_session_claude_launch_config": AsyncMock()})
        extract(self.app, ["_claude_ensure_build"], self.ns)
        extract(self.orch, ["_launch_claude"], self.ns)
        enriched = await self.ns["_claude_ensure_build"](dataclasses.replace(self.ctx, woow_strict_resume=plan))
        self.assertIs(enriched.woow_strict_resume, plan)
        self.assertEqual(await self.ns["_launch_claude"](enriched), "terminal")
        self.assertIs(self.ns["_auto_create_claude_terminal"].call_args.kwargs["woow_strict_resume"], plan)
        ordinary = await self.ns["_claude_ensure_build"](self.ctx)
        self.assertIsNone(ordinary.woow_strict_resume)

    async def test_actual_launch_checks_before_existing_cleanup_and_preserves_after_build(self):
        plan = self.plan()
        adapter = AsyncMock(return_value="terminal")
        self.ns.update({"native_coding_agent_for_harness": lambda _: types.SimpleNamespace(key="claude", terminal_name="claude", display_name="Claude"),
            "native_provider_for_key": lambda _: object(), "resolve_hook": lambda *args: adapter,
            "_publish_terminal_pending": Mock(), "_publish_native_terminal_start_error": Mock()})
        extract(self.orch, ["_launch_native_terminal"], self.ns)
        build = AsyncMock(side_effect=lambda ctx: dataclasses.replace(ctx, agent_name="same-agent"))
        strict_ctx = dataclasses.replace(self.ctx, woow_strict_resume=plan)
        self.assertTrue(await self.ns["_launch_native_terminal"]("claude-native", strict_ctx,
            ensure_locks={}, build_context=build, reraise=True))
        self.assertIs(adapter.call_args.args[0].woow_strict_resume, plan)
        self.registry.terminal_registry.get.return_value = "existing"
        pre = AsyncMock(return_value=self.ns["PreLaunchResult"](force_recreate=True))
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_ALREADY_RUNNING"):
            await self.ns["_launch_native_terminal"]("claude-native", strict_ctx, ensure_locks={}, pre_launch=pre)
        pre.assert_not_called()
        self.registry.terminal_registry.cleanup_conversation.assert_not_called()
        # Original non-strict fork/rebuild behavior still invokes its callback.
        await self.ns["_launch_native_terminal"]("claude-native", self.ctx, ensure_locks={}, pre_launch=pre)
        pre.assert_awaited_once()
        self.registry.terminal_registry.cleanup_conversation.assert_awaited_once_with(SID)

    async def test_actual_creator_strict_branch_never_enters_synthesis_or_fallback(self):
        # Execute the exact native persistence branch, including its normal
        # fallback block. The stub is adversarial: synthesis would erase history.
        function = next(n for n in ast.walk(ast.parse(self.orch)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_auto_create_claude_terminal")
        branch = next(n for n in function.body if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
            and ast.unparse(n.test) == "woow_strict_resume is not None"
            and any(isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_transcript" for t in x.targets) for x in n.body))
        wrapper = ast.parse("async def actual_branch():\n    pass\n").body[0]
        wrapper.body = [branch, ast.parse("return resume_external_session_id, resume_prefix_bytes").body[0]]
        tree = ast.Module(body=[wrapper], type_ignores=[])
        ns = {"woow_strict_resume": self.plan(), "session_external_id": NID,
            "fork_source_external_id": None, "fork_carry_history": False, "server_client": object()}
        exec(compile(ast.fix_missing_locations(tree), "actual-native-persistence-branch", "exec"), ns)
        resumed, prefix = await ns["actual_branch"]()
        self.assertEqual(resumed, NID)
        self.assertEqual(prefix, len(self.raw))
        self.assertEqual(self.path.read_bytes(), self.raw)

    async def test_failed_explicit_bootstrap_cannot_fall_into_later_ordinary_ensure(self):
        self.ns["os"] = os
        self.ns["_cancel_auto_forwarder_task"] = AsyncMock()
        for name in ("_auto_create_claude_terminal", "_auto_create_pi_terminal"):
            extract(self.orch, [name], self.ns)
            with patch.dict(os.environ, {cold.ENV: "/private/pending-request.json"}), \
                self.assertRaisesRegex(native.StrictResumeError, "STRICT_BOOTSTRAP_REQUIRED"):
                await self.ns[name](SID, self.registry, Mock(), server_client=Mock())
        self.ns["_cancel_auto_forwarder_task"].assert_not_called()

    def test_patch_idempotence_and_forged_receipt_cannot_bless_drift(self):
        before = {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()}
        self.assertEqual(patcher.patch(self.site)["state"], "already-applied")
        self.assertEqual(before, {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()})
        name = "runner/app.py"
        target = self.site / "omnigent" / name
        target.write_text(target.read_text() + "\n# malicious drift\n")
        receipt = self.site / "omnigent" / patcher.RECEIPT
        value = json.loads(receipt.read_text())
        value["targets"][name]["patched"] = patcher.digest(target.read_bytes())
        receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "STRICT_PATCH_SOURCE_MISMATCH"):
            patcher.patch(self.site)

    def test_capability_probe_is_readonly_and_requires_actual_installed_patch(self):
        self.assertIn('terminal_id == "woow-strict-resume-capability-v1"', self.app)
        # Shared initial dispatch happens before the normal auto-create call.
        self.assertIn('_launch_callable = strict_cold_launch', self.app)
        self.assertIn('if os.environ.get("WOOW_NATIVE_STRICT_RESUME_REQUEST"):', self.app)


class Attachment(Fixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_fixture()

    def actual_process_fixture(self, plan):
        plan.before_launch("claude", ("--resume", NID), self.workspace, False)
        plan.launch_start_ticks = 1000
        self.directory = self.base / plan.bridge_id
        self.directory.mkdir()
        settings = self.directory / "claude-settings.json"
        settings.write_text(json.dumps({"hooks": {key: [{"command": str(self.directory) + "/hook"}]
            for key in ("SessionStart", "Stop")}}))
        settings.chmod(0o600)
        self.proc = self.base / "attachment-proc"
        self.proc.mkdir()
        self.process = self.proc / "123"
        self.process.mkdir()
        fields = ["S"] + ["0"] * 18 + ["1001"]
        (self.process / "stat").write_text("123 (claude) " + " ".join(fields))
        self.args = [b"claude", b"--resume", NID.encode(), b"--settings", str(settings).encode()]
        (self.process / "cmdline").write_bytes(b"\0".join(self.args) + b"\0")
        (self.process / "environ").write_bytes(b"")
        (self.process / "cwd").symlink_to(self.workspace)
        executable = self.base / "claude.exe"
        executable.touch()
        (self.process / "exe").symlink_to(executable)
        children = self.process / "task/123"
        children.mkdir(parents=True)
        (children / "children").write_text("")
        self.hook = {"recorded_at": time.time(), "payload": {"hook_event_name": "SessionStart",
            "session_id": NID, "transcript_path": str(self.path)}}
        self.write_hook()
        self.terminal = types.SimpleNamespace(pane_pid_sync=Mock(return_value=123))
        self.registry = types.SimpleNamespace(get_terminal_resource=AsyncMock(return_value={"id": "terminal_claude_main"}),
            terminal_registry=types.SimpleNamespace(get=lambda *args: self.terminal))
        original = native.verify_native_process
        proc_patch = patch.object(native, "verify_native_process", side_effect=lambda *args:
            original(*args, proc_root=self.proc))
        proc_patch.start()
        self.addCleanup(proc_patch.stop)
        bridge = types.SimpleNamespace(bridge_dir_for_bridge_id=lambda value: self.base / value,
            read_claude_session_id=lambda path: NID if path == self.directory else "replacement-native-id",
            read_active_session_id=lambda path: SID if path == self.directory else "replacement-session")
        modules = {"omnigent.harnesses.claude_native": types.SimpleNamespace(bridge=bridge),
            "omnigent.entities.session_resources": types.SimpleNamespace(terminal_resource_id=lambda *args: "terminal_claude_main")}
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)

    def write_hook(self):
        (self.directory / "hooks.jsonl").write_text(json.dumps(self.hook) + "\n")

    async def test_cleared_original_receipt_ignores_live_replacement_default_bridge(self):
        self.info["labels"]["omnigent.claude_native.bridge_id"] = SID + "-cleared"
        plan = self.plan()
        self.actual_process_fixture(plan)
        receipt = await native.confirm_attachment(plan, self.registry)
        self.assertEqual(receipt["bridgeId"], SID + "-cleared")
        self.assertEqual(receipt["nativeSessionId"], NID)
        self.assertFalse(receipt["toolsVerified"])
        self.assertTrue(receipt["historyPrefixPreserved"])
        self.assertTrue(receipt["currentNativeVerified"])
        self.assertEqual((receipt["nativePid"], receipt["nativeStartTicks"]), (123, 1001))
        self.assertGreaterEqual(receipt["sessionStartRecordedAt"], receipt["launchStartedAt"])

    async def test_alive_registered_tmux_with_dead_or_non_native_process_refuses(self):
        plan = self.plan()
        self.actual_process_fixture(plan)
        state = self.process / "stat"
        state.write_text(state.read_text().replace("(claude) S", "(claude) Z"))
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_PROCESS_UNAVAILABLE"):
            await native.confirm_attachment(plan, self.registry)
        state.write_text(state.read_text().replace("(claude) Z", "(claude) S"))
        (self.process / "cmdline").write_bytes(b"node\0project-server.mjs\0")
        (self.process / "exe").unlink()
        (self.process / "exe").symlink_to(self.path)
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_PROCESS_UNAVAILABLE"):
            await native.confirm_attachment(plan, self.registry)

    async def test_prior_process_generation_and_foreign_resume_are_not_attached(self):
        plan = self.plan()
        self.actual_process_fixture(plan)
        plan.launch_start_ticks = 1002
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_GENERATION_CHANGED"):
            await native.confirm_attachment(plan, self.registry)
        plan.launch_start_ticks = 1000
        (self.process / "cmdline").write_bytes(b"\0".join(self.args).replace(NID.encode(), b"wrong-native"))
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_ID_CHANGED"):
            await native.confirm_attachment(plan, self.registry)

    async def test_foreign_bridge_env_and_settings_binding_refused(self):
        plan = self.plan()
        self.actual_process_fixture(plan)
        (self.process / "environ").write_bytes(b"HARNESS_CLAUDE_NATIVE_BRIDGE_DIR=" + str(self.base).encode())
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_BINDING_CHANGED"):
            await native.confirm_attachment(plan, self.registry)
        (self.process / "environ").write_bytes(b"")
        (self.directory / "claude-settings.json").write_text('{"hooks":{}}')
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_BINDING_CHANGED"):
            await native.confirm_attachment(plan, self.registry)

    async def test_old_hook_or_foreign_transcript_never_confirms_new_process(self):
        plan = self.plan()
        self.actual_process_fixture(plan)
        for field, value in [("recorded_at", plan.launch_started_at - 1), ("transcript_path", str(self.trust))]:
            if field == "recorded_at":
                self.hook[field] = value
            else:
                self.hook["recorded_at"] = time.time()
                self.hook["payload"][field] = value
            self.write_hook()
            with self.assertRaisesRegex(native.StrictResumeError, "STRICT_ATTACH_UNCONFIRMED"):
                await native.confirm_attachment(plan, self.registry, timeout=0.01)

    async def test_pane_exit_between_probe_and_receipt_refuses(self):
        plan = self.plan()
        self.actual_process_fixture(plan)
        self.terminal.pane_pid_sync.side_effect = [123, None]
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_NATIVE_GENERATION_CHANGED"):
            await native.confirm_attachment(plan, self.registry)

    async def test_hook_state_without_registered_live_terminal_is_not_success(self):
        plan = self.plan()
        bridge = types.SimpleNamespace(bridge_dir_for_bridge_id=lambda value: self.base / value,
            read_claude_session_id=lambda path: NID, read_active_session_id=lambda path: SID)
        with patch.dict(sys.modules, {"omnigent.harnesses.claude_native": types.SimpleNamespace(bridge=bridge),
            "omnigent.entities.session_resources": types.SimpleNamespace(terminal_resource_id=lambda *a: "terminal")}), \
            self.assertRaisesRegex(native.StrictResumeError, "STRICT_ATTACH_UNCONFIRMED"):
            await native.confirm_attachment(plan, types.SimpleNamespace(get_terminal_resource=AsyncMock(return_value=None)))


class ColdRequest(Fixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_fixture()
        self.private = self.base / "requests"
        self.private.mkdir(mode=0o700)
        self.file = self.private / "original.json"
        self.value = {"version": 1, "engine": "claude", "sessionId": SID, "nativeSessionId": NID,
            "workspace": str(self.workspace), "originalBytes": len(self.raw),
            "originalSHA256": hashlib.sha256(self.raw).hexdigest(), "requestId": "a" * 32,
            "issuedAt": time.time() - 10, "expiresAt": time.time() + 120}
        self.write()
        self.module = patch.dict(sys.modules, {"omnigent.runner.native.woow_claude_strict_resume": native})
        self.module.start()
        self.addCleanup(self.module.stop)

    def write(self):
        self.file.write_text(json.dumps(self.value))
        self.file.chmod(0o600)

    def test_owner_bound_short_lived_request_and_atomic_reservation(self):
        fd, value, digest = cold.read_request(self.file)
        try:
            self.assertEqual(value, self.value)
            self.assertEqual(digest, hashlib.sha256(self.file.read_bytes()).hexdigest())
            self.code("SESSION_BUSY", lambda: cold.read_request(self.file))
        finally:
            os.close(fd)

    def test_expired_shared_directory_and_world_readable_requests_refused(self):
        self.value["expiresAt"] = time.time() - 1
        self.write()
        self.code("STRICT_REQUEST_EXPIRED", lambda: cold.read_request(self.file))
        self.value["expiresAt"] = time.time() + 120
        self.write()
        self.file.chmod(0o644)
        self.code("STRICT_REQUEST_UNSAFE", lambda: cold.read_request(self.file))

    async def cold_call(self, **options):
        @dataclasses.dataclass(frozen=True)
        class Context:
            session_id: str
            server_client: object
            resource_registry: object
            woow_strict_resume: object = None
        response = types.SimpleNamespace(status_code=200, json=lambda: self.info)
        ctx = Context(SID, types.SimpleNamespace(get=AsyncMock(return_value=response)), types.SimpleNamespace(
            session_turn_is_active=lambda _: self.busy, session_activity_epoch=lambda _: self.epoch))
        self.launch = AsyncMock(return_value=True)
        self.confirm = AsyncMock(return_value={"state": "attached", "sessionId": SID, "nativeSessionId": NID,
            "historyPrefixPreserved": True, "toolsVerified": False})
        modules = {"omnigent.runner.native.orchestration": types.SimpleNamespace(_launch_native_terminal=self.launch)}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {cold.ENV: str(self.file), "CLAUDE_CONFIG_DIR": str(self.root)}), \
            patch.object(native, "confirm_attachment", self.confirm):
            return await cold.strict_cold_launch("claude-native", ctx, ensure_locks={}, pre_launch=Mock())

    async def test_actual_cold_dispatch_binds_plan_and_durable_receipt(self):
        self.assertTrue(await self.cold_call())
        args, kwargs = self.launch.call_args
        self.assertIsInstance(args[1].woow_strict_resume, native.StrictPlan)
        self.assertIsNone(kwargs["pre_launch"])
        self.assertTrue(kwargs["reraise"])
        self.confirm.assert_awaited_once()
        receipt = json.loads(self.file.with_name(self.file.name + ".attached.json").read_text())
        self.assertEqual(receipt["nativeSessionId"], NID)
        self.assertFalse(receipt["toolsVerified"])
        self.assertEqual(self.path.read_bytes(), self.raw)
        with self.assertRaisesRegex(native.StrictResumeError, "STRICT_REQUEST_ALREADY_USED"):
            await self.cold_call()
        self.launch.assert_not_called()

    async def test_cold_wrong_id_hash_busy_refuse_before_any_normal_launch(self):
        for field, value, code in [("sessionId", "wrong_session", "STRICT_SESSION_INVALID"),
            ("nativeSessionId", "wrong-native", "STRICT_NATIVE_ID_CHANGED"),
            ("originalSHA256", "b" * 64, "STRICT_NATIVE_FILE_CHANGED")]:
            original = self.value[field]
            self.value[field] = value
            self.write()
            with self.assertRaisesRegex(native.StrictResumeError, code):
                await self.cold_call()
            self.launch.assert_not_called()
            self.value[field] = original
        self.write()
        self.busy = True
        with self.assertRaisesRegex(native.StrictResumeError, "SESSION_BUSY"):
            await self.cold_call()
        self.launch.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.file.chmod(0o600)
        self.private.chmod(0o755)
        self.code("STRICT_REQUEST_UNSAFE", lambda: cold.read_request(self.file))


if __name__ == "__main__":
    unittest.main()
