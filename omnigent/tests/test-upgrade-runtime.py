#!/usr/bin/env python3
"""Run actual HTTP seed/verify across published and candidate runtimes, SQLite.

Supply two Python environments with omnigent installed. This does not test
HA Supervisor, PostgreSQL, Alpine or aarch64; those remain release gates.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from unittest.mock import patch

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON / "upgrade-check"))
import omnigent_upgrade as hooks


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-python", type=Path, required=True)
    ap.add_argument("--new-python", type=Path, required=True)
    ap.add_argument("--state", type=Path, required=True, help="new private directory for test evidence")
    args = ap.parse_args()
    root = args.state.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    for folder in ("data", "hooks", "reports", "runtime"):
        (root / folder).mkdir(mode=0o700)
    options = {"admin_username": "upgrade-admin", "admin_password": secrets.token_urlsafe(24),
               "mcp_public_base_url": "https://mcp.example.test"}
    (root / "data/options.json").write_text(json.dumps(options))
    (root / "data/options.json").chmod(0o600)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OMNIGENT_", "OPENAI_", "ANTHROPIC_", "PYTHONPATH"))}
    env.update({"UPGRADE_RUNTIME_DIR": str(root / "runtime"), "UPGRADE_RUNTIME_PORT": str(port),
                "PYTHONDONTWRITEBYTECODE": "1", "OMNIGENT_AUTH_PROVIDER": "accounts", "OMNIGENT_AUTH_ENABLED": "1",
                "OMNIGENT_ACCOUNTS_COOKIE_SECRET": secrets.token_hex(32),
                "OMNIGENT_ACCOUNTS_BASE_URL": base, "OMNIGENT_MCP_PUBLIC_BASE_URL": options["mcp_public_base_url"],
                "OMNIGENT_ACCOUNTS_INIT_ADMIN_USERNAME": options["admin_username"],
                "OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD": options["admin_password"],
                "OMNIGENT_ADMIN_CREDENTIALS_PATH": str(root / "runtime/admin-credentials"),
                "ARTIFACT_DIR": str(root / "runtime/artifacts"), "OMNIGENT_PUBLIC_SHARING": "0",
                "OMNIGENT_ACCOUNTS_AUTO_OPEN": "0", "ADDON_URL": base,
                "DATA_DIR_DATA": str(root / "data"), "HOOK_STATE_DIR": str(root / "hooks"),
                "REPORT_DIR": str(root / "reports")})

    @contextlib.contextmanager
    def server(python, phase):
        with (root / f"{phase}.log").open("w") as log:
            proc = subprocess.Popen([str(python.absolute()), str(ADDON / "tests/runtime_server.py")],
                                    cwd=root / "runtime", env=env, stdout=log, stderr=log)
            try:
                for _ in range(300):
                    if proc.poll() is not None:
                        raise RuntimeError(f"{phase} exited {proc.returncode}; inspect private log")
                    try:
                        with urllib.request.urlopen(base + "/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError(f"{phase} did not become ready")
                yield
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    def hook(name, phase):
        report = root / "reports" / phase
        report.mkdir()
        subprocess.run([sys.executable, str(ADDON / "upgrade-check" / name)],
                       env={**env, "REPORT_DIR": str(report)}, check=True)

    with server(args.old_python, "published"):
        hook("seed", "published-seed")
    with server(args.new_python, "candidate"):
        hook("verify", "candidate-verify")
        # Record candidate-era tokens for a real process stop/start. The
        # same hook also handles future MCP A -> B candidate upgrades.
        keys = ("ADDON_URL", "DATA_DIR_DATA", "HOOK_STATE_DIR", "REPORT_DIR")
        with patch.dict(os.environ, {k: env[k] for k in keys}):
            state = json.loads((root / "hooks/omnigent-seed.json").read_text())
            api = hooks.Client(base)
            api.login(options["admin_username"], options["admin_password"])
            hooks.seed_profiles(api, state)
            (root / "hooks/omnigent-seed.json").write_text(json.dumps(state))
    with server(args.new_python, "candidate-restarted"):
        hook("verify", "candidate-restart-verify")
        # A negative control proves content loss is detected, not just startup.
        path = root / "hooks/omnigent-seed.json"
        state = json.loads(path.read_text())
        state["artifact"]["sha256"] = "0" * 64
        path.write_text(json.dumps(state))
        negative = root / "reports/negative-control"
        negative.mkdir()
        result = subprocess.run([sys.executable, str(ADDON / "upgrade-check/verify")],
                                env={**env, "REPORT_DIR": str(negative)}, capture_output=True, text=True)
        report = json.loads((negative / "verify.json").read_text())
        assert result.returncode != 0 and any(c["name"] == "private/shared sessions and artifact kept" and
                                             c["result"] == "fail" for c in report["checks"]), "negative control failed"
        print("PASS negative control: changed artifact digest is detected")
    print("PASS published -> candidate -> restart data/profile checks (SQLite)")


if __name__ == "__main__":
    main()
