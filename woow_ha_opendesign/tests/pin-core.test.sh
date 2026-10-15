#!/usr/bin/env bash
# .github/scripts/pin-core.sh rewrites every core pin on a copy of the repository and refuses bad input.
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/.github/scripts" "$work/.github/workflows" "$work/tests"
cp "$root/Dockerfile" "$root/build.yaml" "$work/"
cp "$root/.github/scripts/pin-core.sh" "$work/.github/scripts/"
cp "$root/.github/workflows/build.yml" "$work/.github/workflows/"
cp "$root/tests/validate.py" "$root/tests/core-base.test.mjs" "$work/tests/"
digest=sha256:$(printf '%064d' 7)
bash "$work/.github/scripts/pin-core.sh" 20991231.2359 "$digest" >/dev/null
for file in Dockerfile build.yaml .github/workflows/build.yml tests/validate.py tests/core-base.test.mjs; do
  grep -qF "ghcr.io/woowtech/open-design-core:20991231.2359" "$work/$file" || { echo "not re-pinned: $file"; exit 1; }
done
grep -qF "ARG BUILD_FROM=ghcr.io/woowtech/open-design-core:20991231.2359@$digest" "$work/Dockerfile"
grep -qF "amd64: ghcr.io/woowtech/open-design-core:20991231.2359" "$work/build.yaml"
if grep -qF "20991231.2359@" "$work/build.yaml"; then  # Supervisor local builds take the tag only
  echo "build.yaml got a digest"; exit 1
fi
for bad in "latest $digest" "20991231.2359 sha256:abc" "20991231.2359-pending $digest"; do
  # shellcheck disable=SC2086
  if bash "$work/.github/scripts/pin-core.sh" $bad >/dev/null 2>&1; then echo "accepted: $bad"; exit 1; fi
done
echo "pin-core: ok"
