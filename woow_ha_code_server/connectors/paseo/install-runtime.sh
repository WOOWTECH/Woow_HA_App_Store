#!/usr/bin/env bash
set -euo pipefail
# Build-time operation only. No state, agents, credentials, or daemon are created.
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
target_dir="${1:-/opt/woow-connectors/paseo}"
if [[ "$target_dir" != /* ]]; then
  printf '%s\n' 'Paseo runtime target must be absolute.' >&2
  exit 2
fi
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if(major<22||(major===22&&minor<19)) process.exit(1)'
node --input-type=module - "$source_dir" <<'NODE'
import { pathToFileURL } from 'node:url';
const { requireSystemTools } = await import(pathToFileURL(process.argv[2] + '/src/system-tools.mjs'));
await requireSystemTools();
NODE
mkdir -p "$target_dir/runtime"
if [[ "$source_dir/runtime" != "$target_dir/runtime" ]]; then
  cp "$source_dir/runtime/package.json" "$source_dir/runtime/package-lock.json" "$target_dir/runtime/"
fi
npm ci --prefix "$target_dir/runtime" --omit=dev --no-audit --no-fund >&2
node --input-type=module - "$source_dir" "$target_dir/runtime" <<'NODE'
import { pathToFileURL } from 'node:url';
const [source, root] = process.argv.slice(2);
const { applyPidLockPatch } = await import(pathToFileURL(source + '/src/pid-lock-patch.mjs'));
const { applyClaudeRootPatch } = await import(pathToFileURL(source + '/src/claude-root-patch.mjs'));
const { runtimeReady } = await import(pathToFileURL(source + '/src/runtime-layout.mjs'));
applyPidLockPatch(root);
applyClaudeRootPatch(root);
if (!runtimeReady({ runtimeDir: root })) throw new Error('PASEO_RUNTIME_VALIDATION_FAILED');
NODE
