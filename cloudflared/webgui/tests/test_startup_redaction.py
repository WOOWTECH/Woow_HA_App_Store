"""Execute actual shell bodies with synthetic Bashio/cloudflared substitutes.

No live HA, filesystem markers, credentials files, or network are touched.
These are isolated shell tests, not tests of a deployed cloudflared binary.
"""
from pathlib import Path
import os
import subprocess

import pytest

ROOT = Path(os.environ.get("HA_TEST_ROOTFS", Path(__file__).resolve().parents[2] / "rootfs"))
MARKER = "SYNTHETIC_PRIVATE_TOKEN_123456789"
STUB = r'''
cloudflared-credential-guard() { return 0; }
__BASHIO_LOG_LEVEL_TRACE=0
__BASHIO_EXIT_OK=0
bashio::log.log() { printf '%s\n' "$*" >&2; }
bashio::log.trace() { printf '%s\n' "$*" >&2; }
bashio::log.info() { printf '%s\n' "$*" >&2; }
bashio::log.debug() { printf '%s\n' "$*" >&2; }
bashio::log.notice() { printf '%s\n' "$*" >&2; }
bashio::config.true() { return 1; }
bashio::config.has_value() { return 0; }
bashio::config() {
    bashio::log.trace bashio::config "$TOKEN"
    if [ "$1" = run_parameters ]; then
        printf '%s\n' "--tag=$TOKEN" "--loglevel=$TOKEN"
    else
        printf '%s\n' "$TOKEN"
    fi
}
'''


def shell(script):
    result = subprocess.run(["bash", "-c", 'TOKEN="$1"; ' + script, "test", MARKER],
                            text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, "synthetic harness failed"
    assert MARKER not in result.stdout + result.stderr, "synthetic secret leaked"
    return result


def test_run_script_hides_arguments_but_preserves_execution():
    source = (ROOT / "run.sh").read_text()
    # Make marker checks false independently of host state, preserving source logic.
    source = source.replace("/tmp/webgui-", "/nonexistent-ha-test-root/webgui-")
    result = shell(STUB + r'''
CLOUDFLARED_TOKEN_FILE="$(mktemp -d)/tunnel-token"
exec() {
    [[ "$*" == *"--token-file=$CLOUDFLARED_TOKEN_FILE"* ]] || return 11
    [[ "$*" != *"--token=$TOKEN"* && " $* " != *" $TOKEN "* ]] || return 12
    [[ "$(<"$CLOUDFLARED_TOKEN_FILE")" = "$TOKEN" ]] || return 13
    printf 'execution-preserved\n'
}
''' + source)
    assert "execution-preserved" in result.stdout
    assert "Connecting Cloudflare Tunnel" in result.stderr


def prepare_definitions():
    return (ROOT / "etc/s6-overlay/s6-rc.d/prepare/run.sh").read_text().split(
        "# RUN LOGIC", 1)[0]


def test_prepare_log_level_keeps_value_without_logging_it():
    result = shell(STUB + prepare_definitions() + r'''
setCloudflaredLogLevel
[[ "$CLOUDFLARED_LOG" = "$TOKEN" ]] || exit 13
printf 'loglevel-preserved\n'
''')
    assert "loglevel-preserved" in result.stdout


def test_create_tunnel_never_dumps_credentials():
    shell(STUB + prepare_definitions() + r'''
data_path=/nonexistent-ha-test-root
tunnel_name=test
CLOUDFLARED_LOG=info
cloudflared() { return 0; }
hasTunnel() { return 0; }
cat() { printf '{"TunnelSecret":"%s"}\n' "$TOKEN"; }
createTunnel
''')


@pytest.mark.parametrize("relative", ["run.sh", "etc/s6-overlay/s6-rc.d/prepare/run.sh"])
def test_trace_discards_arguments_after_static_event_label(relative):
    source = (ROOT / relative).read_text()
    # Match the Bashio contract: a static event label followed by config values.
    start = source.index("bashio::log.trace() {")
    override = source[start:source.index("\n}", start) + 2]
    result = shell(STUB + override + '\nbashio::log.trace "bashio::config" "$TOKEN"\n')
    assert result.stderr.strip(), "trace diagnostics unexpectedly silent"
