#!/usr/bin/env bash
# Regenerate the hash-pinned wheel lists for the base image's Python (default 3.14, Alpine/musl).
# *.in pin EXACTLY the versions of the vendored source's uv.lock (management: /uv.lock, child:
# apps/opendesign/uv.lock); only the interpreter differs (the source pins CPython 3.13, the core image has 3.14).
# Hashes cover every published wheel of each pinned version, so amd64 and aarch64 both install.
set -Eeuo pipefail
cd "$(dirname "$0")"
python=${1:-3.14}
for name in management child; do
  uv pip compile "$name.in" --python-version "$python" --python-platform x86_64-unknown-linux-musl \
    --generate-hashes --no-header --no-annotate -o "$name.txt"
  diff <(grep -o '^[a-z0-9_.-]*==[^ ]*' "$name.txt" | sort) <(sort "$name.in")
done
