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
