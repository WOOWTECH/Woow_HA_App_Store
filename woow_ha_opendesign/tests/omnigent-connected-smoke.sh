#!/usr/bin/env bash
# Real-service acceptance for owned candidates only. Never targets existing
# containers/HA. Requires authorized provider files for the disposable runtime.
# tests/omnigent-connected-smoke.sh <candidate-image> <private-json-file> <private-provider-directory> [upgrade-image]
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")/.."
image=${1:?candidate image}
credential_file=${2:?private JSON file with server/username/password}
provider_directory=$(realpath "${3:?private provider fixture directory}")
upgrade_image=${4:-$image}
credential_file=$(realpath "$credential_file")
python3 tests/validate-omnigent-provider-fixture.py "$provider_directory"
python3 - "$credential_file" <<'PY'
import json, os, stat, sys
p = sys.argv[1]
s = os.stat(p)
if not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077:
    raise SystemExit('credential file must be a private regular file (0600)')
try:
    data = json.load(open(p))
    assert all(isinstance(data.get(k), str) and data[k] for k in ('server', 'username', 'password'))
except Exception:
    raise SystemExit('credential file must contain server, username and password') from None
PY
scratch=$(mktemp -d)
container="ha-omnigent-connected-${RANDOM}-${RANDOM}"
original_volume="${container}-data"
restored_volume="${container}-restored"
volume=$original_volume
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$original_volume" "$restored_volume" >/dev/null 2>&1 || true
  rm -rf "$scratch"
}
trap cleanup EXIT
# No log dumps, published ports, host networking or production volume mounts.
docker volume create "$original_volume" >/dev/null
docker volume create "$restored_volume" >/dev/null
# Seed only the reviewed provider files. Omnigent state is deliberately absent;
# fresh setup must still ask for its server/account/password. These files never
# enter the candidate image or the source tree.
docker run --rm --platform linux/amd64 --entrypoint /bin/sh \
  -v "$original_volume:/data" -v "$provider_directory:/provider-fixture:ro" "$image" -ceu \
  'mkdir -p /data/opendesign/home; cp -R /provider-fixture/. /data/opendesign/home/; chown -R 1001:1001 /data/opendesign; chmod 0700 /data/opendesign /data/opendesign/home'
probe() { docker exec "$container" node /tmp/ha-omnigent-connected.mjs "$1"; }
start() {
  docker run -d --name "$container" --platform linux/amd64 \
    -v "$volume:/data" -v "$credential_file:/run/ha-omnigent-smoke-credentials.json:ro" "$image" >/dev/null
  docker cp tests/container-omnigent-connected.mjs "$container:/tmp/ha-omnigent-connected.mjs"
  for _attempt in $(seq 1 90); do
    if docker exec "$container" node -e "fetch('http://127.0.0.1:8099/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; then return; fi
    sleep 1
  done
  echo 'candidate health timed out (logs withheld)' >&2
  return 1
}
stop() {
  # Scan logs inside the still-running container, with private tokens available.
  docker logs "$container" >"$scratch/container.log" 2>&1
  docker exec -i "$container" node /tmp/ha-omnigent-connected.mjs logs <"$scratch/container.log"
  docker stop -t 45 "$container" >/dev/null
  docker logs "$container" >"$scratch/container.log" 2>&1
  # Run the same secret scan on shutdown logs without restarting the daemon.
  docker run --rm -i --platform linux/amd64 --entrypoint node \
    -v "$volume:/data:ro" -v "$credential_file:/run/ha-omnigent-smoke-credentials.json:ro" \
    -v "$PWD/tests/container-omnigent-connected.mjs:/tmp/check.mjs:ro" \
    "$image" /tmp/check.mjs logs <"$scratch/container.log"
  docker rm "$container" >/dev/null
  docker run --rm --platform linux/amd64 --entrypoint node -v "$volume:/data:ro" \
    -v "$PWD/tests/container-omnigent-connected.mjs:/tmp/check.mjs:ro" "$image" /tmp/check.mjs stopped
}
start
probe setup
stop
start
probe resumed
stop
# Cold backup/restore onto a distinct empty volume, dropping file ownership as
# Supervisor does. The second image can be a newer native Omnigent candidate.
docker run --rm --platform linux/amd64 --entrypoint sh \
  -v "$volume:/source:ro" -v "$scratch:/backup" "$image" -ceu 'tar -cf /backup/data.tar -C /source .'
docker run --rm --platform linux/amd64 --entrypoint sh \
  -v "$restored_volume:/data" -v "$scratch:/backup:ro" "$image" -ceu \
  'tar -xf /backup/data.tar -C /data; find /data -exec chown -h 0:0 {} +'
volume=$restored_volume
image=$upgrade_image
start
probe resumed
probe controls
# The host has already stopped on disconnect; verify remaining addon shutdown.
stop
echo 'authenticated native Omnigent restart/restore/upgrade/control acceptance passed'
