#!/usr/bin/env python3
"""Static-tier contracts for the Rewrite scan service and its log summary
(issue #94, ADR 0005 and ADR 0009).

Two halves, and they fail in different ways.

The **service** is five shipped lines of shell that must keep running when
everything they call fails. It is the first service in this image whose
`finish` does not halt the container, so the tests here pin that against
the four that do: a Rewrite scan that cannot read a database is a degraded
rule set, never a reason to take Odoo down with it.

The **log summary** is the only thing an operator ever sees of a round.
Every assertion about it is really one of two questions -- can a round go
silent, and can a round leak an Ingress token -- so the tests drive whole
rounds through `rewrite_apply.report` rather than the formatting helpers
alone, and read the lines the add-on log would carry.

The modules are loaded by path, the way `test_rewrite_apply.py:44` loads
theirs.
"""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "rootfs/usr/local/lib"
SERVICES_DIR = ROOT / "rootfs/etc/services.d"
SERVICE_DIR = SERVICES_DIR / "rewrite-scan"
RUN = SERVICE_DIR / "run"
FINISH = SERVICE_DIR / "finish"
ODOO_RUN = SERVICES_DIR / "odoo/run"
APPLY_CLI = ROOT / "rootfs/usr/local/bin/odoo-rewrite-apply"
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
DOCKERFILE = ROOT / "Dockerfile"
ADR_DIR = ROOT.parent / "docs/adr"

#: The services that are the container: without any of them the add-on is
#: not serving, so each one halts and lets the Supervisor restart it.
HALTING_SERVICES = ("postgres", "odoo", "nginx", "jsonrpc-filter")

#: Five minutes between rounds (#77).
ROUND_INTERVAL_SECONDS = 300


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

# Documentation names only; no real database or host here.
DB = "odoo_test"
OTHER_DB = "odoo_other"
EMPTY_DB = "odoo_fresh"
URL = "/web/assets/1/8c63e6a/web.assets_web.min.js"
OTHER_URL = "/web/assets/2b4d1f0/web.assets_web.min.js"
SUM = "7683fa082aaa53fd969289bc141aa78853af2d7c"
OTHER_SUM = "0f1e2d3c4b5a69788796a5b4c3d2e1f009182736"

# One bundle that reaches every level: a navigation no shipped rule covers
# (FAIL, and the only kind that earns a rule), a comparison the exception
# list excuses (WARN), an RPC path the template already rewrites (dropped
# as covered) and an asset path nothing covers (INFO).
BUNDLE = """
function post(){window.location.href="/forum/ask";}
function rpc(){return fetch("/web/dataset/call_kw");}
if (window.location.pathname.startsWith("/scoped_app")) { return; }
const icon = "/library/static/description/icon.png";
"""

# A token an operator's browser would carry. It reaches the log through the
# snippet of the finding it sits in, which is the one place a round prints
# bundle text back.
TOKEN = "01H8XGJWBWBAQ4TK1Z9MY3MNFW"
TOKEN_BUNDLE = f'function go(){{window.location.href="/api/hassio_ingress/{TOKEN}/forum";}}\n'


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


def ok(database=DB, *rows) -> "scan.DatabaseScan":
    return scan.DatabaseScan(database, scan.STATUS_OK, tuple(rows))


def rendered_conf() -> str:
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
    return config


class Runner:
    """A stand-in for `subprocess.run`: nginx accepts everything, silently."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "test is successful\n")


def matching_state(*rows):
    """A previous state that agrees with these rows and the shipped generation inputs."""
    inputs = apply.generation_inputs(apply.shipped_rules(rendered_conf()), apply.load_exceptions())
    return scan.state_from_rows(rows, "0" * 64, inputs=inputs)


def round_lines(tmp_path: Path, scan_result, *, state_note="no previous state", **keywords):
    """One whole round, as the lines the add-on log would carry."""
    include = tmp_path / "nginx-generated-rewrites.conf"
    include.write_text("", encoding="utf-8")
    conf = tmp_path / "nginx.conf"
    conf.write_text(rendered_conf(), encoding="utf-8")
    keywords.setdefault("runner", Runner())
    keywords.setdefault("running", lambda: False)
    keywords.setdefault("state_path", tmp_path / "state.json")
    outcome = apply.apply_round(
        scan_result,
        include_path=include,
        nginx_conf_path=conf,
        version="0" * 64,
        **keywords,
    )
    lines: list[str] = []
    apply.report(outcome, state_note, lines.append)
    return outcome, lines


def find(lines, needle: str) -> str:
    """The first line holding `needle`, or a readable failure."""
    matches = [line for line in lines if needle in line]
    assert matches, f"no line holds {needle!r}:\n" + "\n".join(lines)
    return matches[0]


def code_of(script: Path) -> str:
    """A shell script with its comments dropped.

    The comments are where these scripts explain themselves, and they name
    the conventions they depart from. Reading them as code would make the
    explanation look like the thing it explains.
    """
    return "\n".join(
        line for line in script.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def level_rows(lines, tag: str) -> list[str]:
    """The per-bundle rows reported at one level (or as an exception).

    Matched by the tag each row opens with rather than by substring: the
    level names also appear in the summary line above the blocks, and a
    prefix appears again in `prefixes:` below them.
    """
    return [line.strip() for line in lines if line.strip().startswith(tag)]


# --- every database is accounted for ------------------------------------------

def test_every_round_names_each_database_and_its_status(tmp_path: Path) -> None:
    """`ok`, `no bundles` and `failed` all reach the log, by name.

    A database that could not be read must never look like one that was
    read and found nothing: #93 refuses to apply an incomplete scan, and
    from outside that refusal is indistinguishable from an add-on that
    simply stopped updating its rules.
    """
    good = row()
    store = filestore(tmp_path, (good, BUNDLE))
    _, lines = round_lines(
        tmp_path,
        scan.ScanResult((
            ok(DB, good),
            scan.DatabaseScan(EMPTY_DB, scan.STATUS_NO_BUNDLES),
            scan.DatabaseScan(OTHER_DB, scan.STATUS_FAILED, error="connection refused"),
        )),
        filestore=store,
    )
    assert find(lines, f"{DB}: ").strip() == f"{DB}: {scan.STATUS_OK}"
    assert find(lines, f"{EMPTY_DB}: ").strip() == f"{EMPTY_DB}: {scan.STATUS_NO_BUNDLES}"
    failed = find(lines, f"{OTHER_DB}: ")
    assert scan.STATUS_FAILED in failed and "connection refused" in failed


def test_an_incomplete_round_says_so_in_the_log(tmp_path: Path) -> None:
    """The word, the consequence, and the database that caused it."""
    good = row()
    store = filestore(tmp_path, (good, BUNDLE))
    outcome, lines = round_lines(
        tmp_path,
        scan.ScanResult((
            ok(DB, good),
            scan.DatabaseScan(OTHER_DB, scan.STATUS_FAILED, error="connection refused"),
        )),
        filestore=store,
    )
    assert outcome.status == apply.STATUS_INCOMPLETE
    text = "\n".join(lines)
    assert "incomplete" in text
    assert "complete: no" in text, "the summary line states it as data, not only as prose"
    assert OTHER_DB in text, "the database that failed is named"
    # Saying only "incomplete" would leave the operator to guess whether the
    # rules on disk moved.
    assert "nothing" in text.lower() or "not applied" in text.lower()


def test_a_listing_that_failed_is_not_a_round_that_found_nothing(tmp_path: Path) -> None:
    _, lines = round_lines(
        tmp_path, scan.ScanResult(error="the databases could not be listed: no such host")
    )
    text = "\n".join(lines)
    assert "could not be listed" in text
    assert "incomplete" in text


# --- the summary, per bundle and per level ------------------------------------

def test_the_summary_counts_every_bundle_at_every_level(tmp_path: Path) -> None:
    one, two = row(), row(database=OTHER_DB, url=OTHER_URL, checksum=OTHER_SUM)
    store = filestore(tmp_path, (one, BUNDLE), (two, BUNDLE))
    _, lines = round_lines(
        tmp_path, scan.ScanResult((ok(DB, one), ok(OTHER_DB, two))), filestore=store
    )
    text = "\n".join(lines)
    # Both bundles get a block of their own, keyed the way #92 keys them:
    # by database and URL, never by name. One database serves the same
    # bundle name twice.
    assert f"{DB} {URL}" in text
    assert f"{OTHER_DB} {OTHER_URL}" in text
    # The navigation that earns the rule, and the asset path that does not.
    assert len(level_rows(lines, "FAIL")) == 2
    assert all("/forum/" in line for line in level_rows(lines, "FAIL"))
    assert all("/library/" in line for line in level_rows(lines, "INFO"))
    summary = find(lines, "findings:")
    assert "FAIL 2" in summary, f"one FAIL per bundle: {summary}"
    assert "WARN 0" in summary, f"the only WARN is excused: {summary}"


def test_a_covered_literal_is_not_reported_as_a_finding(tmp_path: Path) -> None:
    """`/web/` ships in the template, so the RPC path in the bundle is quiet.

    Asserted over the rows rather than over the whole text, because a
    covered literal can still sit inside the snippet of a finding beside
    it -- which is the point of a snippet.
    """
    one = row()
    store = filestore(tmp_path, (one, BUNDLE))
    _, lines = round_lines(tmp_path, scan.ScanResult((ok(DB, one),)), filestore=store)
    reported = level_rows(lines, "INFO") + level_rows(lines, "WARN") + level_rows(lines, "FAIL")
    assert reported, "the bundle does have findings; the covered one is not among them"
    assert not [line for line in reported if line.split()[1].startswith("/web/")]


def test_an_exception_hit_is_reported_as_an_exception(tmp_path: Path) -> None:
    """`/scoped_app` WARN is registered, so it is a hit and never a finding."""
    one = row()
    store = filestore(tmp_path, (one, BUNDLE))
    _, lines = round_lines(tmp_path, scan.ScanResult((ok(DB, one),)), filestore=store)
    hits = find(lines, "exception hits:")
    assert "/scoped_app" in hits and "WARN" in hits
    excused = level_rows(lines, "exception")
    assert excused and "/scoped_app" in excused[0], (
        f"the row says it is excused: {excused}"
    )
    assert not level_rows(lines, "WARN"), "an excused comparison is never a WARN row"


def test_the_applied_prefixes_are_logged(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, BUNDLE))
    outcome, lines = round_lines(tmp_path, scan.ScanResult((ok(DB, one),)), filestore=store)
    assert outcome.status == apply.STATUS_APPLIED
    assert "/forum/" in find(lines, "prefixes:")


def test_a_round_that_needed_no_pass_still_reports_its_databases(tmp_path: Path) -> None:
    """The cheap round is the common one; it must not be a silent one.

    No bundle was read, so there is no per-bundle block to print. The
    verdict and the per-database statuses are what is true, and they are
    what the log says.
    """
    one = row()
    store = filestore(tmp_path, (one, BUNDLE))
    state = matching_state(one)
    outcome, lines = round_lines(
        tmp_path, scan.ScanResult((ok(DB, one),)), filestore=store, previous_state=state,
    )
    assert outcome.status == apply.STATUS_UP_TO_DATE
    assert find(lines, DB)
    assert find(lines, "no change")
    assert not [line for line in lines if "findings:" in line], (
        "nothing was scanned, so nothing is summarised"
    )


def test_a_round_that_generated_nothing_still_names_the_live_prefixes(
    tmp_path: Path,
) -> None:
    """"Which Generated rewrites are live" is the question, every round.

    An up-to-date round writes nothing and a refused one writes nothing, so
    neither has a generation of its own to report. Reading the include file
    is what keeps them from going quiet about the rules that are in force:
    otherwise every round after the first application would stop naming
    them, and a host doing its job would read like a host that had
    forgotten how.
    """
    one = row()
    store = filestore(tmp_path, (one, BUNDLE))
    include = tmp_path / "nginx-generated-rewrites.conf"
    conf = tmp_path / "nginx.conf"
    conf.write_text(rendered_conf(), encoding="utf-8")
    # A file already holding the rule the bundle earns, and a state that
    # agrees with it, which is the ordinary five-minute round.
    include.write_text(
        apply.build_include(
            apply.scan_bundles({one.key: BUNDLE}),
            apply.shipped_rules(rendered_conf()),
            apply.load_exceptions(),
        ),
        encoding="utf-8",
    )
    outcome = apply.apply_round(
        scan.ScanResult((ok(DB, one),)),
        include_path=include,
        nginx_conf_path=conf,
        version="0" * 64,
        filestore=store,
        previous_state=matching_state(one),
        state_path=tmp_path / "state.json",
        runner=Runner(),
        running=lambda: False,
    )
    lines: list[str] = []
    apply.report(outcome, "no previous state", lines.append)
    assert outcome.status == apply.STATUS_UP_TO_DATE
    assert "/forum/" in find(lines, "prefixes:")


def test_a_refused_round_names_the_live_prefixes_too(tmp_path: Path) -> None:
    """The rules stayed; saying which ones is how the log says they stayed."""
    include = tmp_path / "nginx-generated-rewrites.conf"
    conf = tmp_path / "nginx.conf"
    conf.write_text(rendered_conf(), encoding="utf-8")
    include.write_text(
        "sub_filter '\"/forum/' '\"$safe_ingress_path/forum/';\n", encoding="utf-8"
    )
    outcome = apply.apply_round(
        scan.ScanResult((
            scan.DatabaseScan(DB, scan.STATUS_FAILED, error="connection refused"),
        )),
        include_path=include,
        nginx_conf_path=conf,
        version="0" * 64,
        state_path=tmp_path / "state.json",
        runner=Runner(),
        running=lambda: False,
    )
    lines: list[str] = []
    apply.report(outcome, "no previous state", lines.append)
    assert outcome.status == apply.STATUS_INCOMPLETE
    assert "/forum/" in find(lines, "prefixes:")


def test_a_pass_scans_each_bundle_once(tmp_path: Path, monkeypatch) -> None:
    """The summary must not cost a second pass over the bytes.

    ADR 0007 measured a round at about four seconds of analysis and chose
    the read path around it; `scan_state` exists to avoid paying that when
    nothing moved. Building the log summary from a second `scan_bundle`
    pass would double it on exactly the rounds that already pay it, and
    nothing else in the add-on would notice.
    """
    one, two = row(), row(database=OTHER_DB, url=OTHER_URL, checksum=OTHER_SUM)
    store = filestore(tmp_path, (one, BUNDLE), (two, BUNDLE))
    passes: list[int] = []
    real = gate.scan_bundle

    def counted(text: str):
        passes.append(len(text))
        return real(text)

    monkeypatch.setattr(gate, "scan_bundle", counted)
    outcome, lines = round_lines(
        tmp_path, scan.ScanResult((ok(DB, one), ok(OTHER_DB, two))), filestore=store
    )
    assert outcome.status == apply.STATUS_APPLIED
    # Both halves were still built: the rule and the summary that explains it.
    assert "/forum/" in find(lines, "prefixes:")
    assert find(lines, "findings:")
    assert len(passes) == 2, (
        f"two bundles, so two passes, not {len(passes)}"
    )


# --- the log never carries an Ingress token -----------------------------------

def test_a_token_in_a_bundle_never_reaches_the_log(tmp_path: Path) -> None:
    one = row()
    store = filestore(tmp_path, (one, TOKEN_BUNDLE))
    _, lines = round_lines(tmp_path, scan.ScanResult((ok(DB, one),)), filestore=store)
    text = "\n".join(lines)
    assert "/api/hassio_ingress/" in text, "the finding itself is still reported"
    assert TOKEN not in text
    assert "<redacted>" in text


def test_a_token_in_a_database_error_never_reaches_the_log(tmp_path: Path) -> None:
    """Whatever psql says comes back verbatim, so it is masked like the rest."""
    _, lines = round_lines(
        tmp_path,
        scan.ScanResult((
            scan.DatabaseScan(
                DB, scan.STATUS_FAILED,
                error=f"could not connect: /api/hassio_ingress/{TOKEN}/db",
            ),
        )),
    )
    text = "\n".join(lines)
    assert TOKEN not in text
    assert "<redacted>" in text


def test_a_token_in_the_state_note_never_reaches_the_log(tmp_path: Path) -> None:
    _, lines = round_lines(
        tmp_path,
        scan.ScanResult((scan.DatabaseScan(EMPTY_DB, scan.STATUS_NO_BUNDLES),)),
        state_note=f"the state at /api/hassio_ingress/{TOKEN}/state.json cannot be read",
    )
    assert TOKEN not in "\n".join(lines)


def test_every_line_of_the_report_goes_through_mask(tmp_path: Path) -> None:
    """The masking is the report's, not each caller's.

    A caller that forgot would put a token in the add-on log, which is
    copied into issues and screenshots.
    """
    source = (LIB_DIR / "rewrite_apply.py").read_text(encoding="utf-8")
    body = source[source.index("def report("):]
    body = body[:body.index("\ndef ")]
    assert "gate.mask(" in body


# --- the service --------------------------------------------------------------

def test_the_rewrite_scan_is_an_s6_service_with_a_run_and_a_finish() -> None:
    assert RUN.is_file(), "the Rewrite scan runs as its own s6 service (#77)"
    assert FINISH.is_file(), "a service with no finish dies silently"
    for script in (RUN, FINISH):
        assert script.read_text(encoding="utf-8").startswith(
            "#!/usr/bin/with-contenv bashio"
        ), f"{script.name} logs with bashio, as every other service does"


def test_only_the_rewrite_scan_finish_declines_to_halt_the_container() -> None:
    """The new convention, pinned against the four that predate it.

    The other four services *are* the container: without any of them the
    add-on is not serving, so halting and letting the Supervisor restart is
    the honest answer. The Rewrite scan is the first that is not -- #77
    requires Odoo to start and keep running whatever the scan does -- so
    halting here would turn a rule that could not be generated into an
    outage.
    """
    for name in HALTING_SERVICES:
        finish = (SERVICES_DIR / name / "finish").read_text(encoding="utf-8")
        assert "/run/s6/basedir/bin/halt" in finish, (
            f"{name} is the container; its finish still halts"
        )
    code = code_of(FINISH)
    assert "halt" not in code, (
        "the Rewrite scan must never stop the container: Odoo keeps running "
        "whatever the scan does (#77)"
    )
    assert "bashio::log.error" in code, (
        "a service that died must not die silently"
    )


def test_the_service_waits_for_postgresql_the_way_the_odoo_service_does() -> None:
    run = RUN.read_text(encoding="utf-8")
    odoo = ODOO_RUN.read_text(encoding="utf-8")
    probe = "pg_isready -h 127.0.0.1 -p 5432 -U odoo -q"
    assert probe in odoo, "services.d/odoo/run is the loop this one copies"
    assert probe in run
    assert "seq 1 30" in run, "the same 30 attempts, one a second"


def test_the_service_runs_a_round_at_start_and_every_five_minutes() -> None:
    run = RUN.read_text(encoding="utf-8")
    assert str(ROUND_INTERVAL_SECONDS) in run, "five minutes between rounds (#77)"
    assert "while true" in run, "one round at start, then a round every interval"
    assert f"/usr/local/bin/{APPLY_CLI.name}" in run, (
        "the round is the shipped CLI, which is where the option and the "
        "state live (#93)"
    )
    # A typo in that path is a round that exits 127 every five minutes, and
    # the Static tier is the only place it can be caught.
    assert APPLY_CLI.is_file()


def test_a_failed_round_neither_ends_the_service_nor_goes_unlogged() -> None:
    """The five-minute loop is the retry; a bad round is a warning, not an exit.

    `set -e` would make the first round that exits 1 -- an incomplete scan,
    or a candidate nginx refused -- end the service, and the add-on would
    stop updating its rules for as long as it kept running.
    """
    code = code_of(RUN)
    assert "set -e" not in code, (
        "a non-zero round must not end the loop; the loop is the retry"
    )
    assert "bashio::log.warning" in code, "a failed round is visible in the log"
    assert "/dev/null" not in code, (
        "the round's own report is what says which database failed"
    )


def test_the_service_waits_for_nothing_but_postgresql() -> None:
    """It must never be a step Odoo or nginx is behind.

    The scan reads `ir_attachment` through psql, so postgres is the only
    thing it needs; waiting for Odoo's HTTP port, as the nginx service
    does, would put a scan between Odoo and the gateway.
    """
    code = code_of(RUN)
    assert "8070" not in code and "curl" not in code
    for name in HALTING_SERVICES:
        other = code_of(SERVICES_DIR / name / "run")
        assert "rewrite" not in other, (
            f"services.d/{name}/run must not wait on the Rewrite scan"
        )


def test_the_service_scripts_are_covered_by_the_dockerfile_permission_list() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "chmod a+rx /etc/services.d/*/run" in dockerfile
    assert "chmod a+rx /etc/services.d/*/finish" in dockerfile


def test_an_adr_records_the_service_convention() -> None:
    adrs = sorted(ADR_DIR.glob("0009-*.md"))
    assert adrs, "issue #94 lands ADR 0009"
    text = adrs[0].read_text(encoding="utf-8")
    assert "status: accepted" in text
    # What the ticket asked to be written down: how a failed scan is
    # retried, what repeated failure does, and what `finish` contains.
    for token in ("halt", "finish", "five minutes", "retr"):
        assert token in text, f"the ADR must record {token!r}"
