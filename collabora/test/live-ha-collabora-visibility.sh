#!/usr/bin/env bash
# Live TDD check for Home Assistant visibility of Woow Collabora.
# Run on the HA host / SSH add-on shell. It intentionally checks the UI-facing
# contracts that caused the regression: installed app list + sidebar ingress.
set -euo pipefail

SLUG="${COLLABORA_SLUG:-1b7b4ce7_woow-collabora}"
ADMIN_SLUG="${COLLABORA_ADMIN_SLUG:-1b7b4ce7_woow-collabora-admin}"
DIRECT_BASE="${COLLABORA_DIRECT_BASE:-http://homeassistant:9981}"
NEXTCLOUD_BASE="${NEXTCLOUD_DIRECT_BASE:-http://homeassistant:8000}"
PUBLIC_HOST="${EXPECTED_HA_PUBLIC_HOST:-}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

need() { command -v "$1" >/dev/null || { echo "missing command: $1" >&2; exit 2; }; }
need ha
need python3
need curl

ha addons --raw-json 2>/dev/null > "$TMP/addons.json"
ha store --raw-json 2>/dev/null > "$TMP/store.json"
ha addons info "$SLUG" --raw-json 2>/dev/null > "$TMP/info.json"
ha addons info "$ADMIN_SLUG" --raw-json 2>/dev/null > "$TMP/admin-info.json"

python3 - "$TMP/addons.json" "$TMP/store.json" "$TMP/info.json" "$TMP/admin-info.json" "$SLUG" "$ADMIN_SLUG" <<'PY'
import json, sys
addons_path, store_path, info_path, admin_info_path, slug, admin_slug = sys.argv[1:]
addons = json.load(open(addons_path))["data"]["addons"]
store = json.load(open(store_path))["data"]["addons"]
info = json.load(open(info_path))["data"]
admin_info = json.load(open(admin_info_path))["data"]
installed = next((a for a in addons if a.get("slug") == slug), None)
admin_installed = next((a for a in addons if a.get("slug") == admin_slug), None)
store_row = next((a for a in store if a.get("slug") == slug), None)
admin_store_row = next((a for a in store if a.get("slug") == admin_slug), None)
assert installed, f"{slug} missing from installed applications list"
assert admin_installed, f"{admin_slug} missing from installed applications list"
assert store_row, f"{slug} missing from store list"
assert admin_store_row, f"{admin_slug} missing from store list"
assert installed["name"] == "Woow Collabora CODE"
assert admin_installed["name"] == "Woow Collabora Admin"
assert installed["stage"] == "stable", installed
assert admin_installed["stage"] == "stable", admin_installed
assert store_row["stage"] == "stable", store_row
assert admin_store_row["stage"] == "stable", admin_store_row
assert store_row["installed"] is True, store_row
assert admin_store_row["installed"] is True, admin_store_row
assert info["state"] == "started", info
assert admin_info["state"] == "started", admin_info
assert info["ingress"] is True, info
assert info["ingress_panel"] is False, "Raw engine panel must be disabled; it has iframe/CSP issues"
assert admin_info["ingress"] is True, admin_info
assert admin_info["ingress_panel"] is True, admin_info
assert admin_info["ingress_url"].startswith("/api/hassio_ingress/"), admin_info["ingress_url"]
assert admin_info["ingress_url"].endswith("/browser/dist/admin/admin.html"), admin_info["ingress_url"]
assert info["stage"] == "stable", info
assert admin_info["stage"] == "stable", admin_info
print("HA installed/store/ingress metadata passed")
PY

printf 'Checking Collabora direct endpoints...\n'
curl -fsS -o "$TMP/discovery.xml" "$DIRECT_BASE/hosting/discovery"
curl -fsS -o "$TMP/capabilities.json" "$DIRECT_BASE/hosting/capabilities"
admin_code="$(curl -sS -o /dev/null -w '%{http_code}' "$DIRECT_BASE/browser/dist/admin/admin.html")"
[ "$admin_code" = "401" ] || { echo "expected admin unauth 401, got $admin_code" >&2; exit 1; }

grep -q '<wopi-discovery>' "$TMP/discovery.xml"
grep -q 'convert-to' "$TMP/capabilities.json"

printf 'Checking Collabora admin ingress proxy rendering contract...\n'
ADMIN_IP="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' app_${ADMIN_SLUG})"
curl -fsS -H 'X-Ingress-Path: /api/hassio_ingress/testtoken' -o "$TMP/admin.html" "http://${ADMIN_IP}:8098/browser/dist/admin/admin.html"
grep -q 'Collabora Online Development Edition' "$TMP/admin.html" || grep -q 'Admin console' "$TMP/admin.html"
if grep -q '"/browser/' "$TMP/admin.html"; then
  echo 'admin proxy did not rewrite absolute /browser assets' >&2
  exit 1
fi
grep -q '/api/hassio_ingress/testtoken/browser/' "$TMP/admin.html"

printf 'Checking Nextcloud pairing target...\n'
curl -fsS -o /dev/null "$NEXTCLOUD_BASE/status.php"

if [ -n "$PUBLIC_HOST" ]; then
  printf 'Checking expected public HA hostname %s...\n' "$PUBLIC_HOST"
  if ! getent hosts "$PUBLIC_HOST" >/dev/null; then
    echo "public hostname $PUBLIC_HOST does not resolve from this HA host" >&2
    exit 1
  fi
fi

printf 'Woow Collabora live visibility checks passed for %s\n' "$SLUG"
