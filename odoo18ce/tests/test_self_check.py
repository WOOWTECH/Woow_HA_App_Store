#!/usr/bin/env python3
"""Static-tier contracts for the start-time self-check (issue #79, ADR 0005).

The add-on requests its own database-manager route the way the Cloudflare
tunnel does and refuses to start on anything but the restricted tier's
answer: `404` with `public_url`, the deny status without it.

`self_check_verdict` is the table. `probe` is driven against a real socket
on loopback -- in the container it is the add-on-network address, which a
test host does not have. `main` is driven with a fake prober and notifier.
The service scripts are read as text, the way `test_rewrite_service.py`
reads the Rewrite scan's.
"""
import http.server
import importlib.machinery
import importlib.util
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "rootfs/usr/local/lib"
SERVICE_DIR = ROOT / "rootfs/etc/services.d/self-check"
CONFIG_SCRIPT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
DOCKERFILE = ROOT / "Dockerfile"


def load_module(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = load_module(LIB_DIR / "rewrite_scan.py", "rewrite_scan")
gate = load_module(LIB_DIR / "literal_rewrite_gate.py", "literal_rewrite_gate")
apply = load_module(LIB_DIR / "rewrite_apply.py", "rewrite_apply")
check = load_module(LIB_DIR / "self_check.py", "self_check")

# Documentation names only; no real host here.
ADDRESS = "172.30.33.4"
PUBLIC_URL = "https://odoo-test.invalid"
PUBLIC_HOST = "odoo-test.invalid"


def code_of(script: Path) -> str:
    """A shell script with its comments dropped."""
    return "\n".join(
        line for line in script.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


# --- the verdict --------------------------------------------------------------

@pytest.mark.parametrize(("status", "public_url_set", "passes"), [
    (404, True, True),       # public shape: the route is closed to the tunnel
    (503, False, True),      # no public_url: every off-LAN caller is denied
    (200, True, False),      # the database manager, reached from the tunnel's path
    (200, False, False),
    (500, True, False),      # a gateway that is not serving
    (502, True, False),
    (502, False, False),
    (None, True, False),     # no answer: nginx's 444, or no listener
    (None, False, False),
    (404, False, False),     # the public shape on an install that has none
    (503, True, False),      # the deny status on an install that has a public_url
])
def test_self_check_verdict(status, public_url_set, passes) -> None:
    assert check.self_check_verdict(status, public_url_set) is passes


def test_the_expected_statuses_are_the_ones_the_gateway_is_rendered_with() -> None:
    """The verdict's two passing statuses are the template's, not copies
    that could drift: the deny status without public_url, and the 404 the
    database route gives every caller that is not LAN tier.
    """
    script = CONFIG_SCRIPT.read_text(encoding="utf-8")
    assert f"DENY_STATUS='{check.DENY_STATUS}'" in script
    template = TEMPLATE.read_text(encoding="utf-8")
    database_route = template.split("location ^~ /web/database/", 1)[1].split("}", 1)[0]
    assert f'if ($woow_origin_gate != "lan") {{ return {check.PUBLIC_STATUS}; ' in database_route
    assert check.ROUTE.startswith("/web/database/")


@pytest.mark.parametrize(("public_url", "host"), [
    ("", ""),
    ("https://odoo-test.invalid", "odoo-test.invalid"),
    ("https://odoo-test.invalid/", "odoo-test.invalid"),
    ("https://odoo-test.invalid:8443/odoo", "odoo-test.invalid:8443"),
])
def test_public_host_is_cut_the_way_the_gateway_map_is(public_url, host) -> None:
    assert check.public_host(public_url) == host


# --- the request --------------------------------------------------------------

class Server:
    """A listener on loopback that answers the way it is told to."""

    def __init__(self, status=None):
        seen = self.seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - the stdlib's name
                seen.append((self.path, self.headers.get("Host"), self.client_address[0]))
                if status is None:
                    # nginx's 444: close the connection without a response.
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.mark.parametrize("status", [404, 503, 200, 502])
def test_probe_returns_the_status_of_the_route(status) -> None:
    server = Server(status)
    try:
        assert check.probe("127.0.0.1", PUBLIC_HOST, port=server.port) == status
    finally:
        server.close()
    assert server.seen == [(check.ROUTE, PUBLIC_HOST, "127.0.0.1")]


def test_probe_without_a_public_host_sends_the_address_as_host() -> None:
    server = Server(503)
    try:
        check.probe("127.0.0.1", "", port=server.port)
    finally:
        server.close()
    assert server.seen[0][1] == "127.0.0.1"


def test_a_connection_closed_without_a_response_is_no_answer() -> None:
    server = Server(None)
    try:
        assert check.probe("127.0.0.1", PUBLIC_HOST, port=server.port) is None
    finally:
        server.close()


def test_a_refused_connection_is_no_answer() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert check.probe("127.0.0.1", PUBLIC_HOST, port=port, timeout=2) is None


def test_a_silent_listener_is_no_answer() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert check.probe("127.0.0.1", PUBLIC_HOST, port=port, timeout=0.5) is None


def test_a_host_http_client_cannot_encode_is_no_answer() -> None:
    """An internationalised public_url host is not latin-1; that is a failed
    check to report, not a traceback that skips the notification."""
    server = Server(404)
    try:
        assert check.probe("127.0.0.1", "商店.invalid", port=server.port) is None
    finally:
        server.close()
    assert server.seen == [], "the request was never sent"


# --- the command --------------------------------------------------------------

class Recorder:
    def __init__(self, answer=None):
        self.answer = answer
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.answer


def run(argv, status):
    prober = Recorder(status)
    notifier = Recorder(True)
    lines, logged = [], []
    code = check.main(argv, prober=prober, notifier=notifier, out=lines.append, log=logged.append)
    return code, prober, notifier, lines


def test_a_pass_is_one_info_line_and_nothing_else() -> None:
    code, prober, notifier, lines = run(["--address", ADDRESS, "--public-url", PUBLIC_URL], 404)
    assert code == 0
    assert prober.calls == [((ADDRESS, PUBLIC_HOST), {"port": check.ORIGIN_PORT})]
    assert notifier.calls == []
    assert len(lines) == 1
    assert "404" in lines[0] and check.ROUTE in lines[0]


def test_a_pass_without_public_url_expects_the_deny_status() -> None:
    code, prober, notifier, lines = run(["--address", ADDRESS], 503)
    assert code == 0
    assert prober.calls == [((ADDRESS, ""), {"port": check.ORIGIN_PORT})]
    assert notifier.calls == []
    assert len(lines) == 1


@pytest.mark.parametrize(("argv", "status", "shown"), [
    (["--address", ADDRESS, "--public-url", PUBLIC_URL], 200, "200"),
    (["--address", ADDRESS, "--public-url", PUBLIC_URL], None, "no answer"),
    (["--address", ADDRESS], 502, "502"),
    (["--address", ADDRESS], 404, "404"),
])
def test_a_fail_names_the_status_and_the_route_and_notifies(argv, status, shown) -> None:
    code, _, notifier, lines = run(argv, status)
    assert code == 1
    assert len(lines) == 1
    assert shown in lines[0] and check.ROUTE in lines[0]
    assert len(notifier.calls) == 1
    (note,), keywords = notifier.calls[0]
    title, body = note
    assert "self-check failed" in title
    assert shown in body and check.ROUTE in body
    assert keywords["notification_id"] == check.NOTIFICATION_ID
    assert keywords["source"] == "Self-check"


@pytest.mark.parametrize("address", ["", "0.0.0.0", "127.0.0.1", "::1"])
def test_no_address_from_the_supervisor_fails_without_touching_loopback(address) -> None:
    # Empty is what a bashio read gives; `0.0.0.0` is the Supervisor's own
    # "not yet" for a container it has not seen on the network. Both, and
    # anything loopback, reach the same branch: LAN tier, never requested.
    code, prober, notifier, lines = run(["--address", address, "--public-url", PUBLIC_URL], 404)
    assert code == 1
    assert prober.calls == []
    assert "no answer" in lines[0] and "loopback" in lines[0]
    assert len(notifier.calls) == 1


def test_a_notifier_that_raises_still_fails_the_check() -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    logged = []
    code = check.main(["--address", ADDRESS], prober=Recorder(200), notifier=broken,
                      out=lambda _: None, log=logged.append)
    assert code == 1
    assert any("boom" in line for line in logged)


def test_the_notification_goes_through_the_rewrite_scan_adapter(monkeypatch) -> None:
    """The failure notification is #78's, not a second Supervisor client,
    and its log lines name the self-check rather than the Rewrite scan.
    Without a token the adapter says so instead of calling out."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    logged = []
    code = check.main(["--address", ADDRESS], prober=Recorder(200),
                      out=lambda _: None, log=logged.append)
    assert code == 1
    assert logged == ["Self-check: no SUPERVISOR_TOKEN, so the notification was not sent"]


# --- the service --------------------------------------------------------------

def test_the_service_sources_the_check_from_the_supervisor_address() -> None:
    run_script = code_of(SERVICE_DIR / "run")
    assert 'ADDRESS="$(woow::supervisor.read "${SUPERVISOR_BUDGET}" "${SUPERVISOR_POLL}"' in run_script
    assert '"addons.self.ip_address addons.self.info" bashio::addon.ip_address' in run_script
    # After the nginx wait, not before it: the Supervisor gets the whole Odoo
    # boot to learn the address before any of the budget is spent.
    assert run_script.index("woow::supervisor.read") > run_script.index("http://127.0.0.1:8069/")
    call = run_script.split("self_check.py", 1)[1].split(")", 1)[0]
    assert '--address "${ADDRESS}"' in call
    assert "127.0.0.1" not in call
    assert '--public-url "${PUBLIC_URL}"' in call


def test_the_service_waits_for_nginx_before_the_check() -> None:
    run_script = code_of(SERVICE_DIR / "run")
    assert "SECONDS + 600" in run_script, "the wait is bounded by the clock"
    wait = run_script.index("http://127.0.0.1:8069/")
    assert wait < run_script.index("self_check.py")


def test_the_service_sleeps_on_pass_and_exits_on_fail() -> None:
    run_script = code_of(SERVICE_DIR / "run")
    after = run_script.split("self_check.py", 1)[1]
    assert "exec sleep infinity" in after
    assert after.rstrip().endswith("exit 1")


def test_a_failed_check_stops_the_container() -> None:
    finish = code_of(SERVICE_DIR / "finish")
    assert "exec /run/s6/basedir/bin/halt" in finish


def test_the_module_is_readable_in_the_image() -> None:
    assert "chmod a+r /usr/local/lib/self_check.py" in DOCKERFILE.read_text(encoding="utf-8")


# --- the service, driven ------------------------------------------------------
# The script is run by bash with bashio, curl, python3 and sleep stubbed. A
# stub `sleep` advances bash's SECONDS instead of waiting, so the 30-second
# budget passes in no time; the `sleep infinity` a pass ends in is an `exec`,
# which bypasses functions, so a no-op `sleep` executable is put on PATH.

import os
import subprocess
import tempfile

from conftest import require_bash

SERVICE_STUBS = r"""
LOG="$1"; ARGS="$2"; ANSWER_AFTER="$3"; VERDICT="$4"; COUNTER="$5"
bashio::log.info()    { printf 'INFO %s\n'  "$1" >> "${LOG}"; }
bashio::log.warning() { printf 'WARN %s\n'  "$1" >> "${LOG}"; }
bashio::log.error()   { printf 'ERROR %s\n' "$1" >> "${LOG}"; }
bashio::log.debug()   { printf 'DEBUG %s\n' "$1" >> "${LOG}"; }
bashio::log.trace()   { :; }
bashio::cache.flush() { printf 'FLUSH %s\n' "$1" >> "${LOG}"; }
bashio::config.has_value() { [ "$1" = public_url ]; }
bashio::config() { printf 'https://odoo-test.invalid'; }
bashio::addon.ip_address() {
    local n; n=$(( $(cat "${COUNTER}") + 1 )); printf '%s' "${n}" > "${COUNTER}"
    if [ "${n}" -ge "${ANSWER_AFTER}" ]; then printf '172.30.33.4'; fi
}
curl() { return 0; }
python3() { printf '%s\n' "$@" > "${ARGS}"; printf 'verdict line'; return "${VERDICT}"; }
sleep() { SECONDS=$((SECONDS + ${1%.*})); }
woow::supervisor.now() { printf '%s' "${SECONDS}"; }
"""


def drive_service(answer_after: int, verdict: int = 0,
                  lib_dir: Path = LIB_DIR) -> tuple[int, list[str], list[str], int]:
    """Run services.d/self-check/run; return exit code, log lines, python3 argv, reads."""
    bash = require_bash()
    with tempfile.TemporaryDirectory() as tmp:
        fake_bin = Path(tmp) / "bin"
        fake_bin.mkdir()
        (fake_bin / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake_bin / "sleep").chmod(0o755)
        log, args, counter = Path(tmp) / "log", Path(tmp) / "args", Path(tmp) / "reads"
        log.touch()
        args.touch()
        counter.write_text("0", encoding="utf-8")
        # The script ends in `exec` or `exit`, so nothing after `source` runs;
        # everything observed is written by the stubs as they go.
        script = (
            f'set -- "{log.as_posix()}" "{args.as_posix()}" {answer_after} {verdict} '
            f'"{counter.as_posix()}"\n'
            f"{SERVICE_STUBS}\n"
            f'source "{(SERVICE_DIR / "run").as_posix()}"\n'
        )
        env = dict(os.environ, PATH=f"{fake_bin.as_posix()}{os.pathsep}{os.environ['PATH']}",
                   WOOW_LIB_DIR=lib_dir.as_posix())
        result = subprocess.run([bash, "-c", script], capture_output=True,
                                encoding="utf-8", errors="replace",
                                timeout=60, env=env)
        lines = log.read_text(encoding="utf-8").splitlines()
        reads = int(counter.read_text(encoding="utf-8"))
        return result.returncode, lines, args.read_text(encoding="utf-8").split(), reads


def test_the_service_waits_for_the_supervisor_address_and_then_checks_once() -> None:
    code, lines, argv, reads = drive_service(answer_after=3)
    assert code == 0, lines
    assert reads == 3
    assert argv[argv.index("--address") + 1] == "172.30.33.4"
    assert [l for l in lines if l.startswith("FLUSH ")] == \
        ["FLUSH addons.self.ip_address", "FLUSH addons.self.info"] * 2
    assert [l for l in lines if l.startswith("INFO ")] == ["INFO verdict line"], \
        "on pass, one info line from the service and nothing else"


def test_an_address_that_never_comes_is_named_once_and_still_refused() -> None:
    code, lines, argv, reads = drive_service(answer_after=999, verdict=1)
    assert code == 1
    assert argv[argv.index("--address") + 1] == "--public-url", "an empty address is handed on, not loopback"
    waited = [l for l in lines if l.startswith("WARN ") and "30 seconds" in l]
    # The 30 comes from the helper's default, sourced by the script.
    assert len(waited) == 1, lines
    assert "no add-on address" in waited[0]
    assert 2 <= reads <= 20, "bounded by the budget, not by a count"
    assert lines[-1] == "ERROR verdict line"


def test_an_address_on_the_first_read_costs_no_wait_and_no_extra_line() -> None:
    code, lines, argv, reads = drive_service(answer_after=1)
    assert code == 0
    assert reads == 1
    assert [l for l in lines if l.startswith(("FLUSH ", "WARN "))] == []
    assert [l for l in lines if l.startswith("INFO ")] == ["INFO verdict line"]


def test_a_missing_helper_stops_the_service_with_the_cause_and_no_check() -> None:
    with tempfile.TemporaryDirectory() as empty:
        code, lines, argv, reads = drive_service(answer_after=1, lib_dir=Path(empty))
    assert code == 1
    assert reads == 0 and argv == [], "nothing was asked and nothing was checked"
    assert lines[-1].startswith("ERROR ") and "supervisor-read.sh" in lines[-1]


def test_the_budget_is_one_number_in_the_service() -> None:
    run_script = code_of(SERVICE_DIR / "run")
    assert 'SUPERVISOR_BUDGET="${WOOW_SUPERVISOR_BUDGET}"' in run_script, "the helper owns the number"
    assert 'SUPERVISOR_POLL="${WOOW_SUPERVISOR_POLL}"' in run_script
    assert "after waiting at least ${SUPERVISOR_BUDGET} seconds" in run_script
    assert "30 seconds" not in run_script, "the message and the call share the number"
