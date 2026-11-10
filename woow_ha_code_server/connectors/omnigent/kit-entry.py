#!/usr/bin/env python3
"""Code-server-only kit overlay, before omnigent-host-entry/launcher starts.

Usage: python3 kit-entry.py /usr/local/bin/omnigent-host-entry <normal args...>
No chart canonical changes, no ConfigMap mutation, no additional supervisor.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("woow_kit_patch", ROOT / "patch-kit.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


def prepare(source):
    source = Path(source)
    # Hash-check/transform before creating the overlay; fallback is unchanged.
    import hashlib
    original = (source / "supervisor.sh").read_bytes()
    if hashlib.sha256(original).hexdigest() != patcher.SOURCE_HASH:
        raise ValueError("unsupported canonical kit source")
    stage = Path(tempfile.mkdtemp(prefix="woow-code-server-omnigent-kit-"))
    try:
        for item in source.iterdir():
            if item.name.startswith(".."):
                continue  # Kubernetes projection bookkeeping is not a kit entry.
            if item.name == "supervisor.sh":
                target = stage / item.name
                shutil.copy2(item, target)
                # ConfigMap scripts are commonly projected as 0555. Only the
                # private, owned copy must be writable for the scoped patch.
                target.chmod((target.stat().st_mode & 0o777) | 0o200)
            else:
                (stage / item.name).symlink_to(item.resolve(), target_is_directory=item.is_dir())
        patcher.patch(stage / "supervisor.sh")
        return stage
    except Exception:
        shutil.rmtree(stage)
        raise


def main():
    args = sys.argv[1:]
    if args[:1] == ["--"]:
        args.pop(0)
    if not args:
        raise SystemExit("kit-entry: product command required")
    env = dict(os.environ)
    env["WOOW_OMNIGENT_SHARED_TOOLS"] = "1"
    # Keep the deployment's pinned CLI intact through the kit and SDK filters.
    env["DISABLE_AUTOUPDATER"] = "1"
    shared_names = ["WOOW_OMNIGENT_SHARED_TOOLS", "PI_AGENT_DATA_DIR", "PI_CODING_AGENT_DIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER"]
    env["OG_PASSTHROUGH"] = ",".join(dict.fromkeys(filter(None, env.get("OG_PASSTHROUGH", "").split(",") + shared_names)))
    data = env.get("PI_AGENT_DATA_DIR", "/data/pi-agent")
    env.setdefault("PI_AGENT_DATA_DIR", data)
    env.setdefault("PI_CODING_AGENT_DIR", data)
    env.setdefault("CODEX_HOME", str(Path(data) / "codex"))
    env.setdefault("CLAUDE_CONFIG_DIR", str(Path(data) / "claude"))
    if env.get("OG_HOST_ENABLED") in ("1", "true", "yes", "on"):
        original = Path(env.get("OG_KIT_DIR", "/etc/omnigent-host"))
        try:
            stage = prepare(original)
            env["WOOW_OMNIGENT_ORIGINAL_KIT_DIR"] = str(original)
            env["OG_KIT_DIR"] = str(stage)
        except (OSError, ValueError):
            print("woow-omnigent: kit pause overlay unavailable; using original deployment manager (pause unsupported)", file=sys.stderr)
    os.execvpe(args[0], args, env)


if __name__ == "__main__":
    main()
