#!/bin/sh
# Offline check of the admin password gate in init-addon-config/run.
#
# The real script reads fixed paths (/data/options.json, /run/s6/...), so this runs a copy whose three
# paths point into a temp directory and which stops right after the admin block. Cases:
#   - no/empty admin_password  -> exit 1 with a FATAL message, nothing exported
#   - a strong password        -> exit 0, exported as-is, no warning
#   - the retired default      -> exit 0 (an existing install keeps running) with a WARNING
# plus: config.yaml no longer carries a default, and no shipped file contains the retired default.
#
# Red proof: the same harness is also run against the script as it was before this fix
# (reconstructed from the current one), which must NOT stop on an empty password.
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
        "$SCRIPT" | sed '/^# --- Base URL/,$d' > "$1"
    for want in "OPTIONS_FILE=$TMP/options.json" "CONFIG_ENV=$TMP/omnigent.env" "S6_ENV_DIR=$TMP/s6env"; do
        grep -qF "$want" "$1" || { echo "FAIL harness: init-addon-config/run no longer has the line for $want; update this test"; exit 1; }
    done
    grep -q 'set_env OMNIGENT_ADMIN_PASSWORD' "$1" || { echo "FAIL harness: the admin block is not in the copied part; update this test"; exit 1; }
}

# run LABEL SCRIPT_COPY OPTIONS_JSON EXPECTED_EXIT [MUST_CONTAIN] [MUST_NOT_CONTAIN]
run() {
    label=$1; copy=$2; options=$3; want=$4; must=${5:-}; mustnot=${6:-}
    rm -rf "$TMP/s6env" "$TMP/omnigent.env"; printf '%s' "$options" > "$TMP/options.json"
    rc=0; sh "$copy" > "$TMP/out.log" 2>&1 || rc=$?
    ok=yes
    [ "$rc" = "$want" ] || ok=no
    if [ -n "$must" ]    && ! grep -qF -- "$must"    "$TMP/out.log" "$TMP/omnigent.env" 2>/dev/null; then ok=no; fi
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

echo "== the script as it is now =="
run 'empty password stops the add-on'        "$TMP/current.sh" '{"admin_username":"woow","admin_password":""}'   1 'FATAL: admin_password is empty'
run 'missing password key stops the add-on'  "$TMP/current.sh" '{"admin_username":"woow"}'                         1 'FATAL: admin_password is empty'
run 'null password stops the add-on'         "$TMP/current.sh" '{"admin_username":"woow","admin_password":null}'  1 'FATAL: admin_password is empty'
run 'a strong password is accepted as-is'    "$TMP/current.sh" '{"admin_username":"ops","admin_password":"correct-horse-battery-staple-42"}' 0 'OMNIGENT_ADMIN_PASSWORD=correct-horse-battery-staple-42' 'WARNING'
run 'the username still defaults to woow'    "$TMP/current.sh" '{"admin_password":"another-long-password-1"}'     0 'OMNIGENT_ADMIN_USERNAME=woow' 'FATAL'
run 'the retired default still starts, with a warning' "$TMP/current.sh" "{\"admin_username\":\"woow\",\"admin_password\":\"$RETIRED\"}" 0 'WARNING: admin_password is the default' 'FATAL'
run 'a look-alike of the retired default is not flagged' "$TMP/current.sh" "{\"admin_username\":\"woow\",\"admin_password\":\"${RETIRED}x\"}" 0 'OMNIGENT_ADMIN_PASSWORD=' 'WARNING'

echo "== the script as it was before this fix (red proof) =="
sed -e '/^if \[ -z "\${ADMIN_PASSWORD}" \]; then$/,/^fi$/d' \
    -e "s#^ADMIN_PASSWORD=\"\$(optget admin_password '')\"#ADMIN_PASSWORD=\"\$(optget admin_password '$RETIRED')\"#" \
    "$TMP/current.sh" > "$TMP/legacy.sh"
grep -qF "optget admin_password '$RETIRED'" "$TMP/legacy.sh" || { echo "FAIL harness: could not rebuild the pre-fix script"; exit 1; }
run 'pre-fix script silently falls back to the retired default on an empty password' "$TMP/legacy.sh" '{"admin_username":"woow","admin_password":""}' 0 "OMNIGENT_ADMIN_PASSWORD=$RETIRED" 'FATAL'

echo "== shipped files =="
# config.yaml: the options block must not carry a password default
default_line=$(awk '/^options:/{f=1; next} /^[^ #]/{f=0} f && /^[ ]+admin_password:/' "$ROOT/config.yaml")
if [ "$default_line" = '  admin_password: ""' ]; then
    echo "PASS config.yaml options.admin_password is empty"
else
    echo "FAIL config.yaml options.admin_password is '$default_line' (want an empty string)"; fail=1
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
