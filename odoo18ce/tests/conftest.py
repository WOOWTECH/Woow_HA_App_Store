"""Shared helpers for the static tier.

The static tier runs without a live Odoo. Some of it still needs OS tools:
nginx to validate rendered gateway configs and node to check the runtime shim.
Locally a missing tool skips those tests; in CI a missing tool is a failure,
because CI is where the static tier is supposed to be complete.
"""
import os
import shutil

import pytest


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    if os.environ.get("CI"):
        pytest.fail(f"{name} is required for the static tier in CI")
    pytest.skip(f"{name} is not installed; install it to run this test locally")


def require_bash() -> str:
    """A bash that can source files by their repo path.

    On Windows `bash` on PATH may be the WSL launcher in System32, which
    cannot open `C:/...` paths; Git's bash can. Prefer Git's when it is
    there — the real binary under `usr/bin`, not the `bin/bash.exe`
    launcher, which puts Git's own `usr/bin` in front of PATH and so in
    front of any executable a test puts there — and skip rather than fail
    on a bash that cannot see the tree.
    """
    if os.name == "nt":
        for candidate in (
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files\Git\bin\bash.exe",
        ):
            if os.path.exists(candidate):
                return candidate
        path = shutil.which("bash")
        if path and "system32" in path.lower():
            pytest.skip("only the WSL bash launcher is on PATH; it cannot read repo paths")
    return require_tool("bash")
