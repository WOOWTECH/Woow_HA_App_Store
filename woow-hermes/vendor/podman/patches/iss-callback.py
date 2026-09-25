#!/usr/bin/env python3
# Hermes source patch — forward RFC 9207 `iss` from Dashboard OAuth callback
# through DashboardOAuthFlow.deliver_callback() into
# _authorization_code_result(), so the MCP SDK can validate it.
#
# Idempotent: skips cleanly if signatures already contain `iss`.
# Run inside container: `python3 /tmp/patches/iss-callback.py`
import os
import sys

os.chdir("/opt/hermes")


def patch(path: str, replacements: list[tuple[str, str, str]]) -> None:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    changed = False
    for label, old, new in replacements:
        # `new` is often a superset of `old` (adding lines). Test new first:
        # if the fully-patched form is already present, skip regardless of
        # whether `old` still matches (it will when new = old + suffix).
        if new in src:
            print(f"  [skip] {path}::{label} (already patched)")
            continue
        if old not in src:
            print(f"  [FAIL] {path}::{label} anchor missing")
            sys.exit(1)
        src = src.replace(old, new, 1)
        changed = True
        print(f"  [ok]   {path}::{label}")
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)


# ── Patch 1: web_routers/mcp.py ──
patch(
    "hermes_cli/web_routers/mcp.py",
    [
        (
            "signature",
            "    error: Optional[str] = None,\n):\n    _gc_mcp_oauth_flows()",
            "    error: Optional[str] = None,\n    iss: Optional[str] = None,\n):\n    _gc_mcp_oauth_flows()",
        ),
        (
            "call",
            "flow.deliver_callback(code=code, state=state, error=error)",
            "flow.deliver_callback(code=code, state=state, error=error, iss=iss)",
        ),
    ],
)

# ── Patch 2: tools/mcp_dashboard_oauth.py ──
patch(
    "tools/mcp_dashboard_oauth.py",
    [
        (
            "field",
            "    _callback_error: str | None = field(default=None, init=False, repr=False)",
            "    _callback_error: str | None = field(default=None, init=False, repr=False)\n"
            "    _callback_iss: str | None = field(default=None, init=False, repr=False)",
        ),
        (
            "signature",
            "    def deliver_callback(\n"
            "        self,\n"
            "        *,\n"
            "        code: str | None,\n"
            "        state: str | None,\n"
            "        error: str | None,\n"
            "    ) -> None:",
            "    def deliver_callback(\n"
            "        self,\n"
            "        *,\n"
            "        code: str | None,\n"
            "        state: str | None,\n"
            "        error: str | None,\n"
            "        iss: str | None = None,\n"
            "    ) -> None:",
        ),
        (
            "store",
            "            elif code:\n                self._callback = (code, state)",
            "            elif code:\n                self._callback = (code, state)\n                self._callback_iss = iss",
        ),
    ],
)

# ── Patch 3: tools/mcp_oauth.py ──
patch(
    "tools/mcp_oauth.py",
    [
        (
            "forward-iss",
            "            dash_code, dash_state = await dashboard_flow.wait_for_callback()\n"
            "            return _authorization_code_result(dash_code, dash_state)",
            "            dash_code, dash_state = await dashboard_flow.wait_for_callback()\n"
            "            return _authorization_code_result(dash_code, dash_state, iss=dashboard_flow._callback_iss)",
        ),
    ],
)

print("ALL OK")
