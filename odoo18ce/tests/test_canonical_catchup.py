#!/usr/bin/env python3
"""Static-tier contracts for the Canonical URL catch-up (issue #164).

The maintenance bootstrap mirrors the Canonical URL into the default
website's ``domain`` once per start, and only when the ``website`` module is
already installed. A ``website`` installed later through the Apps screen had
no domain until the next restart, so under Ingress the home page's
canonical and ``og:`` links carried the Home Assistant address (P-5, U-D8).

The catch-up is a second step of the Rewrite scan service's round. Its
decision is a pure function driven here with a fake query runner, in the
style of ``test_rewrite_scan.py``; the writer is the maintenance library
through ``odoo shell``, stubbed here; and the service script is driven by
bash with bashio stubbed, the way ``test_self_check.py`` drives its service.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import require_bash

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "rootfs/usr/local/lib"
SERVICES_DIR = ROOT / "rootfs/etc/services.d"
RUN = SERVICES_DIR / "rewrite-scan/run"
CLI = ROOT / "rootfs/usr/local/bin/odoo-canonical-catchup"
BOOTSTRAP = ROOT / "rootfs/usr/local/bin/odoo-maintenance-bootstrap"
DOCKERFILE = ROOT / "Dockerfile"
DOCS = ROOT / "DOCS.md"
CONTEXT = ROOT.parent / "CONTEXT.md"
PARITY_PLAN = ROOT.parent / "docs/testing/INGRESS_VS_PUBLIC_PARITY.md"


def load_module(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = load_module(LIB_DIR / "rewrite_scan.py", "rewrite_scan")
catchup = load_module(LIB_DIR / "canonical_catchup.py", "canonical_catchup")

# Documentation names and addresses only (RFC 2606); no real host here.
CANONICAL = "https://odoo.example.test"
DB = "odoo_test"
OTHER_DB = "odoo_other"
FRESH_DB = "odoo_fresh"
TOKEN = "01H8XGJWBWBAQ4TK1Z9MY3MNFW"


def fake_runner(websites, odoo=None, no_website_table=(), fail=(), list_error=None):
    """A stand-in for `psql`.

    `websites` maps a database to the default website's domain, or to None
    for a database whose `website` table holds no record. `no_website_table`
    names the databases without the module; `fail` the ones whose domain
    read raises; `list_error` makes the listing itself raise.
    """
    odoo = set(websites if odoo is None else odoo)
    calls: list = []

    def run_query(database, sql):
        calls.append((database, sql))
        if database is None:
            if list_error:
                raise RuntimeError(list_error)
            return "".join(name + scan.RECORD_SEPARATOR for name in sorted(websites))
        if sql == scan.IS_ODOO_SQL:
            return ("t" if database in odoo else "f") + scan.RECORD_SEPARATOR
        if sql == catchup.HAS_WEBSITE_SQL:
            return ("f" if database in no_website_table else "t") + scan.RECORD_SEPARATOR
        assert sql == catchup.DEFAULT_WEBSITE_DOMAIN_SQL, sql
        if database in fail:
            raise RuntimeError(f"psql: {database}: connection failed")
        domain = websites[database]
        if domain is None:
            return ""
        return "1" + scan.FIELD_SEPARATOR + domain + scan.RECORD_SEPARATOR

    run_query.calls = calls
    return run_query


class FakeShell:
    """A stand-in for `odoo shell` piping the maintenance library."""

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.calls: list = []

    def __call__(self, database, conf, environment):
        self.calls.append((database, conf, dict(environment)))
        if database in self.failing:
            return subprocess.CompletedProcess(
                ["odoo", "shell"], 1, "", "Traceback (most recent call last):\nKeyError: 'boom'\n"
            )
        line = (f"maintenance db={database}: web.base.url={CANONICAL} "
                f"web.base.url.freeze=True website.domain={CANONICAL}\n")
        return subprocess.CompletedProcess(["odoo", "shell"], 0, line, "")


def verdicts(plan) -> dict:
    return {verdict.database: (verdict.action, verdict.reason) for verdict in plan.verdicts}


# --- the decision, pure -------------------------------------------------------

@pytest.mark.parametrize("domain", ["", "   ", "/"])
def test_an_empty_domain_needs_a_catch_up(domain) -> None:
    needed, _ = catchup.needs_catchup(domain, CANONICAL)
    assert needed


def test_no_website_record_needs_none() -> None:
    """Nothing to write over, and a registry load every round would say so at cost."""
    needed, reason = catchup.needs_catchup(None, CANONICAL)
    assert not needed and reason == "no website record"


@pytest.mark.parametrize("domain", [CANONICAL, CANONICAL + "/", " " + CANONICAL + " "])
def test_a_domain_equal_to_the_canonical_url_needs_none(domain) -> None:
    needed, reason = catchup.needs_catchup(domain, CANONICAL)
    assert not needed
    assert "already" in reason


def test_the_canonical_url_is_compared_without_its_trailing_slash() -> None:
    assert not catchup.needs_catchup(CANONICAL, CANONICAL + "/")[0]


@pytest.mark.parametrize("domain", ["https://other.example.test", "http://localhost:8070"])
def test_a_different_domain_needs_a_catch_up(domain) -> None:
    needed, reason = catchup.needs_catchup(domain, CANONICAL)
    assert needed
    assert domain not in reason, "the stored value could carry a token; the reason never repeats it"


# --- the plan, over the cluster -----------------------------------------------

def test_a_database_without_the_website_table_is_skipped_without_reading_a_domain() -> None:
    run_query = fake_runner({DB: ""}, no_website_table={DB})
    plan = catchup.plan(run_query, CANONICAL)
    assert verdicts(plan) == {DB: (catchup.ACTION_SKIP, "website module not installed")}
    assert not [sql for _, sql in run_query.calls if sql == catchup.DEFAULT_WEBSITE_DOMAIN_SQL]


def test_a_database_whose_website_table_holds_no_record_is_skipped() -> None:
    plan = catchup.plan(fake_runner({DB: None}), CANONICAL)
    assert verdicts(plan) == {DB: (catchup.ACTION_SKIP, "no website record")}


def test_an_empty_domain_is_caught_up_and_a_matching_one_is_not() -> None:
    plan = catchup.plan(
        fake_runner({DB: "", OTHER_DB: CANONICAL, FRESH_DB: CANONICAL + "/"}), CANONICAL
    )
    assert verdicts(plan)[DB][0] == catchup.ACTION_CATCH_UP
    assert verdicts(plan)[OTHER_DB][0] == catchup.ACTION_SKIP
    assert verdicts(plan)[FRESH_DB][0] == catchup.ACTION_SKIP
    assert plan.due == (DB,)


def test_a_different_domain_is_caught_up() -> None:
    plan = catchup.plan(fake_runner({DB: "https://old.example.test"}), CANONICAL)
    assert plan.due == (DB,)


def test_a_database_that_is_not_odoo_is_never_probed() -> None:
    run_query = fake_runner({DB: "", "not_odoo": ""}, odoo={DB})
    plan = catchup.plan(run_query, CANONICAL)
    assert set(verdicts(plan)) == {DB}
    assert not [d for d, sql in run_query.calls if d == "not_odoo" and sql != scan.IS_ODOO_SQL]


def test_a_psql_failure_on_one_database_fails_that_one_and_the_others_proceed() -> None:
    plan = catchup.plan(
        fake_runner({DB: "", OTHER_DB: "", FRESH_DB: CANONICAL}, fail={DB}), CANONICAL
    )
    assert verdicts(plan)[DB][0] == catchup.ACTION_FAILED
    assert "connection failed" in verdicts(plan)[DB][1]
    assert plan.due == (OTHER_DB,)
    assert plan.failed == (DB,)


def test_a_listing_that_fails_is_reported_and_nothing_is_due() -> None:
    plan = catchup.plan(
        fake_runner({DB: ""}, list_error="the cluster is not accepting connections"), CANONICAL
    )
    assert plan.verdicts == ()
    assert plan.due == ()
    assert "not accepting connections" in plan.error


def test_the_plan_reuses_the_scans_database_listing() -> None:
    run_query = fake_runner({DB: CANONICAL})
    catchup.plan(run_query, CANONICAL)
    assert (None, scan.DATABASE_LIST_SQL) in run_query.calls
    assert (DB, scan.IS_ODOO_SQL) in run_query.calls


def test_the_query_picks_the_record_the_maintenance_library_writes() -> None:
    """The SQL re-states the library's ORM choice; this pins the two together.

    `apply()` writes `website.default_website` and falls back to the lowest
    id. A read that picked a different record would decide from one
    website's domain and write another's, every round.
    """
    library = (LIB_DIR / "odoo-maintenance.py").read_text(encoding="utf-8")
    assert 'env.ref("website.default_website"' in library
    assert 'search([], order="id", limit=1)' in library
    sql = catchup.DEFAULT_WEBSITE_DOMAIN_SQL
    assert "d.module = 'website' AND d.name = 'default_website'" in sql
    assert "ORDER BY d.id IS NULL, w.id" in sql and "LIMIT 1" in sql


# --- the step, end to end with the writer stubbed -----------------------------

def run_main(run_query, shell=None, canonical=CANONICAL, conf="/data/odoo.conf"):
    shell = shell if shell is not None else FakeShell()
    lines: list = []
    code = catchup.main(["--conf", conf], run_query=run_query, run_shell=shell,
                        canonical=canonical, out=lines.append)
    return code, lines, shell


def test_no_canonical_url_this_start_means_no_read_no_write_and_no_line() -> None:
    run_query = fake_runner({DB: ""})
    code, lines, shell = run_main(run_query, canonical=None)
    assert code == 0
    assert lines == [], "the unprotected case must not log every round"
    assert run_query.calls == []
    assert shell.calls == []


def test_a_steady_state_round_runs_no_odoo_shell_and_prints_nothing() -> None:
    code, lines, shell = run_main(fake_runner({DB: CANONICAL, OTHER_DB: CANONICAL + "/"}))
    assert code == 0
    assert shell.calls == []
    assert lines == []


def test_a_database_that_needs_it_is_written_through_the_maintenance_library() -> None:
    code, lines, shell = run_main(fake_runner({DB: "", OTHER_DB: CANONICAL}), conf="/tmp/odoo.conf")
    assert code == 0
    assert [call[0] for call in shell.calls] == [DB]
    database, conf, environment = shell.calls[0]
    assert conf == "/tmp/odoo.conf"
    assert environment["ODOO_MAINT_DB"] == DB, "the library reads the name for its log line"
    # One line per catch-up, in the bootstrap's shape, naming the value written.
    assert lines == [f"maintenance db={DB}: web.base.url={CANONICAL} "
                     f"web.base.url.freeze=True website.domain={CANONICAL}"]


def test_a_failed_odoo_shell_is_a_warning_and_the_others_still_run() -> None:
    shell = FakeShell(failing={DB})
    code, lines, shell = run_main(fake_runner({DB: "", OTHER_DB: ""}), shell=shell)
    assert code == 1
    assert sorted(call[0] for call in shell.calls) == sorted([DB, OTHER_DB])
    warning = [line for line in lines if "WARNING" in line]
    assert len(warning) == 1 and f"maintenance db={DB}:" in warning[0]
    assert "KeyError" in warning[0], "the last line of the traceback names the cause"
    assert any(f"maintenance db={OTHER_DB}: " in line and "WARNING" not in line for line in lines)


def test_a_failed_psql_read_is_a_warning_and_exits_non_zero() -> None:
    code, lines, shell = run_main(fake_runner({DB: "", OTHER_DB: ""}, fail={DB}))
    assert code == 1
    assert [call[0] for call in shell.calls] == [OTHER_DB]
    assert any("WARNING" in line and f"maintenance db={DB}:" in line for line in lines)


def test_a_failed_listing_is_one_warning() -> None:
    code, lines, shell = run_main(fake_runner({DB: ""}, list_error="no such host"))
    assert code == 1
    assert shell.calls == []
    assert len(lines) == 1 and "WARNING" in lines[0] and "no such host" in lines[0]


def test_every_line_masks_an_ingress_token() -> None:
    error = f"could not connect: /api/hassio_ingress/{TOKEN}/db"
    code, lines, _ = run_main(fake_runner({DB: ""}, list_error=error))
    assert TOKEN not in "\n".join(lines)
    assert "<redacted>" in lines[0]


def test_the_canonical_url_comes_from_the_maintenance_library(monkeypatch) -> None:
    """One start has one Canonical URL: the rule stays in `canonical_url()`."""
    monkeypatch.setenv("ODOO_MAINT_PUBLIC_URL", CANONICAL + "/")
    monkeypatch.setenv("ODOO_MAINT_LAN_IPV4", "192.0.2.10/24")
    monkeypatch.setenv("ODOO_MAINT_PORT", "8069")
    assert catchup.canonical_url_from_environment() == CANONICAL
    monkeypatch.setenv("ODOO_MAINT_PUBLIC_URL", "")
    assert catchup.canonical_url_from_environment() == "http://192.0.2.10:8069"
    monkeypatch.setenv("ODOO_MAINT_LAN_IPV4", "")
    assert catchup.canonical_url_from_environment() is None


def test_the_library_signals_the_workers_after_its_commit() -> None:
    """A write from `odoo shell` reaches the database, not the workers' caches.

    Measured on the test host: after the catch-up wrote the domain, the
    Ingress home page kept `og:url` and `og:image` on the Home Assistant
    address until `registry.signal_changes()` was called by hand, and
    moved onto the Canonical URL within one fetch after it. An RPC request
    makes that call after its commit (odoo/service/model.py); the library's
    entry block must make it too, after the commit and before it exits.
    """
    library = (LIB_DIR / "odoo-maintenance.py").read_text(encoding="utf-8")
    entry = library[library.index('if __name__ == "__main__":'):]
    assert "env.cr.commit()" in entry
    assert "env.registry.signal_changes()" in entry
    assert entry.index("env.cr.commit()") < entry.index("env.registry.signal_changes()")


def test_the_writer_is_the_bootstraps_odoo_shell_invocation() -> None:
    """Same user, same binary, same flags, same library on stdin."""
    calls: list = []

    def runner(command, **keywords):
        calls.append((command, keywords))
        return subprocess.CompletedProcess(command, 0, "", "")

    catchup.odoo_shell(DB, "/data/odoo.conf", {"ODOO_MAINT_DB": DB}, runner=runner)
    command, keywords = calls[0]
    assert command == ["s6-setuidgid", "odoo", "/usr/bin/odoo", "shell",
                       "-c", "/data/odoo.conf", "-d", DB, "--no-http"]
    assert keywords["input"] == (LIB_DIR / "odoo-maintenance.py").read_text(encoding="utf-8")
    assert keywords["env"]["ODOO_MAINT_DB"] == DB
    assert keywords["timeout"] == catchup.SHELL_TIMEOUT_SECONDS
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert "s6-setuidgid odoo /usr/bin/odoo shell" in bootstrap
    assert '-d "${DB}" --no-http < "${MAINT_LIB}"' in bootstrap


# --- the CLI wrapper ----------------------------------------------------------

def code_of(script: Path) -> str:
    return "\n".join(
        line for line in script.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_cli_feeds_the_library_the_bootstraps_inputs_and_forwards_its_lines() -> None:
    assert CLI.is_file()
    script = CLI.read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/with-contenv bashio")
    assert "/usr/local/lib/canonical_catchup.py" in script
    # The same inputs, from the same places, as odoo-maintenance-bootstrap.
    for token in (
        "bashio::config 'public_url'",
        'if [ "${WOOW_CANONICAL_SETTLED:-}" = 1 ]',
        'LAN_IPV4="${WOOW_LAN_IPV4:-}"',
        'PUBLISHED_PORT="${WOOW_LAN_PORT:-}"',
        'export ODOO_MAINT_PUBLIC_URL="${PUBLIC_URL}"',
        'export ODOO_MAINT_LAN_IPV4="${LAN_IPV4}"',
        'export ODOO_MAINT_PORT="${PUBLISHED_PORT}"',
    ):
        assert token in script, token
    # Never a second derivation (ADR 0006), and never a warning every round
    # for the unprotected case.
    assert "bashio::network.ipv4_address" not in script
    assert "bashio::addon.port" not in script
    assert "woow::supervisor" not in script
    assert "published no settled Canonical URL inputs" not in script
    # Lines forwarded the way the bootstrap forwards them.
    assert "*WARNING*) bashio::log.warning" in script
    assert "literal_rewrite_auto" not in code_of(CLI), (
        "the option freezes Generated rewrites, not the Canonical URL"
    )
    # Every CLI under /usr/local/bin keeps `set -e` (ADR 0009); the one
    # command that may fail has its status captured.
    assert "set -euo pipefail" in script
    assert 'OUTPUT="$(python3 "${LIB}" --conf "${CONF}")" || STATUS=$?' in script


def test_the_image_makes_the_new_files_readable() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "chmod a+r /usr/local/lib/canonical_catchup.py" in dockerfile
    assert "chmod a+rx /usr/local/bin/odoo-canonical-catchup" in dockerfile


# --- the service, driven ------------------------------------------------------
# services.d/rewrite-scan/run is sourced by bash with bashio, pg_isready and
# sleep stubbed and the two steps replaced by scripts of the test's own. The
# stubbed `sleep` ends the process after the first round.

SERVICE_STUBS = r"""
LOG="$1"
bashio::log.info()    { printf 'INFO %s\n'  "$1" >> "${LOG}"; }
bashio::log.warning() { printf 'WARN %s\n'  "$1" >> "${LOG}"; }
bashio::log.error()   { printf 'ERROR %s\n' "$1" >> "${LOG}"; }
pg_isready() { return 0; }
sleep() { printf 'SLEEP %s\n' "$1" >> "${LOG}"; exit 0; }
"""


def drive_service(round_status: int, catchup_status: int) -> tuple:
    """Source services.d/rewrite-scan/run for one round; return exit code and log lines.

    The two steps write to stdout, as the real ones do, and the log
    collects what bashio was asked to print; both are returned, the
    stdout lines tagged, in the order the log saw its own.
    """
    bash = require_bash()
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "log"
        log.touch()
        # The round writes its report and sends its notification itself
        # (rewrite_apply.main), so the stub does both, then exits.
        round_script = Path(tmp) / "round"
        round_script.write_text(
            f"#!/bin/sh\necho 'round report line' >> \"{log.as_posix()}\"\n"
            f"echo 'NOTIFY round' >> \"{log.as_posix()}\"\nexit {round_status}\n",
            encoding="utf-8",
        )
        catchup_script = Path(tmp) / "catchup"
        catchup_script.write_text(
            f"#!/bin/sh\necho 'catch-up line' >> \"{log.as_posix()}\"\nexit {catchup_status}\n",
            encoding="utf-8",
        )
        for script in (round_script, catchup_script):
            script.chmod(0o755)
        driver = (
            f'set -- "{log.as_posix()}"\n{SERVICE_STUBS}\n'
            f'source "{RUN.as_posix()}"\n'
        )
        env = dict(os.environ,
                   WOOW_REWRITE_ROUND=round_script.as_posix(),
                   WOOW_CANONICAL_CATCHUP=catchup_script.as_posix())
        result = subprocess.run([bash, "-c", driver], capture_output=True,
                                encoding="utf-8", errors="replace", timeout=60, env=env)
        return result.returncode, log.read_text(encoding="utf-8").splitlines()


def test_a_failed_catch_up_does_not_change_the_round_or_end_the_loop() -> None:
    code, lines = drive_service(round_status=0, catchup_status=1)
    assert code == 0, lines
    assert "round report line" in lines, "the round's own report still reaches the log"
    assert "catch-up line" in lines
    assert not [l for l in lines if l.startswith("WARN ") and "round above ended" in l], (
        "a healthy round is not reported as failed because the catch-up failed"
    )
    catchup_warnings = [l for l in lines if l.startswith("WARN ") and "catch-up" in l]
    assert len(catchup_warnings) == 1 and "exit 1" in catchup_warnings[0]
    # The round's notification is the round's own and went out before the
    # catch-up ran; the catch-up sends none of its own (the brief keeps the
    # two existing notifications the only ones).
    notifications = [l for l in lines if l.startswith("NOTIFY ")]
    assert notifications == ["NOTIFY round"]
    assert lines.index("NOTIFY round") < lines.index("catch-up line")
    assert lines[-1] == "SLEEP 300", "the loop goes on to the next round"


def test_a_failed_round_is_still_reported_when_the_catch_up_succeeds() -> None:
    code, lines = drive_service(round_status=1, catchup_status=0)
    assert code == 0, lines
    round_warnings = [l for l in lines if l.startswith("WARN ") and "round above ended at exit 1" in l]
    assert len(round_warnings) == 1
    assert not [l for l in lines if l.startswith("WARN ") and "catch-up" in l]
    # The round's warning comes before the catch-up runs: the catch-up
    # cannot alter what the round said about itself.
    assert lines.index(round_warnings[0]) < lines.index("catch-up line")
    assert lines[-1] == "SLEEP 300"


def test_the_catch_up_runs_after_the_round_every_round_without_set_e() -> None:
    code = code_of(RUN)
    assert "set -e" not in code
    assert "/usr/local/bin/odoo-canonical-catchup" in code
    assert code.index("odoo-rewrite-apply") < code.index("odoo-canonical-catchup")
    assert CLI.is_file()


# --- the documents ------------------------------------------------------------

def test_docs_say_a_website_installed_later_gets_the_domain_within_five_minutes() -> None:
    docs = DOCS.read_text(encoding="utf-8")
    assert "Rewrite scan" in docs and "within five minutes" in docs
    assert "maintenance db=" in docs, "DOCS.md names the log line that shows the catch-up"


def test_context_extends_the_canonical_url_definition() -> None:
    context = CONTEXT.read_text(encoding="utf-8")
    definition = context[context.index("**Canonical URL**:"):]
    definition = definition[:definition.index("_Avoid_")]
    assert "Rewrite scan" in definition
    assert "on every start" in definition


def test_the_parity_plan_has_a_g_06_row_that_cites_this_issue() -> None:
    plan = PARITY_PLAN.read_text(encoding="utf-8")
    rows = [line for line in plan.splitlines() if line.startswith("| `G-06`")]
    assert len(rows) == 1
    assert "#164" in rows[0]
