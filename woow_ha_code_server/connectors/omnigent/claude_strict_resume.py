"""Explicit cold Claude resume from existing native bytes, never AP synthesis.

Used only by the opt-in, pinned runner patch. Normal ensure/fork/rewind paths do
not import this module. The caller retains central LEVEL_EDIT authorization.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time


class StrictResumeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code):
    raise StrictResumeError(code)


def native_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value
    ):
        fail("STRICT_NATIVE_ID_INVALID")
    return value


def config_root():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).resolve(strict=True)


def transcript_path(root, workspace, sid):
    return root / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(workspace)) / (native_id(sid) + ".jsonl")


def read_native(path, limit=None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o002:
                fail("STRICT_NATIVE_FILE_UNSAFE")
            if info.st_size <= 0 or info.st_size > 128 * 1024 * 1024:
                fail("STRICT_NATIVE_FILE_INVALID")
            raw = stream.read(limit if limit is not None else info.st_size + 1)
            after = os.fstat(stream.fileno())
            if (info.st_size, info.st_mtime_ns, info.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                fail("STRICT_NATIVE_FILE_CHANGED")
            return raw, info
    except StrictResumeError:
        raise
    except (OSError, ValueError):
        fail("STRICT_NATIVE_FILE_UNAVAILABLE")


def validate_records(raw, sid, workspace):
    found_message = False
    found_root = False
    try:
        if not raw.endswith(b"\n"):
            fail("STRICT_NATIVE_FILE_INVALID")
        for line in raw.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                fail("STRICT_NATIVE_FILE_INVALID")
            if row.get("sessionId") is not None and row["sessionId"] != sid:
                fail("STRICT_NATIVE_ID_CHANGED")
            if row.get("type") in ("user", "assistant"):
                if row.get("sessionId") != sid or not isinstance(row.get("message"), dict):
                    fail("STRICT_NATIVE_FILE_INVALID")
                found_message = True
                # A real conversation may cd into child directories. Bind the
                # project to at least one original-root message, not every cwd.
                found_root |= row.get("cwd") == str(workspace)
    except (ValueError, UnicodeDecodeError, TypeError):
        fail("STRICT_NATIVE_FILE_INVALID")
    if not found_message or not found_root:
        fail("STRICT_WORKSPACE_MISMATCH")


def assert_existing_trust(root, workspace):
    try:
        obj = json.loads((root / ".claude.json").read_text())
        accepted = obj.get("hasCompletedOnboarding") is True and obj.get("projects", {}).get(
            str(workspace), {}
        ).get("hasTrustDialogAccepted") is True
    except (OSError, ValueError, AttributeError):
        accepted = False
    if not accepted:
        fail("STRICT_EXISTING_TRUST_REQUIRED")


def claude_executable(value):
    """Recognize the npm binary and the official versioned native installer."""
    path = Path(value)
    return path.name in ("claude", "claude-native", "claude.exe") or (
        path.parent.name == "versions" and path.parent.parent.name == "claude"
        and re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?", path.name) is not None
    )


def process_is_claude(args, executable):
    return bool(args) and (claude_executable(os.fsdecode(args[0]))
        or claude_executable(executable)
        or any(b"@anthropic-ai/claude-code/" in arg for arg in args[:3]))


def assert_no_matching_process(sid, workspace, *, proc_root=Path("/proc")):
    """Reject a separately resumed or same-workspace native CLI; never kill it."""
    for proc in proc_root.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.geteuid():
                continue
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if not args or not args[0]:
                continue
            is_claude = process_is_claude(args, "")
            # Version-only argv0 needs /proc/exe to distinguish the official
            # native installer. Unrelated setuid processes need not expose
            # their executable merely to prove they are not a supported CLI.
            if not is_claude and re.fullmatch(rb"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?", args[0]):
                is_claude = process_is_claude(args, str((proc / "exe").resolve()))
            has_id = any(arg == sid.encode() or arg in (b"--resume=" + sid.encode(), b"-r=" + sid.encode()) for arg in args)
            if is_claude and (has_id or (proc / "cwd").resolve() == workspace.resolve()):
                fail("STRICT_NATIVE_ALREADY_RUNNING")
        except FileNotFoundError:
            continue
        except PermissionError:
            fail("STRICT_PROCESS_CHECK_UNAVAILABLE")


@dataclass
class StrictPlan:
    session_id: str
    native_id: str
    workspace: Path
    root: Path
    path: Path
    size: int
    sha256: str
    inode: tuple
    epoch: int
    busy: object
    current_epoch: object
    bridge_id: str
    launch_started_at: float | None = None
    launch_start_ticks: int | None = None

    def check_prefix(self, *, allow_append=False):
        raw, info = read_native(self.path, self.size if allow_append else None)
        if (info.st_dev, info.st_ino) != self.inode or len(raw) != self.size or hashlib.sha256(raw).hexdigest() != self.sha256:
            fail("STRICT_NATIVE_FILE_CHANGED")
        if not allow_append and info.st_size != self.size:
            fail("STRICT_NATIVE_FILE_CHANGED")

    def check_cold(self):
        if self.busy() or self.current_epoch() != self.epoch:
            fail("SESSION_BUSY")
        self.check_prefix()
        assert_no_matching_process(self.native_id, self.workspace)

    def before_prepare(self, workspace):
        if Path(workspace).resolve() != self.workspace.resolve():
            fail("STRICT_WORKSPACE_MISMATCH")
        self.check_cold()
        assert_existing_trust(self.root, self.workspace)

    def resume_existing(self, external_id, fork_source, fork_carry):
        if external_id != self.native_id or fork_source is not None or fork_carry:
            fail("STRICT_NATIVE_ID_CHANGED")
        self.check_cold()
        return self.path

    def bind_bridge(self, selected):
        if selected != self.bridge_id:
            fail("STRICT_BRIDGE_ID_CHANGED")

    def before_launch(self, command, args, workspace, reset_pick):
        self.before_prepare(workspace)
        executable = shutil.which(command) or command
        if reset_pick or not claude_executable(executable):
            fail("STRICT_LAUNCH_CONFIG_CHANGED")
        args = tuple(args)
        forbidden = {"--fork-session", "--session-id", "--continue", "-c", "--print", "-p", "--resume-session-at", "--rewind-files", "-r"}
        if any(arg.split("=", 1)[0] in forbidden or arg.startswith("--resume=") for arg in args):
            fail("STRICT_LAUNCH_CONFIG_CHANGED")
        if args.count("--resume") != 1 or args[args.index("--resume") + 1:args.index("--resume") + 2] != (self.native_id,):
            fail("STRICT_NATIVE_ID_CHANGED")
        # Capture the actual spawn boundary, not plan creation or a persisted
        # hook's timestamp. /proc uptime and process starttime share boot ticks.
        self.launch_start_ticks = int(float(Path("/proc/uptime").read_text().split()[0]) * os.sysconf("SC_CLK_TCK"))
        self.launch_started_at = time.time()


def prepare_plan(session_id, body, info, *, busy, epoch, root=None):
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
        fail("STRICT_REQUEST_INVALID")
    if body.get("woow_strict_claude_resume") is not True or body.get("ensure_native_terminal") is not True or body.get("terminal") != "claude" or body.get("session_key") != "main":
        fail("STRICT_REQUEST_INVALID")
    if (info.get("harness") or info.get("harness_override")) != "claude-native" or info.get("archived"):
        fail("STRICT_SESSION_INVALID")
    if info.get("status") != "idle" or busy():
        fail("SESSION_BUSY")
    if any(info.get(key) for key in ("active_response_id", "pending_inputs", "pending_elicitations", "terminal_pending")):
        fail("SESSION_BUSY")
    if info.get("id", session_id) != session_id:
        fail("STRICT_SESSION_INVALID")
    sid = native_id(info.get("external_session_id"))
    if body.get("expected_external_session_id") != sid:
        fail("STRICT_NATIVE_ID_CHANGED")
    raw_workspace = info.get("workspace")
    if not isinstance(raw_workspace, str) or not Path(raw_workspace).is_absolute():
        fail("STRICT_WORKSPACE_MISMATCH")
    # Claude keys native projects/trust by the launch spelling, including
    # legitimate mount aliases. Keep that spelling while validating its target.
    workspace = Path(raw_workspace)
    workspace.resolve(strict=True)
    if body.get("expected_workspace") != str(workspace):
        fail("STRICT_WORKSPACE_MISMATCH")
    root = Path(root).resolve(strict=True) if root is not None else config_root()
    path = transcript_path(root, workspace, sid)
    if path.parent.resolve(strict=True) != path.parent:
        fail("STRICT_NATIVE_FILE_UNSAFE")
    raw, meta = read_native(path)
    validate_records(raw, sid, workspace)
    selected_bridge = (info.get("labels") or {}).get("omnigent.claude_native.bridge_id")
    bridge_id = session_id + "-cleared" if selected_bridge == session_id + "-cleared" else session_id
    plan = StrictPlan(session_id, sid, workspace, root, path, len(raw), hashlib.sha256(raw).hexdigest(),
                      (meta.st_dev, meta.st_ino), epoch(), busy, epoch, bridge_id)
    plan.before_prepare(workspace)
    return plan


@contextmanager
def reserve_native(plan):
    directory = plan.root / ".woow-strict-resume"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        fail("STRICT_NATIVE_FILE_UNSAFE")
    fd = os.open(directory / (plan.native_id + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            fail("STRICT_NATIVE_FILE_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("SESSION_BUSY")
        yield
    finally:
        os.close(fd)


def _process_record(pid, *, proc_root=Path("/proc")):
    try:
        path = proc_root / str(pid)
        fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
        if path.stat().st_uid != os.geteuid() or fields[0] in ("Z", "X", "x"):
            fail("STRICT_NATIVE_PROCESS_UNAVAILABLE")
        return {"pid": pid, "startTicks": int(fields[19]), "path": path,
            "args": [x for x in (path / "cmdline").read_bytes().split(b"\0") if x],
            "exe": str((path / "exe").resolve(strict=True))}
    except (OSError, ValueError, IndexError):
        fail("STRICT_NATIVE_PROCESS_UNAVAILABLE")


def verify_native_process(plan, directory, pane_pid, *, proc_root=Path("/proc")):
    """Inspect only the registered pane's process tree, without exposing env."""
    if type(pane_pid) is not int or pane_pid <= 0 or plan.launch_start_ticks is None:
        fail("STRICT_NATIVE_PROCESS_UNAVAILABLE")
    todo, seen, candidates = [pane_pid], set(), []
    while todo and len(seen) < 128:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        record = _process_record(pid, proc_root=proc_root)
        if process_is_claude(record["args"], record["exe"]):
            candidates.append(record)
            # MCP children and background agents are not the pane's native
            # root. Their independent lifetimes must not invalidate this PID.
            continue
        try:
            todo.extend(map(int, (record["path"] / "task" / str(pid) / "children").read_text().split()))
        except (OSError, ValueError):
            fail("STRICT_NATIVE_PROCESS_UNAVAILABLE")
    if todo or len(candidates) != 1:
        fail("STRICT_NATIVE_PROCESS_UNAVAILABLE")
    record = candidates[0]
    path, args = record["path"], [os.fsdecode(x) for x in record["args"]]
    if record["startTicks"] < plan.launch_start_ticks:
        fail("STRICT_NATIVE_GENERATION_CHANGED")
    if args.count("--resume") != 1 or args[args.index("--resume") + 1:args.index("--resume") + 2] != [plan.native_id]:
        fail("STRICT_NATIVE_ID_CHANGED")
    forbidden = {"--fork-session", "--session-id", "--continue", "-c", "--print", "-p", "--resume-session-at", "--rewind-files", "-r"}
    if any(arg.split("=", 1)[0] in forbidden or arg.startswith("--resume=") for arg in args):
        fail("STRICT_LAUNCH_CONFIG_CHANGED")
    try:
        if (path / "cwd").resolve(strict=True) != plan.workspace.resolve(strict=True):
            fail("STRICT_WORKSPACE_MISMATCH")
        env = dict(x.split(b"=", 1) for x in (path / "environ").read_bytes().split(b"\0") if b"=" in x)
        declared = env.get(b"HARNESS_CLAUDE_NATIVE_BRIDGE_DIR")
        if declared:
            if not Path(os.fsdecode(declared)).samefile(directory):
                fail("STRICT_NATIVE_BINDING_CHANGED")
        else:
            if args.count("--settings") != 1:
                fail("STRICT_NATIVE_BINDING_CHANGED")
            offset = args.index("--settings")
            if offset + 1 >= len(args):
                fail("STRICT_NATIVE_BINDING_CHANGED")
            settings = Path(args[offset + 1])
            meta = settings.lstat()
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o077 or not settings.samefile(directory / "claude-settings.json"):
                fail("STRICT_NATIVE_BINDING_CHANGED")
            hooks = json.loads(settings.read_text()).get("hooks", {})
            if not all(str(directory) in json.dumps(hooks.get(event, [])) for event in ("SessionStart", "Stop")):
                fail("STRICT_NATIVE_BINDING_CHANGED")
    except (OSError, ValueError, TypeError):
        fail("STRICT_NATIVE_BINDING_CHANGED")
    return {"pid": record["pid"], "startTicks": record["startTicks"], "panePid": pane_pid}


def fresh_session_start(plan, directory):
    """Require a native hook from this launch, never just state.json identity."""
    if plan.launch_started_at is None:
        return None
    try:
        records = (directory / "hooks.jsonl").read_text().splitlines()
        for line in reversed(records):
            row = json.loads(line)
            when, payload = row.get("recorded_at"), row.get("payload", {})
            if type(when) not in (float, int) or when < plan.launch_started_at:
                continue
            if payload.get("hook_event_name") == "SessionStart" and payload.get("session_id") == plan.native_id:
                if Path(payload.get("transcript_path", "")).samefile(plan.path):
                    return when
    except (OSError, ValueError, TypeError):
        return None
    return None


async def confirm_attachment(plan, registry, *, timeout=30):
    from omnigent.harnesses.claude_native import bridge
    from omnigent.entities.session_resources import terminal_resource_id
    directory = bridge.bridge_dir_for_bridge_id(plan.bridge_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = bridge.read_claude_session_id(directory)
        if found is not None:
            if found != plan.native_id or bridge.read_active_session_id(directory) != plan.session_id:
                fail("STRICT_NATIVE_ID_CHANGED")
            view = await registry.get_terminal_resource(plan.session_id, terminal_resource_id("claude", "main"))
            if view is None:
                fail("STRICT_ATTACH_UNCONFIRMED")
            terminal = registry.terminal_registry.get(plan.session_id, "claude", "main")
            if terminal is None:
                fail("STRICT_ATTACH_UNCONFIRMED")
            pane_pid = await asyncio.to_thread(terminal.pane_pid_sync)
            identity = await asyncio.to_thread(verify_native_process, plan, directory, pane_pid)
            hook_at = fresh_session_start(plan, directory)
            if hook_at is None:
                await asyncio.sleep(0.1)
                continue
            plan.check_prefix(allow_append=True)
            # Recheck after hook/history reads: a dead pane or reused PID must
            # not turn an earlier successful probe into a durable receipt.
            again = await asyncio.to_thread(terminal.pane_pid_sync)
            if again != pane_pid or await asyncio.to_thread(verify_native_process, plan, directory, again) != identity:
                fail("STRICT_NATIVE_GENERATION_CHANGED")
            return {"state": "attached", "sessionId": plan.session_id,
                "nativeSessionId": plan.native_id, "bridgeId": plan.bridge_id,
                "historyPrefixPreserved": True, "originalBytes": plan.size,
                "originalSHA256": plan.sha256, "toolsVerified": False,
                "nativePid": identity["pid"], "nativeStartTicks": identity["startTicks"],
                "panePid": pane_pid, "launchStartedAt": plan.launch_started_at,
                "sessionStartRecordedAt": hook_at, "currentNativeVerified": True}
        await asyncio.sleep(0.1)
    fail("STRICT_ATTACH_UNCONFIRMED")


async def strict_ensure(body, ctx, *, ensure, ensure_locks, build_context, busy):
    """Runner-only route, after existing central session EDIT authorization."""
    from starlette.responses import JSONResponse
    try:
        response = await ctx.server_client.get("/v1/sessions/" + ctx.session_id, params={"include_usage": "false"})
        if response.status_code != 200:
            fail("STRICT_SESSION_UNAVAILABLE")
        plan = prepare_plan(ctx.session_id, body, response.json(), busy=busy,
                            epoch=lambda: ctx.resource_registry.session_activity_epoch(ctx.session_id))
        with reserve_native(plan):
            response = await ensure("claude", replace(ctx, woow_strict_resume=plan),
                                    ensure_locks=ensure_locks, build_context=build_context)
            if response is None or response.status_code != 200:
                fail("STRICT_ATTACH_FAILED")
            receipt = await confirm_attachment(plan, ctx.resource_registry)
            payload = json.loads(response.body)
            payload["woow_strict_resume"] = receipt
            return JSONResponse(status_code=200, content=payload)
    except StrictResumeError as error:
        code = error.code
    except Exception:
        code = "STRICT_ATTACH_FAILED"
    return JSONResponse(status_code=409, content={"error": {"code": code, "message": code}})
