#!/bin/bash
# Smoke test of a BUILT add-on image (CI): versions inside the image, then a real /init boot
# with synthetic options in a throwaway container. Usage: ci-image-smoke.sh <image> <expected-nextcloud-version>
set -euo pipefail
IMAGE=$1 EXPECT_NC=$2
run() { docker run --rm --network none --entrypoint bash "$IMAGE" -c "$1"; }
echo "== static checks"
run 'php -v | head -1; php-fpm8.4 -v | head -1; /usr/lib/postgresql/16/bin/postgres --version; nginx -v 2>&1; dpkg-query -W -f="coolwsd \${Version}\n" coolwsd'
got=$(run "php -r 'include \"/var/www/nextcloud/version.php\"; echo \$OC_VersionString;'")
[[ "$got" == "$EXPECT_NC" ]] || { echo "Nextcloud in image is $got, expected $EXPECT_NC" >&2; exit 1; }
run 'test ! -e /var/www/nextcloud/apps/richdocuments' || { echo "richdocuments must not be baked into apps/" >&2; exit 1; }
echo "== boot with /init (synthetic data)"
work=$(mktemp -d); trap 'docker rm -f nc-smoke >/dev/null 2>&1 || true; sudo rm -rf "$work" 2>/dev/null || rm -rf "$work"' EXIT
mkdir -p "$work/data" "$work/share"
cat > "$work/data/options.json" <<JSON
{"TZ":"UTC","NEXTCLOUD_PUBLIC_URL":"https://nextcloud.ci.invalid","HA_PUBLIC_URL":"https://ha.ci.invalid","ADMIN_USER":"ci-admin","ADMIN_PASS":"$(openssl rand -hex 16)","NEXTCLOUD_DATADIR":"/share/nextcloud","DEFAULT_PHONE_REGION":"TW","COLLABORA_ADMIN_USER":"ci-code","COLLABORA_ADMIN_PASS":"$(openssl rand -hex 16)","ENABLE_COLLABORA":false,"ENABLE_COLLABORA_ADMIN":false,"trusted_domains":[],"trusted_proxies":[]}
JSON
docker run -d --name nc-smoke --tmpfs /tmp -v "$work/data:/data" -v "$work/share:/share" "$IMAGE" >/dev/null
for i in $(seq 1 120); do
  if docker logs nc-smoke 2>&1 | grep -q -E "legacy-services successfully started|unable to start service"; then break; fi
  sleep 5
done
docker logs nc-smoke 2>&1 | grep -E "^s6-rc: warning|successfully installed|legacy-services" || true
docker logs nc-smoke 2>&1 | grep -q "legacy-services successfully started" || { docker logs nc-smoke 2>&1 | tail -40; echo "boot did not complete" >&2; exit 1; }
status=$(docker exec nc-smoke curl -fsS -H 'Host: localhost' http://127.0.0.1:8000/status.php)
echo "$status"
python3 -c "import json,sys; s=json.loads(sys.argv[1]); assert s['installed'] and not s['maintenance'] and s['versionstring']==sys.argv[2], s" "$status" "$EXPECT_NC"
docker exec nc-smoke test -f /data/nextcloud/config/apps.config.php
modes=$(docker exec nc-smoke stat -c '%a' /data/nextcloud/config /data/nextcloud/config/config.php /share/nextcloud | tr '\n' ' ')
[[ "$modes" == "750 640 770 " ]] || { echo "unexpected modes (config dir, config.php, data dir): $modes" >&2; exit 1; }
echo "smoke OK: $IMAGE runs Nextcloud $EXPECT_NC"
