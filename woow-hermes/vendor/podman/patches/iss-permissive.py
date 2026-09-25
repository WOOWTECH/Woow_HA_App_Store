#!/usr/bin/env python3
# MCP SDK patch — tolerate iss mismatch when the AS did NOT advertise
# `authorization_response_iss_parameter_supported` in its metadata.
#
# This works around broken OAuth proxies (e.g. mcp.higgsfield.ai) that
# advertise themselves as issuer but forward the upstream provider's iss
# in the callback. Under RFC 9207 strict rules the SDK aborts the flow;
# per SEP-2468 the check is only mandatory when the server declares support.
#
# Idempotent: skips cleanly if already patched.
# Run inside container: `python3 /tmp/patches/iss-permissive.py`
import glob
import os
import sys

# Locate the MCP SDK auth utils regardless of python minor version.
candidates = sorted(
    glob.glob("/opt/hermes/.venv/lib/python*/site-packages/mcp/client/auth/utils.py")
)
if not candidates:
    print("  [FAIL] mcp/client/auth/utils.py not found")
    sys.exit(1)
path = candidates[-1]

with open(path, encoding="utf-8") as f:
    src = f.read()

marker = "iss mismatch tolerated"
if marker in src:
    print(f"  [skip] {path} (already patched)")
    sys.exit(0)

old = (
    "    if iss is not None:\n"
    "        if iss != expected:\n"
    "            raise OAuthFlowError(f\"Authorization response iss mismatch: {iss} != {expected}\")\n"
    "        return\n"
    "\n"
    "    if oauth_metadata is not None and oauth_metadata.authorization_response_iss_parameter_supported:\n"
    "        raise OAuthFlowError(\"Authorization response missing iss parameter advertised by the authorization server\")"
)
new = (
    "    advertised = bool(oauth_metadata is not None and oauth_metadata.authorization_response_iss_parameter_supported)\n"
    "    if iss is not None:\n"
    "        if iss != expected:\n"
    "            if advertised:\n"
    "                raise OAuthFlowError(f\"Authorization response iss mismatch: {iss} != {expected}\")\n"
    "            import logging as _lg\n"
    "            _lg.getLogger(__name__).warning(\"iss mismatch tolerated (server did not advertise iss support): %s != %s\", iss, expected)\n"
    "        return\n"
    "\n"
    "    if advertised:\n"
    "        raise OAuthFlowError(\"Authorization response missing iss parameter advertised by the authorization server\")"
)
if old not in src:
    print(f"  [FAIL] {path} anchor missing (SDK upgraded?)")
    sys.exit(1)
with open(path, "w", encoding="utf-8") as f:
    f.write(src.replace(old, new, 1))
print(f"  [ok]   {path}")
