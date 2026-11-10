#!/usr/bin/env python3
"""Build-only opt-in Claude strict resume; normal ensure/fork stays unchanged."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zlib

HASHES = {
    "runner/app.py": "9dde9dc61b4e8068702657862c298e0dac028e882eea004d177b742fcf3025db",
    "runner/native/orchestration.py": "c7bf262233ecc4a8a90c25499ab581d3c0c93c24e9fc8a88a712f96f9edd8fb8",
}
LEGACY_TARGETS = {'runner/app.py': 'ed052f0e0f19858bea8af627d08ec0996e3e3147c89afd8bd4753afd21ad45a3', 'runner/native/orchestration.py': 'ba822f5202004d6b70b6bef33c2e187ea8fcd289a8c81c0ee75ff1d63df31b34'}
HELPER = "runner/native/woow_claude_strict_resume.py"
HELPERS = {HELPER: "claude_strict_resume.py", "runner/native/woow_native_strict_bootstrap.py": "native_strict_bootstrap.py",
    "runner/native/woow_pi_strict_resume.py": "pi_strict_resume.py",
    "runner/native/pi_strict_launcher.mjs": "pi_strict_launcher.mjs",
    "runner/native/woow_pi_native_resume.py": "native_resume.py",
    "runner/native/woow_codex_strict_resume.py": "codex_strict_resume.py"}
RECEIPT = ".woow-claude-strict-resume-v1.json"
MARKER = "WOOW_CLAUDE_STRICT_RESUME_V1"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("STRICT_PATCH_ANCHOR_CHANGED")
    return text.replace(old, new, 1)


def scoped(text, start, end, transform):
    first = text.index(start)
    last = text.index(end, first + len(start))
    return text[:first] + transform(text[first:last]) + text[last:]


def transform(name, source):
    if name == "runner/app.py":
        def route(part):
            part = once(part, '        _ensure_agent = native_coding_agent_for_terminal_name(terminal_name)\n',
                '''        # WOOW_CLAUDE_STRICT_RESUME_V1: explicit opt-in, never a normal ensure.
        if "woow_strict_claude_resume" in body and not (
            body["woow_strict_claude_resume"] is True
            and body.get("ensure_native_terminal") is True
            and terminal_name == "claude" and session_key == "main"
        ):
            return JSONResponse(status_code=400, content={"error": {
                "code": "STRICT_REQUEST_INVALID", "message": "STRICT_REQUEST_INVALID"}})
        _ensure_agent = native_coding_agent_for_terminal_name(terminal_name)
''')
            return once(part, '            _ensure_result = await _ensure_native_terminal(\n',
                '''            if body.get("woow_strict_claude_resume") is True:
                from omnigent.runner.native.woow_claude_strict_resume import strict_ensure
                return await strict_ensure(
                    body, _ensure_ctx, ensure=_ensure_native_terminal,
                    ensure_locks=_ensure_locks, build_context=_ensure_build,
                    busy=lambda: (
                        session_id in _active_turns
                        or resource_registry.session_turn_is_active(session_id)
                        or (process_manager is not None and process_manager.has_active_turn(session_id))
                    ),
                )
            _ensure_result = await _ensure_native_terminal(
''')
        result = scoped(source, '    async def create_session_terminal(\n', '    async def _ensure_native_terminal_for_turn(', route)
        result = once(result, '            _launch_result = await _launch_native_terminal(\n',
            '''            # WOOW_CLAUDE_STRICT_RESUME_V1: explicit private cold-bootstrap request.
            _launch_callable = _launch_native_terminal
            if os.environ.get("WOOW_NATIVE_STRICT_RESUME_REQUEST"):
                from omnigent.runner.native.woow_native_strict_bootstrap import strict_cold_launch
                _launch_callable = strict_cold_launch
            _launch_result = await _launch_callable(
''')
        result = scoped(result, '    async def get_session_terminal(\n', '    @app.get("/v1/sessions/{session_id}/sign-in-link")',
            lambda part: once(part, '        resource = await resource_registry.get_terminal_resource(\n',
                '''        if terminal_id == "woow-strict-resume-capability-v1":
            return JSONResponse(status_code=200, content={"woow_strict_resume": {
                "version": 1, "engine": "claude", "explicitColdBootstrap": True}})
        resource = await resource_registry.get_terminal_resource(
'''))
    else:
        def creator(part):
            part = once(part, ') -> SessionResourceView:\n', '    woow_strict_resume: object | None = None,\n) -> SessionResourceView:\n')
            part = once(part, '    from pathlib import Path\n',
                '''    if woow_strict_resume is None and os.environ.get("WOOW_NATIVE_STRICT_RESUME_REQUEST"):
        # A failed explicit bootstrap must never become a normal ensure on a
        # later UI/turn retry while its private request is still armed.
        from omnigent.runner.native.woow_claude_strict_resume import StrictResumeError
        raise StrictResumeError("STRICT_BOOTSTRAP_REQUIRED")
    from pathlib import Path
''')
            part = once(part, '    started_at = time.monotonic()\n',
                '''    # WOOW_CLAUDE_STRICT_RESUME_V1: bind the authoritative original workspace.
    if woow_strict_resume is not None:
        workspace = str(woow_strict_resume.workspace)
        woow_strict_resume.before_prepare(workspace)
    started_at = time.monotonic()
''')
            part = once(part, '    ensure_claude_workspace_trusted(Path(workspace))\n',
                '''    if woow_strict_resume is None:
        ensure_claude_workspace_trusted(Path(workspace))
''')
            part = once(part, '    bridge_id = cleared_bridge_id if existing_bridge_id == cleared_bridge_id else session_id\n',
                '    bridge_id = cleared_bridge_id if existing_bridge_id == cleared_bridge_id else session_id\n'
                '    if woow_strict_resume is not None:\n'
                '        woow_strict_resume.bind_bridge(bridge_id)\n')
            part = once(part, '    if server_client is not None and session_external_id is not None:\n',
                '''    if woow_strict_resume is not None:
        # Never enter AP synthesis or any fork/fresh fallback in strict mode.
        _transcript = woow_strict_resume.resume_existing(
            session_external_id, fork_source_external_id, fork_carry_history,
        )
        resume_external_session_id = woow_strict_resume.native_id
        resume_prefix_bytes = woow_strict_resume.size
    elif server_client is not None and session_external_id is not None:
''')
            return once(part, '    try:\n        terminal_view = await resource_registry.launch_required_terminal(\n',
                '''    if woow_strict_resume is not None:
        woow_strict_resume.before_launch(launch_command, launch_args, workspace, reset_pick_after_launch)
    try:
        terminal_view = await resource_registry.launch_required_terminal(
''')
        result = scoped(source, 'async def _auto_create_claude_terminal(\n', '\n\nasync def _auto_create_repl_terminal(', creator)
        result = scoped(result, 'class NativeLaunchContext:\n', '\n\n@dataclasses.dataclass(frozen=True)\nclass PreLaunchResult:',
            lambda part: part.rstrip() + '\n    woow_strict_resume: object | None = None\n')
        result = scoped(result, 'async def _launch_claude(ctx:', '\n\nasync def _launch_native_terminal(',
            lambda part: once(part, '        record_launch_config=ctx.record_launch_config,\n',
                '        record_launch_config=ctx.record_launch_config,\n        woow_strict_resume=ctx.woow_strict_resume,\n'))
        def ensure(part):
            part = once(part, '    async with lock:\n',
                '''    async with lock:
        if ctx.woow_strict_resume is not None:
            ctx.woow_strict_resume.check_cold()
''')
            part = once(part, '        if existing is not None:\n',
                '''        if existing is not None:
            if ctx.woow_strict_resume is not None:
                from omnigent.runner.native.woow_claude_strict_resume import StrictResumeError
                raise StrictResumeError("STRICT_NATIVE_ALREADY_RUNNING")
''')
            return part
        result = scoped(result, 'async def _ensure_native_terminal(\n', '\n\nasync def _claude_native_session_wants_rebuild(', ensure)
        result = scoped(result, 'async def _launch_native_terminal(\n', '\n\ndef _ensure_native_terminal_default_response(',
            lambda part: once(part, '        decision = await pre_launch(has_terminal) if pre_launch is not None else PreLaunchResult()\n',
                '''        if ctx.woow_strict_resume is not None:
            ctx.woow_strict_resume.check_cold()
            if has_terminal:
                from omnigent.runner.native.woow_claude_strict_resume import StrictResumeError
                raise StrictResumeError("STRICT_NATIVE_ALREADY_RUNNING")
        decision = await pre_launch(has_terminal) if pre_launch is not None else PreLaunchResult()
'''))
        result = scoped(result, 'async def _auto_create_pi_terminal(\n', '\n\nasync def _post_pi_native_credential_warning(',
            lambda part: once(part, '    await _cancel_auto_forwarder_task(session_id)\n',
                '''    if os.environ.get("WOOW_NATIVE_STRICT_RESUME_REQUEST"):
        # The explicit Pi callback owns its strict launcher; an ordinary
        # ensure after a failed bootstrap must not synthesize a replacement.
        from omnigent.runner.native.woow_claude_strict_resume import StrictResumeError
        raise StrictResumeError("STRICT_BOOTSTRAP_REQUIRED")
    await _cancel_auto_forwarder_task(session_id)
'''))
        def codex_creator(part):
            part = once(part, ') -> SessionResourceView:\n', '    woow_strict_resume: object | None = None,\n) -> SessionResourceView:\n')
            part = once(part, '    import socket as _socket\n',
                '    # WOOW_CODEX_STRICT_RESUME_V1: no ordinary fallback while armed.\n'
                '    if woow_strict_resume is None and os.environ.get("WOOW_NATIVE_STRICT_RESUME_REQUEST"):\n'
                '        from omnigent.runner.native.woow_claude_strict_resume import StrictResumeError\n'
                '        raise StrictResumeError("STRICT_BOOTSTRAP_REQUIRED")\n'
                '    import socket as _socket\n')
            part = once(part, '    original_external_session_id = launch_config.external_session_id\n',
                '    if woow_strict_resume is not None:\n'
                '        woow_strict_resume.before_prepare(launch_config)\n'
                '    original_external_session_id = launch_config.external_session_id\n')
            part = once(part, '    if codex_binding is None and (\n',
                '    if woow_strict_resume is None and codex_binding is None and (\n')
            # Reaping is not an admissible way to make a strict original cold.
            part = once(part, '    if launch_config.external_session_id is not None:\n        from omnigent.harnesses.codex_native.process_registry import (\n',
                '    if woow_strict_resume is None and launch_config.external_session_id is not None:\n        from omnigent.harnesses.codex_native.process_registry import (\n')
            part = once(part, '    if launch_config.external_session_id is not None and original_external_session_id is not None:\n',
                '    if woow_strict_resume is not None:\n'
                '        woow_strict_resume.resume_existing(launch_config, codex_home)\n'
                '    elif launch_config.external_session_id is not None and original_external_session_id is not None:\n')
            part = once(part, '        trust_project=True,\n', '        trust_project=woow_strict_resume is None,\n')
            part = once(part, '        trust_all_hooks=True,\n', '        trust_all_hooks=woow_strict_resume is None,\n')
            part = once(part, '    await app_server.start()\n',
                '    if woow_strict_resume is not None:\n'
                '        woow_strict_resume.before_server(app_server, launch_config, pick_to_reset)\n'
                '    await app_server.start()\n')
            part = once(part, '            if not isinstance(exc, Exception) or not is_unreadable_thread_error(exc):\n',
                '            if woow_strict_resume is not None or not isinstance(exc, Exception) or not is_unreadable_thread_error(exc):\n')
            return part
        result = scoped(result, 'async def _auto_create_codex_terminal(\n', '\n\nasync def ', codex_creator)
        result = scoped(result, 'async def _launch_codex(ctx:', '\n\nasync def _launch_antigravity(',
            lambda part: once(part, '        ensure_comment_relay=ctx.ensure_comment_relay,\n',
                '        ensure_comment_relay=ctx.ensure_comment_relay,\n        woow_strict_resume=ctx.woow_strict_resume,\n'))
    compile(result, name, 'exec')
    return result


def patch(site, *, check=False):
    package = Path(site) / "omnigent"
    if package.is_symlink() or any((package / p).is_symlink() for p in ("runner", "runner/native")):
        raise ValueError("STRICT_PATCH_UNSAFE_PATH")
    metadata = Path(site) / "omnigent-0.16.0.dist-info/METADATA"
    if "Version: 0.16.0" not in metadata.read_text().splitlines():
        raise ValueError("STRICT_PATCH_VERSION_MISMATCH")
    receipt_file = package / RECEIPT
    if receipt_file.is_symlink():
        raise ValueError("STRICT_PATCH_UNSAFE_PATH")
    receipt = json.loads(receipt_file.read_text()) if receipt_file.exists() else None
    helpers = {target: Path(__file__).with_name(source).read_bytes() for target, source in HELPERS.items()}
    targets = {}
    prepared = {}
    states = []
    for name, expected in HASHES.items():
        if (package / name).is_symlink():
            raise ValueError("STRICT_PATCH_UNSAFE_PATH")
        raw = (package / name).read_bytes()
        if MARKER in raw.decode():
            # Reconstruct from a SHA-bound pristine source. A forged receipt
            # cannot bless modified patched bytes, even with a matching digest.
            row = receipt.get("targets", {}).get(name, {}) if receipt else {}
            encoded = row.get("sourceZlib", "")
            if len(encoded) > 1024 * 1024:
                raise ValueError("STRICT_PATCH_SOURCE_MISMATCH")
            inflater = zlib.decompressobj()
            original = inflater.decompress(base64.b64decode(encoded, validate=True), 2 * 1024 * 1024)
            if not inflater.eof or digest(original) != expected:
                raise ValueError("STRICT_PATCH_SOURCE_MISMATCH")
            replacement = transform(name, original.decode()).encode()
            if replacement != raw and digest(raw) != LEGACY_TARGETS[name]:
                raise ValueError("STRICT_PATCH_SOURCE_MISMATCH")
            if row.get("original") != expected or row.get("patched") != digest(raw):
                raise ValueError("STRICT_PATCH_RECEIPT_MISMATCH")
            if replacement == raw:
                targets[name] = row
                states.append("patched")
            else:
                targets[name] = {**row, "patched": digest(replacement)}
                prepared[name] = replacement
                states.append("legacy")
        else:
            if digest(raw) != expected:
                raise ValueError("STRICT_PATCH_SOURCE_MISMATCH")
            replacement = transform(name, raw.decode()).encode()
            prepared[name] = replacement
            targets[name] = {"original": expected, "patched": digest(replacement),
                "sourceZlib": base64.b64encode(zlib.compress(raw)).decode()}
            states.append("original")
    expected_receipt = {"version": 1, "targets": targets, "helpers": {p: digest(raw) for p, raw in helpers.items()}}
    if states == ["patched"] * len(HASHES):
        if receipt != expected_receipt or any((package / p).is_symlink() or not (package / p).is_file() or (package / p).read_bytes() != raw for p, raw in helpers.items()):
            raise ValueError("STRICT_PATCH_HELPER_MISMATCH")
        return {"state": "already-applied"}
    upgrading = "legacy" in states and "original" not in states
    if upgrading:
        previous_helpers = set(HELPERS) - {"runner/native/woow_codex_strict_resume.py"}
        if set((receipt or {}).get("helpers", {})) != previous_helpers:
            raise ValueError("STRICT_PATCH_HELPER_MISMATCH")
        for name in previous_helpers:
            path = package / name
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != receipt["helpers"][name]:
                raise ValueError("STRICT_PATCH_HELPER_MISMATCH")
        if (package / "runner/native/woow_codex_strict_resume.py").exists() or (package / "runner/native/woow_codex_strict_resume.py").is_symlink():
            raise ValueError("STRICT_PATCH_DESTINATION_CONFLICT")
    elif "patched" in states or "legacy" in states:
        raise ValueError("STRICT_PATCH_PARTIAL")
    elif receipt is not None or any((package / p).exists() or (package / p).is_symlink() for p in helpers):
        raise ValueError("STRICT_PATCH_DESTINATION_CONFLICT")
    if check:
        return {"state": "verified"}
    prepared.update(helpers)
    prepared[RECEIPT] = (json.dumps(expected_receipt, sort_keys=True) + "\n").encode()
    staged = []
    try:
        for name, raw in prepared.items():
            target = package / name
            fd, temp = tempfile.mkstemp(prefix=".woow-strict-", dir=target.parent)
            staged.append((temp, target))
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                os.fchmod(stream.fileno(), target.stat().st_mode & 0o777 if target.exists() else 0o644)
                stream.flush()
                os.fsync(stream.fileno())
        for temp, target in staged:
            os.replace(temp, target)
    finally:
        for temp, _ in staged:
            Path(temp).unlink(missing_ok=True)
    return {"state": "upgraded" if upgrading else "applied"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = patch(args.site_packages, check=args.check)
    except (OSError, ValueError, UnicodeError, SyntaxError, zlib.error):
        raise SystemExit("STRICT_PATCH_REFUSED") from None
    print(MARKER + ": " + result["state"])
