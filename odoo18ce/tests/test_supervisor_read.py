#!/usr/bin/env python3
"""Static-tier contracts for the Supervisor read helper (issues #119, #108).

A bashio read at boot can come back empty for a moment — the Supervisor has
not answered yet, or a DHCP lease has not arrived — and bashio caches that
empty answer in a file for the container's lifetime. `supervisor-read.sh`
retries the read for a bounded time, flushing the cache keys behind it
between attempts, so one bad moment is not the whole start.

The helper is a bash function, so it is driven by bash: sourced into a shell
whose `bashio::*` functions are stubs, and observed through what it prints,
what it returns and which cache keys it flushed.
"""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import require_bash

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "rootfs/usr/local/lib/supervisor-read.sh"

# The stubs stand in for bashio. `bashio::cache.flush` records the key on
# stderr, prefixed so the test can pick those lines out of any other stderr.
STUBS = r"""
bashio::log.debug() { :; }
bashio::log.trace() { :; }
bashio::log.warning() { printf 'WARN %s\n' "$1" >&2; }
bashio::cache.flush() { printf 'FLUSH %s\n' "$1" >&2; }
# No real waiting, and no real clock: `sleep` advances a counter that the
# helper's clock reads, so a 30-second budget is a matter of counting and
# the test does not depend on how fast this host forks a subshell.
SLEPT="$(mktemp)"; printf '0' > "${SLEPT}"
sleep() { printf '%s' $(( $(cat "${SLEPT}") + $1 )) > "${SLEPT}"; }
woow::supervisor.now() { cat "${SLEPT}"; }
# A read the Supervisor API refuses: bashio logs the refusal and returns
# non-zero with nothing on stdout.
refused() { printf 'Failed to get addon info from Supervisor API\n' >&2; return 1; }
# A read that answers after N empty attempts. The command substitution the
# helper wraps the read in is a subshell, so the count lives in a file.
COUNTER="$(mktemp)"; printf '0' > "${COUNTER}"
read_after() {
    local after=$1 value=$2 n
    n=$(( $(cat "${COUNTER}") + 1 )); printf '%s' "${n}" > "${COUNTER}"
    if [ "${n}" -ge "${after}" ]; then printf '%s' "${value}"; fi
    return 0
}
# A read that answers with a placeholder until the N-th attempt: what the
# Supervisor says for a container whose network it has not seen yet.
placeholder_until() {
    local until=$1 placeholder=$2 value=$3 n
    n=$(( $(cat "${COUNTER}") + 1 )); printf '%s' "${n}" > "${COUNTER}"
    if [ "${n}" -ge "${until}" ]; then printf '%s' "${value}"; else printf '%s' "${placeholder}"; fi
}
# The two Canonical URL reads under the test's control: the address answers
# after N empty attempts; the port request fails N times, then answers
# (possibly empty: a port that is not published). The directory s6 hands
# services their environment from is a temporary one, removed on exit with
# the counters.
bashio::network.ipv4_address() {
    if [ "${LAN_REFUSED:-0}" = 1 ]; then refused; return; fi
    read_after "${LAN_AFTER:-1}" 192.0.2.10/24
}
PORT_COUNTER="$(mktemp)"; printf '0' > "${PORT_COUNTER}"
bashio::addon.port() {
    local n; n=$(( $(cat "${PORT_COUNTER}") + 1 )); printf '%s' "${n}" > "${PORT_COUNTER}"
    if [ "${n}" -lt "${PORT_OK_AFTER:-1}" ]; then
        printf 'Failed to get addon info from Supervisor API\n' >&2; return 1
    fi
    printf '%s' "${PORT_VALUE-8069}"
}
export WOOW_CONTAINER_ENV_DIR; WOOW_CONTAINER_ENV_DIR="$(mktemp -d)"
# Expanded now, so a test that points WOOW_CONTAINER_ENV_DIR elsewhere still
# leaves the directory mktemp made removed.
trap "rm -rf '${WOOW_CONTAINER_ENV_DIR}' '${COUNTER}' '${SLEPT}' '${PORT_COUNTER}'" EXIT
"""


def run_helper(script: str) -> subprocess.CompletedProcess:
    bash = require_bash()
    posix_helper = HELPER.as_posix()
    return subprocess.run(
        [bash, "-c", f'source "{posix_helper}"\n{STUBS}\n{script}'],
        capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )


def flushed(result: subprocess.CompletedProcess) -> list[str]:
    return [line[len("FLUSH "):] for line in result.stderr.splitlines()
            if line.startswith("FLUSH ")]


def test_a_value_on_the_first_read_is_returned_at_once_without_a_flush() -> None:
    result = run_helper(
        'woow::supervisor.read 30 2 "addons.self.ip_address addons.self.info" '
        'read_after 1 172.30.33.4; echo " rc=$?"'
    )
    assert result.stdout == "172.30.33.4 rc=0\n", result.stderr
    assert flushed(result) == []


def test_a_read_that_answers_after_empties_is_retried_with_the_cache_flushed() -> None:
    result = run_helper(
        'woow::supervisor.read 30 2 "addons.self.ip_address addons.self.info" '
        'read_after 3 172.30.33.4; echo " rc=$? attempts=$(cat "${COUNTER}") slept=$(cat "${SLEPT}")"'
    )
    assert result.stdout == "172.30.33.4 rc=0 attempts=3 slept=4\n", result.stderr
    # Both keys, before each of the two retries, the filtered key first so a
    # flush interrupted between the two never leaves a stale filtered value
    # in front of a fresh info.
    assert flushed(result) == ["addons.self.ip_address", "addons.self.info"] * 2


def test_an_exhausted_budget_prints_nothing_fails_and_leaves_no_empty_answer_cached() -> None:
    result = run_helper(
        'woow::supervisor.read 30 2 "network.interface.default.info.ipv4.address" '
        'read_after 999 never; echo "rc=$? attempts=$(cat "${COUNTER}") slept=$(cat "${SLEPT}")"'
    )
    stdout = result.stdout.strip()
    assert stdout.startswith("rc=1 "), result.stderr
    fields = dict(part.split("=") for part in stdout.split())
    attempts, waited = int(fields["attempts"]), int(fields["slept"])
    assert attempts == 17, "one read every two seconds until the clock is past thirty"
    assert waited == 32, "never shorter than the budget, at most one poll longer"
    # The last empty answer is flushed too: nothing this helper gave up on
    # is left in bashio's cache for the next reader in this container.
    assert flushed(result) == ["network.interface.default.info.ipv4.address"] * attempts
    assert "WARN" not in result.stderr, "an answer that never came is not an error to log"


def test_a_read_the_supervisor_refuses_is_named_when_the_budget_runs_out() -> None:
    result = run_helper(
        'woow::supervisor.read 30 2 "addons.self.ip_address addons.self.info" '
        'refused; echo "rc=$?"'
    )
    assert result.stdout.strip() == "rc=1"
    warnings = [l for l in result.stderr.splitlines() if l.startswith("WARN ")]
    assert len(warnings) == 1, result.stderr
    assert "refused" in warnings[0] and "Failed to get addon info from Supervisor API" in warnings[0]


@pytest.mark.parametrize("placeholder", ["0.0.0.0", "null"])
def test_the_supervisor_placeholder_address_counts_as_not_yet(placeholder) -> None:
    # supervisor/docker/app.py answers `0.0.0.0` for a container whose
    # network it has not loaded; a jq `// empty` on a missing key is `null`.
    result = run_helper(
        'woow::supervisor.read 30 2 "addons.self.ip_address addons.self.info" '
        f'placeholder_until 3 {placeholder} 172.30.33.4; echo " rc=$? attempts=$(cat "${{COUNTER}}")"'
    )
    assert result.stdout == "172.30.33.4 rc=0 attempts=3\n", result.stderr
    assert flushed(result) == ["addons.self.ip_address", "addons.self.info"] * 2


def test_the_helper_is_readable_in_the_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "chmod a+r /usr/local/lib/supervisor-read.sh" in dockerfile


def test_the_helper_is_in_the_shellcheck_gate() -> None:
    ci = (ROOT.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'rootfs/usr/local/lib/supervisor-read.sh"' in ci.split("shellcheck -s bash", 1)[0]


# --- a read whose empty answer is final --------------------------------------

def test_read_until_ok_retries_a_failed_request_and_accepts_an_empty_answer() -> None:
    result = run_helper(
        'PORT_OK_AFTER=3 PORT_VALUE=""; '
        'v="$(woow::supervisor.read_until_ok 30 2 "addons.self.network.8069-tcp addons.self.info" '
        'bashio::addon.port 8069)"; echo "rc=$? value=[${v}] attempts=$(cat "${PORT_COUNTER}")"'
    )
    assert result.stdout.strip() == "rc=0 value=[] attempts=3", result.stderr
    assert flushed(result) == [], "bashio caches only a request that succeeded; nothing to flush"
    assert "WARN" not in result.stderr


def test_read_until_ok_gives_up_and_names_the_refusal() -> None:
    result = run_helper(
        'PORT_OK_AFTER=999; '
        'v="$(woow::supervisor.read_until_ok 30 2 "addons.self.network.8069-tcp addons.self.info" '
        'bashio::addon.port 8069)"; echo "rc=$? value=[${v}] attempts=$(cat "${PORT_COUNTER}")"'
    )
    assert result.stdout.strip() == "rc=1 value=[] attempts=17", result.stderr
    warnings = [l for l in result.stderr.splitlines() if l.startswith("WARN ")]
    assert len(warnings) == 1 and "Failed to get addon info" in warnings[0]


# --- the Canonical URL inputs, settled once per start ------------------------
# cont-init settles the host's LAN address and the published port for the
# Canonical URL and publishes them to the container environment; the
# maintenance bootstrap reads them from there (issue #108, ADR 0006: one value
# per start, derived once).

def published(result: subprocess.CompletedProcess) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for line in result.stdout.splitlines():
        if line.startswith("PUBLISHED "):
            name, _, value = line[len("PUBLISHED "):].partition("=")
            out[name] = None if value == "<none>" else value
    return out


SETTLE = (
    'woow::supervisor.settle_canonical_inputs; rc=$?; '
    'echo "ipv4=[${WOOW_LAN_IPV4}] port=[${WOOW_LAN_PORT}] rc=${rc} '
    'attempts=$(cat "${COUNTER}") slept=$(cat "${SLEPT}")"; '
    'echo "PORT_ATTEMPTS=$(cat "${PORT_COUNTER}")"; '
    'for n in WOOW_LAN_IPV4 WOOW_LAN_PORT WOOW_CANONICAL_SETTLED; do '
    'f="${WOOW_CONTAINER_ENV_DIR}/${n}"; '
    'if [ -e "$f" ]; then echo "PUBLISHED ${n}=$(cat "$f")"; else echo "PUBLISHED ${n}=<none>"; fi; done'
)


def test_a_lan_address_that_arrives_late_is_settled_once_and_published() -> None:
    result = run_helper("LAN_AFTER=3; " + SETTLE)
    assert "ipv4=[192.0.2.10/24] port=[8069] rc=0 attempts=3 slept=4" in result.stdout, result.stderr
    assert published(result) == {
        "WOOW_LAN_IPV4": "192.0.2.10/24", "WOOW_LAN_PORT": "8069", "WOOW_CANONICAL_SETTLED": "1",
    }
    assert flushed(result) == [
        "network.interface.default.info.ipv4.address", "network.interface.default.info",
    ] * 2
    assert "WARN" not in result.stderr


def test_a_lan_address_that_never_arrives_is_one_warning_and_a_settled_empty_publication() -> None:
    result = run_helper("LAN_AFTER=999; " + SETTLE)
    assert "ipv4=[] port=[8069] rc=1 attempts=17 slept=32" in result.stdout, result.stderr
    # The marker is what tells the bootstrap not to ask again: to s6-envdir an
    # empty file is an unset variable, so the empty value alone would not.
    assert published(result) == {
        "WOOW_LAN_IPV4": "", "WOOW_LAN_PORT": "8069", "WOOW_CANONICAL_SETTLED": "1",
    }
    warnings = [l for l in result.stderr.splitlines() if l.startswith("WARN ")]
    assert len(warnings) == 1 and "30 seconds" in warnings[0] and "LAN" in warnings[0], result.stderr


def test_the_inputs_on_the_first_read_cost_no_wait() -> None:
    result = run_helper("LAN_AFTER=1; " + SETTLE)
    assert "ipv4=[192.0.2.10/24] port=[8069] rc=0 attempts=1 slept=0" in result.stdout, result.stderr
    assert published(result)["WOOW_CANONICAL_SETTLED"] == "1"
    assert flushed(result) == [] and "WARN" not in result.stderr


def test_an_unpublished_port_is_settled_as_empty_without_waiting() -> None:
    result = run_helper('LAN_AFTER=1 PORT_VALUE=""; ' + SETTLE)
    assert "ipv4=[192.0.2.10/24] port=[] rc=0 attempts=1 slept=0" in result.stdout, result.stderr
    assert published(result)["WOOW_LAN_PORT"] == ""


def test_a_supervisor_that_cannot_be_asked_costs_one_budget_not_two() -> None:
    # Both reads fail throughout (no hassio_api, no token, Supervisor down).
    # The address spends the budget; the port gets what is left of it.
    result = run_helper('LAN_REFUSED=1 PORT_OK_AFTER=999; ' + SETTLE)
    assert "ipv4=[] port=[] rc=1" in result.stdout, result.stderr
    fields = dict(part.split("=") for part in result.stdout.splitlines()[0].split() if "=" in part)
    assert int(fields["slept"]) == 32, "one shared budget, at most one poll over, not two budgets"
    assert published(result)["WOOW_CANONICAL_SETTLED"] == "1"
    port_attempts = int(result.stdout.split("PORT_ATTEMPTS=", 1)[1].split()[0])
    assert port_attempts == 1, "a spent budget is one attempt for the port, no poll"
    warnings = [l for l in result.stderr.splitlines() if l.startswith("WARN ")]
    # The address refusal, the no-address line, the port refusal: each once.
    assert len(warnings) == 3, result.stderr
    assert sum("Failed to get addon info" in w for w in warnings) == 2


def test_the_budget_is_owned_by_the_helper() -> None:
    result = run_helper('echo "${WOOW_SUPERVISOR_BUDGET} ${WOOW_SUPERVISOR_POLL}"')
    assert result.stdout.strip() == "30 2", "the #108 decision, in one place"


def test_a_publication_that_fails_is_one_warning_and_the_values_still_come_back() -> None:
    # A file where the directory should be: mkdir -p fails on it. The trap
    # still removes the directory mktemp made, because it was expanded then.
    result = run_helper(
        'LAN_AFTER=1; : > "${WOOW_CONTAINER_ENV_DIR}/blocked"; '
        'WOOW_CONTAINER_ENV_DIR="${WOOW_CONTAINER_ENV_DIR}/blocked/env"; ' + SETTLE
    )
    # Both sides end equal: nothing published, and nothing kept here either.
    assert "ipv4=[] port=[] rc=1" in result.stdout, result.stderr
    warnings = [l for l in result.stderr.splitlines() if l.startswith("WARN ")]
    assert len(warnings) == 1 and "could not be published" in warnings[0]


@pytest.mark.skipif(os.name == "nt", reason="file modes are not POSIX on Windows")
def test_a_published_value_is_readable_by_every_service_whatever_the_umask() -> None:
    result = run_helper(
        'umask 077; woow::supervisor.publish WOOW_LAN_IPV4 x; '
        'stat -c %a "${WOOW_CONTAINER_ENV_DIR}/WOOW_LAN_IPV4"'
    )
    assert result.stdout.strip() == "644", result.stderr
