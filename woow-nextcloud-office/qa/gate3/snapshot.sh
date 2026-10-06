set -u
read -r ADMIN_PASS; read -r USER_PASS; read -r USER2_PASS
H='Host: localhost'; B=http://127.0.0.1:8000
echo "version $(occ status --output=json | php -r '$s=json_decode(stream_get_contents(STDIN),true); echo $s["versionstring"]," installed=",var_export($s["installed"],true)," maint=",var_export($s["maintenance"],true)," needsDbUpgrade=",var_export($s["needsDbUpgrade"],true);')"
echo "users $(occ user:list --output=json | php -r 'echo implode(",",array_keys(json_decode(stream_get_contents(STDIN),true)));')"
for c in "ha-cand-admin:$ADMIN_PASS:ha-cand-admin" "ha-cand-user:$USER_PASS:ha-cand-user" "ha-cand-user2:$USER2_PASS:ha-cand-user2"; do IFS=: read -r u p d <<<"$c"; echo "login $u $(curl -s -o /dev/null -w '%{http_code}' -u "$u:$p" -H "$H" -X PROPFIND -H 'Depth: 0' "$B/remote.php/dav/files/$d/")"; done
echo "marker $(curl -s -u "ha-cand-user:$USER_PASS" -H "$H" "$B/remote.php/dav/files/ha-cand-user/gate2/marker.txt" | sha256sum | cut -c1-16)"
echo "versioned $(curl -s -u "ha-cand-user:$USER_PASS" -H "$H" "$B/remote.php/dav/files/ha-cand-user/gate2/versioned.txt" | tr -d '\n')"
echo "versions $(curl -s -u "ha-cand-user:$USER_PASS" -H "$H" -X PROPFIND -H 'Depth: 1' "$B/remote.php/dav/versions/ha-cand-user/versions/$(occ files:scan --help >/dev/null; curl -s -u "ha-cand-user:$USER_PASS" -H "$H" -X PROPFIND -H 'Depth: 0' --data '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop><oc:fileid/></d:prop></d:propfind>' "$B/remote.php/dav/files/ha-cand-user/gate2/versioned.txt" | grep -o '<oc:fileid>[0-9]*' | cut -d'>' -f2)" | grep -o '<d:response>' | wc -l)"
echo "share-user2 $(curl -s -u "ha-cand-user2:$USER2_PASS" -H "$H" -X PROPFIND -H 'Depth: 1' "$B/remote.php/dav/files/ha-cand-user2/gate2/" | grep -o 'marker.txt' | head -1)"
echo "after35 $(curl -s -o /dev/null -w '%{http_code}' -u "ha-cand-user:$USER_PASS" -H "$H" "$B/remote.php/dav/files/ha-cand-user/gate2/after-35.txt")"
echo "appconfig $(occ config:app:get woow_gate3 marker)"
echo "richdocuments $(occ app:list --output=json | php -r '$a=json_decode(stream_get_contents(STDIN),true); echo $a["enabled"]["richdocuments"]??("disabled:".($a["disabled"]["richdocuments"]??"absent"));')"
echo "code $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9980/hosting/discovery)"
echo "perms $(stat -c '%a:%U' /data/postgres /data/nextcloud/config/config.php /share/nextcloud | tr '\n' ' ')"
echo "pg $(gosu postgres psql -h /run/postgresql -Atc 'show server_version')"
echo "php $(php -r 'echo PHP_VERSION;')"
