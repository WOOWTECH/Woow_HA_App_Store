#!/usr/bin/env bash
# tests/lib/parity.sh — portable adapter for the code-server parity trio
# (podman / HA add-on / k3s chart). Source this from a smoke test:
#
#   . "$(dirname "$0")/lib/parity.sh"
#   CX pi --version
#   curl "${BASE}/healthz"
#
# Select the target with PARITY_TARGET=podman|ha|k3s (default: podman).
# Every row in PARITY_CONTRACT.md's checklist is written against these
# names (CX, SETTINGS, PORT, BASE, LIVENESS, EXT_INSTALLED) — the same
# assertion text in smoke-*.sh runs unmodified against all three targets.
#
# EXT_INSTALLED exists because `code-server --list-extensions` only lists
# the USER extensions-dir, not the builtin scan directory — and the HA
# add-on deliberately installs the ACP Client extension into the builtin
# dir (upstream's init-code-server purges /data/vscode/extensions/<id>*
# on every boot, which would self-delete a /data install). Confirmed by
# building and running the HA image: `--list-extensions` returns empty
# there even for upstream's own pre-installed marketplace extensions.

: "${PARITY_TARGET:=podman}"

case "${PARITY_TARGET}" in
podman)
    CODE_SERVER_HOST="${CODE_SERVER_HOST:-127.0.0.1}"
    PORT="${CODE_SERVER_PORT:-8443}"
    BASE="${CODE_SERVER_BASE:-http://${CODE_SERVER_HOST}:${PORT}}"
    SETTINGS="/home/coder/.local/share/code-server/User/settings.json"
    # Overridable so a freshly built image can be smoke-tested in a throwaway
    # container without disturbing the live `code-server` unit.
    : "${PODMAN_CONTAINER:=code-server}"
    CX()       { podman exec -u coder "${PODMAN_CONTAINER}" "$@"; }
    CX_ROOT()  { podman exec "${PODMAN_CONTAINER}" "$@"; }
    LIVENESS() { podman inspect --format '{{.State.Health.Status}}' "${PODMAN_CONTAINER}" 2>/dev/null; }
    EXT_INSTALLED() { CX code-server --list-extensions 2>/dev/null | grep -qi '^formulahendry\.acp-client$'; }
    ;;
ha)
    : "${SSHHA:?set SSHHA to the ssh helper, e.g. /path/to/sshha.sh}"
    # The Supervisor prefixes the container name with the REPOSITORY hash
    # (app_<hash>_<slug>), and that hash differs per HA install — so a
    # hardcoded default is wrong everywhere except the machine it was written
    # on. It was: every check reported "No such container" and FAILED, which
    # reads exactly like a broken deployment. Detect it, and only fall back to
    # the unprefixed form (what a local `docker run` of the image would be
    # called) if detection finds nothing.
    if [ -z "${HA_ADDON_CONTAINER:-}" ]; then
        HA_ADDON_CONTAINER="$("${SSHHA}" "docker ps --format '{{.Names}}' | grep -m1 'woow_ha_code_server'" 2>/dev/null | tr -d '\r')"
        : "${HA_ADDON_CONTAINER:=app_woow_ha_code_server}"
    fi
    PORT="1337"
    BASE="${CODE_SERVER_BASE:-}"
    SETTINGS="/data/vscode/User/settings.json"
    # SSHHA takes ONE opaque string, run remotely as `sh -c "<string>"` — so
    # each of our own arguments must be individually shell-quoted before
    # joining, or an argument containing a space or a redirect (e.g.
    # `sh -c 'ls ... 2>/dev/null'`) silently loses its quoting and gets
    # re-split as separate words on the remote end. `printf %q` round-trips
    # correctly through that remote re-parse. (Caught by actually building
    # and running this image against a mock Supervisor and exercising every
    # CX_ROOT call — the naive `$*` join below passed every check that
    # didn't involve a space or a redirect, which is exactly the bug class
    # that ships silently.)
    CX()       { "${SSHHA}" "docker exec ${HA_ADDON_CONTAINER} $(printf '%q ' "$@")"; }
    CX_ROOT()  { CX "$@"; }
    LIVENESS() { "${SSHHA}" "docker inspect --format '{{.State.Status}}' ${HA_ADDON_CONTAINER}" 2>/dev/null | tr -d '\r'; }
    EXT_INSTALLED() { CX_ROOT sh -c 'ls /usr/local/lib/code-server/lib/vscode/extensions/ 2>/dev/null' | grep -qi '^formulahendry\.acp-client-'; }
    ;;
k3s)
    : "${KUBECTL_CONTEXT:=woow-k3s}"
    : "${K3S_NAMESPACE:=code-server}"
    PORT="8080"
    BASE="${CODE_SERVER_BASE:-https://code-server-woow-k3s.woowtech.io}"
    SETTINGS="/home/coder/.local/share/code-server/User/settings.json"
    CX()       { kubectl --context "${KUBECTL_CONTEXT}" -n "${K3S_NAMESPACE}" exec deploy/code-server -c code-server -- "$@"; }
    CX_ROOT()  { CX "$@"; }
    LIVENESS() { kubectl --context "${KUBECTL_CONTEXT}" -n "${K3S_NAMESPACE}" get deploy/code-server -o jsonpath='{.status.readyReplicas}' 2>/dev/null; }
    EXT_INSTALLED() { CX code-server --list-extensions 2>/dev/null | grep -qi '^formulahendry\.acp-client$'; }
    ;;
*)
    echo "Unknown PARITY_TARGET=${PARITY_TARGET} (want podman|ha|k3s)" >&2
    exit 2
    ;;
esac
