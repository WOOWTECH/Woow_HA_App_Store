#!/usr/bin/env python3
"""Build-only pinned Omnigent 0.16 / Pi 0.99.1 MCP reload extension backport.

No runner/central API changes or restart. Never run against a live installation.
Existing native sessions require a coordinator-owned, idle /reload bootstrap;
this script does not find or modify their bridge directories.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

VERSION = "0.16.0"
MARKER = "WOOW_PI_MCP_REFRESH_V1"
RECEIPT = ".woow-pi-mcp-refresh-v1.json"
HASHES = {
    "harnesses/pi_native/bridge.py": "d685293a035ce9a78a021bd52b7735e27d888aa9d51a2e49e94c6bdb7e953435",
    "resources/pi_native/omnigent_pi_native_extension.js": "dfa2d58304d3045f56658020683aafe61adb57e4775c6de5d86e10307c82a5fa",
}
HELPER = "resources/pi_native/woow_pi_mcp_refresh.cjs"
BRIDGE_ANCHOR = '    _atomic_text(extension_path(bridge_dir), _extension_source())\n'
RETENTION_MARKER = 'WOOW_PI_NATIVE_HISTORY_RETENTION_V1'
PRUNE_ANCHOR = '    return native_bridge_common.prune_orphaned_dirs(bridge_root())\n'
PRUNE_REPLACEMENT = '''    return native_bridge_common.prune_orphaned_dirs(
        bridge_root(), should_prune=_woow_pi_bridge_has_no_native_history,
    )
'''
RETENTION_HELPER = '''def _woow_pi_bridge_has_no_native_history(directory: Path) -> bool:
    # WOOW_PI_NATIVE_HISTORY_RETENTION_V1: JSONL is durable conversation data.
    # This predicate runs under the SDK's existing cleanup/preparation lock.
    # Explicit conversation deletion is unchanged; only orphan GC is narrowed.
    sessions = directory / _SESSIONS_DIR
    try:
        if sessions.is_symlink():
            return False
        return not any(entry.name.endswith(".jsonl") for entry in sessions.iterdir())
    except FileNotFoundError:
        return True
    except OSError:
        return False


'''
BRIDGE_HOOK = '''    # WOOW_PI_MCP_REFRESH_V1: only the build-time packaged helper, never user code.
    _atomic_text(
        bridge_dir / "woow_pi_mcp_refresh.cjs",
        files(_EXTENSION_PACKAGE).joinpath("woow_pi_mcp_refresh.cjs").read_text(encoding="utf-8"),
    )
'''
JS_ANCHOR = 'module.exports = function (pi) {\n  const config = readConfig();\n'
JS_PREAMBLE = 'import * as mcpApi from "@earendil-works/pi-coding-agent";\n'
JS_HOOK = '''  // WOOW_PI_MCP_REFRESH_V1: replace only the built-in MCP extension.
  // Pi's replaceable builtin:mcp yields to this extension's /mcp registration.
  // Jiti resolves this public API to the same Pi instance loading the extension.
  if (mcpApi.VERSION !== "0.99.1" || typeof mcpApi.createMcpExtension !== "function" || !config)
    throw new Error("MCP_NATIVE_UNAVAILABLE");
  // Invalidate only this packaged helper, so a supported /reload can load an
  // updated helper without retaining its old CommonJS implementation.
  const mcpRequire = require("node:module").createRequire(__filename);
  const mcpHelper = mcpRequire.resolve("./woow_pi_mcp_refresh.cjs");
  delete mcpRequire.cache[mcpHelper];
  mcpRequire(mcpHelper).install(pi, config, mcpApi.createMcpExtension);
  // Pi invalidates the extension API on reload; an orphan poller must not
  // consume messages through that stale API after the new extension loads.
  pi.on("session_shutdown", () => {
    if (pi.__omnigentInboxPoller) {
      clearInterval(pi.__omnigentInboxPoller);
      delete pi.__omnigentInboxPoller;
    }
  });
'''
HOOKS = {
    "harnesses/pi_native/bridge.py": (BRIDGE_ANCHOR, BRIDGE_HOOK),
    "resources/pi_native/omnigent_pi_native_extension.js": (JS_ANCHOR, JS_HOOK),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def transformed(name, source):
    anchor, hook = HOOKS[name]
    if source.count(anchor) != 1:
        raise ValueError("MCP_NATIVE_PATCH_ANCHOR_MISMATCH")
    result = source.replace(anchor, anchor + hook, 1)
    if name == 'harnesses/pi_native/bridge.py':
        if result.count(PRUNE_ANCHOR) != 1 or result.count('def prune_orphaned_bridge_dirs() -> int:\n') != 1:
            raise ValueError('MCP_NATIVE_PATCH_ANCHOR_MISMATCH')
        result = result.replace(PRUNE_ANCHOR, PRUNE_REPLACEMENT, 1)
        result = result.replace('def prune_orphaned_bridge_dirs() -> int:\n',
                                RETENTION_HELPER + 'def prune_orphaned_bridge_dirs() -> int:\n', 1)
    return JS_PREAMBLE + result if name.endswith(".js") else result


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("MCP_NATIVE_PATCH_UNSAFE_PATH")
    return path.read_bytes()


def patch(site_packages, *, check=False):
    site = Path(site_packages)
    if not site.is_absolute():
        raise ValueError("MCP_NATIVE_PATCH_ABSOLUTE_PATH_REQUIRED")
    package = site / "omnigent"
    if any((package / part).is_symlink() for part in (".", "harnesses", "harnesses/pi_native", "resources", "resources/pi_native")):
        raise ValueError("MCP_NATIVE_PATCH_UNSAFE_PATH")
    metadata = site / ("omnigent-" + VERSION + ".dist-info") / "METADATA"
    if ("Version: " + VERSION) not in _read(metadata).decode().splitlines():
        raise ValueError("MCP_NATIVE_PATCH_VERSION_MISMATCH")
    helper = _read(Path(__file__).with_name("pi_mcp_refresh.cjs"))
    receipt_path = package / RECEIPT
    prepared = []
    targets = {}
    prior_targets = {}
    states = []
    for name, expected in HASHES.items():
        file = package / name
        original = _read(file)
        if MARKER.encode() in original:
            hook = HOOKS[name][1].encode()
            restored = original.replace(hook, b"", 1)
            if name == 'harnesses/pi_native/bridge.py' and RETENTION_MARKER.encode() in restored:
                if restored.count(RETENTION_HELPER.encode()) != 1 or restored.count(PRUNE_REPLACEMENT.encode()) != 1:
                    raise ValueError('MCP_NATIVE_PATCH_SOURCE_MISMATCH')
                restored = restored.replace(RETENTION_HELPER.encode(), b'', 1)
                restored = restored.replace(PRUNE_REPLACEMENT.encode(), PRUNE_ANCHOR.encode(), 1)
            if name.endswith(".js"):
                if not restored.startswith(JS_PREAMBLE.encode()):
                    raise ValueError("MCP_NATIVE_PATCH_SOURCE_MISMATCH")
                restored = restored[len(JS_PREAMBLE):]
            if original.count(hook) != 1 or digest(restored) != expected:
                raise ValueError("MCP_NATIVE_PATCH_SOURCE_MISMATCH")
            replacement = transformed(name, restored.decode()).encode()
            states.append("patched" if replacement == original else "upgrade")
        else:
            if digest(original) != expected:
                raise ValueError("MCP_NATIVE_PATCH_SOURCE_MISMATCH")
            replacement = transformed(name, original.decode()).encode()
            states.append("original")
        if name.endswith(".py"):
            compile(replacement, "omnigent/" + name, "exec")
        targets[name] = {"original": expected, "patched": digest(replacement)}
        prior_targets[name] = {"original": expected, "patched": digest(original)}
        prepared.append((file, replacement, file.stat().st_mode & 0o777))
    receipt = {"version": VERSION, "marker": MARKER, "targets": targets, "helper": digest(helper)}
    if all(state in {'patched', 'upgrade'} for state in states):
        prior_receipt = {"version": VERSION, "marker": MARKER, "targets": prior_targets, "helper": digest(helper)}
        if json.loads(_read(receipt_path)) != prior_receipt or _read(package / HELPER) != helper:
            raise ValueError("MCP_NATIVE_PATCH_RECEIPT_MISMATCH")
        if all(state == 'patched' for state in states):
            return {"state": "already-applied", **receipt}
    elif any(state != "original" for state in states):
        raise ValueError("MCP_NATIVE_PATCH_PARTIAL")
    else:
        for path in (package / HELPER, receipt_path):
            if path.exists() or path.is_symlink():
                raise ValueError("MCP_NATIVE_PATCH_DESTINATION_CONFLICT")
    if check:
        return {"state": "verified", **receipt}
    prepared.insert(0, (package / HELPER, helper, 0o644))
    prepared.append((receipt_path, (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode(), 0o644))
    staged = []
    try:
        # Hash/anchor checks across all vendor targets finish before any writes.
        for file, data, mode in prepared:
            descriptor, temporary = tempfile.mkstemp(prefix=".pi-mcp-refresh-", dir=file.parent)
            staged.append((Path(temporary), file))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
        for temporary, file in staged:
            os.replace(temporary, file)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return {"state": "applied", **receipt}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-packages", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = patch(args.site_packages, check=args.check)
    except (OSError, ValueError, UnicodeError, SyntaxError):
        raise SystemExit("MCP_NATIVE_PATCH_REFUSED") from None
    print(MARKER + ": " + result["state"])
