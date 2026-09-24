#!/usr/bin/env python3
"""Static-tier contracts for the Rewrite scan's apply path (issue #93, ADR 0008).

This is the half that can break a running container, so the tests here are
mostly about what the add-on refuses to do: an incomplete scan is not
applied, a bundle whose bytes are gone fails its database, an unchanged
generation is not written, a candidate nginx rejects never reaches the
include file, and `literal_rewrite_auto = false` freezes application
without stopping the scan.

Everything runs with a fake process runner and a temporary filestore,
except the one test that drives a real `nginx -t` over a candidate rendered
from the real template -- the same tool the Static tier already needs for
`test_dual_gateway.py`.

The modules are loaded by path, the way `test_rewrite_scan.py:34` loads
theirs.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import require_tool

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "rootfs/usr/local/lib"
APPLY_LIB = LIB_DIR / "rewrite_apply.py"
CLI = ROOT / "rootfs/usr/local/bin/odoo-rewrite-apply"
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
DOCKERFILE = ROOT / "Dockerfile"
CONFIG = ROOT / "config.yaml"
CI_WORKFLOW = ROOT.parent / ".github/workflows/ci.yml"
ADR_DIR = ROOT.parent / "docs/adr"


def load_module(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    # The modules annotate their dataclasses lazily and dataclasses resolves
    # those annotations through sys.modules, so each is registered first.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = load_module(LIB_DIR / "rewrite_scan.py", "rewrite_scan")
gate = load_module(LIB_DIR / "literal_rewrite_gate.py", "literal_rewrite_gate")
apply = load_module(APPLY_LIB, "rewrite_apply")

# Documentation names only; no real database or host here.
DB = "odoo_test"
OTHER_DB = "odoo_other"
URL = "/web/assets/1/8c63e6a/web.assets_web.min.js"
OTHER_URL = "/web/assets/2b4d1f0/web.assets_web.min.js"
SUM = "7683fa082aaa53fd969289bc141aa78853af2d7c"
OTHER_SUM = "0f1e2d3c4b5a69788796a5b4c3d2e1f009182736"

# A bundle that navigates to a prefix the template does not cover, which is
# what earns a Generated rewrite, plus one the shim handles (INFO) and one
# comparison (WARN), neither of which ever earns a rule.
FORUM_BUNDLE = """
function post(){window.location.href="/forum/ask";}
function rpc(){return fetch("/web/dataset/call_kw");}
if (window.location.pathname.startsWith("/scoped_app")) { return; }
"""
LIVECHAT_BUNDLE = 'function chat(){document.location.assign("/livechat/open");}\n'
QUIET_BUNDLE = 'const url = "/web/image/1";\n'


def row(database=DB, url=URL, checksum=SUM):
    return scan.BundleRow(
        database=database, url=url, name="web.assets_web.min.js",
        checksum=checksum, store_fname=f"{checksum[:2]}/{checksum}", file_size=1024,
    )


def filestore(tmp_path: Path, *bundles) -> str:
    """A filestore holding these (row, text) pairs, one directory per database."""
    root = tmp_path / "filestore"
    for one, text in bundles:
        path = Path(scan.bundle_path(one, str(root)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(root)


def result(*databases) -> "scan.ScanResult":
    return scan.ScanResult(tuple(databases))


def ok(database=DB, *rows) -> "scan.DatabaseScan":
    return scan.DatabaseScan(database, scan.STATUS_OK, tuple(rows))


def rendered_conf(include_path: str = scan.GENERATED_REWRITES_PATH) -> str:
    """The template rendered the way `10-odoo-config.sh` renders it."""
    config = TEMPLATE.read_text(encoding="utf-8")
    for placeholder, value in {
        "%%WS_PORT%%": "8070",
        "%%PUBLIC_PROTO%%": "https",
        "%%PUBLIC_HOST_MAP%%": '"odoo-test.invalid" 1;',
        "%%DENY_STATUS%%": "444",
        "%%LAN_NETWORKS%%": "192.168.0.0/16 1;",
        "%%INGRESS_CACHE_VERSION%%": "test",
        "%%CANONICAL_URL%%": "https://odoo-test.invalid",
    }.items():
        config = config.replace(placeholder, value)
    assert "%%" not in config, "the rendering left a placeholder behind"
    if include_path != scan.GENERATED_REWRITES_PATH:
        config = config.replace(
            f"include {scan.GENERATED_REWRITES_PATH};", f"include {include_path};"
        )
    return config


class Runner:
    """A stand-in for `subprocess.run`: records calls, answers as told."""

    def __init__(self, returncode: int = 0, stderr: str = "syntax is ok\ntest is successful\n"):
        self.calls: list = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)

    @property
    def reloads(self) -> list:
        return [call for call in self.calls if call[1:] == ["-s", "reload"]]

    @property
    def tests(self) -> list:
        return [call for call in self.calls if "-t" in call]


def inputs_of(conf_text=None, exceptions_path=apply.EXCEPTIONS_PATH):
    """The generation inputs a round over this gateway and exception list sees."""
    return apply.generation_inputs(
        apply.shipped_rules(conf_text if conf_text is not None else rendered_conf()),
        apply.load_exceptions(exceptions_path),
    )


def matching_state(*rows, conf_text=None, exceptions_path=apply.EXCEPTIONS_PATH):
    """A previous state that agrees with these rows and these generation inputs."""
    return scan.state_from_rows(rows, "0" * 64, inputs=inputs_of(conf_text, exceptions_path))


def apply_round(tmp_path, scan_result, *, include_text="", conf_text=None, **keywords):
    """Run a round against a temporary include file, state and filestore."""
    include = tmp_path / "nginx-generated-rewrites.conf"
    include.write_text(include_text, encoding="utf-8")
    conf = tmp_path / "nginx.conf"
    conf.write_text(conf_text if conf_text is not None else rendered_conf(), encoding="utf-8")
    keywords.setdefault("runner", Runner())
    keywords.setdefault("running", lambda: True)
    keywords.setdefault("state_path", tmp_path / "state.json")
    outcome = apply.apply_round(
        scan_result,
        include_path=include,
        nginx_conf_path=conf,
        version="0" * 64,
        **keywords,
    )
    return outcome, include


# --- an incomplete scan is never applied --------------------------------------

def test_a_failed_database_stops_the_round_before_anything_is_written(tmp_path: Path) -> None:
    good = row()
    store = filestore(tmp_path, (good, FORUM_BUNDLE))
    runner = Runner()
    outcome, include = apply_round(
        tmp_path,
        result(ok(DB, good), scan.DatabaseScan(OTHER_DB, scan.STATUS_FAILED, error="connection refused")),
        filestore=store, runner=runner,
    )
    assert outcome.status == apply.STATUS_INCOMPLETE
    # The database that failed is named: an operator has to know which one,
    # and a total failure must not read as a scan that found nothing.
    assert OTHER_DB in outcome.detail
    assert include.read_text(encoding="utf-8") == ""
    assert not outcome.wrote and not outcome.reloaded
    assert runner.calls == [], "an incomplete scan runs neither nginx -t nor a reload"
    assert not (tmp_path / "state.json").exists(), "a refused round must not write the state"


def test_a_bundle_missing_from_the_filestore_fails_its_database(tmp_path: Path) -> None:
    present, gone = row(), row(url=OTHER_URL, checksum=OTHER_SUM)
    # Only the first bundle is written, so the second is a row with no bytes.
    store = filestore(tmp_path, (present, FORUM_BUNDLE))
    outcome, include = apply_round(tmp_path, result(ok(DB, present, gone)), filestore=store)
    assert outcome.status == apply.STATUS_INCOMPLETE
    assert DB in outcome.detail
    assert include.read_text(encoding="utf-8") == ""
    # The union would have been short by whatever the missing bundle uses,
    # which is how a working Generated rewrite gets deleted.
    assert outcome.scan.failed == (DB,)


def test_a_bundle_the_scan_had_to_skip_fails_its_database(tmp_path: Path) -> None:
    """`ok` with skips is an all-clear only for the read path's own report."""
    present = row()
    in_database = scan.BundleRow(
        database=DB, url=OTHER_URL, name="web.assets_web.min.js",
        checksum=OTHER_SUM, store_fname=None, file_size=2048,
    )
    store = filestore(tmp_path, (present, FORUM_BUNDLE))
    outcome, include = apply_round(
        tmp_path,
        result(scan.DatabaseScan(DB, scan.STATUS_OK, (present,), (in_database,))),
        filestore=store,
    )
    assert outcome.status == apply.STATUS_INCOMPLETE
    assert "unsupported storage" in outcome.detail
    assert include.read_text(encoding="utf-8") == ""


def test_the_completeness_test_comes_before_the_rescan_verdict(tmp_path: Path) -> None:
    """A failed database must not be read as "nothing changed" either."""
    good = row()
    store = filestore(tmp_path, (good, FORUM_BUNDLE))
    # A previous state that holds exactly the rows the short union holds:
    # the verdict alone would say no rescan is due and look healthy.
    previous = scan.ScanState(analysis_version="0" * 64, bundles={good.key: good.checksum})
    outcome, _ = apply_round(
        tmp_path,
        result(ok(DB, good), scan.DatabaseScan(OTHER_DB, scan.STATUS_FAILED, error="timeout")),
        filestore=store, previous_state=previous,
    )
    assert outcome.status == apply.STATUS_INCOMPLETE
    assert outcome.verdict is None, "the verdict is not reached from a short union"


def test_a_database_that_serves_no_bundles_is_not_a_failure(tmp_path: Path) -> None:
    good = row()
    store = filestore(tmp_path, (good, QUIET_BUNDLE))
    outcome, include = apply_round(
        tmp_path,
        result(ok(DB, good), scan.DatabaseScan(OTHER_DB, scan.STATUS_NO_BUNDLES)),
        filestore=store,
    )
    # Nothing in the bundle earns a rule, so the empty file it already holds
    # is the right answer -- and the round is healthy, not refused.
    assert outcome.status == apply.STATUS_UNCHANGED
    assert include.read_text(encoding="utf-8") == ""


# --- byte stability -----------------------------------------------------------

def test_an_unchanged_generation_is_neither_written_nor_reloaded(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    runner = Runner()
    # What the previous pass would have written for the same bundle.
    text = apply.build_include(
        apply.scan_bundles({one.key: FORUM_BUNDLE}),
        apply.shipped_rules(rendered_conf()),
        apply.load_exceptions(),
    )
    assert "/forum/" in text, "the fixture must earn a rule for this test to mean anything"
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), include_text=text, filestore=store, runner=runner,
    )
    assert outcome.status == apply.STATUS_UNCHANGED
    assert not outcome.wrote and not outcome.reloaded
    assert runner.calls == [], "an unchanged file is not validated and not reloaded"
    assert include.read_text(encoding="utf-8") == text


def test_the_union_is_taken_across_databases(tmp_path: Path) -> None:
    here, there = row(), row(database=OTHER_DB, url=OTHER_URL, checksum=OTHER_SUM)
    store = filestore(tmp_path, (here, FORUM_BUNDLE), (there, LIVECHAT_BUNDLE))
    outcome, include = apply_round(
        tmp_path, result(ok(DB, here), ok(OTHER_DB, there)), filestore=store,
    )
    assert outcome.status == apply.STATUS_APPLIED
    assert outcome.prefixes == ("/forum/", "/livechat/")
    assert include.read_text(encoding="utf-8") == outcome.include_text


def test_only_navigation_prefixes_earn_a_rule(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    outcome, _ = apply_round(tmp_path, result(ok(DB, one)), filestore=store)
    # `/web/` is shipped, `/scoped_app` is a WARN and registered besides,
    # and the RPC path is an INFO the Runtime shim already reaches.
    assert outcome.prefixes == ("/forum/",)


def test_a_generated_rule_is_not_read_back_as_a_shipped_one(tmp_path: Path) -> None:
    """Otherwise the rules would flap: covered, dropped, found again."""
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    first, include = apply_round(tmp_path, result(ok(DB, one)), filestore=store)
    assert first.status == apply.STATUS_APPLIED
    # The second round sees the file it just wrote. The rules it generates
    # must be the same ones, not an empty file.
    second, _ = apply_round(
        tmp_path, result(ok(DB, one)), include_text=include.read_text(encoding="utf-8"),
        filestore=store,
    )
    assert second.status == apply.STATUS_UNCHANGED
    assert second.prefixes == ("/forum/",)


# --- validation ---------------------------------------------------------------

def test_a_candidate_is_validated_before_it_is_moved_into_place(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    runner = Runner()
    outcome, include = apply_round(tmp_path, result(ok(DB, one)), filestore=store, runner=runner)
    assert outcome.status == apply.STATUS_APPLIED
    assert len(runner.tests) == 1, "the candidate is validated exactly once"
    # `nginx -t -c <temporary conf>`, never `nginx -t` against the live one.
    command = runner.tests[0]
    assert "-c" in command and command[command.index("-c") + 1].endswith("nginx.conf")
    assert command[command.index("-c") + 1] != str(tmp_path / "nginx.conf")
    assert include.read_text(encoding="utf-8") == outcome.include_text
    assert not (include.parent / (include.name + ".candidate")).exists()


def test_a_candidate_nginx_refuses_leaves_the_previous_file_alone(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    previous = 'sub_filter \'"/livechat/\' \'"$safe_ingress_path/livechat/\';\n'
    runner = Runner(returncode=1, stderr='nginx: [emerg] invalid number of arguments\n')
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), include_text=previous, filestore=store, runner=runner,
    )
    assert outcome.status == apply.STATUS_INVALID
    assert "invalid number of arguments" in outcome.detail
    assert include.read_text(encoding="utf-8") == previous, "the last good file stays"
    assert not outcome.wrote and not outcome.reloaded
    assert runner.reloads == [], "a refused candidate never reaches a reload"
    assert not (include.parent / (include.name + ".candidate")).exists()
    assert not (tmp_path / "state.json").exists()


def test_a_candidate_that_does_not_parse_is_refused_by_real_nginx(tmp_path: Path) -> None:
    """The same refusal, driven through the nginx the Static tier installs."""
    nginx = require_tool("nginx")
    include = tmp_path / "nginx-generated-rewrites.conf"
    previous = 'sub_filter \'"/forum/\' \'"$safe_ingress_path/forum/\';\n'
    include.write_text(previous, encoding="utf-8")
    broken = "sub_filter 'unterminated;\n"
    outcome = apply.apply_include(
        broken, rendered_conf(), include_path=include, work_dir=tmp_path / "work",
        running=lambda: False,
    )
    assert nginx, "nginx is the tool under test here"
    assert outcome.status == apply.STATUS_INVALID
    assert include.read_text(encoding="utf-8") == previous
    assert not outcome.wrote


def test_a_valid_candidate_is_accepted_by_real_nginx(tmp_path: Path) -> None:
    require_tool("nginx")
    include = tmp_path / "nginx-generated-rewrites.conf"
    include.write_text("", encoding="utf-8")
    text = gate.generate_include(
        gate.scan_bundle(FORUM_BUNDLE), apply.shipped_rules(rendered_conf()), apply.load_exceptions()
    )
    outcome = apply.apply_include(
        text, rendered_conf(), include_path=include, work_dir=tmp_path / "work",
        running=lambda: False,
    )
    assert outcome.status == apply.STATUS_APPLIED, outcome.detail
    assert include.read_text(encoding="utf-8") == text
    assert oct(include.stat().st_mode)[-3:] == "644" or os.name != "posix"


def test_the_test_configuration_keeps_no_tcp_listener(tmp_path: Path) -> None:
    config = apply.render_test_config(rendered_conf(), tmp_path / "candidate.conf", tmp_path)
    listeners = [line.strip() for line in config.splitlines() if line.strip().startswith("listen ")]
    assert listeners, "the rendered configuration must still have listeners"
    for listener in listeners:
        assert listener.startswith("listen unix:"), (
            f"{listener}: the running nginx holds 8069, 8072 and 5691, and nginx -t "
            "opens listener sockets"
        )
    assert str(tmp_path / "candidate.conf") in config
    assert scan.GENERATED_REWRITES_PATH not in config
    # The running master owns the real pid file.
    assert "pid /var/run/nginx.pid;" not in config


def test_the_include_line_is_found_in_the_shipped_template() -> None:
    """The one line the whole apply path depends on being exactly one line."""
    assert rendered_conf().count(f"include {scan.GENERATED_REWRITES_PATH};") == 1


# --- the reload ---------------------------------------------------------------

def test_a_written_file_reloads_the_running_nginx(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    runner = Runner()
    outcome, _ = apply_round(
        tmp_path, result(ok(DB, one)), filestore=store, runner=runner, running=lambda: True,
    )
    assert outcome.status == apply.STATUS_APPLIED
    assert outcome.reloaded
    assert [call[1:] for call in runner.reloads] == [["-s", "reload"]]


def test_nothing_is_reloaded_before_nginx_is_running(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    runner = Runner()
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), filestore=store, runner=runner, running=lambda: False,
    )
    assert outcome.status == apply.STATUS_APPLIED
    assert outcome.wrote and not outcome.reloaded
    assert runner.reloads == [], "there is no master to signal yet"
    assert include.read_text(encoding="utf-8") == outcome.include_text
    assert "not running" in outcome.detail


def test_a_failed_reload_keeps_the_file_and_says_the_rules_are_not_live(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))

    class ReloadFails(Runner):
        def __call__(self, command, **kwargs):
            if command[1:] == ["-s", "reload"]:
                self.calls.append(list(command))
                return subprocess.CompletedProcess(command, 1, "", "nginx: [error] open() failed")
            return super().__call__(command, **kwargs)

    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), filestore=store, runner=ReloadFails(),
    )
    assert outcome.status == apply.STATUS_APPLIED
    assert outcome.wrote and not outcome.reloaded
    assert "not live" in outcome.detail
    assert include.read_text(encoding="utf-8") == outcome.include_text


def test_no_master_pid_file_means_nginx_is_not_running(tmp_path: Path) -> None:
    assert apply.nginx_master(tmp_path / "absent.pid") is None
    (tmp_path / "rubbish.pid").write_text("not a pid\n", encoding="utf-8")
    assert apply.nginx_master(tmp_path / "rubbish.pid") is None


@pytest.mark.skipif(os.name != "posix", reason="os.kill probes a process only on POSIX")
def test_a_live_pid_file_is_read_as_a_running_master(tmp_path: Path) -> None:
    pid_file = tmp_path / "nginx.pid"
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
    assert apply.nginx_master(pid_file) == os.getpid()


# --- the kill switch ----------------------------------------------------------

def test_application_off_scans_reports_and_touches_nothing(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    runner = Runner()
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), filestore=store, runner=runner, auto=False,
    )
    assert outcome.status == apply.STATUS_OFF
    # The scan still ran and the report still says what would be rewritten.
    assert outcome.prefixes == ("/forum/",)
    assert "literal_rewrite_auto is false" in outcome.detail
    assert include.read_text(encoding="utf-8") == ""
    assert not outcome.wrote and not outcome.reloaded
    assert runner.calls == []
    assert not (tmp_path / "state.json").exists(), (
        "a state written while application is off would silence the report"
    )


def test_application_off_leaves_the_rules_already_in_place_live(tmp_path: Path) -> None:
    """The option freezes application; it does not roll back."""
    one = row()
    store = filestore(tmp_path, (one, QUIET_BUNDLE))
    live = 'sub_filter \'"/forum/\' \'"$safe_ingress_path/forum/\';\n'
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), include_text=live, filestore=store, auto=False,
    )
    assert outcome.status == apply.STATUS_OFF
    assert include.read_text(encoding="utf-8") == live


def test_application_off_never_takes_the_nothing_changed_skip(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    previous = scan.ScanState(analysis_version="0" * 64, bundles={one.key: one.checksum})
    outcome, _ = apply_round(
        tmp_path, result(ok(DB, one)), filestore=store, auto=False, previous_state=previous,
    )
    # With the skip taken there would be no findings to report, and the log
    # would go quiet exactly while the operator is watching it.
    assert outcome.status == apply.STATUS_OFF
    assert outcome.prefixes == ("/forum/",)


# --- the state ----------------------------------------------------------------

def test_the_state_is_written_only_after_a_pass_that_was_applied(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    outcome, _ = apply_round(tmp_path, result(ok(DB, one)), filestore=store)
    assert outcome.status == apply.STATUS_APPLIED and outcome.state_saved
    written = scan.load_state(tmp_path / "state.json", tmp_path / "nginx-generated-rewrites.conf")
    assert written.state is not None, written.reason
    assert written.state.bundles == {one.key: one.checksum}


def test_a_state_that_matches_skips_the_expensive_pass(tmp_path: Path) -> None:
    one = row()
    # No filestore at all: if the pass were taken, reading would fail the
    # database, so reaching "up to date" proves nothing was read.
    previous = matching_state(one)
    runner = Runner()
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), filestore=str(tmp_path / "absent"),
        previous_state=previous, runner=runner,
    )
    assert outcome.status == apply.STATUS_UP_TO_DATE
    assert runner.calls == []
    assert include.read_text(encoding="utf-8") == ""


def test_force_takes_the_pass_even_when_the_state_matches(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    previous = matching_state(one)
    outcome, _ = apply_round(
        tmp_path, result(ok(DB, one)), filestore=store, previous_state=previous, force=True,
    )
    assert outcome.status == apply.STATUS_APPLIED


# --- the generation inputs (issue #135) ---------------------------------------

# Shipped rewrites as the rendered template writes them.
WEB_SHIPPED = "            sub_filter '\"/web/' '\"$safe_ingress_path/web/';\n"
MAIL_SHIPPED = "            sub_filter '\"/mail/' '\"$safe_ingress_path/mail/';\n"
# One more Shipped rewrite, the one FORUM_BUNDLE earns.
FORUM_SHIPPED = "            sub_filter '\"/forum/' '\"$safe_ingress_path/forum/';\n"


def conf_shipping_forum() -> str:
    config = rendered_conf()
    assert config.count(WEB_SHIPPED) == 1
    return config.replace(WEB_SHIPPED, WEB_SHIPPED + FORUM_SHIPPED)


def forum_include() -> str:
    """The include file the template as it is earns for FORUM_BUNDLE."""
    return apply.build_include(
        apply.scan_bundles({row().key: FORUM_BUNDLE}),
        apply.shipped_rules(rendered_conf()), apply.load_exceptions(),
    )


def test_a_change_of_the_shipped_rewrites_makes_a_pass_due(tmp_path: Path) -> None:
    """A Release that ships a rule moves no bundle, and must still be applied."""
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    live = forum_include()
    assert "/forum/" in apply.include_prefixes(live)
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), include_text=live, filestore=store,
        conf_text=conf_shipping_forum(), previous_state=matching_state(one),
    )
    assert outcome.status == apply.STATUS_APPLIED
    assert "Shipped rewrites changed" in outcome.verdict.reason
    assert "/forum/" not in apply.include_prefixes(include.read_text(encoding="utf-8")), (
        "the Shipped rule covers the prefix now, so the Generated one is dropped"
    )


def test_a_change_of_the_exception_list_makes_a_pass_due(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    exceptions = tmp_path / "exceptions.yaml"
    exceptions.write_text(
        Path(apply.EXCEPTIONS_PATH).read_text(encoding="utf-8")
        + "- prefix: /forum/\n  level: FAIL\n  reason: approved for this test\n",
        encoding="utf-8",
    )
    outcome, include = apply_round(
        tmp_path, result(ok(DB, one)), include_text=forum_include(), filestore=store,
        exceptions_path=exceptions, previous_state=matching_state(one),
    )
    assert outcome.status == apply.STATUS_APPLIED
    assert "exception list changed" in outcome.verdict.reason
    assert "/forum/" not in apply.include_prefixes(include.read_text(encoding="utf-8"))


def test_a_state_without_generation_inputs_makes_a_pass_due_once(tmp_path: Path) -> None:
    """A state file written by 0.4.3 or earlier: loaded, then replaced."""
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "analysis_version": "0" * 64, "databases": {DB: {one.url: one.checksum}},
    }), encoding="utf-8")
    include = tmp_path / "nginx-generated-rewrites.conf"
    include.write_text(forum_include(), encoding="utf-8")
    loaded = scan.load_state(state_path, include)
    assert loaded.state is not None, loaded.reason

    outcome, _ = apply_round(
        tmp_path, result(ok(DB, one)), include_text=forum_include(), filestore=store,
        previous_state=loaded.state,
    )
    assert outcome.status == apply.STATUS_UNCHANGED
    assert outcome.state_saved


def test_the_saved_state_carries_the_inputs_and_the_next_round_skips(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, FORUM_BUNDLE))
    conf = conf_shipping_forum()
    first, include = apply_round(
        tmp_path, result(ok(DB, one)), filestore=store, conf_text=conf,
    )
    assert first.state_saved
    saved = scan.load_state(tmp_path / "state.json", include).state
    assert saved.inputs == inputs_of(conf)

    runner = Runner()
    second, _ = apply_round(
        tmp_path, result(ok(DB, one)), include_text=include.read_text(encoding="utf-8"),
        filestore=str(tmp_path / "absent"), conf_text=conf, previous_state=saved,
        runner=runner,
    )
    assert second.status == apply.STATUS_UP_TO_DATE
    assert runner.calls == []


def test_the_fingerprint_ignores_the_order_and_layout_of_the_shipped_rules() -> None:
    config = rendered_conf()
    assert config.count(WEB_SHIPPED) == 1 and config.count(MAIL_SHIPPED) == 1
    reordered = (
        config.replace(WEB_SHIPPED, "@@WEB@@")
        .replace(MAIL_SHIPPED, WEB_SHIPPED)
        .replace("@@WEB@@", MAIL_SHIPPED)
    )
    assert reordered != config
    spaced = config.replace(WEB_SHIPPED, "\n        sub_filter   '\"/web/'    '\"$safe_ingress_path/web/';\n\n")
    assert apply.shipped_rules(reordered) == apply.shipped_rules(config)
    assert inputs_of(reordered) == inputs_of(config)
    assert inputs_of(spaced) == inputs_of(config)
    assert inputs_of(conf_shipping_forum()) != inputs_of(config)


# --- what the image and the option ship ---------------------------------------

def test_the_image_carries_a_yaml_reader() -> None:
    """ADR 0008: the exception list is YAML and the container had no reader."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "python3-yaml" in dockerfile, (
        "generate_include takes the shipped exceptions, so something in the "
        "image has to read literal_rewrite_exceptions.yaml (ADR 0008)"
    )


def test_the_new_files_are_in_the_dockerfile_permission_list() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "chmod a+rx /usr/local/bin/odoo-rewrite-apply" in dockerfile
    library = next(
        line for line in dockerfile.splitlines() if "/usr/local/lib/rewrite_apply.py" in line
    )
    assert "a+r" in library, "the module must be readable by the user the round runs as"


def test_a_build_tier_step_runs_the_shipped_code_in_the_shipped_image() -> None:
    """The Static tier cannot see inside the image; this is what would have
    caught the missing YAML reader before a host did."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "load: true" in workflow, "the built image has to reach the local daemon to be run"
    assert "rewrite_apply" in workflow and "docker run" in workflow
    assert "load_exceptions" in workflow


def test_the_option_is_in_the_schema_with_a_default_of_true() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["schema"]["literal_rewrite_auto"] == "bool?"
    assert config["options"]["literal_rewrite_auto"] is True, (
        "ADR 0005 makes application the default; the option is the kill switch"
    )


def test_the_option_is_read_with_bashio() -> None:
    cli = CLI.read_text(encoding="utf-8")
    assert cli.startswith("#!/usr/bin/with-contenv bashio")
    assert "bashio::config.false 'literal_rewrite_auto'" in cli, (
        "the option is read with bashio, as odoo-maintenance-bootstrap reads its own"
    )
    # An absent or true option applies; only an explicit false freezes.
    assert "--no-auto" in cli and "--auto" in cli
    assert "exec python3 /usr/local/lib/rewrite_apply.py" in cli


def test_the_apply_module_is_not_part_of_the_analysis_version() -> None:
    """It selects no rules, so a change here must not force every host to rescan."""
    assert APPLY_LIB.resolve() not in [Path(p).resolve() for p in scan.ANALYSIS_MODULES]


def test_the_module_imports_with_the_standard_library_and_pyyaml(tmp_path: Path) -> None:
    """Nothing but PyYAML may be needed, and only where the exceptions are read."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(LIB_DIR)!r})\n"
        "import rewrite_apply\n"
        "print(rewrite_apply.STATUS_APPLIED)\n",
        encoding="utf-8",
    )
    # -S drops site-packages, where PyYAML lives in the test environment.
    environment = dict(os.environ, PYTHONPATH="")
    finished = subprocess.run(
        [sys.executable, "-S", "-E", str(probe)],
        capture_output=True, text=True, env=environment,
    )
    assert finished.returncode == 0, finished.stderr


def test_an_adr_records_the_decisions_this_ticket_took() -> None:
    adrs = sorted(ADR_DIR.glob("0008-*.md"))
    assert adrs, "issue #93 lands ADR 0008"
    text = adrs[0].read_text(encoding="utf-8")
    assert "status: accepted" in text
    for token in ("python3-yaml", "nginx -t -c", "unix socket", "literal_rewrite_auto"):
        assert token in text, f"the ADR must record {token!r}"
