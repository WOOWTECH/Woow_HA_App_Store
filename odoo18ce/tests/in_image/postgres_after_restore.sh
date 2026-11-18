#!/usr/bin/env bash
# ==============================================================================
# Build tier: the add-on starts on a cluster a Home Assistant restore gave back.
#
# Supervisor restores an add-on by extracting its backup into a temporary
# directory, removing /data and copying the extracted tree back with
# shutil.copytree(symlinks=True) as root (supervisor/apps/app.py, restore(),
# 2026.11.0). copytree keeps no owner, so every file of the PostgreSQL
# cluster arrives owned by root, and up to 0.4.12 the start stopped in
# 00-postgres-init.sh at
#   pg_ctl: could not open PID file "/data/postgres/postmaster.pid": Permission denied
#
# One data volume, all in the image under test:
#   1. A first start creates a real cluster and a row is written into it. A
#      new cluster has nothing to repair, so this start must not log one.
#   2. The add-on is stopped, as for a cold backup, and restored the way
#      Supervisor restores it. Over that goes the state the test box showed
#      after its own restore: files 0644, directories 0755, the cluster
#      directory 0700. A symbolic link to a root-only file outside the
#      cluster is planted too; the repair must not follow it.
#   3. A start must log one repair, start PostgreSQL on the restored cluster
#      and read the row back. Afterwards nothing under the cluster belongs to
#      anyone but postgres, its directory is 0700, and the link's target is
#      still root's, mode unchanged.
#   4. Steps 2 and 3 again with the cluster directory restored at 0755, as a
#      restore that does not keep directory modes leaves it: the repair must
#      set it back to 0700 as well.
#
# The image does not start without a Supervisor (bashio reads the options
# from it), so supervisor_stub.py beside this file answers the few reads a
# start makes, from a container whose network namespace the add-on joins.
#
# Usage: postgres_after_restore.sh <image>
# ENGINE names the container CLI (default docker). Anything with docker's
# verbs works, such as a podman wrapper bound to separate storage. The last
# line is `postgres-after-restore: ok` on a pass; any failure exits non-zero
# with a `postgres-after-restore: FAIL:` line saying what was read.
# ==============================================================================
set -euo pipefail

IMAGE="${1:?usage: postgres_after_restore.sh <image>}"
ENGINE="${ENGINE:-docker}"
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
CONFIG="${HERE}/../../config.yaml"
RUN="pg-after-restore-$$"
VOLUME="${RUN}"
STUB="${RUN}-supervisor"
# Not a port the add-on listens on (5432, 5691, 8069, 8070, 8072, 8073):
# the add-on shares the stub's network namespace.
STUB_PORT=18099
# A start without public_url waits for nothing the stub does not answer, so
# PostgreSQL answers within a minute; this is the ceiling on a slow runner.
READY_WITHIN=240
# The start of the line 00-postgres-init.sh logs when it repaired something;
# tests/test_postgres_after_restore.py keeps the two spellings equal.
REPAIR_LINE="Repaired /data/postgres"

say() { printf 'postgres-after-restore: %s\n' "$*"; }
fail() { say "FAIL: $*"; exit 1; }

# One name per call: podman 4.9 removes nothing when one of several names
# does not exist, and a failed run never made the later containers. The stub
# goes last, after the containers that share its network namespace.
cleanup() {
    local name
    for name in "${RUN}-first" "${RUN}-second" "${RUN}-third" "${STUB}"; do
        "${ENGINE}" rm -f "${name}" >/dev/null 2>&1 || true
    done
    "${ENGINE}" volume rm -f "${VOLUME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# A throwaway root container of the same image on the data volume. The
# restore and its check run from inside, so they see the owners and modes
# the add-on sees, however the engine maps users.
on_volume() {
    "${ENGINE}" run --rm -i --no-healthcheck -v "${VOLUME}:/data" \
        --entrypoint "$1" "${IMAGE}" "${@:2}"
}

start() {
    "${ENGINE}" run -d --name "$1" --no-healthcheck --network "container:${STUB}" \
        -e "SUPERVISOR_API=http://127.0.0.1:${STUB_PORT}" -e SUPERVISOR_TOKEN=stub \
        -v "${VOLUME}:/data" "${IMAGE}" >/dev/null
}

# Waits until PostgreSQL in container $1 answers on 127.0.0.1:5432. Only the
# postgres service listens there; the temporary server cont-init starts has
# no TCP listener, so an answer means cont-init finished.
wait_for_postgres() {
    local name=$1 deadline=$((SECONDS + READY_WITHIN))
    until "${ENGINE}" exec "${name}" pg_isready -q -h 127.0.0.1 -p 5432 2>/dev/null; do
        if [ "$("${ENGINE}" inspect -f '{{.State.Running}}' "${name}")" != "true" ]; then
            "${ENGINE}" logs "${name}" 2>&1 | tail -n 40
            fail "${name} stopped before PostgreSQL answered; the end of its log is above"
        fi
        if [ "${SECONDS}" -ge "${deadline}" ]; then
            "${ENGINE}" logs "${name}" 2>&1 | tail -n 40
            fail "PostgreSQL in ${name} did not answer within ${READY_WITHIN} s; the end of its log is above"
        fi
        sleep 2
    done
}

# Backs the stopped add-on's /data up and restores it the way Supervisor
# does, then lays the test box's modes over it with the cluster directory at
# mode $1.
restore() {
    on_volume python3 - "$1" <<'PY'
import os, shutil, sys, tarfile, tempfile

DATA = "/data"
CLUSTER = os.path.join(DATA, "postgres")
# The backup: Supervisor writes the stopped add-on's /data with TarFile.add
# (securetar.atomic_contents_add), which records owner, group and mode.
backup = "/tmp/backup.tar"
with tarfile.open(backup, "w") as tar:
    for name in sorted(os.listdir(DATA)):
        tar.add(os.path.join(DATA, name), arcname="data/" + name)
# The restore: extract into a temporary directory, remove /data, copy it
# back with copytree(symlinks=True) as root. Supervisor's "tar" filter
# clears the high and group/other write bits, done here by hand because the
# image's Python predates extractall(filter=...). /data itself is the
# volume's mount point here, so its contents go instead of the directory.
extracted = tempfile.mkdtemp()
with tarfile.open(backup) as tar:
    members = tar.getmembers()
    for member in members:
        member.mode &= 0o755
    tar.extractall(extracted, members=members)
for name in os.listdir(DATA):
    path = os.path.join(DATA, name)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)
shutil.copytree(os.path.join(extracted, "data"), DATA, symlinks=True, dirs_exist_ok=True)
# The modes the test box showed after its own restore. A link has no mode
# of its own: chmod would change the file it points to.
for root, dirs, files in os.walk(CLUSTER):
    for name, mode in [(name, 0o755) for name in dirs] + [(name, 0o644) for name in files]:
        if not os.path.islink(os.path.join(root, name)):
            os.chmod(os.path.join(root, name), mode)
os.chmod(CLUSTER, int(sys.argv[1], 8))
# A link out of the cluster to a file only root may read; a later round
# finds both in the backup.
target = os.path.join(DATA, "restore-probe-target")
link = os.path.join(CLUSTER, "restore-probe-link")
if not os.path.lexists(link):
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("root only\n")
    os.chmod(target, 0o600)
    os.symlink(target, link)
# Checked, not assumed: the next start gets a cluster that is all root's.
entries = [CLUSTER] + [os.path.join(root, name)
                       for root, dirs, files in os.walk(CLUSTER) for name in dirs + files]
others = [path for path in entries if (os.lstat(path).st_uid, os.lstat(path).st_gid) != (0, 0)]
if others or not os.path.isfile(os.path.join(CLUSTER, "PG_VERSION")):
    raise SystemExit(f"the restore left {len(others)} of {len(entries)} entries not root's")
print(f"postgres-after-restore: restored: {len(entries)} entries under {CLUSTER}, all 0:0,"
      f" cluster directory {sys.argv[1]}")
PY
}

psql_in() {
    "${ENGINE}" exec -i -u postgres "$1" psql -X -q -t -A -v ON_ERROR_STOP=1 "${@:2}"
}

# Starts container $1 on the restored cluster and checks it was repaired and
# served. $2 is the mode repair the logged line must name, or "" for none.
start_restored() {
    local name=$1 mode_repair=$2 read_back readings repairs
    start "${name}"
    wait_for_postgres "${name}"
    read_back="$(psql_in "${name}" -d restore_probe -c "SELECT value FROM marker")"
    if [ "${read_back}" != "${MARKER}" ]; then
        fail "${name} read '${read_back}' back, not the row written before the restore"
    fi
    # One exec for every reading, in the running container: the add-on
    # itself stops later, when its self-check gets no add-on address. The
    # sh in the container expands these, not this script.
    # shellcheck disable=SC2016
    readings="$("${ENGINE}" exec "${name}" sh -c '
        printf "not-postgres=%s\n" "$(find /data/postgres \( ! -user postgres -o ! -group postgres \) | wc -l)"
        printf "cluster-mode=%s\n" "$(stat -c %a /data/postgres)"
        printf "link-owner=%s\n" "$(stat -c %U:%G /data/postgres/restore-probe-link)"
        printf "target=%s\n" "$(stat -c "%u:%g %a" /data/restore-probe-target)"
    ')"
    reading() { sed -n "s/^$1=//p" <<< "${readings}"; }
    [ "$(reading not-postgres)" = "0" ] \
        || fail "${name}: $(reading not-postgres) entries under /data/postgres are not postgres:postgres"
    [ "$(reading cluster-mode)" = "700" ] \
        || fail "${name}: /data/postgres is mode $(reading cluster-mode), not 700"
    [ "$(reading link-owner)" = "postgres:postgres" ] \
        || fail "${name}: the link in the cluster is $(reading link-owner), not postgres:postgres"
    [ "$(reading target)" = "0:0 600" ] \
        || fail "${name}: the repair followed the link; its target is $(reading target), not 0:0 600"
    # bashio colours its lines; the colour codes go before they are compared.
    repairs="$("${ENGINE}" logs "${name}" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
        | grep -F "${REPAIR_LINE}" || true)"
    [ "$(grep -c . <<< "${repairs}")" = "1" ] \
        || fail "${name} logged the repair $(grep -c . <<< "${repairs}") times, not once"
    if [ -n "${mode_repair}" ] && ! grep -qF "${mode_repair}" <<< "${repairs}"; then
        fail "${name} logged '${repairs}', which does not name '${mode_repair}'"
    fi
    if [ -z "${mode_repair}" ] && grep -qF " mode " <<< "${repairs}"; then
        fail "${name} logged '${repairs}', a mode repair on a cluster restored at 0700"
    fi
    say "${name}: row read back; logged: ${repairs#*"${REPAIR_LINE}"}"
}

say "image ${IMAGE}, engine ${ENGINE}"
"${ENGINE}" volume create "${VOLUME}" >/dev/null

# What Supervisor writes before a start: the defaults from config.yaml and
# the two required passwords, generated here and never printed.
on_volume python3 - "$(cat "${CONFIG}")" <<'PY'
import json, os, secrets, sys
import yaml
options = {key: value for key, value in yaml.safe_load(sys.argv[1])["options"].items()
           if value is not None}
options["admin_passwd"] = secrets.token_urlsafe(24)
options["db_password"] = secrets.token_urlsafe(24)
os.umask(0o077)
with open("/data/options.json", "w", encoding="utf-8") as handle:
    json.dump(options, handle)
PY

# python3 is the stub's PID 1 and so ignores SIGTERM; the short stop timeout
# spares the cleanup the engine's default wait before it kills it. The
# add-on asks for its options first thing, so the stub must answer first.
"${ENGINE}" run -d --name "${STUB}" --no-healthcheck --stop-timeout 1 -v "${VOLUME}:/data:ro" \
    --entrypoint python3 "${IMAGE}" -c "$(cat "${HERE}/supervisor_stub.py")" "${STUB_PORT}" >/dev/null
stub_answers() {
    "${ENGINE}" exec "${STUB}" python3 -c "import urllib.request
urllib.request.urlopen('http://127.0.0.1:${STUB_PORT}/addons/self/info', timeout=2)" 2>/dev/null
}
for _ in $(seq 1 30); do
    stub_answers && break
    sleep 1
done
stub_answers || fail "the Supervisor stub did not answer on 127.0.0.1:${STUB_PORT}"

# ---------- 1. A first start makes a real cluster ----------
start "${RUN}-first"
wait_for_postgres "${RUN}-first"
MARKER="restored-${RUN}-${RANDOM}${RANDOM}"
psql_in "${RUN}-first" -c "CREATE DATABASE restore_probe"
psql_in "${RUN}-first" -d restore_probe \
    -c "CREATE TABLE marker (value text); INSERT INTO marker VALUES ('${MARKER}')"
"${ENGINE}" stop -t 60 "${RUN}-first" >/dev/null
if "${ENGINE}" logs "${RUN}-first" 2>&1 | grep -qF "${REPAIR_LINE}"; then
    fail "the first start repaired a cluster initdb had just made"
fi
say "first start: new cluster, row written, nothing repaired"

# ---------- 2, 3. The restore the test box saw ----------
restore 0700
start_restored "${RUN}-second" ""
"${ENGINE}" stop -t 60 "${RUN}-second" >/dev/null

# ---------- 4. A restore that loosened the cluster directory ----------
restore 0755
start_restored "${RUN}-third" "mode 755 -> 700"
say "ok"
