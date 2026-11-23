#!/usr/bin/env bash
# Starts the add-on's real ngrok legacy service (ngrok disabled, the default)
# next to a stand-in longrun on the add-on's s6-overlay base image, then checks
# that s6 finishes starting (legacy-services completes) and that `docker stop`
# ends the container within its 10-second grace period instead of SIGKILL
# (exit 137). Pipeline unattended-pipeline/213.
#
# grep reads captured logs, not a pipe: with pipefail, `docker logs | grep -q`
# fails whenever grep exits before docker logs has written everything.
#
# Needs docker. Usage: bash headscale/tests/test-s6-startup.sh
set -euo pipefail

addon_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
base=$(sed -n 's/^ *amd64: *"\(.*\)"$/\1/p' "${addon_dir}/build.yaml")
[[ -n "${base}" ]] || { echo 'FAIL: no amd64 base in build.yaml' >&2; exit 1; }

work=$(mktemp -d)
image="woow-headscale-s6-startup-test:$$"
container="woow-headscale-s6-startup-test-$$"
network="woow-headscale-s6-startup-test-$$"
supervisor="woow-headscale-s6-startup-supervisor-$$"
cleanup() {
    docker rm -f "${container}" "${supervisor}" > /dev/null 2>&1 || true
    docker network rm "${network}" > /dev/null 2>&1 || true
    docker rmi -f "${image}" > /dev/null 2>&1 || true
    rm -rf "${work}"
}
trap cleanup EXIT

mkdir -p "${work}/services.d"
cp -a "${addon_dir}/rootfs/etc/services.d/ngrok" "${work}/services.d/ngrok"
mkdir -p "${work}/services.d/standin"
printf '#!/bin/sh\nexec sleep infinity\n' > "${work}/services.d/standin/run"
echo longrun > "${work}/services.d/standin/type"

# bashio reads the add-on options from the Supervisor API, so a stand-in
# Supervisor answers /addons/self/options/config with the add-on defaults
# (ngrok_enabled: false) and every other call with empty data.
cat > "${work}/supervisor.py" <<'PYTHON'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

OPTIONS = {
    "log_level": "info",
    "ngrok_enabled": False,
    "ngrok_authtoken": "",
    "ngrok_mode": "http",
    "ngrok_domain": "",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = OPTIONS if self.path == "/addons/self/options/config" else {}
        body = json.dumps({"result": "ok", "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET


HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
PYTHON
cat > "${work}/Dockerfile" <<DOCKERFILE
FROM ${base}
COPY services.d /etc/services.d
RUN chmod +x /etc/services.d/*/run
DOCKERFILE

docker build -q -t "${image}" "${work}" > /dev/null
docker network create "${network}" > /dev/null
docker run -d --name "${supervisor}" --network "${network}" --network-alias supervisor \
    -v "${work}/supervisor.py:/supervisor.py:ro" python:3.12-alpine \
    python -u /supervisor.py > /dev/null
for _ in $(seq 1 30); do
    docker exec "${supervisor}" wget -qO /dev/null http://127.0.0.1/ 2> /dev/null && break
    sleep 1
done
docker run -d --name "${container}" --network "${network}" "${image}" > /dev/null

started=false
for _ in $(seq 1 30); do
    if grep -q 'legacy-services successfully started' <<< "$(docker logs "${container}" 2>&1)"; then
        started=true
        break
    fi
    sleep 1
done
if ! ${started}; then
    docker logs "${container}" 2>&1 | sed 's/^/  log: /' >&2
    echo 'FAIL: s6 legacy-services never finished starting' >&2
    exit 1
fi

docker stop -t 10 "${container}" > /dev/null
exit_code=$(docker inspect -f '{{.State.ExitCode}}' "${container}")
if [[ "${exit_code}" == '137' ]]; then
    docker logs "${container}" 2>&1 | sed 's/^/  log: /' >&2
    echo 'FAIL: container was SIGKILLed on stop (exit 137)' >&2
    exit 1
fi
if ! grep -q 'legacy-services: stopping' <<< "$(docker logs "${container}" 2>&1)"; then
    docker logs "${container}" 2>&1 | sed 's/^/  log: /' >&2
    echo 'FAIL: s6 did not run the legacy-services stop' >&2
    exit 1
fi

printf 'PASS: s6 startup completes with ngrok disabled; stop exits %s\n' "${exit_code}"
