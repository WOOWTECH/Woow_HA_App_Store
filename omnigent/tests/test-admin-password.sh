#!/bin/sh
# Offline check of the admin password gate in init-addon-config/run.
#
# The real script reads fixed paths (/data/options.json, /run/s6/...), so this runs a copy whose
# paths point into a temp directory and which stops right after the admin block. A stand-in curl
# plays the Supervisor API (POST /addons/self/options). Cases:
#   - empty admin_password, no database yet -> a random 32-character password is generated, saved to
#     the add-on options (the POST body keeps every other option) and exported; it is never logged and
#     never on a command line; two installs get different passwords
#   - the same, but the Supervisor refuses or there is no token -> exit 1 with a FATAL message, nothing exported
#   - empty admin_password, database present -> exit 0 with a WARNING, nothing generated, no Supervisor call
#   - a strong password        -> exit 0, exported as-is, no warning, no Supervisor call
#   - the retired default      -> exit 0 (an existing install keeps running) with a WARNING
# plus: init-admin-claim stops whenever the server reports no admin,
# config.yaml carries no default, and no shipped file contains the retired default.
#
# Red proofs: the same harness is also run against earlier or broken versions of the script (rebuilt from
# the current one): release 0.1.15, which falls back to the retired default, must NOT stop on an empty
# password; release 0.1.20, which stops on an empty password, must fail the new-install case; a script
# that ignores the database must be caught generating and saving a password on an existing install.
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
        -e "s#^SUPERVISOR_URL=.*#SUPERVISOR_URL=http://supervisor.test#" \
        "$SCRIPT" | sed '/^# --- Base URL/,$d' > "$1"
    for want in "OPTIONS_FILE=$TMP/options.json" "CONFIG_ENV=$TMP/omnigent.env" "S6_ENV_DIR=$TMP/s6env" "PG_VERSION_FILE=$TMP/PG_VERSION" "SUPERVISOR_URL=http://supervisor.test"; do
        grep -qF "$want" "$1" || { echo "FAIL harness: init-addon-config/run no longer has the line for $want; update this test"; exit 1; }
    done
    grep -q 'set_env OMNIGENT_ADMIN_PASSWORD' "$1" || { echo "FAIL harness: the admin block is not in the copied part; update this test"; exit 1; }
}

# A stand-in for curl as the Supervisor: records its arguments and the request body,
# answers with exit $CURL_EXIT (0 = accepted, 22 = HTTP error).
mkdir -p "$TMP/supbin"
cat > "$TMP/supbin/curl" <<'STUB'
#!/bin/sh
printf '%s\n' "$@" > "$CURL_ARGS"
cat > "$CURL_BODY"
exit "${CURL_EXIT:-0}"
STUB
chmod +x "$TMP/supbin/curl"

# run LABEL SCRIPT_COPY OPTIONS_JSON EXPECTED_EXIT [MUST_CONTAIN] [MUST_NOT_CONTAIN]
# Environment knobs: DB=yes (database present); TOKEN (SUPERVISOR_TOKEN, default a test token, '' = none);
# TOKEN_FILE (a token in the s6 environment directory instead); CURL_EXIT (the Supervisor's answer);
# POSTED=yes|no (whether the options must have been saved).
run() {
    label=$1; copy=$2; options=$3; want=$4; must=${5:-}; mustnot=${6:-}
    rm -rf "$TMP/s6env" "$TMP/omnigent.env" "$TMP/PG_VERSION" "$TMP/curl.args" "$TMP/curl.body"
    printf '%s' "$options" > "$TMP/options.json"
    if [ "${DB:-no}" = yes ]; then : > "$TMP/PG_VERSION"; fi
    if [ -n "${TOKEN_FILE:-}" ]; then mkdir -p "$TMP/s6env"; printf '%s' "$TOKEN_FILE" > "$TMP/s6env/SUPERVISOR_TOKEN"; fi
    rc=0; env PATH="$TMP/supbin:$PATH" SUPERVISOR_TOKEN="${TOKEN-test-token}" CURL_EXIT="${CURL_EXIT:-0}" \
        CURL_ARGS="$TMP/curl.args" CURL_BODY="$TMP/curl.body" sh "$copy" > "$TMP/out.log" 2>&1 || rc=$?
    : > "$TMP/observed.env"
    for setting in "$TMP/s6env"/*; do
        [ -f "$setting" ] || continue
        printf '%s=%s\n' "${setting##*/}" "$(cat "$setting")" >> "$TMP/observed.env"
    done
    ok=yes
    [ "$rc" = "$want" ] || ok=no
    if [ -n "$must" ]    && ! grep -qF -- "$must"    "$TMP/out.log" "$TMP/observed.env" 2>/dev/null; then ok=no; fi
    if [ -n "$mustnot" ] &&   grep -qF -- "$mustnot" "$TMP/out.log" 2>/dev/null; then ok=no; fi
    posted=no; [ -e "$TMP/curl.args" ] && posted=yes
    if [ -n "${POSTED:-}" ] && [ "$posted" != "$POSTED" ]; then ok=no; fi
    if [ "$ok" = yes ]; then
        echo "PASS $label"
    else
        echo "FAIL $label: exit $rc (want $want); must contain '$must'; must not contain '$mustnot'; options saved: $posted (want ${POSTED:-either})"
        sed 's/^/    | /' "$TMP/out.log"
        fail=1
    fi
}

cut_script "$TMP/current.sh"

# check LABEL COMMAND... : one PASS/FAIL line for a plain shell condition
check() { label=$1; shift; if "$@"; then echo "PASS $label"; else echo "FAIL $label"; fail=1; fi; }
exported() { cat "$TMP/s6env/$1" 2>/dev/null || true; }

FULL='{"admin_username":"ops","admin_password":"","base_url":"https://omni.example","features":"usage_page","env_vars":[{"key":"A_B","value":"x y"}]}'
SAVE_FATAL='FATAL: admin_password is empty, and a generated password could not be saved'

echo "== init-addon-config/run, new install (no database yet): generate and save =="
POSTED=yes run 'empty password: generated and saved to the options' "$TMP/current.sh" "$FULL" 0 'generated a random password' 'FATAL'
pw=$(exported OMNIGENT_ADMIN_PASSWORD)
check 'the generated password is 32 letters and digits' sh -c 'printf "%s" "$1" | grep -qxE "[A-Za-z0-9]{32}"' _ "$pw"
check 'the server bootstrap gets the same password' test "$(exported OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD)" = "$pw"
check 'the shell-sourced env file carries it too' sh -c '. "$1"; test "$OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD" = "$2"' _ "$TMP/omnigent.env" "$pw"
check 'POSTed to /addons/self/options with the token' sh -c 'grep -qx POST "$1" && grep -qx "http://supervisor.test/addons/self/options" "$1" && grep -qx "Authorization: Bearer test-token" "$1"' _ "$TMP/curl.args"
check 'the saved options carry the generated password' test "$(jq -r '.options.admin_password' "$TMP/curl.body")" = "$pw"
check 'the saved options keep every other option unchanged' test "$(jq -cS '.options | del(.admin_password)' "$TMP/curl.body")" = "$(printf '%s' "$FULL" | jq -cS 'del(.admin_password)')"
check 'the password is not on the curl command line' sh -c '! grep -qF -- "$1" "$2"' _ "$pw" "$TMP/curl.args"
check 'the password is not in the log' sh -c '! grep -qF -- "$1" "$2"' _ "$pw" "$TMP/out.log"
POSTED=yes run 'a second new install'                 "$TMP/current.sh" "$FULL" 0 'generated a random password'
check 'two installs get different passwords' test "$(exported OMNIGENT_ADMIN_PASSWORD)" != "$pw"
POSTED=yes run 'missing password key: generated'      "$TMP/current.sh" '{"admin_username":"woow"}'                        0 'generated a random password'
check 'missing key: the saved password is the exported one' test "$(jq -r '.options.admin_password' "$TMP/curl.body")" = "$(exported OMNIGENT_ADMIN_PASSWORD)"
POSTED=yes run 'null password: generated'             "$TMP/current.sh" '{"admin_username":"woow","admin_password":null}' 0 'generated a random password'
check 'null: the saved password is the exported one' test "$(jq -r '.options.admin_password' "$TMP/curl.body")" = "$(exported OMNIGENT_ADMIN_PASSWORD)"
TOKEN='' TOKEN_FILE=file-token POSTED=yes run 'a token only in the s6 environment directory is used' "$TMP/current.sh" "$FULL" 0 'generated a random password'
check 'the s6 directory token is sent' grep -qx 'Authorization: Bearer file-token' "$TMP/curl.args"

echo "== init-addon-config/run, new install: cannot save, so stop before anything is created =="
CURL_EXIT=22 POSTED=yes run 'the Supervisor refuses: stop' "$TMP/current.sh" "$FULL" 1 "$SAVE_FATAL"
check 'refused: nothing is exported to later services' test ! -e "$TMP/s6env/OMNIGENT_ADMIN_PASSWORD" -a ! -e "$TMP/s6env/OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD"
check 'refused: the password is not in the log' sh -c '! grep -qF -- "$(jq -r .options.admin_password "$1")" "$2"' _ "$TMP/curl.body" "$TMP/out.log"
TOKEN='' POSTED=no run 'no Supervisor token: stop without a call' "$TMP/current.sh" "$FULL" 1 "$SAVE_FATAL"
check 'no token: nothing is exported to later services' test ! -e "$TMP/s6env/OMNIGENT_ADMIN_PASSWORD"

echo "== init-addon-config/run, existing install (database present): never generate =="
DB=yes POSTED=no run 'empty password keeps running, with a warning'   "$TMP/current.sh" '{"admin_username":"woow","admin_password":""}'  0 'WARNING: admin_password is empty' 'FATAL'
DB=yes POSTED=no run 'missing password key keeps running'             "$TMP/current.sh" '{"admin_username":"woow"}'                        0 'WARNING: admin_password is empty' 'generated'
DB=yes POSTED=no run 'null password keeps running'                    "$TMP/current.sh" '{"admin_username":"woow","admin_password":null}' 0 'WARNING: admin_password is empty' 'generated'
DB=yes POSTED=no run 'the username is still exported'                 "$TMP/current.sh" '{"admin_username":"ops","admin_password":""}'     0 'OMNIGENT_ADMIN_USERNAME=ops'
check 'existing install: the password stays empty, no bootstrap password' test -z "$(exported OMNIGENT_ADMIN_PASSWORD)" -a ! -e "$TMP/s6env/OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD"

echo "== init-addon-config/run, either way =="
POSTED=no run 'a strong password is accepted as-is'    "$TMP/current.sh" '{"admin_username":"ops","admin_password":"correct-horse-battery-staple-42"}' 0 'OMNIGENT_ADMIN_PASSWORD=correct-horse-battery-staple-42' 'WARNING'
DB=yes POSTED=no run 'a strong password on an existing install gets no warning' "$TMP/current.sh" '{"admin_username":"ops","admin_password":"correct-horse-battery-staple-42"}' 0 'OMNIGENT_ADMIN_PASSWORD=correct-horse-battery-staple-42' 'WARNING'
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

echo "== release 0.1.20 (red proof: a new install with an empty password stopped) =="
awk '/^        # 32 characters from/ { print "        log \"FATAL: admin_password is empty. Set a strong password on the add-on Configuration tab, then start the add-on again.\""; print "        exit 1"; skip = 1 }
     skip && /^    fi$/ { skip = 0 }
     !skip' "$TMP/current.sh" > "$TMP/r0120.sh"
{ grep -qF 'FATAL: admin_password is empty. Set a strong' "$TMP/r0120.sh" && ! grep -qF 'head -c 48' "$TMP/r0120.sh"; } \
    || { echo "FAIL harness: could not rebuild the 0.1.20 script"; exit 1; }
POSTED=no run '0.1.20 stops a new install with an empty password' "$TMP/r0120.sh" '{"admin_username":"woow","admin_password":""}' 1 'FATAL: admin_password is empty. Set a strong'

echo "== a script that ignores the database (red proof for the existing-install cases) =="
sed -e 's#if \[ -f "\${PG_VERSION_FILE}" \]; then#if false; then#' "$TMP/current.sh" > "$TMP/nodb.sh"
grep -qF 'if false; then' "$TMP/nodb.sh" || { echo "FAIL harness: could not rebuild the database-blind script"; exit 1; }
DB=yes POSTED=yes run 'a database-blind script would generate and save a password on an existing install' "$TMP/nodb.sh" '{"admin_username":"woow","admin_password":""}' 0 'generated a random password'

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
