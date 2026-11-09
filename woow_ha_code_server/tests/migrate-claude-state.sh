#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
export CLAUDE_CANONICAL_DIR=$scratch/pi-agent/claude
export CLAUDE_LEGACY_DIR=$scratch/legacy-claude
mkdir -p "$CLAUDE_LEGACY_DIR"
printf 'legacy-login\n' > "$CLAUDE_LEGACY_DIR/credentials"

[ "$(sh "$repo/rootfs/usr/local/bin/migrate-claude-state")" = copied ]
[ "$(cat "$CLAUDE_CANONICAL_DIR/credentials")" = legacy-login ]
[ "$(cat "$CLAUDE_LEGACY_DIR/credentials")" = legacy-login ]
[ "$(stat -c %a "$CLAUDE_CANONICAL_DIR")" = 700 ]

printf 'current-login\n' > "$CLAUDE_CANONICAL_DIR/credentials"
[ "$(sh "$repo/rootfs/usr/local/bin/migrate-claude-state")" = retained ]
[ "$(cat "$CLAUDE_CANONICAL_DIR/credentials")" = current-login ]
[ "$(cat "$CLAUDE_LEGACY_DIR/credentials")" = legacy-login ]
echo 'Claude migration: copied an empty target and preserved an existing login'
