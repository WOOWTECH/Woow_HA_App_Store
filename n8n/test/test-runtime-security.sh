#!/usr/bin/env bash
# Exercise the add-on's secret handling in its real s6 scripts:
#   - option logging masks secrets and writes nothing outside the s6 env dir
#   - the task broker token is generated per installation, root-only, stable
#   - n8n and the runner launcher start without the Supervisor token
#   - the startup guard keeps the watchdog marker until n8n is ready
#   - Redis is loopback-only with protected mode and a private socket
set -euo pipefail

ADDON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
S6="${ADDON_DIR}/rootfs/etc/s6-overlay/s6-rc.d"
GUARD="${ADDON_DIR}/rootfs/usr/local/bin/woow-n8n-startup-guard"
REDIS_RUN="${ADDON_DIR}/.common/redis/etc/s6-overlay/s6-rc.d/svc-redis/run"
DOCKERFILE="${ADDON_DIR}/Dockerfile"

tmp="$(mktemp -d)"
cleanup() {
    jobs -p | xargs -r kill 2>/dev/null || true
    rm -rf "${tmp}"
}
trap cleanup EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

# --- init-addon-config: masking and no stray copies -------------------------
env_dir="${tmp}/env"
mkdir -p "${env_dir}"
cat >"${tmp}/options.json" <<'JSON'
{
  "N8N_LOG_LEVEL": "info",
  "N8N_SECURE_COOKIE": false,
  "N8N_WEBHOOK_URL": "https://webhook-user:webhook-pass@n8n.example.test/",
  "env_vars": [
    {"key": "DB_POSTGRESDB_PASSWORD", "value": "pg-secret-value"},
    {"key": "N8N_ENCRYPTION_KEY", "value": "enc-secret-value"},
    {"key": "MY_API_TOKEN", "value": "token-secret-value"},
    {"key": "lower_auth_header", "value": "auth-secret-value"},
    {"key": "N8N_SENTRY_DSN", "value": "dsn-secret-value"},
    {"key": "DB_POSTGRESDB_HOST", "value": "postgres.local"}
  ]
}
JSON
log="$(env -i PATH="${PATH}" HOME="${tmp}/home" OPTIONS_SOURCE="${tmp}/options.json" \
    S6_ENV_DIR="${env_dir}" bash "${S6}/init-addon-config/run")"

for secret in pg-secret-value enc-secret-value token-secret-value auth-secret-value \
    dsn-secret-value webhook-pass; do
    if grep -q -- "${secret}" <<<"${log}"; then
        fail "init-addon-config logged a secret value (${secret}): ${log}"
    fi
done
grep -q '    DB_POSTGRESDB_PASSWORD=\*\*\*\*\*\*' <<<"${log}" || fail "password not masked"
grep -q '    MY_API_TOKEN=\*\*\*\*\*\*' <<<"${log}" || fail "token not masked"
grep -q '    lower_auth_header=\*\*\*\*\*\*' <<<"${log}" || fail "lower-case key not masked"
grep -q '    DB_POSTGRESDB_HOST=postgres.local' <<<"${log}" || fail "plain value hidden"
grep -q '    N8N_WEBHOOK_URL=https://\*\*\*\*\*\*@n8n.example.test/' <<<"${log}" \
    || fail "URL credentials not removed: ${log}"

[[ "$(<"${env_dir}/DB_POSTGRESDB_PASSWORD")" == "pg-secret-value" ]] || fail "env value not exported"
[[ "$(<"${env_dir}/N8N_WEBHOOK_URL")" == "https://webhook-user:webhook-pass@n8n.example.test/" ]] \
    || fail "URL value altered in the environment"
mode="$(stat -c '%a' "${env_dir}/DB_POSTGRESDB_PASSWORD")"
[[ "${mode}" == "600" ]] || fail "s6 env file mode ${mode}, expected 600"
[[ ! -e "${tmp}/home/.bashrc" ]] || fail "init-addon-config wrote a shell profile"
if grep -nE '/\.env|/etc/environment|\.bashrc' "${S6}/init-addon-config/run" \
    | grep -v '^[0-9]*:#'; then
    fail "init-addon-config still copies settings into /.env, /etc/environment or .bashrc"
fi

# --- init-keygen: per-installation task broker token ------------------------
cat >"${tmp}/mock-bashio" <<'SH'
bashio::network.ipv4_address() { printf '%s\n' '192.0.2.10/24'; }
bashio::addon.port() { printf '%s\n' '5678'; }
SH
keygen() {
    local dir="$1"
    shift
    mkdir -p "${dir}"
    env -i PATH="${PATH}" BASH_ENV="${tmp}/mock-bashio" S6_ENV_DIR="${dir}" \
        WOOW_RUNNER_TOKEN_FILE="${tmp}/data/n8n-runners-auth-token" "$@" \
        bash "${S6}/init-keygen/run" >/dev/null
}
mkdir -p "${tmp}/data" "${tmp}/kg1"
printf '%s' 'sv-secret' >"${tmp}/kg1/SUPERVISOR_TOKEN"
printf '%s' 'sv-secret' >"${tmp}/kg1/HASSIO_TOKEN"
keygen "${tmp}/kg1"
[[ ! -e "${tmp}/kg1/SUPERVISOR_TOKEN" && ! -e "${tmp}/kg1/HASSIO_TOKEN" ]] \
    || fail "init-keygen left the Supervisor token in the s6 container environment"
token_file="${tmp}/data/n8n-runners-auth-token"
[[ -s "${token_file}" ]] || fail "runner token not generated"
first_token="$(<"${token_file}")"
[[ "${first_token}" =~ ^[0-9a-f]{64}$ ]] || fail "runner token is not 32 random bytes in hex"
[[ "${first_token}" != "n8n-runner" ]] || fail "runner token is the old shared constant"
[[ "$(stat -c '%a' "${token_file}")" == "600" ]] || fail "runner token file is not 600"
[[ "$(<"${tmp}/kg1/N8N_RUNNERS_AUTH_TOKEN_FILE")" == "${token_file}" ]] \
    || fail "n8n is not pointed at the token file"
[[ ! -e "${tmp}/kg1/N8N_RUNNERS_AUTH_TOKEN" ]] || fail "token value exported into the n8n environment"
chmod 644 "${token_file}"
keygen "${tmp}/kg2"
[[ "$(<"${token_file}")" == "${first_token}" ]] || fail "runner token changed across restarts"
[[ "$(stat -c '%a' "${token_file}")" == "600" ]] || fail "runner token permissions not repaired"
keygen "${tmp}/kg3" N8N_RUNNERS_AUTH_TOKEN=user-chosen-token
[[ ! -e "${tmp}/kg3/N8N_RUNNERS_AUTH_TOKEN_FILE" ]] || fail "explicit user token overridden"

grep -q 'N8N_RUNNERS_AUTH_TOKEN=' "${DOCKERFILE}" && fail "Dockerfile still bakes a shared runner token"
grep -q 'N8N_RUNNERS_BROKER_LISTEN_ADDRESS="127.0.0.1"' "${DOCKERFILE}" \
    || fail "task broker is not loopback-only"
grep -q 'N8N_RUNNERS_TASK_BROKER_URI="http://127.0.0.1:5679"' "${DOCKERFILE}" \
    || fail "launcher does not dial the loopback broker"
grep -q 'N8N_BLOCK_ENV_ACCESS_IN_NODE=false' "${DOCKERFILE}" \
    || fail "\$env access changed; existing workflows rely on it"

# --- service run scripts: no Supervisor token in n8n or the launcher --------
bin="${tmp}/bin"
mkdir -p "${bin}"
cat >"${bin}/n8n" <<'SH'
#!/bin/bash
env > "${CAPTURE}"
SH
cat >"${bin}/fake-guard" <<'SH'
#!/bin/bash
printf '%s' "$1" > "${CAPTURE}.guard"
SH
chmod +x "${bin}/n8n" "${bin}/fake-guard"
env -i PATH="${bin}:${PATH}" CAPTURE="${tmp}/n8n.env" SUPERVISOR_TOKEN=sv-secret \
    HASSIO_TOKEN=hassio-secret WOOW_N8N_STARTUP_MARKER="${tmp}/run/starting" \
    WOOW_N8N_STARTUP_GUARD="${bin}/fake-guard" KEEP_ME=kept \
    bash "${S6}/svc-n8n/run"
grep -q '^SUPERVISOR_TOKEN=' "${tmp}/n8n.env" && fail "n8n receives SUPERVISOR_TOKEN"
grep -q '^HASSIO_TOKEN=' "${tmp}/n8n.env" && fail "n8n receives HASSIO_TOKEN"
grep -q '^KEEP_ME=kept$' "${tmp}/n8n.env" || fail "svc-n8n dropped an ordinary variable"
for _ in $(seq 1 50); do [[ -s "${tmp}/n8n.env.guard" ]] && break; sleep 0.1; done
[[ -f "${tmp}/run/starting" ]] || fail "svc-n8n did not create the startup marker"
[[ "$(<"${tmp}/run/starting")" == "$(<"${tmp}/n8n.env.guard")" ]] \
    || fail "startup marker and guard disagree on the n8n PID"

runner_run="${tmp}/svc-runner-run"
sed -e "s#/usr/local/bin/task-runner-launcher#${bin}/n8n#" \
    -e "s#/config/runner#${tmp}/config-runner#g" "${S6}/svc-runner/run" >"${runner_run}"
printf '%s' 'file-token' >"${tmp}/runner-token"
env -i PATH="${PATH}" CAPTURE="${tmp}/runner.env" SUPERVISOR_TOKEN=sv-secret \
    HASSIO_TOKEN=hassio-secret N8N_RUNNERS_AUTH_TOKEN_FILE="${tmp}/runner-token" \
    bash "${runner_run}"
grep -q '^SUPERVISOR_TOKEN=' "${tmp}/runner.env" && fail "launcher receives SUPERVISOR_TOKEN"
grep -q '^HASSIO_TOKEN=' "${tmp}/runner.env" && fail "launcher receives HASSIO_TOKEN"
grep -q '^N8N_RUNNERS_AUTH_TOKEN=file-token$' "${tmp}/runner.env" \
    || fail "launcher did not get the broker token from the file"
grep -q '^N8N_RUNNERS_AUTH_TOKEN_FILE=' "${tmp}/runner.env" && fail "token file path leaked to the launcher"
python3 - "${ADDON_DIR}/rootfs/etc/n8n-task-runners.json" <<'PY'
import json, sys
for runner in json.load(open(sys.argv[1]))["task-runners"]:
    env = set(runner["allowed-env"])
    leaked = env & {"SUPERVISOR_TOKEN", "HASSIO_TOKEN", "N8N_RUNNERS_AUTH_TOKEN"}
    assert not leaked, f"{runner['runner-type']} runner allows {leaked}"
PY

# --- startup guard -----------------------------------------------------------
cat >"${bin}/curl" <<'SH'
#!/bin/bash
[[ -f "${READY_FLAG}" ]]
SH
chmod +x "${bin}/curl"
sleep 300 &
fake_pid=$!
marker="${tmp}/guard/starting"
mkdir -p "$(dirname "${marker}")"
printf '%s' "${fake_pid}" >"${marker}"
PATH="${bin}:${PATH}" READY_FLAG="${tmp}/ready" WOOW_N8N_STARTUP_MARKER="${marker}" \
    WOOW_N8N_STARTUP_POLL=0.1 "${GUARD}" "${fake_pid}" >"${tmp}/guard.log" &
guard_pid=$!
sleep 0.5
[[ -f "${marker}" ]] || fail "guard removed the marker before n8n was ready"
touch "${tmp}/ready"
wait "${guard_pid}"
[[ ! -e "${marker}" ]] || fail "guard kept the marker after n8n became ready"
grep -q 'n8n is ready after' "${tmp}/guard.log" || fail "guard did not report readiness"

printf '%s' "99999999" >"${marker}"
rm -f "${tmp}/ready"
PATH="${bin}:${PATH}" READY_FLAG="${tmp}/ready" WOOW_N8N_STARTUP_MARKER="${marker}" \
    WOOW_N8N_STARTUP_POLL=0.1 "${GUARD}" "${fake_pid}" >/dev/null &
guard_pid=$!
sleep 0.3
touch "${tmp}/ready"
wait "${guard_pid}"
[[ "$(<"${marker}")" == "99999999" ]] || fail "guard removed the marker of a newer n8n start"

printf '%s' "${fake_pid}" >"${marker}"
rm -f "${tmp}/ready"
PATH="${bin}:${PATH}" READY_FLAG="${tmp}/ready" WOOW_N8N_STARTUP_MARKER="${marker}" \
    WOOW_N8N_STARTUP_POLL=0.1 WOOW_N8N_STARTUP_GRACE=1 "${GUARD}" "${fake_pid}" >"${tmp}/guard.log"
[[ ! -e "${marker}" ]] || fail "guard kept the marker past the grace period"
grep -q 'not ready after 1s' "${tmp}/guard.log" || fail "guard did not report the grace timeout"
kill "${fake_pid}"

# Long-running services must not keep a shell (or nginx) whose start-up
# environment still holds the token: they unset it and exec.
grep -q '^exec s6-notifyoncheck' "${REDIS_RUN}" || fail "svc-redis leaves its shell running"
for run in "${S6}/nginx/run" "${S6}/svc-n8n/run" "${S6}/svc-runner/run" "${REDIS_RUN}"; do
    grep -q '^unset SUPERVISOR_TOKEN HASSIO_TOKEN$' "${run}" || fail "${run} keeps the Supervisor token"
done

# Stop order: s6-rc stops dependants first. n8n must stop before the task
# runners (it drains running executions through them, and the launcher waits
# for the broker to drain), so n8n depends on the runner and not vice versa.
# The runner needs init-keygen for the broker token.
[[ -e "${S6}/svc-n8n/dependencies.d/svc-runner" ]] || fail "n8n would stop after its task runners"
[[ ! -e "${S6}/svc-runner/dependencies.d/svc-n8n" ]] || fail "task runners would stop before n8n"
[[ -e "${S6}/svc-runner/dependencies.d/init-keygen" ]] || fail "launcher may start before its token exists"
# n8n does not use Redis: a Redis that refuses to start (e.g. its ARM64
# copy-on-write self-check) must not keep n8n down. Redis is started on its own.
[[ ! -e "${S6}/svc-n8n/dependencies.d/svc-redis" ]] || fail "n8n waits for Redis"
[[ -e "${ADDON_DIR}/.common/redis/etc/s6-overlay/s6-rc.d/user/contents.d/svc-redis" ]] \
    || fail "Redis is no longer started without the n8n dependency"

# --- Redis --------------------------------------------------------------------
grep -q -- '--bind 127.0.0.1 -::1' "${REDIS_RUN}" || fail "Redis is not loopback-only"
grep -q -- '--bind 0.0.0.0' "${REDIS_RUN}" && fail "Redis still binds every interface"
grep -q -- '--protected-mode yes' "${REDIS_RUN}" || fail "Redis protected mode not forced"
grep -q -- '--unixsocketperm 770' "${REDIS_RUN}" || fail "Redis socket is world-accessible"
grep -q 'dump.rdb"' "${REDIS_RUN}" || fail "clean_redis does not remove dump.rdb"
grep -q 'dump.rdd' "${REDIS_RUN}" && fail "clean_redis still targets dump.rdd"
grep -q '^protected-mode yes$' "${ADDON_DIR}/.common/redis/defaults/redis.conf" \
    || fail "default redis.conf disables protected mode"

printf '%s\n' 'runtime security tests passed'
