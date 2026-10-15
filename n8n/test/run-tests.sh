#!/usr/bin/env bash
# Run every repository test that needs no Docker image: the configuration,
# script and nginx tests plus the ingress browser regression.
# Needs: bash, jq, python3 with requirements.txt (PyYAML, Playwright with
# Chromium) and nginx (with the sub module) in PATH.
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
export PYTHON

run() {
    printf '\n==> %s\n' "$*"
    "$@"
}

run bash "${TEST_DIR}/test-cloudflare-config.sh"
run bash "${TEST_DIR}/test-runtime-security.sh"
run "${PYTHON}" "${TEST_DIR}/test-upstream-pins.py"
run "${PYTHON}" "${TEST_DIR}/test-prebuilt-image-release.py"
run "${PYTHON}" "${TEST_DIR}/test-apk-bootstrap.py"
run "${PYTHON}" "${TEST_DIR}/test-ingress-nginx.py"
run "${PYTHON}" "${TEST_DIR}/test-ingress-preload-dedup.py"

printf '\nall repository tests passed\n'
