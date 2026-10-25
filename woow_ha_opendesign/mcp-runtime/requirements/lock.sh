#!/usr/bin/env bash
# Regenerate the hash-pinned wheel lists for the base image's Python (default 3.14, Alpine/musl).
# *.in pin EXACT versions of every package (management: the gateway process, child: the OpenDesign tools). Until 0.2.3
# they were the versions of the vendored source's uv.lock (management: /uv.lock, child: apps/opendesign/uv.lock).
# 0.2.4-0.2.5: the newest releases that fit MCP Python SDK 1.x. Since 0.2.6 (the joint SDK 2 round with the WOOW PaaS
# and the HA MCP add-ons 0.4.0): child: mcp 2.3.0 and mcp-types 2.3.0 exactly (the vendored runtime reviewed that SDK's
# tool dispatch and error handling: apps/runtime/bounded_tools.py, tool_error_text.py), whose HTTP stack (httpx2,
# httpcore2, truststore, opentelemetry-api) replaces httpx-sse, pydantic-settings and python-dotenv, while the tools'
# backend client stays on the sources apps/runtime/backend_policy.py reviewed, httpx 0.28.1 / httpcore 1.0.9; every other
# package at its newest release, except starlette 1.9.0 and sse-starlette 3.5.0, kept in step with the WOOW PaaS twin and
# the HA MCP add-ons 0.4.0 children (owner decision 2026-10-25: their 1.10.0 / 3.5.1 of 2026-10-24 fix nothing and change
# behaviour). management: what the HA MCP add-ons 0.4.0 pin for their core gateway (/uv.lock there), except where this
# add-on already pins a newer release of the same major, which it keeps (all of them in 0.2.6: management is 0.2.5's set);
# no new major (websockets stays on 16.x). Never below the WOOW PaaS floor certifi 2026.10.23.
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
