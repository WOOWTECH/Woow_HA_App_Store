#!/usr/bin/env bash
# Live Woow Nextcloud equivalence regression for direct/public/ingress entries.
# Required env:
#   NEXTCLOUD_USER, NEXTCLOUD_PASS
# Optional env:
#   DIRECT_BASE=http://homeassistant:8000
#   PUBLIC_BASE=https://woowtech-nextcloud.woowtech.io
#   INGRESS_BASE=http://172.30.33.6:8090
#   INGRESS_PATH=/api/hassio_ingress/<token-or-test-prefix>
# Notes:
#   When running outside Supervisor, temporarily allow the test client in the
#   ingress adapter and restore it after the test.
set -euo pipefail

DIRECT_BASE=${DIRECT_BASE:-http://homeassistant:8000}
PUBLIC_BASE=${PUBLIC_BASE:-https://woowtech-nextcloud.woowtech.io}
INGRESS_BASE=${INGRESS_BASE:-http://172.30.33.6:8090}
INGRESS_PATH=${INGRESS_PATH:-/api/hassio_ingress/abcdefghijklmnop}
NEXTCLOUD_USER=${NEXTCLOUD_USER:-admin}
: "${NEXTCLOUD_PASS:?NEXTCLOUD_PASS is required}"

AUTH=(-u "${NEXTCLOUD_USER}:${NEXTCLOUD_PASS}" -H 'OCS-APIRequest: true')
INGRESS_HEADER=(-H "X-Ingress-Path: ${INGRESS_PATH}")
RUN_ID="live-$(date +%s)"
TEST_DIR="/WOOW_EQ_${RUN_ID}"
DAV_DIR="/remote.php/dav/files/${NEXTCLOUD_USER}${TEST_DIR}"
TMP=${TMPDIR:-/tmp}/nc-eq-${RUN_ID}
mkdir -p "$TMP"

pass=0
fail=0
record() {
  local name=$1 ok=$2 details=${3:-}
  if [[ "$ok" == "true" ]]; then
    printf 'PASS %-58s %s\n' "$name" "$details"
    pass=$((pass + 1))
  else
    printf 'FAIL %-58s %s\n' "$name" "$details"
    fail=$((fail + 1))
  fi
}
http_code() {
  local method=$1 base=$2 path=$3 header_mode=${4:-direct}
  shift 4 || true
  if [[ "$header_mode" == ingress ]]; then
    curl -sS -o "$TMP/body" -D "$TMP/head" -w '%{http_code}' --max-time 30 \
      "${AUTH[@]}" "${INGRESS_HEADER[@]}" -X "$method" "$base$path" "$@" || true
  else
    curl -sS -o "$TMP/body" -D "$TMP/head" -w '%{http_code}' --max-time 30 \
      "${AUTH[@]}" -X "$method" "$base$path" "$@" || true
  fi
}
content_type() { awk 'BEGIN{IGNORECASE=1}/^content-type:/{print $0}' "$TMP/head" | tail -1 | tr -d '\r'; }
cache_control() { awk 'BEGIN{IGNORECASE=1}/^cache-control:/{print $0}' "$TMP/head" | tail -1 | tr -d '\r'; }

printf 'Woow Nextcloud live equivalence test %s\n' "$RUN_ID"
printf 'direct=%s public=%s ingress=%s prefix=%s\n\n' "$DIRECT_BASE" "$PUBLIC_BASE" "$INGRESS_BASE" "$INGRESS_PATH"

# Anonymous/basic endpoint matrix.
paths=(
  '/status.php'
  '/login'
  '/core/css/server.css'
  '/core/img/favicon.ico'
  '/ocs/v2.php/cloud/capabilities?format=json'
  '/remote.php/dav/files/admin/'
  '/index.php/apps/files/'
  '/public.php/webdav/'
)
methods=('GET' 'GET' 'GET' 'GET' 'GET' 'PROPFIND' 'GET' 'PROPFIND')
for i in "${!paths[@]}"; do
  p=${paths[$i]}; m=${methods[$i]}
  dc=$(http_code "$m" "$DIRECT_BASE" "$p" direct); dct=$(content_type); dcc=$(cache_control)
  ic=$(http_code "$m" "$INGRESS_BASE" "$p" ingress); ict=$(content_type); icc=$(cache_control)
  pc=$(http_code "$m" "$PUBLIC_BASE" "$p" direct); pct=$(content_type)
  ok=true
  [[ "$dc" == "$ic" ]] || ok=false
  [[ "${dct,,}" == "${ict,,}" ]] || ok=false
  # Public may differ for authenticated API if Cloudflare Access is enabled; status endpoint/assets should still match.
  record "matrix $m $p" "$ok" "direct=$dc ingress=$ic public=$pc ct='$dct' cache='$dcc|$icc'"
done

# WebDAV CRUD cross-entry.
http_code DELETE "$DIRECT_BASE" "$DAV_DIR" direct >/dev/null || true
mk=$(http_code MKCOL "$DIRECT_BASE" "$DAV_DIR" direct)
record 'WebDAV MKCOL direct' "$([[ "$mk" == 201 || "$mk" == 405 ]] && echo true || echo false)" "code=$mk"
printf 'hello direct %s\n' "$RUN_ID" > "$TMP/direct.txt"
pd=$(http_code PUT "$DIRECT_BASE" "$DAV_DIR/direct.txt" direct --data-binary "@$TMP/direct.txt")
gi=$(http_code GET "$INGRESS_BASE" "$DAV_DIR/direct.txt" ingress)
record 'direct PUT -> ingress GET' "$([[ "$pd" =~ ^(201|204)$ && "$gi" == 200 ]] && cmp -s "$TMP/direct.txt" "$TMP/body" && echo true || echo false)" "put=$pd get=$gi"
printf 'hello ingress %s\n' "$RUN_ID" > "$TMP/ingress.txt"
pi=$(http_code PUT "$INGRESS_BASE" "$DAV_DIR/ingress.txt" ingress --data-binary "@$TMP/ingress.txt")
gd=$(http_code GET "$DIRECT_BASE" "$DAV_DIR/ingress.txt" direct)
record 'ingress PUT -> direct GET' "$([[ "$pi" =~ ^(201|204)$ && "$gd" == 200 ]] && cmp -s "$TMP/ingress.txt" "$TMP/body" && echo true || echo false)" "put=$pi get=$gd"
ci=$(http_code COPY "$INGRESS_BASE" "$DAV_DIR/direct.txt" ingress -H "Destination: ${INGRESS_BASE}${DAV_DIR}/direct-copy.txt")
gc=$(http_code GET "$DIRECT_BASE" "$DAV_DIR/direct-copy.txt" direct)
record 'ingress COPY -> direct GET' "$([[ "$ci" =~ ^(201|204)$ && "$gc" == 200 ]] && echo true || echo false)" "copy=$ci get=$gc"
mi=$(http_code MOVE "$INGRESS_BASE" "$DAV_DIR/ingress.txt" ingress -H "Destination: ${INGRESS_BASE}${DAV_DIR}/ingress-moved.txt")
gm=$(http_code GET "$DIRECT_BASE" "$DAV_DIR/ingress-moved.txt" direct)
record 'ingress MOVE -> direct GET' "$([[ "$mi" =~ ^(201|204)$ && "$gm" == 200 ]] && echo true || echo false)" "move=$mi get=$gm"
prop=$(http_code PROPFIND "$INGRESS_BASE" "$DAV_DIR/" ingress)
record 'ingress PROPFIND folder' "$([[ "$prop" == 207 ]] && grep -q direct.txt "$TMP/body" && grep -q ingress-moved.txt "$TMP/body" && echo true || echo false)" "code=$prop"

# OCS share create direct, list/delete ingress.
share_xml=$(curl -sS "${AUTH[@]}" -X POST "$DIRECT_BASE/ocs/v2.php/apps/files_sharing/api/v1/shares" \
  -d "path=${TEST_DIR}/direct.txt" -d shareType=3 -d permissions=1)
share_id=$(printf '%s' "$share_xml" | python3 -c 'import re,sys; s=sys.stdin.read(); m=re.search(r"<id>([^<]+)</id>",s); print(m.group(1) if m else "")')
record 'OCS create share direct' "$([[ -n "$share_id" ]] && echo true || echo false)" "id=${share_id:-none}"
ls_code=$(http_code GET "$INGRESS_BASE" "/ocs/v2.php/apps/files_sharing/api/v1/shares?format=json" ingress)
record 'OCS list share ingress' "$([[ "$ls_code" == 200 && -n "$share_id" ]] && grep -q "$share_id" "$TMP/body" && echo true || echo false)" "code=$ls_code id=$share_id"
if [[ -n "$share_id" ]]; then
  del_share=$(http_code DELETE "$INGRESS_BASE" "/ocs/v2.php/apps/files_sharing/api/v1/shares/${share_id}" ingress)
  record 'OCS delete share ingress' "$([[ "$del_share" == 200 ]] && echo true || echo false)" "code=$del_share"
fi

# Login workflow asset and prefix rewrite.
login_html=$(curl -sS --max-time 30 "${INGRESS_HEADER[@]}" "$INGRESS_BASE/login")
root_leaks=$(printf '%s' "$login_html" | python3 -c "import re,sys; h=sys.stdin.read(); urls=re.findall(r'(?:href|src|action)=\"([^\"]+)', h); print(len([u for u in urls if u.startswith('/') and not u.startswith('${INGRESS_PATH}/')]))")
webroot=$(printf '%s' "$login_html" | grep -o 'var _oc_webroot="[^"]*' | head -1 || true)
record 'ingress login root URL leaks' "$([[ "$root_leaks" == 0 ]] && echo true || echo false)" "root_leaks=$root_leaks $webroot"
redir=$(curl -sS -i --max-time 15 "${INGRESS_HEADER[@]}" "$INGRESS_BASE/" | awk 'BEGIN{IGNORECASE=1}/^location:/{print $0}' | tr -d '\r')
record 'ingress root redirect stays prefixed' "$([[ "$redir" == *"${INGRESS_PATH}/login"* ]] && echo true || echo false)" "$redir"

# Cleanup.
http_code DELETE "$DIRECT_BASE" "$DAV_DIR" direct >/dev/null || true
printf '\nSUMMARY pass=%s fail=%s\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
