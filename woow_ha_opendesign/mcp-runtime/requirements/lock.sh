#!/usr/bin/env bash
# Regenerate the hash-pinned wheel lists for the base image's Python (default 3.14, Alpine/musl).
# *.in pin EXACT versions of every package (management: the gateway process, child: the OpenDesign tools). Until 0.2.3
# they were the versions of the vendored source's uv.lock (management: /uv.lock, child: apps/opendesign/uv.lock).
# Since 0.2.4 they are the newest releases that fit MCP Python SDK 1.x (mcp<2; 2.x is a separate migration) and the
# sources the vendored runtime reviewed: httpx 0.28.1 / httpcore 1.0.9 (apps/runtime/backend_policy.py) and the SDK's
# tool dispatch (apps/runtime/bounded_tools.py); never below the WOOW PaaS floors mcp 1.30.0 and certifi 2026.10.23.
# Major updates wait for a joint round with the WOOW PaaS and the HA MCP add-ons (owner decision 2026-10-24): websockets
# stays on the newest 16.x, mcp on 1.x.
# To raise them: change *.in (find the newest set with a loose `uv pip compile`), run this script, run the unit tests.
# Hashes cover every published wheel of each pinned version, so amd64 and aarch64 both install.
set -Eeuo pipefail
cd "$(dirname "$0")"
python=${1:-3.14}
for name in management child; do
  uv pip compile "$name.in" --python-version "$python" --python-platform x86_64-unknown-linux-musl \
    --generate-hashes --no-header --no-annotate -o "$name.txt"
  diff <(grep -o '^[a-z0-9_.-]*==[^ ]*' "$name.txt" | sort) <(sort "$name.in")
done
