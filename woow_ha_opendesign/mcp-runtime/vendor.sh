#!/usr/bin/env bash
# Re-vendor the pinned Woow MCP runtime from a local clone of WOOWTECH/Woow_ha_mcp_addons.
#
#   mcp-runtime/vendor.sh <clone-dir> <commit-sha> [<vendored file>=<commit-sha> ...]
#
# Copies ONLY the files the built-in OpenDesign MCP needs (exact list below) with `git archive`, so
# nothing from the clone's working tree or untracked files can enter, then writes VENDOR.json with the
# source commit and the sha256 of every vendored file. Vendored files are never edited here: local
# behaviour lives in mcp-runtime/ha_opendesign_mcp/. Review the diff of vendor/ and VENDOR.json.
#
# A <vendored file>=<commit-sha> argument replaces that one file (it must be one of the files copied above) with
# its copy at another commit of the same repository, again with `git archive`; VENDOR.json records it in
# file_sources. 0.2.4 used this for the two runtime files the source repository reviewed for MCP Python SDK
# 1.30.0 on another branch; 0.2.6 keeps apps/runtime/backend_policy.py of the 0.2.5 pin (public error codes only,
# see README.md). 0.2.6 also copies apps/runtime/tool_error_text.py (MCP SDK 2) and no longer output_policy.py
# (gone from the source; the HA overlay keeps the list_runs projection).
set -Eeuo pipefail

if (( $# < 2 )); then
  echo "usage: $0 <Woow_ha_mcp_addons clone> <full commit sha> [<vendored file>=<full commit sha> ...]" >&2
  exit 64
fi
src=$1
commit=$2
shift 2
overrides=("$@")
here=$(cd "$(dirname "$0")" && pwd)
if [[ ! $commit =~ ^[0-9a-f]{40}$ ]]; then
  echo "commit must be a full 40-hex sha" >&2
  exit 64
fi
git -C "$src" cat-file -e "$commit^{commit}"
for override in "${overrides[@]}"; do
  file=${override%%=*}
  from=${override#*=}
  if [[ $override != *=* || -z $file || $file == /* || /$file/ == */../* || /$file/ == */./* || ! $from =~ ^[0-9a-f]{40}$ ]]; then
    echo "an override must be <relative vendored file>=<full 40-hex commit sha>: $override" >&2
    exit 64
  fi
  git -C "$src" cat-file -e "$from^{commit}"
  git -C "$src" cat-file -e "$from:$file"
done

paths=(
  LICENSE
  THIRD_PARTY_NOTICES.md
  docs/provenance/opendesign-upstream-chain.md
  packages/mcp-admin-core/mcp_admin_core
  packages/mcp-admin-ui/package.json
  packages/mcp-admin-ui/package-lock.json
  packages/mcp-admin-ui/NOTICE.txt
  packages/mcp-admin-ui/scripts/build.mjs
  packages/mcp-admin-ui/src
  apps/runtime/backend_policy.py
  apps/runtime/bounded_tools.py
  apps/runtime/session_idle.py
  apps/runtime/tool_error_text.py
  apps/opendesign/launch.py
  apps/opendesign/vendor
  packaging/entrypoint.py
  packaging/management_launcher.py
)

rm -rf "$here/vendor"
mkdir -p "$here/vendor"
git -C "$src" archive --format=tar "$commit" -- "${paths[@]}" | tar -x -C "$here/vendor"
for override in "${overrides[@]}"; do
  file=${override%%=*}
  if [[ ! -f $here/vendor/$file || -L $here/vendor/$file ]]; then
    echo "not a vendored file of $commit: $file" >&2
    exit 64
  fi
  git -C "$src" archive --format=tar "${override#*=}" -- "$file" | tar -x -C "$here/vendor"
done

python3 - "$here" "$commit" "${overrides[@]}" <<'PY'
import hashlib, json, pathlib, sys
here, commit = pathlib.Path(sys.argv[1]), sys.argv[2]
sources = dict(sorted(override.split('=', 1) for override in sys.argv[3:]))
root = here / 'vendor'
files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(root.rglob('*')) if p.is_file()}
manifest = {
    'source_repository': 'https://github.com/WOOWTECH/Woow_ha_mcp_addons',
    'source_commit': commit,
}
if sources:
    manifest['file_sources'] = sources
manifest['note'] = 'Pinned copy; never edit vendor/ by hand. Re-run vendor.sh and review the diff.'
manifest['files'] = files
(here / 'VENDOR.json').write_text(json.dumps(manifest, indent=2, sort_keys=False) + '\n')
print('vendored %d files from %s' % (len(files), commit)
      + ''.join('\n  %s from %s' % item for item in sources.items()))
PY
