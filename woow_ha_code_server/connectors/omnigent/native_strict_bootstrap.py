"""Explicit owner-requested cold bootstrap; absent opt-in leaves upstream alone.

The request is local, private, short lived, and bound to the existing native
history bytes. It is never inferred from a normal ensure or incoming chat turn.
"""
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

ENV = "WOOW_NATIVE_STRICT_RESUME_REQUEST"


def read_request(path):
    from omnigent.runner.native.woow_claude_strict_resume import fail
    if not path.is_absolute() or path.parent.resolve(strict=True) != path.parent:
        fail("STRICT_REQUEST_UNSAFE")
    parent = path.parent.lstat()
    if parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
        fail("STRICT_REQUEST_UNSAFE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o077 or not 0 < meta.st_size <= 16384:
            fail("STRICT_REQUEST_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("SESSION_BUSY")
        raw = os.read(fd, 16385)
        value = json.loads(raw)
        now = time.time()
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
            fail("STRICT_REQUEST_INVALID")
        if value.get("engine") not in ("claude", "pi", "codex") or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", str(value.get("sessionId", ""))):
            fail("STRICT_REQUEST_INVALID")
        if not re.fullmatch(r"[0-9a-f]{32}", str(value.get("requestId", ""))) or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("originalSHA256", ""))):
            fail("STRICT_REQUEST_INVALID")
        issued, expires = value.get("issuedAt"), value.get("expiresAt")
        if type(issued) not in (int, float) or type(expires) not in (int, float) or not issued <= now < expires or not 0 < expires - issued <= 3600:
            fail("STRICT_REQUEST_EXPIRED")
        if type(value.get("originalBytes")) is not int or not 0 < value["originalBytes"] <= 128 * 1024 * 1024:
            fail("STRICT_REQUEST_INVALID")
        return fd, value, hashlib.sha256(raw).hexdigest()
    except BaseException:
        os.close(fd)
        raise


async def strict_cold_launch(harness_name, ctx, **launch_kwargs):
    """Called before upstream auto-create, covering central's wake-before-POST."""
    from omnigent.runner.native.woow_claude_strict_resume import (
        confirm_attachment, fail, prepare_plan, reserve_native,
    )
    from omnigent.runner.native.orchestration import _launch_native_terminal
    path = Path(os.environ[ENV])
    fd, request, request_hash = read_request(path)
    try:
        receipt_path = path.with_name(path.name + ".attached.json")
        if receipt_path.exists() or receipt_path.is_symlink():
            fail("STRICT_REQUEST_ALREADY_USED")
        if request["sessionId"] != ctx.session_id or harness_name != request["engine"] + "-native":
            fail("STRICT_SESSION_INVALID")
        if request["engine"] == "codex":
            from omnigent.runner.native.woow_codex_strict_resume import cold_resume
            result, receipt = await cold_resume(ctx, request, launch_kwargs=launch_kwargs)
        elif request["engine"] == "pi":
            # Added by the separate Pi strict launcher package. A missing
            # helper is an error, never permission to invoke ordinary ensure.
            from omnigent.runner.native.woow_pi_strict_resume import cold_resume
            result, receipt = await cold_resume(ctx, request, launch_kwargs=launch_kwargs)
        else:
            response = await ctx.server_client.get("/v1/sessions/" + ctx.session_id, params={"include_usage": "false"})
            if response.status_code != 200:
                fail("STRICT_SESSION_UNAVAILABLE")
            body = {"woow_strict_claude_resume": True, "ensure_native_terminal": True,
                "terminal": "claude", "session_key": "main",
                "expected_external_session_id": request.get("nativeSessionId"),
                "expected_workspace": request.get("workspace")}
            plan = prepare_plan(ctx.session_id, body, response.json(),
                busy=lambda: ctx.resource_registry.session_turn_is_active(ctx.session_id),
                epoch=lambda: ctx.resource_registry.session_activity_epoch(ctx.session_id))
            if plan.size != request["originalBytes"] or plan.sha256 != request["originalSHA256"]:
                fail("STRICT_NATIVE_FILE_CHANGED")
            with reserve_native(plan):
                # No fork/rewind/transfer decisions in this explicitly bound
                # cold-original operation. Shared launch still holds its lock.
                result = await _launch_native_terminal(harness_name, replace(ctx, woow_strict_resume=plan),
                    **{**launch_kwargs, "pre_launch": None, "reraise": True})
                if result is not True:
                    fail("STRICT_ATTACH_FAILED")
                receipt = await confirm_attachment(plan, ctx.resource_registry)
        # Durable success is correlated to the exact owner request. Do not
        # overwrite an earlier receipt or restore a stale whole-file backup.
        if result is not True or receipt.get("state") != "attached" or receipt.get("sessionId") != ctx.session_id or receipt.get("nativeSessionId") != request.get("nativeSessionId") or receipt.get("historyPrefixPreserved") is not True:
            fail("STRICT_ATTACH_UNCONFIRMED")
        receipt_fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(receipt_fd, "w") as stream:
            json.dump({"requestId": request["requestId"], "requestSHA256": request_hash, **receipt}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # This is a one-shot per-process bootstrap. A restarted copy with the
        # old request cannot silently change the original hash or fall back.
        os.environ.pop(ENV, None)
        return result
    finally:
        os.close(fd)
