#!/usr/bin/env python3
"""Static-tier contracts for the Rewrite scan's read path (issue #92, ADR 0007).

The add-on decides for itself which asset bundles a database serves and
whether they changed since the last pass. ADR 0007 chose the cheap read:
one `psql` query against `ir_attachment` plus the filestore, no Odoo
registry. This file pins the pure half of that -- listing the databases,
turning query output into rows, the per-database status, and the rescan
verdict -- with a fake query runner, so the Static tier needs no postgres
and no live Odoo.

The module is loaded by path, the way `test_literal_rewrite_gate.py:25`
loads its own.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "rootfs/usr/local/lib/rewrite_scan.py"
GATE_LIB = ROOT / "rootfs/usr/local/lib/literal_rewrite_gate.py"
CLI = ROOT / "rootfs/usr/local/bin/odoo-rewrite-scan"
DOCKERFILE = ROOT / "Dockerfile"
BOOTSTRAP = ROOT / "rootfs/usr/local/bin/odoo-maintenance-bootstrap"
ADR_DIR = ROOT.parent / "docs/adr"


def load_module(path: Path, name: str):
    # The CLI has no .py suffix, so the loader is named rather than guessed.
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    # The module annotates its dataclasses lazily and dataclasses resolves
    # those annotations through sys.modules, so it is registered first.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan = load_module(LIB, "rewrite_scan")
# The CLI loads its libraries by path from /usr/local/lib; here they are in
# the tree instead, which is the reason the override exists.
os.environ["ODOO_REWRITE_SCAN_LIB"] = str(LIB.parent)
cli = load_module(CLI, "odoo_rewrite_scan_cli")

# Documentation names only; no real database or host here.
DB = "odoo_test"
OTHER_DB = "odoo_other"

# One file served under two URLs under one name, which is what a real Odoo 18
# database holds: the website-scoped bundle and the unscoped one.
SHARED_NAME = "web.assets_web.min.js"
URL_A = "/web/assets/1/8c63e6a/" + SHARED_NAME
URL_B = "/web/assets/2b4d1f0/" + SHARED_NAME
SUM_A = "7683fa082aaa53fd969289bc141aa78853af2d7c"
SUM_B = "0f1e2d3c4b5a69788796a5b4c3d2e1f009182736"

VERSION = "0" * 64
OTHER_VERSION = "1" * 64


def row(database=DB, url=URL_A, name=SHARED_NAME, checksum=SUM_A,
        store_fname=None, file_size=6585684):
    if store_fname is None:
        store_fname = f"{checksum[:2]}/{checksum}"
    return scan.BundleRow(
        database=database, url=url, name=name, checksum=checksum,
        store_fname=store_fname, file_size=file_size,
    )


def query_output(*rows) -> str:
    """What `psql -tA -F <sep> -R <sep>` prints for these rows."""
    records = [
        scan.FIELD_SEPARATOR.join([
            one.url, one.name, one.checksum, one.store_fname or "", str(one.file_size),
        ])
        for one in rows
    ]
    return "".join(record + scan.RECORD_SEPARATOR for record in records)


def fake_runner(bundles, odoo=None, fail=(), unreachable=()):
    """A stand-in for `psql`: a mapping of database -> the rows it holds.

    `odoo` names the databases that answer the `ir_config_parameter` probe
    (every one in `bundles` by default); `fail` names the databases whose
    bundle query raises, the way a dropped connection mid-pass would; and
    `unreachable` names the ones that cannot even be probed.
    """
    odoo = set(bundles if odoo is None else odoo)

    def run_query(database, sql):
        if database is None:
            return "".join(name + scan.RECORD_SEPARATOR for name in sorted(bundles))
        if database in unreachable:
            raise RuntimeError(f"psql: {database}: could not connect")
        if "ir_config_parameter" in sql:
            return ("t" if database in odoo else "f") + scan.RECORD_SEPARATOR
        if database in fail:
            raise RuntimeError(f"psql: {database}: connection failed")
        return query_output(*bundles.get(database, ()))

    return run_query


# --- the query ----------------------------------------------------------------

def test_the_bundle_query_is_the_settled_one() -> None:
    sql = scan.BUNDLE_ROWS_SQL
    assert "FROM ir_attachment" in sql
    assert "url LIKE '/web/assets/%'" in sql
    # type = 'url' rows carry no content, so they are excluded here rather
    # than filtered out of the rows afterwards.
    assert "type = 'binary'" in sql
    # The mimetype allow-list, not a .min suffix filter: source maps are
    # application/json and hold unminified source (false FAIL findings),
    # while a dev_mode install serves bundles that are not minified at all
    # and the Literal rewrite location covers both.
    assert "mimetype IN ('application/javascript', 'text/css')" in sql
    assert ".min.js" not in sql and "json" not in sql
    # store_fname is selected, not filtered on: a NULL is a reportable skip.
    assert "store_fname IS NOT NULL" not in sql
    for column in ("url", "name", "checksum", "store_fname", "file_size"):
        assert column in sql


def test_databases_are_listed_the_way_the_maintenance_bootstrap_lists_them() -> None:
    sql = scan.DATABASE_LIST_SQL
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    for clause in (
        "NOT datistemplate",
        "datallowconn",
        "datname <> 'postgres'",
        "pg_get_userbyid(datdba) = 'odoo'",
    ):
        assert clause in sql, f"the database listing must keep {clause!r}"
        assert clause in bootstrap, f"the bootstrap no longer uses {clause!r}"
    assert "ir_config_parameter" in scan.IS_ODOO_SQL


def test_only_odoo_databases_are_listed() -> None:
    # The fake cluster answers the listing with a database that carries no
    # ir_config_parameter; postgres and the templates never reach this point
    # because the listing SQL excludes them in the server.
    run_query = fake_runner({DB: (), "plain_db": ()}, odoo={DB})
    assert scan.list_databases(run_query) == [DB]


def test_a_database_that_cannot_be_probed_is_not_listed() -> None:
    run_query = fake_runner({DB: (), OTHER_DB: ()}, unreachable={OTHER_DB})
    assert scan.list_databases(run_query) == [DB]


# --- rows ---------------------------------------------------------------------

def test_read_bundle_rows_takes_the_query_runner_and_needs_no_postgres() -> None:
    expected = row()
    calls = []

    def run_query(database, sql):
        calls.append((database, sql))
        return query_output(expected)

    assert scan.read_bundle_rows(run_query, DB) == [expected]
    assert calls == [(DB, scan.BUNDLE_ROWS_SQL)]


def test_rows_are_keyed_by_database_and_url_never_by_name() -> None:
    first, second = row(url=URL_A, checksum=SUM_A), row(url=URL_B, checksum=SUM_B)
    assert first.name == second.name
    rows = scan.read_bundle_rows(fake_runner({DB: (first, second)}), DB)
    assert len(rows) == 2, "a same-name bundle must not displace the first sighting"
    assert {r.key for r in rows} == {(DB, URL_A), (DB, URL_B)}
    assert {r.key: r.checksum for r in rows} == {(DB, URL_A): SUM_A, (DB, URL_B): SUM_B}


def test_the_same_url_in_two_databases_is_two_rows() -> None:
    here, there = row(database=DB), row(database=OTHER_DB)
    assert here.key != there.key


def test_a_null_store_fname_is_an_unsupported_storage_skip_not_a_failure() -> None:
    stored_in_db = row(url=URL_B, checksum=SUM_B, store_fname="")
    result = scan.scan_databases(fake_runner({DB: (row(), stored_in_db)}))
    database = result.databases[0]
    assert database.status == scan.STATUS_OK
    assert [r.url for r in database.rows] == [URL_A]
    assert [r.url for r in database.skipped] == [URL_B]
    assert result.complete, "an unreadable row must not make the scan incomplete"
    # psql prints a NULL as an empty field; the row carries it as None.
    assert database.skipped[0].store_fname is None
    assert not database.skipped[0].readable and database.rows[0].readable


def test_a_malformed_row_fails_its_database_rather_than_being_dropped() -> None:
    # A dropped row is a bundle nobody scans, so it would show up as a
    # missing rule and a Prefix escape. Failing the database is visible.
    def run_query(database, sql):
        return "not-five-fields" + scan.RECORD_SEPARATOR

    with pytest.raises(ValueError):
        scan.read_bundle_rows(run_query, DB)


def test_the_query_is_the_only_filter() -> None:
    # The exclusions happen in postgres, so the module keeps every row the
    # query returned, whatever it holds. A filter repeated here would make
    # BUNDLE_ROWS_SQL no longer the authority on what is scanned, and the
    # test above it would stop meaning anything.
    #
    # A source map is what the mimetype allow-list drops (application/json,
    # unminified source, false FAIL findings), so it can never come back;
    # an unminified bundle is what a dev_mode install serves and must be
    # scanned. Neither is filtered here.
    source_map = row(url="/web/assets/1/8c63e6a/web.assets_web.min.js.map",
                     name="web.assets_web.min.js.map")
    unminified = row(url="/web/assets/1/8c63e6a/web.assets_web.js",
                     name="web.assets_web.js", checksum=SUM_B)
    assert scan.read_bundle_rows(
        fake_runner({DB: (source_map, unminified)}), DB
    ) == [source_map, unminified]


def test_a_name_holding_a_newline_or_a_pipe_still_reads_as_one_row() -> None:
    # `ir_attachment.name` is free text an operator can write anything into,
    # which is why the separators are the ASCII unit and record characters
    # rather than `|` and a newline.
    awkward = row(name="web.assets|weird\nname.min.js")
    assert scan.read_bundle_rows(fake_runner({DB: (awkward,)}), DB) == [awkward]


def test_the_filestore_path_is_the_per_database_subdirectory() -> None:
    assert scan.bundle_path(row()) == f"{scan.FILESTORE_DIR}/{DB}/{SUM_A[:2]}/{SUM_A}"
    assert scan.bundle_path(row(store_fname="")) is None


# --- the per-database status --------------------------------------------------

def test_a_database_whose_every_bundle_is_unreadable_is_not_no_bundles() -> None:
    # It serves bundles; the scan just cannot reach their bytes. Calling that
    # "no bundles" would read to #94 as an all-clear for a database whose
    # rules nobody checked.
    result = scan.scan_databases(fake_runner({DB: (row(store_fname=""),)}))
    database = result.databases[0]
    assert database.status == scan.STATUS_OK
    assert database.rows == () and len(database.skipped) == 1
    assert result.complete


def test_a_database_with_no_bundle_attachments_is_nothing_to_do() -> None:
    result = scan.scan_databases(fake_runner({DB: ()}))
    assert result.databases[0].status == scan.STATUS_NO_BUNDLES
    assert result.complete, "a fresh database is not a failure"
    assert result.rows == ()
    assert result.error == ""


def test_no_database_at_all_is_a_complete_scan() -> None:
    result = scan.scan_databases(fake_runner({}))
    assert result.databases == ()
    assert result.complete
    assert result.rows == ()


def test_one_failed_database_is_recorded_and_the_others_still_count() -> None:
    result = scan.scan_databases(
        fake_runner({DB: (row(),), OTHER_DB: (row(database=OTHER_DB),)}, fail={OTHER_DB})
    )
    statuses = {d.database: d.status for d in result.databases}
    assert statuses == {DB: scan.STATUS_OK, OTHER_DB: scan.STATUS_FAILED}
    # The union still carries the database that answered.
    assert [r.key for r in result.rows] == [(DB, URL_A)]
    assert not result.complete, "#93 must refuse to apply this"
    assert result.failed == (OTHER_DB,)
    assert "connection failed" in dict(
        (d.database, d.error) for d in result.databases
    )[OTHER_DB]


def test_rows_are_the_union_across_databases() -> None:
    result = scan.scan_databases(fake_runner({
        DB: (row(), row(url=URL_B, checksum=SUM_B)),
        OTHER_DB: (row(database=OTHER_DB),),
    }))
    assert [r.key for r in result.rows] == [
        (OTHER_DB, URL_A), (DB, URL_A), (DB, URL_B),
    ]
    assert result.complete


def test_an_incomplete_scan_is_distinguishable_from_one_that_found_no_bundles() -> None:
    empty = scan.scan_databases(fake_runner({DB: ()}))
    broken = scan.scan_databases(fake_runner({DB: ()}, fail={DB}))
    assert empty.rows == broken.rows == ()
    # Same union, opposite meanings.
    assert empty.complete and not broken.complete
    assert empty.databases[0].status == scan.STATUS_NO_BUNDLES
    assert broken.databases[0].status == scan.STATUS_FAILED


def test_a_failed_database_listing_fails_the_whole_scan() -> None:
    def run_query(database, sql):
        raise RuntimeError("psql: the cluster is not accepting connections")

    result = scan.scan_databases(run_query)
    assert result.databases == ()
    assert not result.complete
    assert "not accepting connections" in result.error


# --- the verdict --------------------------------------------------------------

def state_of(*rows, version=VERSION):
    return scan.state_from_rows(rows, version)


def test_an_unchanged_set_of_bundles_is_not_rescanned() -> None:
    rows = [row(), row(url=URL_B, checksum=SUM_B)]
    verdict = scan.scan_state(rows, state_of(*rows), version=VERSION)
    assert not verdict.rescan
    assert verdict.added == verdict.changed == verdict.removed == ()


def test_a_new_bundle_attachment_is_rescanned() -> None:
    previous = state_of(row())
    verdict = scan.scan_state([row(), row(url=URL_B, checksum=SUM_B)], previous, version=VERSION)
    assert verdict.rescan
    assert verdict.added == ((DB, URL_B),)
    assert verdict.changed == verdict.removed == ()


def test_a_changed_checksum_is_rescanned() -> None:
    verdict = scan.scan_state([row(checksum=SUM_B)], state_of(row(checksum=SUM_A)), version=VERSION)
    assert verdict.rescan
    assert verdict.changed == ((DB, URL_A),)
    assert verdict.added == verdict.removed == ()


def test_a_removed_attachment_is_rescanned() -> None:
    previous = state_of(row(), row(url=URL_B, checksum=SUM_B))
    verdict = scan.scan_state([row()], previous, version=VERSION)
    assert verdict.rescan
    assert verdict.removed == ((DB, URL_B),)
    assert verdict.added == verdict.changed == ()


def test_a_regenerated_bundle_arrives_as_a_removal_and_an_addition() -> None:
    # The `unique` segment is part of the URL, so the ORM usually replaces a
    # bundle rather than changing one in place. Both verdicts mean rescan.
    verdict = scan.scan_state(
        [row(url=URL_B, checksum=SUM_B)], state_of(row(url=URL_A, checksum=SUM_A)),
        version=VERSION,
    )
    assert verdict.rescan
    assert verdict.added == ((DB, URL_B),)
    assert verdict.removed == ((DB, URL_A),)


def test_an_empty_database_that_was_already_empty_is_nothing_to_do() -> None:
    verdict = scan.scan_state([], state_of(), version=VERSION)
    assert not verdict.rescan
    assert "no change" in verdict.reason


def test_no_previous_state_is_a_rescan() -> None:
    verdict = scan.scan_state([row()], None, version=VERSION)
    assert verdict.rescan
    assert "no previous state" in verdict.reason


def test_a_different_analysis_version_forces_a_rescan() -> None:
    previous = state_of(row(), version=OTHER_VERSION)
    verdict = scan.scan_state([row()], previous, version=VERSION)
    assert verdict.rescan
    assert "analysis version" in verdict.reason
    # The bundles are identical; only the classification moved.
    assert verdict.added == verdict.changed == verdict.removed == ()


# The generation inputs outside the analysis modules (issue #135): what the
# Shipped rewrites and the exception list were when the include was built.
INPUTS = scan.GenerationInputs(shipped_rules="a" * 64, exceptions="b" * 64)


def test_a_change_of_the_shipped_rewrites_forces_a_rescan() -> None:
    previous = scan.state_from_rows([row()], VERSION, inputs=INPUTS)
    moved = scan.GenerationInputs(shipped_rules="c" * 64, exceptions=INPUTS.exceptions)
    verdict = scan.scan_state([row()], previous, version=VERSION, inputs=moved)
    assert verdict.rescan
    assert "Shipped rewrites changed" in verdict.reason
    assert "exception list" not in verdict.reason
    assert verdict.added == verdict.changed == verdict.removed == ()


def test_a_change_of_the_exception_list_forces_a_rescan() -> None:
    previous = scan.state_from_rows([row()], VERSION, inputs=INPUTS)
    moved = scan.GenerationInputs(shipped_rules=INPUTS.shipped_rules, exceptions="c" * 64)
    verdict = scan.scan_state([row()], previous, version=VERSION, inputs=moved)
    assert verdict.rescan
    assert "exception list changed" in verdict.reason
    assert "Shipped" not in verdict.reason


def test_unchanged_generation_inputs_are_not_a_rescan() -> None:
    previous = scan.state_from_rows([row()], VERSION, inputs=INPUTS)
    verdict = scan.scan_state([row()], previous, version=VERSION, inputs=INPUTS)
    assert not verdict.rescan


def test_a_state_that_records_no_generation_inputs_is_a_rescan_once() -> None:
    """A state written before #135 cannot say what the include was built from."""
    previous = scan.state_from_rows([row()], VERSION)
    verdict = scan.scan_state([row()], previous, version=VERSION, inputs=INPUTS)
    assert verdict.rescan
    assert "generation inputs" in verdict.reason


def test_the_generation_inputs_round_trip_through_the_state_file(tmp_path) -> None:
    path, include = tmp_path / "state.json", tmp_path / "include.conf"
    include.write_text("", encoding="utf-8")
    state = scan.state_from_rows([row()], VERSION, inputs=INPUTS)
    scan.save_state(path, state)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["generation_inputs"] == {
        "shipped_rules": INPUTS.shipped_rules, "exceptions": INPUTS.exceptions,
    }
    loaded = scan.load_state(path, include)
    assert loaded.state == state


def test_a_state_file_written_before_the_generation_inputs_still_loads(tmp_path) -> None:
    path, include = tmp_path / "state.json", tmp_path / "include.conf"
    include.write_text("", encoding="utf-8")
    path.write_text(json.dumps({
        "analysis_version": VERSION, "databases": {DB: {URL_A: SUM_A}},
    }), encoding="utf-8")
    loaded = scan.load_state(path, include)
    assert loaded.state is not None, loaded.reason
    assert loaded.state.inputs is None
    # Not a match: the next round takes the pass and records the inputs.
    assert scan.scan_state([row()], loaded.state, version=VERSION, inputs=INPUTS).rescan


# --- the analysis version -----------------------------------------------------

def test_the_analysis_version_is_the_hash_of_both_analysis_modules(tmp_path) -> None:
    gate, module = tmp_path / "gate.py", tmp_path / "scan.py"
    gate.write_text("a", encoding="utf-8")
    module.write_text("b", encoding="utf-8")
    first = scan.analysis_version((gate, module))
    assert len(first) == 64
    # A change in either module is a new version.
    gate.write_text("c", encoding="utf-8")
    assert scan.analysis_version((gate, module)) != first
    module.write_text("d", encoding="utf-8")
    assert scan.analysis_version((gate, module)) != first


def test_the_analysis_version_defaults_to_the_shipped_modules() -> None:
    assert scan.analysis_version() == scan.analysis_version((GATE_LIB, LIB))
    # Not the add-on version, and not a hand-maintained constant.
    text = LIB.read_text(encoding="utf-8")
    assert "config.yaml" not in text


# --- the state file -----------------------------------------------------------

def test_the_state_lives_beside_the_include_file() -> None:
    assert scan.STATE_PATH == "/data/rewrite-scan-state.json"
    assert scan.GENERATED_REWRITES_PATH == "/data/nginx-generated-rewrites.conf"


def test_a_saved_state_round_trips_and_carries_the_analysis_version(tmp_path) -> None:
    path, include = tmp_path / "state.json", tmp_path / "include.conf"
    include.write_text("", encoding="utf-8")
    state = state_of(row(), row(url=URL_B, checksum=SUM_B))
    scan.save_state(path, state)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["analysis_version"] == VERSION
    assert stored["databases"] == {DB: {URL_A: SUM_A, URL_B: SUM_B}}

    loaded = scan.load_state(path, include)
    assert loaded.reason == ""
    assert loaded.state == state
    assert not scan.scan_state([row(), row(url=URL_B, checksum=SUM_B)],
                               loaded.state, version=VERSION).rescan


def test_the_state_file_is_readable_by_more_than_root(tmp_path) -> None:
    path, state = tmp_path / "state.json", state_of(row())
    scan.save_state(path, state)
    if os.name == "posix":
        # cont-init runs under umask 077; the include file beside it is made
        # 0644 for the same reason.
        assert oct(path.stat().st_mode & 0o777) == "0o644"


def test_an_absent_state_file_is_absent(tmp_path) -> None:
    include = tmp_path / "include.conf"
    include.write_text("", encoding="utf-8")
    loaded = scan.load_state(tmp_path / "missing.json", include)
    assert loaded.state is None
    assert "no previous state file" in loaded.reason


def test_an_unreadable_state_is_treated_as_absent(tmp_path) -> None:
    path, include = tmp_path / "state.json", tmp_path / "include.conf"
    include.write_text("", encoding="utf-8")
    # A directory in its place is the readable shape of "cannot be read" on
    # every platform; a 000 file is not, since this tier also runs as root.
    path.mkdir()
    loaded = scan.load_state(path, include)
    assert loaded.state is None
    assert "cannot be read" in loaded.reason


@pytest.mark.parametrize("text,why", [
    ("{not json", "cannot be read"),
    ("[]", "cannot be read"),
    ('{"databases": {}}', "cannot be read"),
    ('{"analysis_version": 7, "databases": {}}', "cannot be read"),
    ('{"analysis_version": "x", "databases": {"db": ["url"]}}', "cannot be read"),
    ('{"analysis_version": "x", "databases": {}, "generation_inputs": "y"}', "cannot be read"),
    ('{"analysis_version": "x", "databases": {}, "generation_inputs": {"shipped_rules": "y"}}',
     "cannot be read"),
])
def test_an_unparseable_state_is_treated_as_absent(tmp_path, text, why) -> None:
    path, include = tmp_path / "state.json", tmp_path / "include.conf"
    include.write_text("", encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    loaded = scan.load_state(path, include)
    assert loaded.state is None
    assert why in loaded.reason


def test_a_missing_include_file_makes_the_state_absent(tmp_path) -> None:
    # The include file was deleted or restored from an older backup. Nothing
    # else repairs it: 10-odoo-config.sh writes it only when it is absent, so
    # without this the rules never come back.
    path = tmp_path / "state.json"
    scan.save_state(path, state_of(row()))
    loaded = scan.load_state(path, tmp_path / "missing.conf")
    assert loaded.state is None
    assert "include file" in loaded.reason
    assert scan.scan_state([row()], loaded.state, version=VERSION).rescan


# --- the CLI ------------------------------------------------------------------

def run_cli(tmp_path, bundles, **kwargs):
    include = tmp_path / "include.conf"
    include.write_text("", encoding="utf-8")
    stdout = []
    code = cli.main(
        ["--state", str(tmp_path / "state.json"), "--include", str(include)],
        run_query=fake_runner(bundles, **kwargs),
        version=VERSION,
        out=stdout.append,
    )
    return code, "\n".join(stdout)


def test_the_cli_prints_the_rows_the_statuses_and_the_verdict(tmp_path) -> None:
    code, text = run_cli(tmp_path, {
        DB: (row(), row(url=URL_B, checksum=SUM_B, store_fname="")),
        OTHER_DB: (),
    })
    assert code == 0
    assert URL_A in text and SUM_A in text
    assert scan.STATUS_OK in text and scan.STATUS_NO_BUNDLES in text
    # The unreadable row is reported as a skip, with its reason.
    assert URL_B in text and "unsupported storage" in text
    assert "rescan" in text and "no previous state" in text
    assert VERSION in text


def test_the_cli_reports_an_incomplete_scan_with_a_non_zero_status(tmp_path) -> None:
    code, text = run_cli(tmp_path, {DB: (row(),), OTHER_DB: ()}, fail={OTHER_DB})
    assert code == 1
    assert scan.STATUS_FAILED in text
    assert "complete: no" in text


def test_the_cli_masks_the_ingress_token(tmp_path) -> None:
    leaked = row(url="/web/assets/1/api/hassio_ingress/secret-token-value/x.min.js")
    _, text = run_cli(tmp_path, {DB: (leaked,)})
    assert "secret-token-value" not in text
    assert "<redacted>" in text


def test_the_cli_never_writes_the_state_file(tmp_path) -> None:
    # It is a debugging tool. Recording a state here would make the next real
    # pass believe the scan that never happened had already been applied.
    run_cli(tmp_path, {DB: (row(),)})
    assert not (tmp_path / "state.json").exists()
    assert "save_state" not in CLI.read_text(encoding="utf-8")


def test_the_cli_queries_through_s6_setuidgid_postgres() -> None:
    # psql peer-authenticates as postgres; the filestore is odoo:odoo under
    # umask 077, so the CLI runs as root and drops to each user in turn.
    assert scan.PSQL_COMMAND[:3] == ("s6-setuidgid", "postgres", "psql")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert "s6-setuidgid postgres psql" in bootstrap
    # Both separators are passed, or the row rules above test a shape psql
    # does not produce.
    assert ("-F", scan.FIELD_SEPARATOR) == scan.PSQL_COMMAND[-4:-2]
    assert ("-R", scan.RECORD_SEPARATOR) == scan.PSQL_COMMAND[-2:]


def test_a_query_that_never_returns_cannot_stall_the_five_minute_loop() -> None:
    assert 0 < scan.PSQL_TIMEOUT_SECONDS < 300
    assert "timeout=PSQL_TIMEOUT_SECONDS" in LIB.read_text(encoding="utf-8")


# --- the import chain ---------------------------------------------------------

def top_level_imports(path: Path) -> set[str]:
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("path", [LIB, CLI, GATE_LIB], ids=lambda p: p.name)
def test_the_scan_imports_with_the_standard_library_alone(path) -> None:
    # Nothing installs a third-party package in the image: the only Python
    # that ships today uses the standard library only, and PyYAML is a test
    # requirement. This ticket is the first code that imports the analysis
    # module inside the container, so `import yaml` may not sit at the top
    # of it; load_exceptions() is the one function that needs it.
    outside = top_level_imports(path) - sys.stdlib_module_names
    assert not outside, f"{path.name} imports {sorted(outside)} at module level"


def test_the_gate_still_parses_the_exception_list() -> None:
    gate = load_module(GATE_LIB, "literal_rewrite_gate_for_yaml_check")
    exceptions = gate.load_exceptions(
        (ROOT / "rootfs/usr/local/lib/literal_rewrite_exceptions.yaml").read_text(encoding="utf-8")
    )
    assert exceptions, "moving the import must not lose the exception list"


def test_the_cli_runs_without_site_packages() -> None:
    # `-S` drops site-packages from sys.path, which is where PyYAML lives in
    # CI. The Static tier cannot see into the built image; this is the
    # nearest thing to it that runs offline.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["ODOO_REWRITE_SCAN_LIB"] = str(LIB.parent)
    probe = subprocess.run(
        [sys.executable, "-S", "-E", "-c", "import yaml"],
        capture_output=True, text=True, env=env,
    )
    if probe.returncode == 0:
        pytest.skip("PyYAML is importable without site-packages here")
    result = subprocess.run(
        [sys.executable, "-S", "-E", str(CLI), "--help"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr


# --- shipped-file contracts ---------------------------------------------------

def test_the_new_files_are_in_the_dockerfile_permission_list() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "chmod a+rx /usr/local/bin/odoo-rewrite-scan" in dockerfile, (
        "the CLI must be executable, like odoo-maintenance-bootstrap"
    )
    library = next(
        line for line in dockerfile.splitlines() if "/usr/local/lib/rewrite_scan.py" in line
    )
    assert "a+r" in library, "the module must be readable by the user the scan runs as"


def test_this_ticket_changes_no_service_or_gateway_file() -> None:
    # 3a is the read path only. The s6 service, the nginx reload and the
    # option belong to #93 and #94.
    text = LIB.read_text(encoding="utf-8") + CLI.read_text(encoding="utf-8")
    assert "services.d" not in text
    assert "nginx -s reload" not in text
    assert "literal_rewrite_auto" not in text


def test_an_adr_records_the_chosen_read_path() -> None:
    adrs = sorted(ADR_DIR.glob("0007-*.md"))
    assert adrs, "issue #92 lands ADR 0007"
    text = adrs[0].read_text(encoding="utf-8")
    # Lowercase, as every ADR before it writes its status.
    assert "status: accepted" in text
    # Read time, scan time and peak memory for both options, from the
    # measurement on the populated database.
    for token in ("odoo shell", "psql", "filestore", "peak", "4.71", "4.17"):
        assert token in text, f"the ADR must record {token!r}"
