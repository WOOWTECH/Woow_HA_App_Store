#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

python3 tests/validate.py
python3 mcp-runtime/tests/verify_vendor.py
python3 -B mcp-runtime/tests/unit/test_od_rules.py
sh -n paseo-runtime/install.sh
bash -n tests/paseo-ingress-e2e.sh
sh -n mcp-runtime/install.sh
sh -n mcp-runtime/tests/unit/run.sh
bash -n mcp-runtime/tests/e2e/run-proof.sh
bash -n mcp-runtime/tests/e2e/run-upgrade-proof.sh
python3 tests/workflow-policy.test.py
python3 tests/candidate-release.test.py
python3 tests/backup-exclude.test.py
python3 -B tests/ha-return.test.py
python3 -B tests/credential-permissions.test.py
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

shellcheck_bin=${SHELLCHECK_BIN:-shellcheck}
if command -v "$shellcheck_bin" >/dev/null 2>&1; then
  "$shellcheck_bin" rootfs/usr/local/bin/ha-opendesign .github/scripts/release-preflight.sh .github/scripts/import-core.sh .github/scripts/pin-core.sh tests/run.sh tests/container-smoke.sh tests/import-core.test.sh tests/pin-core.test.sh tests/paseo-ingress-e2e.sh paseo-runtime/install.sh
else
  echo "shellcheck: SKIP (not installed)"
fi

nginx_bin=${NGINX_BIN:-nginx}
if command -v "$nginx_bin" >/dev/null 2>&1; then
  nginx_test_dir=$(mktemp -d)
  trap 'rm -rf "$nginx_test_dir"' EXIT
  mkdir -p "$nginx_test_dir"/{client,proxy,fastcgi,uwsgi,scgi}
  # shellcheck disable=SC2016 # Keep nginx variable names literal in the fixture.
  printf 'set $ha_return_path "/";\nset $ha_return_label "← 返回 Home Assistant";\n' >"$nginx_test_dir/back-link.conf"
  sed -e "s#/etc/nginx/paseo-proxy.conf#$PWD/rootfs/etc/nginx/paseo-proxy.conf#g" \
      -e "s#/run/ha-opendesign-return/back-link.conf#$nginx_test_dir/back-link.conf#g" \
      rootfs/etc/nginx/paseo-setup.conf >"$nginx_test_dir/paseo-setup.conf"
  sed -e "s#/tmp/ha-opendesign-nginx#$nginx_test_dir#g" \
      -e "s#/etc/nginx/mime.types#${NGINX_MIME_TYPES:-/etc/nginx/mime.types}#g" \
      -e "s#/etc/nginx/paseo-proxy.conf#$PWD/rootfs/etc/nginx/paseo-proxy.conf#g" \
      -e "s#/etc/nginx/paseo-setup.conf#$nginx_test_dir/paseo-setup.conf#g" \
      rootfs/etc/nginx/nginx.conf >"$nginx_test_dir/nginx.conf"
  "$nginx_bin" -e stderr -t -c "$nginx_test_dir/nginx.conf"
  ./tests/paseo-ingress-e2e.sh
  rm -rf "$nginx_test_dir"
  trap - EXIT
else
  echo "nginx -t: SKIP (not installed)"
fi

echo "all non-container validation passed"
