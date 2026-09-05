#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

# The execution harness invokes the pinned Pi binary directly, outside Docker.
# Keep its installation ephemeral so non-container validation leaves no workspace artifacts.
cleanup_pi_runtime() {
  rm -rf runtime/pi/node_modules
}
trap cleanup_pi_runtime EXIT
npm ci --prefix runtime/pi

python3 tests/validate.py
python3 tests/workflow-policy.test.py

for file in rootfs/opt/ha-opendesign/*.js rootfs/opt/ha-opendesign/*.mjs tests/*.mjs; do
  node --check "$file"
done

bash -n rootfs/usr/local/bin/ha-opendesign rootfs/usr/local/bin/pi .github/scripts/release-preflight.sh tests/run.sh tests/container-smoke.sh
node --test tests/*.test.mjs

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck rootfs/usr/local/bin/ha-opendesign .github/scripts/release-preflight.sh tests/run.sh tests/container-smoke.sh
else
  echo "shellcheck: SKIP (not installed)"
fi

if command -v nginx >/dev/null 2>&1; then
  mkdir -p /tmp/ha-opendesign-nginx/{client,proxy,fastcgi,uwsgi,scgi}
  nginx_test_config=$(mktemp)
  trap 'rm -f "$nginx_test_config"; cleanup_pi_runtime' EXIT
  sed -e 's#/dev/stderr#/tmp/ha-opendesign-nginx/error.log#' \
      -e 's#/dev/stdout#/tmp/ha-opendesign-nginx/access.log#' \
      rootfs/etc/nginx/nginx.conf >"$nginx_test_config"
  nginx -t -c "$nginx_test_config"
  rm -f "$nginx_test_config"
  cleanup_pi_runtime
  trap - EXIT
else
  echo "nginx -t: SKIP (not installed)"
fi

echo "all non-container validation passed"
