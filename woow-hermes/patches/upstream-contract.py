#!/usr/bin/env python3
"""Exercise upstream contracts that supersede the old WOOW login/OAuth patches.

Runs against the digest-pinned image during its build. No real account, network
connection, credentials or model is used.
"""
import argparse
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, default=Path("/opt/hermes"))
args = parser.parse_args()
sys.path.insert(0, str(args.root))

from hermes_cli.dashboard_auth import login_page
from tools.mcp_dashboard_oauth import DashboardOAuthFlow

prefix = "/api/hassio_ingress/" + "a" * 32
original = login_page.list_session_providers
try:
    login_page.list_session_providers = lambda: [
        SimpleNamespace(name="password", display_name="Password", supports_password=True),
        SimpleNamespace(name="oauth", display_name="OAuth", supports_password=False),
    ]
    rendered = login_page.render_login_html(prefix=prefix)
    assert f'data-prefix="{prefix}"' in rendered
    assert "fetch(prefix + '/auth/password-login'" in rendered
    assert f'href="{prefix}/auth/login?provider=oauth"' in rendered
    assert f"url('{prefix}/fonts/" in rendered
    assert "window.location.assign((data && data.next) || (prefix + '/'))" in rendered
    bare = login_page.render_login_html()
    assert 'href="/auth/login?provider=oauth"' in bare
finally:
    login_page.list_session_providers = original

flow = DashboardOAuthFlow(flow_id="synthetic", server_name="test", profile=None,
                         hermes_home="/tmp", redirect_uri="https://example.invalid/callback")
flow.expected_state = "test-state"
try:
    flow.deliver_callback(code="test-code", state="wrong-state", error=None, iss="https://issuer.invalid")
except ValueError:
    pass
else:
    raise AssertionError("OAuth state mismatch was accepted")
flow.deliver_callback(code="test-code", state="test-state", error=None, iss="https://issuer.invalid")
assert asyncio.run(flow.wait_for_callback(timeout=1)) == ("test-code", "test-state", "https://issuer.invalid")
source = (args.root / "tools/mcp_oauth.py").read_text()
assert "_authorization_code_result(*await dashboard_flow.wait_for_callback())" in source
# Approval gate behavior is separately exercised by test-approval-gate.py inside
# both the candidate and published image; this verifies its current shared path.
source = (args.root / "tools/approval.py").read_text()
assert "def _presence(" in source and "_NOTIFIER_BLIND_APPROVAL_PLATFORMS" in source
print("upstream v0.22.5 HA login, OAuth state/issuer and approval contracts: ok")
