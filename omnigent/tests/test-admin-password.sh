#!/bin/sh
# Offline check of the admin password gate in init-addon-config/run.
#
# The real script reads fixed paths (/data/options.json, /run/s6/...), so this runs a copy whose three
# paths point into a temp directory and which stops right after the admin block. Cases:
#   - empty admin_password, no database yet -> exit 1 with a FATAL message, nothing exported
#   - empty admin_password, database present -> exit 0 with a WARNING (the account already exists)
#   - a strong password        -> exit 0, exported as-is, no warning
#   - the retired default      -> exit 0 (an existing install keeps running) with a WARNING
# plus: init-admin-claim stops whenever the server reports no admin,
# config.yaml carries no default, and no shipped file contains the retired default.
#
# Red proofs: the same harness is also run against two earlier versions of the script (reconstructed from
# the current one): release 0.1.15, which falls back to the retired default, must NOT stop on an empty
# password; release 0.1.16, which stops on any empty password, must stop on an existing install.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SCRIPT="$ROOT/rootfs/etc/s6-overlay/s6-rc.d/init-addon-config/run"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fail=0

# The retired default, assembled so that this file is not a plain-text copy of it.
RETIRED="woowtech""2026"

# Copy of the script that works on $TMP and ends before the "Base URL" section.
cut_script() { # out_file
    sed -e "s#^OPTIONS_FILE=.*#OPTIONS_FILE=$TMP/options.json#" \
        -e "s#^CONFIG_ENV=.*#CONFIG_ENV=$TMP/omnigent.env#" \
        -e "s#^S6_ENV_DIR=.*#S6_ENV_DIR=$TMP/s6env#" \
        -e "s#^PG_VERSION_FILE=.*#PG_VERSION_FILE=$TMP/PG_VERSION#" \
        "$SCRIPT" | sed '/^# --- Base URL/,$d' > "$1"
    for want in "OPTIONS_FILE=$TMP/options.json" "CONFIG_ENV=$TMP/omnigent.env" "S6_ENV_DIR=$TMP/s6env" "PG_VERSION_FILE=$TMP/PG_VERSION"; do
        grep -qF "$want" "$1" || { echo "FAIL harness: init-addon-config/run no longer has the line for $want; update this test"; exit 1; }
    done
    grep -q 'set_env OMNIGENT_ADMIN_PASSWORD' "$1" || { echo "FAIL harness: the admin block is not in the copied part; update this test"; exit 1; }
}

# run LABEL SCRIPT_COPY OPTIONS_JSON EXPECTED_EXIT [MUST_CONTAIN] [MUST_NOT_CONTAIN]
run() {
    label=$1; copy=$2; options=$3; want=$4; must=${5:-}; mustnot=${6:-}
    rm -rf "$TMP/s6env" "$TMP/omnigent.env" "$TMP/PG_VERSION"; printf '%s' "$options" > "$TMP/options.json"
    if [ "${DB:-no}" = yes ]; then : > "$TMP/PG_VERSION"; fi
    rc=0; sh "$copy" > "$TMP/out.log" 2>&1 || rc=$?
    : > "$TMP/observed.env"
    for setting in "$TMP/s6env"/*; do
        [ -f "$setting" ] || continue
        printf '%s=%s\n' "${setting##*/}" "$(cat "$setting")" >> "$TMP/observed.env"
    done
    ok=yes
    [ "$rc" = "$want" ] || ok=no
    if [ -n "$must" ]    && ! grep -qF -- "$must"    "$TMP/out.log" "$TMP/observed.env" 2>/dev/null; then ok=no; fi
    if [ -n "$mustnot" ] &&   grep -qF -- "$mustnot" "$TMP/out.log" 2>/dev/null; then ok=no; fi
    if [ "$ok" = yes ]; then
        echo "PASS $label"
    else
        echo "FAIL $label: exit $rc (want $want); must contain '$must'; must not contain '$mustnot'"
        sed 's/^/    | /' "$TMP/out.log"
        fail=1
    fi
}

cut_script "$TMP/current.sh"

echo "== init-addon-config/run, new install (no database yet) =="
run 'empty password stops the add-on'        "$TMP/current.sh" '{"admin_username":"woow","admin_password":""}'   1 'FATAL: admin_password is empty'
run 'missing password key stops the add-on'  "$TMP/current.sh" '{"admin_username":"woow"}'                         1 'FATAL: admin_password is empty'
run 'null password stops the add-on'         "$TMP/current.sh" '{"admin_username":"woow","admin_password":null}'  1 'FATAL: admin_password is empty'

echo "== init-addon-config/run, existing install (database present) =="
DB=yes run 'empty password keeps running, with a warning'   "$TMP/current.sh" '{"admin_username":"woow","admin_password":""}'  0 'WARNING: admin_password is empty' 'FATAL'
DB=yes run 'missing password key keeps running'             "$TMP/current.sh" '{"admin_username":"woow"}'                        0 'WARNING: admin_password is empty' 'FATAL'
DB=yes run 'null password keeps running'                    "$TMP/current.sh" '{"admin_username":"woow","admin_password":null}' 0 'WARNING: admin_password is empty' 'FATAL'
DB=yes run 'the username is still exported'                 "$TMP/current.sh" '{"admin_username":"ops","admin_password":""}'     0 'OMNIGENT_ADMIN_USERNAME=ops'

echo "== init-addon-config/run, either way =="
run 'a strong password is accepted as-is'    "$TMP/current.sh" '{"admin_username":"ops","admin_password":"correct-horse-battery-staple-42"}' 0 'OMNIGENT_ADMIN_PASSWORD=correct-horse-battery-staple-42' 'WARNING'
DB=yes run 'a strong password on an existing install gets no warning' "$TMP/current.sh" '{"admin_username":"ops","admin_password":"correct-horse-battery-staple-42"}' 0 'OMNIGENT_ADMIN_PASSWORD=correct-horse-battery-staple-42' 'WARNING'
run 'the username still defaults to woow'    "$TMP/current.sh" '{"admin_password":"another-long-password-1"}'     0 'OMNIGENT_ADMIN_USERNAME=woow' 'FATAL'
run 'the retired default still starts, with a warning' "$TMP/current.sh" "{\"admin_username\":\"woow\",\"admin_password\":\"$RETIRED\"}" 0 'WARNING: admin_password is the default'
run 'a look-alike of the retired default is not flagged' "$TMP/current.sh" "{\"admin_username\":\"woow\",\"admin_password\":\"${RETIRED}x\"}" 0 'OMNIGENT_ADMIN_PASSWORD=' 'WARNING'

echo '== shell-safe configuration values =='
run 'INIT_ADMIN username and password are exported' "$TMP/current.sh" '{"admin_username":"ops","admin_password":"long-password-42"}' 0 'OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD=long-password-42'
DB=yes run 'empty password does not set INIT_ADMIN_PASSWORD' "$TMP/current.sh" '{"admin_username":"ops","admin_password":""}' 0 'OMNIGENT_ACCOUNTS_INIT_ADMIN_USERNAME=ops'
if [ ! -e "$TMP/s6env/OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD" ]; then echo 'PASS empty existing install has no INIT_ADMIN_PASSWORD'; else echo 'FAIL empty existing install sets INIT_ADMIN_PASSWORD'; fail=1; fi
marker="$TMP/password-ran"
malicious="long-\$(touch $marker)-password"
run 'shell metacharacters in a password are stored as data' "$TMP/current.sh" "$(printf '%s' "$malicious" | jq -Rs '{admin_username:"ops",admin_password:.}')" 0 'OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD='
( . "$TMP/omnigent.env"; [ "$OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD" = "$malicious" ] ) \
    && [ ! -e "$marker" ] \
    && echo 'PASS sourced password is literal data' \
    || { echo 'FAIL sourced password was changed or executed'; fail=1; }
if ( . "$TMP/omnigent.env"; EXPECTED_PASSWORD="$malicious" sh -c 'test "$OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD" = "$EXPECTED_PASSWORD"' ) \
    2>/dev/null; then
    echo 'PASS bootstrap password reaches the server subprocess'
else
    echo 'FAIL bootstrap password was not exported to the server subprocess'; fail=1
fi
if [ "$(stat -c %a "$TMP/omnigent.env")" = 600 ]; then
    echo 'PASS shell-sourced environment file is private'
else
    echo 'FAIL shell-sourced environment file is not mode 0600'; fail=1
fi

echo "== release 0.1.16 (red proof: stops on any empty password) =="
sed -e 's#if \[ -f "\${PG_VERSION_FILE}" \]; then#if false; then#' "$TMP/current.sh" > "$TMP/r0116.sh"
grep -qF 'if false; then' "$TMP/r0116.sh" || { echo "FAIL harness: could not rebuild the 0.1.16 script"; exit 1; }
DB=yes run '0.1.16 stops an existing install that has no password option' "$TMP/r0116.sh" '{"admin_username":"woow","admin_password":""}' 1 'FATAL: admin_password is empty'

echo "== release 0.1.15 (red proof: silently falls back to the retired default) =="
sed -e '/^if \[ -z "\${ADMIN_PASSWORD}" \]; then$/,/^fi$/d' \
    -e "s#^ADMIN_PASSWORD=\"\$(optget admin_password '')\"#ADMIN_PASSWORD=\"\$(optget admin_password '$RETIRED')\"#" \
    "$TMP/current.sh" > "$TMP/legacy.sh"
grep -qF "optget admin_password '$RETIRED'" "$TMP/legacy.sh" || { echo "FAIL harness: could not rebuild the 0.1.15 script"; exit 1; }
run '0.1.15 silently falls back to the retired default on an empty password' "$TMP/legacy.sh" '{"admin_username":"woow","admin_password":""}' 0 "OMNIGENT_ADMIN_PASSWORD=$RETIRED"

echo "== init-admin-claim/run =="
CLAIM="$ROOT/rootfs/etc/s6-overlay/s6-rc.d/init-admin-claim/run"
mkdir -p "$TMP/bin"
# A stand-in for curl: /health answers, /v1/info reports $NEEDS_SETUP; any
# /auth/setup call is recorded so the test can prove it never happens.
cat > "$TMP/bin/curl" <<'STUB'
#!/bin/sh
for last; do :; done
case "$last" in
    */health)     exit 0 ;;
    */v1/info)    printf '{"needs_setup": %s}' "$NEEDS_SETUP"; exit 0 ;;
    */auth/setup) : > "$SETUP_CALLED"; printf '201'; exit 0 ;;
esac
exit 22
STUB
chmod +x "$TMP/bin/curl"
cp "$CLAIM" "$TMP/claim.sh"
# claim LABEL NEEDS_SETUP PASSWORD EXPECTED_EXIT SETUP_CALLED(yes|no) [MUST_CONTAIN]
claim() {
    label=$1; needs=$2; pw=$3; want=$4; called=$5; must=${6:-}
    rm -f "$TMP/setup-called"
    rc=0; env PATH="$TMP/bin:$PATH" NEEDS_SETUP="$needs" SETUP_CALLED="$TMP/setup-called" \
        OMNIGENT_ADMIN_USERNAME=woow OMNIGENT_ADMIN_PASSWORD="$pw" sh "$TMP/claim.sh" > "$TMP/out.log" 2>&1 || rc=$?
    got=no; [ -e "$TMP/setup-called" ] && got=yes
    ok=yes
    [ "$rc" = "$want" ] || ok=no
    [ "$got" = "$called" ] || ok=no
    if [ -n "$must" ] && ! grep -qF -- "$must" "$TMP/out.log"; then ok=no; fi
    if [ "$ok" = yes ]; then
        echo "PASS $label"
    else
        echo "FAIL $label: exit $rc (want $want), setup called: $got (want $called); must contain '$must'"
        sed 's/^/    | /' "$TMP/out.log"
        fail=1
    fi
}
claim 'no admin and no password: fail closed without setup call' true  ''                 1 no 'server still needs setup'
claim 'no admin despite password: fail closed without setup call' true 'a-long-password-1' 1 no 'server still needs setup'
claim 'admin exists with no password option: accept'             false ''                 0 no 'admin exists'
claim 'admin exists with a password option: accept'             false 'a-long-password-1' 0 no 'admin exists'

echo '== existing database preflight, before the server binds =='
sed "s#/var/run/omnigent.env#$TMP/preflight.env#g" "$ROOT/rootfs/etc/s6-overlay/s6-rc.d/init-omnigent-config/run" > "$TMP/preflight.sh"
cat > "$TMP/bin/pg_isready" <<'STUB'
#!/bin/sh
exit 0
STUB
cat > "$TMP/bin/psql" <<'STUB'
#!/bin/sh
cat >/dev/null
[ "${PSQL_FAIL:-0}" = 0 ] || exit 1
printf '%s\n' "${PSQL_COUNT:-0}"
STUB
chmod +x "$TMP/bin/pg_isready" "$TMP/bin/psql"
preflight() {
    label=$1; password=$2; count=$3; expect=$4; marker=$5
    printf "OMNIGENT_ADMIN_PASSWORD='%s'\nOMNIGENT_ADMIN_USERNAME='woow'\nPOSTGRES_PASSWORD='internal'\n" "$password" > "$TMP/preflight.env"
    rc=0
    env PATH="$TMP/bin:$PATH" PSQL_COUNT="$count" sh "$TMP/preflight.sh" > "$TMP/out.log" 2>&1 || rc=$?
    if [ "$rc" = "$expect" ] && grep -qF "$marker" "$TMP/out.log"; then
        echo "PASS $label"
    else
        echo "FAIL $label: exit $rc (want $expect)"; sed -n '1,6p' "$TMP/out.log"; fail=1
    fi
}
preflight 'existing admin permits an empty option' '' 1 0 'postgres ready'
preflight 'missing admin blocks server startup' '' 0 1 'FATAL: no existing admin'
preflight 'configured password lets server bootstrap' 'strong-password' 0 0 'postgres ready'

echo "== shipped files =="
# config.yaml: the options block must not carry a password default
default_line=$(awk '/^options:/{f=1; next} /^[^ #]/{f=0} f && /^[ ]+admin_password:/' "$ROOT/config.yaml")
if [ "$default_line" = '  admin_password: ""' ]; then
    echo "PASS config.yaml options.admin_password is empty"
else
    echo "FAIL config.yaml options.admin_password is '$default_line' (want an empty string)"; fail=1
fi
if grep -q 'pg_wal' "$ROOT/config.yaml"; then
    echo 'FAIL backup excludes PostgreSQL WAL'; fail=1
else
    echo 'PASS cold backup includes PostgreSQL WAL'
fi
# the retired default must not be readable in anything the add-on ships (this test itself builds it from two halves)
leaks=$(grep -rIl -F --exclude-dir=tests -e "$RETIRED" "$ROOT" || true)
if [ -z "$leaks" ]; then
    echo "PASS no shipped file contains the retired default"
else
    echo "FAIL the retired default is still in: $leaks"; fail=1
fi

if [ "$fail" != 0 ]; then echo "FAILED"; exit 1; fi
echo "ALL PASSED"
