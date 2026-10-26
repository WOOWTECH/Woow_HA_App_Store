#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
(cd paseo-runtime && sha256sum -c checksums.sha256)
tar -xzf paseo-runtime/package.tgz --strip-components=1 -C "$fixture"
cp paseo-runtime/package-lock.json "$fixture/package-lock.json"
npm ci --omit=dev --ignore-scripts --no-audit --no-fund --prefix "$fixture"
PASEO_PACKAGE_ROOT="$fixture" node --test tests/paseo-ingress-e2e.mjs tests/paseo-startup-e2e.mjs
