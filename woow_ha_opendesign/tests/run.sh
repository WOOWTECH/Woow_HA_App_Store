#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

python3 tests/validate.py
python3 mcp-runtime/tests/verify_vendor.py
python3 -B mcp-runtime/tests/unit/test_od_rules.py
sh -n mcp-runtime/install.sh
sh -n mcp-runtime/tests/unit/run.sh
bash -n mcp-runtime/tests/e2e/run-proof.sh
bash -n mcp-runtime/tests/e2e/run-upgrade-proof.sh
python3 tests/workflow-policy.test.py
python3 tests/sign-in-hint.test.py
python3 tests/import-core-policy.test.py

for file in rootfs/opt/ha-opendesign/*.js rootfs/opt/ha-opendesign/*.mjs tests/*.mjs mcp-runtime/tests/e2e/*.mjs docs/repro/*.cjs; do
  node --check "$file"
done

# bash -n checks only its first file argument: one call per script.
for file in rootfs/usr/local/bin/ha-opendesign rootfs/usr/local/bin/ha-opendesign-agents .github/scripts/release-preflight.sh .github/scripts/import-core.sh .github/scripts/pin-core.sh tests/run.sh tests/container-smoke.sh tests/import-core.test.sh tests/pin-core.test.sh; do
  bash -n "$file"
done
node --test tests/*.test.mjs
bash tests/import-core.test.sh
bash tests/pin-core.test.sh

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck rootfs/usr/local/bin/ha-opendesign .github/scripts/release-preflight.sh .github/scripts/import-core.sh .github/scripts/pin-core.sh tests/run.sh tests/container-smoke.sh tests/import-core.test.sh tests/pin-core.test.sh
else
  echo "shellcheck: SKIP (not installed)"
fi

if command -v nginx >/dev/null 2>&1; then
  mkdir -p /tmp/ha-opendesign-nginx/{client,proxy,fastcgi,uwsgi,scgi}
  nginx_test_config=$(mktemp)
  trap 'rm -f "$nginx_test_config"' EXIT
  sed -e 's#/dev/stderr#/tmp/ha-opendesign-nginx/error.log#' \
      -e 's#/dev/stdout#/tmp/ha-opendesign-nginx/access.log#' \
      rootfs/etc/nginx/nginx.conf >"$nginx_test_config"
  nginx -t -c "$nginx_test_config"
  rm -f "$nginx_test_config"
  trap - EXIT
else
  echo "nginx -t: SKIP (not installed)"
fi

echo "all non-container validation passed"
