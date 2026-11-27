#!/usr/bin/env bash
set -euo pipefail
# Build/setup-time only. Extension commands never install dependencies.
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
target_dir="${1:-/opt/woow-connectors/paseo}"
if [[ "$target_dir" != /* ]]; then
  printf '%s\n' 'Agent Connect runtime target must be absolute.' >&2
  exit 2
fi
exec node "$source_dir/src/runtime-installer.mjs" "$target_dir"
