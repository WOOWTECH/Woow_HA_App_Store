#!/usr/bin/env bash
# ok() always returns 0, so `A && ok || bad` is a plain if/else in this file.
# shellcheck disable=SC2015
# Behaviour tests for .github/scripts/import-core.sh with fake skopeo/curl (no network).
set -Eeuo pipefail
cd "$(dirname "$0")/.."
SCRIPT=$PWD/.github/scripts/import-core.sh
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT
PASS=0 FAIL=0
ok() { echo "  ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $1"; FAIL=$((FAIL + 1)); }

SRC=jcr-prod.woowtech.io/woow-paas-docker-local/open-design-core
DEST=ghcr.io/woowtech/open-design-core
TAG=20261014.2300

mkdir -p "$ROOT/bin"
cat > "$ROOT/bin/skopeo" <<'SK'
#!/usr/bin/env bash
# fake skopeo: refs map to files in $STATE/refs/<ref with / : @ -> _>
key() { local r=${1#docker://}; r=${r//\//_}; r=${r//:/_}; echo "${r//@/_}"; }
echo "skopeo $*" >> "$STATE/calls.log"
case "$1" in
  inspect)
    if [ "$2" = --raw ]; then f="$STATE/refs/$(key "$3")"
      [ -f "$f" ] && { cat "$f"; exit 0; }
      if [[ "$3" == docker://ghcr.io/* ]]; then echo "${GHCR_MISSING_ERR:-manifest unknown}" >&2; else echo "manifest unknown" >&2; fi
      exit 1
    elif [ "$2" = --config ]; then cat "$STATE/config.json"; exit 0; fi ;;
  copy)
    shift; while [[ "$1" == --* ]]; do [ "$1" = --retry-times ] && shift; shift; done
    [ "${COPY_FAILS:-0}" = 1 ] && exit 1
    cp "$STATE/refs/$(key "$1")" "$STATE/refs/$(key "$2")"
    # a registry also serves the pushed manifest by its digest
    d=$(sha256sum "$STATE/refs/$(key "$2")" | cut -d' ' -f1); repo=${2%:*}
    cp "$STATE/refs/$(key "$2")" "$STATE/refs/$(key "${repo}@sha256:${d}")"
    echo "copy $1 $2" >> "$STATE/copies.log"; exit 0 ;;
esac
exit 2
SK
cat > "$ROOT/bin/curl" <<'CU'
#!/usr/bin/env bash
# fake curl: token endpoint + anonymous manifest GET; public only when $STATE/public exists
out="" url=""
while [ $# -gt 0 ]; do case "$1" in --output) out=$2; shift 2 ;; --write-out|--header|--request|--data-urlencode) shift 2 ;; -*) shift ;; *) url=$1; shift ;; esac; done
case "$url" in
  */token) echo '{"token":"anon"}' ;;
  */v2/*/manifests/*)
    t=${url##*/}; f="$STATE/refs/ghcr.io_woowtech_open-design-core_${t}"
    if [ -f "$STATE/public" ] && [ -f "$f" ]; then cp "$f" "$out"; printf 200; else printf 401; fi ;;
esac
CU
chmod +x "$ROOT/bin/skopeo" "$ROOT/bin/curl"

setup() {  # fresh state with one approved source image
  STATE=$(mktemp -d "$ROOT/state.XXXX"); export STATE
  mkdir -p "$STATE/refs"; : > "$STATE/calls.log"; : > "$STATE/copies.log"
  printf '{"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json","layers":[]}' > "$STATE/m.json"
  DIGEST="sha256:$(sha256sum "$STATE/m.json" | cut -d' ' -f1)"
  cp "$STATE/m.json" "$STATE/refs/jcr-prod.woowtech.io_woow-paas-docker-local_open-design-core_${DIGEST/:/_}"
  cp "$STATE/m.json" "$STATE/refs/jcr-prod.woowtech.io_woow-paas-docker-local_open-design-core_${TAG}"
  printf '{"architecture":"amd64","os":"linux","config":{"Labels":{"io.woow.opendesign.source-revision":"%s","io.woow.opendesign.upstream-revision":"%s"}}}' \
    "$(printf 'a%.0s' {1..40})" "$(printf 'b%.0s' {1..40})" > "$STATE/config.json"
}
run() {  # env overrides as KEY=VAL...
  env PATH="$ROOT/bin:$PATH" STATE="$STATE" IMPORT_WORK_DIR="$(mktemp -d "$ROOT/w.XXXX")" GITHUB_STEP_SUMMARY="$STATE/summary.md" \
    CORE_TAG="$TAG" CORE_DIGEST="$DIGEST" "$@" bash "$SCRIPT" > "$STATE/out.log" 2>&1
}
dest() { echo "$STATE/refs/ghcr.io_woowtech_open-design-core_$1"; }

echo "== public package: copies by digest, verifies both paths"
setup; touch "$STATE/public"
if run CORE_ALIAS_TAG=0.24.1-w3; then ok "exit 0"; else bad "exit $?"; cat "$STATE/out.log"; fi
cmp -s "$(dest "$TAG")" "$STATE/m.json" && cmp -s "$(dest 0.24.1-w3)" "$STATE/m.json" && ok "both tags hold the exact source manifest" || bad "tag content differs"
grep -q -- "copy --preserve-digests --retry-times 5 docker://${SRC}@${DIGEST} docker://${DEST}:${TAG}" "$STATE/calls.log" && ok "copy uses --preserve-digests from the source digest" || bad "copy invocation"
grep -q "GHCR (anonymous): ${DEST}:${TAG}" "$STATE/out.log" && ok "anonymous pull verified" || bad "anonymous check missing"

echo "== re-run with the same inputs: no copy, still green"
: > "$STATE/copies.log"
if run CORE_ALIAS_TAG=0.24.1-w3; then ok "exit 0"; else bad "exit $?"; fi
[ ! -s "$STATE/copies.log" ] && ok "nothing copied" || bad "copied again"

echo "== private package (first import): published but job fails with the visibility step"
setup
if run; then bad "exit 0 although not public"; else ok "non-zero exit"; fi
[ -f "$(dest "$TAG")" ] && ok "image copied" || bad "image not copied"
grep -q "set the package visibility to Public" "$STATE/out.log" && ok "explains the visibility step" || bad "no visibility hint"

echo "== existing tag with another digest: refused, nothing copied"
setup; touch "$STATE/public"; printf '{"other":1}' > "$(dest "$TAG")"
if run; then bad "exit 0"; else ok "non-zero exit"; fi
grep -q "tags are immutable" "$STATE/out.log" && ok "immutable-tag error" || bad "wrong error"
[ ! -s "$STATE/copies.log" ] && ok "nothing copied" || bad "copied over an existing tag"

echo "== JCR tag no longer points at the digest: refused"
setup; printf '{"moved":1}' > "$STATE/refs/jcr-prod.woowtech.io_woow-paas-docker-local_open-design-core_${TAG}"
if run; then bad "exit 0"; else ok "non-zero exit"; fi
[ ! -s "$STATE/copies.log" ] && ok "nothing copied" || bad "copied"

echo "== wrong architecture / missing provenance labels: refused"
setup; sed -i 's/"amd64"/"arm64"/' "$STATE/config.json"
if run; then bad "arm64 accepted"; else ok "arm64 refused"; fi
setup; printf '{"architecture":"amd64","os":"linux","config":{"Labels":{}}}' > "$STATE/config.json"
if run; then bad "unlabelled image accepted"; else ok "unlabelled image refused"; fi

echo "== bad inputs: refused before any registry call"
for args in "CORE_TAG=${TAG}-pending-approval" "CORE_TAG=latest" "CORE_DIGEST=sha256:abc" "CORE_ALIAS_TAG=latest"; do
  setup
  if run "$args"; then bad "accepted $args"; else ok "refused $args"; fi
  [ ! -s "$STATE/calls.log" ] && ok "no registry call for $args" || bad "registry called for $args"
done

echo "== unexpected destination error: fail closed"
setup
if run GHCR_MISSING_ERR="connection reset by peer"; then bad "exit 0"; else ok "non-zero exit"; fi
[ ! -s "$STATE/copies.log" ] && ok "nothing copied" || bad "copied"

echo "passed ${PASS}, failed ${FAIL}"
[ "$FAIL" = 0 ]
