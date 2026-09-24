#!/usr/bin/env python3
"""The Rewrite scan's read path: which bundles a host serves, and whether
they changed (issue #92, ADR 0005 and ADR 0007).

ADR 0005 made the add-on run the Rewrite scan itself, over "the asset
bundles every database serves (from `ir.attachment`, no login, no network)",
and rescan when their checksums change. ADR 0007 chose how that read is
done: one `psql` query per database plus the filestore, rather than an
`odoo shell` registry load. This module is that read path and the decision
that guards it.

The analysis itself lives in `literal_rewrite_gate.py` and is not imported
here; this module only says *which* bundles exist, *where* their bytes are,
and *whether* the pass is worth paying for. A round costs about four seconds
of CPU whatever the read path (ADR 0007), so `scan_state` is what keeps that
from being paid every five minutes when nothing changed.

Three shapes make the difference to the consumers in #93 and #94:

- A bundle is keyed by ``(database, url)``, never by name. One Odoo database
  serves the same bundle name under a website-scoped URL and an unscoped
  one, with different content; a name-keyed mapping loses the second.
- Every row carries its ``checksum``, which is both the change signal and
  the filestore path, so findings can be cached against it.
- A scan in which any database failed is **incomplete**. The Generated
  rewrite include is the union over databases, so a failed read makes a
  smaller union, and applying it would delete rules that were working and
  hand the operator a Prefix escape. `complete` lets #93 refuse it, and it
  is what distinguishes that case from a complete scan that honestly found
  no bundle attachments.

Only `psql_query` runs a process, only `load_state`, `save_state` and
`analysis_version` touch the disk, and the rest is pure, so the Static tier
drives the row rules and the verdict with a fake query runner and needs no
postgres.

The module must import with the standard library alone: nothing installs a
third-party package in the image.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Callable, Iterable, Mapping, Sequence

#: Where the previous state is kept, beside the include file it agrees with.
STATE_PATH = "/data/rewrite-scan-state.json"
#: The Generated rewrite include file (ADR 0005). Its absence voids the state.
GENERATED_REWRITES_PATH = "/data/nginx-generated-rewrites.conf"
#: The filestore's parent; the bytes of a bundle are under <this>/<database>/.
FILESTORE_DIR = "/data/odoo/filestore"

#: psql field and record separators. The ASCII unit and record separators,
#: rather than `|` and a newline: a bundle name is `ir_attachment.name`, free
#: text an operator can put anything into, and a name holding either of the
#: obvious separators would otherwise split one row into two or shift every
#: field after it.
FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"

#: The per-database status carried by `DatabaseScan`.
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_NO_BUNDLES = "no bundles"

# The database listing the maintenance bootstrap uses
# (odoo-maintenance-bootstrap:91-96): every database owned by the odoo role
# that carries ir_config_parameter is an Odoo database. postgres and the
# templates are never listed.
DATABASE_LIST_SQL = """SELECT datname FROM pg_database
WHERE NOT datistemplate AND datallowconn
  AND datname <> 'postgres'
  AND pg_get_userbyid(datdba) = 'odoo'
ORDER BY datname"""

IS_ODOO_SQL = "SELECT to_regclass('public.ir_config_parameter') IS NOT NULL"

# The bundle rows. `type = 'binary'` drops the `url` attachments, which carry
# no content. The mimetype allow-list, rather than a `.min.js` / `.min.css`
# suffix filter, because source maps are `application/json` and hold
# unminified source that would produce false FAIL findings, while a
# `dev_mode` install serves bundles that are not minified at all. The
# Literal rewrite location is `^~ /web/assets/`, so it covers both.
# `store_fname` is selected rather than filtered on: a NULL one
# (`ir_attachment.location = db`) is a reportable skip, not a row to hide.
BUNDLE_ROWS_SQL = """SELECT url, name, checksum, store_fname, file_size
FROM ir_attachment
WHERE url LIKE '/web/assets/%'
  AND type = 'binary'
  AND mimetype IN ('application/javascript', 'text/css')"""

#: How `psql_query` reaches postgres. The CLI runs as root because no single
#: user can both query and read the bundles: psql peer-authenticates as
#: postgres, and the filestore is odoo:odoo under umask 077
#: (10-odoo-config.sh:7,16). This is the shape
#: odoo-maintenance-bootstrap:75 already uses; no password is handled and no
#: permission is widened.
PSQL_COMMAND = (
    "s6-setuidgid", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-tA",
    "-F", FIELD_SEPARATOR, "-R", RECORD_SEPARATOR,
)

#: How long one query may take. The scan runs on a five-minute loop, so a
#: `psql` that never returns would stall every later round rather than fail
#: one; the timeout turns that into an ordinary failed database.
PSQL_TIMEOUT_SECONDS = 60

#: A query runner: `(database or None for the cluster default, sql) -> stdout`.
QueryRunner = Callable[[object, str], str]


# --- rows ---------------------------------------------------------------------

@dataclass(frozen=True)
class BundleRow:
    """One asset bundle attachment a database serves."""

    database: str
    url: str
    name: str
    checksum: str
    store_fname: str | None     # None when the content is in the database
    file_size: int

    @property
    def key(self) -> tuple[str, str]:
        """What identifies this bundle: the database and the URL it is served at.

        Not the name. One database serves the same bundle name under a
        website-scoped URL and an unscoped one, with different content.
        """
        return (self.database, self.url)

    @property
    def readable(self) -> bool:
        """Are the bytes in the filestore, where the scan can reach them?"""
        return bool(self.store_fname)


def bundle_path(row: BundleRow, filestore: str = FILESTORE_DIR) -> str | None:
    """Where this bundle's bytes are, or None when they are not in the filestore.

    `store_fname` is `<first two characters of the checksum>/<checksum>`,
    relative to the *per-database* subdirectory; `FILESTORE_DIR` names the
    parent only.
    """
    if not row.store_fname:
        return None
    return f"{filestore}/{row.database}/{row.store_fname}"


def records(output: str) -> list[str]:
    """Split `psql` output into rows on the record separator.

    Stripping each record is safe for the whitespace `psql` puts between
    them: the first field selected is a URL and the last is a number, so
    neither can begin or end with a space of its own.
    """
    return [record.strip() for record in output.split(RECORD_SEPARATOR) if record.strip()]


def read_bundle_rows(run_query: QueryRunner, database: str) -> list[BundleRow]:
    """The bundle attachments `database` serves, through the given runner.

    The runner is an argument so the Static tier can pass a fake one: there
    is no postgres in that tier and CI installs nginx only.

    A row that does not split into the five selected fields raises. Dropping
    it would mean a bundle nobody scans, which surfaces later as a missing
    rule and a Prefix escape; the caller turns the exception into a `failed`
    database, which is visible and refuses to be applied.
    """
    rows: list[BundleRow] = []
    for number, record in enumerate(records(run_query(database, BUNDLE_ROWS_SQL)), 1):
        fields = record.split(FIELD_SEPARATOR)
        if len(fields) != 5:
            raise ValueError(
                f"{database}: row {number} has {len(fields)} fields, expected 5"
            )
        url, name, checksum, store_fname, file_size = fields
        rows.append(BundleRow(
            database=database,
            url=url,
            name=name,
            checksum=checksum,
            store_fname=store_fname or None,
            file_size=int(file_size) if file_size else 0,
        ))
    return rows


# --- databases ----------------------------------------------------------------

def is_odoo_database(run_query: QueryRunner, database: str) -> bool:
    """Does this database carry `ir_config_parameter`?

    A probe that fails answers no, as it does in the maintenance bootstrap
    (`2>/dev/null || echo f`): a database that cannot be probed is not one
    this add-on owns.
    """
    try:
        return run_query(database, IS_ODOO_SQL).strip() == "t"
    except Exception:       # noqa: BLE001 - mirrors the bootstrap's `|| echo f`
        return False


def list_databases(run_query: QueryRunner) -> list[str]:
    """Every Odoo database in the cluster, the way the bootstrap lists them."""
    names = records(run_query(None, DATABASE_LIST_SQL))
    return [name for name in names if is_odoo_database(run_query, name)]


# --- the scan -----------------------------------------------------------------

@dataclass(frozen=True)
class DatabaseScan:
    """What one database answered."""

    database: str
    status: str
    rows: tuple[BundleRow, ...] = ()        # readable bundles
    skipped: tuple[BundleRow, ...] = ()     # unsupported storage
    error: str = ""


@dataclass(frozen=True)
class ScanResult:
    """What the cluster answered, per database and as a union."""

    databases: tuple[DatabaseScan, ...] = ()
    error: str = ""     # the database listing itself failed

    @property
    def rows(self) -> tuple[BundleRow, ...]:
        """The readable bundles across every database, in a stable order."""
        rows = [row for scan in self.databases for row in scan.rows]
        return tuple(sorted(rows, key=lambda row: row.key))

    @property
    def skipped(self) -> tuple[BundleRow, ...]:
        """The bundles whose bytes are not in the filestore, across every database."""
        rows = [row for scan in self.databases for row in scan.skipped]
        return tuple(sorted(rows, key=lambda row: row.key))

    @property
    def failed(self) -> tuple[str, ...]:
        """The databases that could not be read."""
        return tuple(
            scan.database for scan in self.databases if scan.status == STATUS_FAILED
        )

    @property
    def complete(self) -> bool:
        """May this result be applied?

        False when the listing failed or any database did. The union would
        be short by exactly the bundles that were not read, and writing the
        include from it would delete rules that were working.
        """
        return not self.error and not self.failed


def scan_databases(
    run_query: QueryRunner,
    databases: Sequence[str] | None = None,
) -> ScanResult:
    """Read every Odoo database's bundle rows; one failure never hides the rest."""
    if databases is None:
        try:
            databases = list_databases(run_query)
        except Exception as error:      # noqa: BLE001 - reported, never raised
            return ScanResult(error=f"the databases could not be listed: {error}")

    scans: list[DatabaseScan] = []
    for database in databases:
        try:
            rows = read_bundle_rows(run_query, database)
        except Exception as error:      # noqa: BLE001 - one database, not the pass
            scans.append(DatabaseScan(database, STATUS_FAILED, error=str(error)))
            continue
        readable = tuple(row for row in rows if row.readable)
        skipped = tuple(row for row in rows if not row.readable)
        # "No bundles" means the database serves none -- a fresh one, or one
        # just after an install and before the next request. A database that
        # serves bundles the scan cannot read is not that: it is `ok` with
        # every skip recorded, so nothing reads it as an all-clear.
        status = STATUS_NO_BUNDLES if not rows else STATUS_OK
        scans.append(DatabaseScan(database, status, readable, skipped))
    return ScanResult(tuple(scans))


def psql_query(database: object, sql: str) -> str:
    """The production query runner: the only one that reaches out of the process."""
    command = list(PSQL_COMMAND)
    if database:
        command += ["-d", str(database)]
    command += ["-c", sql]
    finished = subprocess.run(
        command, capture_output=True, text=True, timeout=PSQL_TIMEOUT_SECONDS
    )
    if finished.returncode != 0:
        detail = finished.stderr.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"psql exited {finished.returncode}")
    return finished.stdout


# --- the analysis version -----------------------------------------------------

_HERE = Path(__file__).resolve()
#: The two modules that decide what a scan produces: the classification and
#: this read path. Their hash is the state's `analysis_version`.
ANALYSIS_MODULES = (_HERE.parent / "literal_rewrite_gate.py", _HERE)


def analysis_version(paths: Iterable[Path | str] = ANALYSIS_MODULES) -> str:
    """The sha256 of the analysis modules, in order.

    Not the add-on version and not a hand-maintained constant. A Release
    that improves the classification must re-run the scan even though no
    bundle changed, and nobody has to remember to bump anything for that to
    happen.
    """
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


# --- the generation inputs ----------------------------------------------------

@dataclass(frozen=True)
class GenerationInputs:
    """What the include file was built from, besides the bundles and the analysis.

    The Shipped rewrites and the exception list both decide which prefixes
    earn a Generated rewrite, and a Release can change either without moving
    a bundle or an analysis module (issue #135). Each is a sha256 kept in
    its own field, so the verdict can name which one moved. They are worked
    out by `rewrite_apply.generation_inputs`, where the rules and the list
    are read; this module only keeps and compares them.
    """

    shipped_rules: str
    exceptions: str

    def to_dict(self) -> dict:
        return {"shipped_rules": self.shipped_rules, "exceptions": self.exceptions}

    @classmethod
    def from_dict(cls, data: object) -> "GenerationInputs":
        if not isinstance(data, dict):
            raise ValueError("generation_inputs must be a JSON object")
        shipped, exceptions = data.get("shipped_rules"), data.get("exceptions")
        if not isinstance(shipped, str) or not isinstance(exceptions, str):
            raise ValueError("generation_inputs must carry shipped_rules and exceptions")
        return cls(shipped_rules=shipped, exceptions=exceptions)


# --- the state ----------------------------------------------------------------

@dataclass(frozen=True)
class ScanState:
    """The previous pass: what was served, what analysed it, and what else
    the include file was built from."""

    analysis_version: str
    bundles: Mapping[tuple[str, str], str]      # (database, url) -> checksum
    # None for a state written before issue #135, which cannot say what the
    # include file was built from, so the next round takes the pass.
    inputs: GenerationInputs | None = None

    def to_dict(self) -> dict:
        databases: dict[str, dict[str, str]] = {}
        for (database, url), checksum in self.bundles.items():
            databases.setdefault(database, {})[url] = checksum
        data = {"analysis_version": self.analysis_version, "databases": databases}
        if self.inputs is not None:
            data["generation_inputs"] = self.inputs.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: object) -> "ScanState":
        if not isinstance(data, dict):
            raise ValueError("the state must be a JSON object")
        version, databases = data.get("analysis_version"), data.get("databases")
        if not isinstance(version, str) or not version:
            raise ValueError("analysis_version must be a non-empty string")
        if not isinstance(databases, dict):
            raise ValueError("databases must be a JSON object")
        bundles: dict[tuple[str, str], str] = {}
        for database, urls in databases.items():
            if not isinstance(urls, dict):
                raise ValueError(f"{database}: the bundles must be a JSON object")
            for url, checksum in urls.items():
                if not isinstance(checksum, str):
                    raise ValueError(f"{database} {url}: the checksum must be a string")
                bundles[(database, url)] = checksum
        inputs = data.get("generation_inputs")
        return cls(
            analysis_version=version, bundles=bundles,
            inputs=GenerationInputs.from_dict(inputs) if inputs is not None else None,
        )


def state_from_rows(
    rows: Iterable[BundleRow],
    version: str | None = None,
    *,
    inputs: GenerationInputs | None = None,
) -> ScanState:
    """The state to keep once a pass over these rows has been applied."""
    return ScanState(
        analysis_version=version if version is not None else analysis_version(),
        bundles={row.key: row.checksum for row in rows},
        inputs=inputs,
    )


@dataclass(frozen=True)
class StateLoad:
    """A previous state, or the reason there is none to use."""

    state: ScanState | None
    reason: str = ""


def load_state(
    path: str | os.PathLike = STATE_PATH,
    include_path: str | os.PathLike = GENERATED_REWRITES_PATH,
) -> StateLoad:
    """The previous state, or `None` with the reason it is treated as absent.

    The state is absent when it cannot be read or cannot be parsed, and also
    when the include file it describes is gone. That second rule is what
    repairs a deleted or rolled-back include: nothing else does, because
    `10-odoo-config.sh:257-267` writes that file only when it is missing, so
    a state that claimed "no change" would keep the rules away for good.
    """
    if not Path(include_path).exists():
        return StateLoad(None, f"the include file {include_path} is absent")
    if not Path(path).exists():
        return StateLoad(None, f"no previous state file at {path}")
    try:
        state = ScanState.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception as error:      # noqa: BLE001 - any unusable state is absent
        return StateLoad(None, f"the state at {path} cannot be read: {error}")
    return StateLoad(state)


def save_state(path: str | os.PathLike, state: ScanState) -> None:
    """Write the state, atomically, readable by more than root.

    cont-init runs under `umask 077` and gives the include file beside this
    one an explicit 0644 for the same reason: the file lives on the /data
    volume, so its mode is set here rather than in the image's chmod list.
    """
    path = Path(path)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(
        json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


# --- the verdict --------------------------------------------------------------

@dataclass(frozen=True)
class ScanVerdict:
    """Whether a pass over the bundles is due, and what moved."""

    rescan: bool
    reason: str
    added: tuple[tuple[str, str], ...] = ()
    changed: tuple[tuple[str, str], ...] = ()
    removed: tuple[tuple[str, str], ...] = ()


def scan_state(
    rows: Iterable[BundleRow],
    previous_state: ScanState | None,
    *,
    version: str | None = None,
    inputs: GenerationInputs | None = None,
) -> ScanVerdict:
    """Is a Rewrite scan due?

    Due on a new bundle attachment, a changed checksum, a removed
    attachment, an absent previous state, a state written by a different
    analysis, or -- when `inputs` is given -- a change of the Shipped
    rewrites or the exception list, or a state that records neither. Not
    otherwise -- a pass costs about four seconds of CPU per round (ADR 0007)
    and the loop runs every five minutes.

    `inputs` is None only for a caller that does not read the rendered
    gateway, which is the read-only `odoo-rewrite-scan`; the generation
    inputs are then not compared.

    A regenerated bundle usually arrives as a removal plus an addition
    rather than a same-URL checksum change, because the `unique` segment is
    part of the URL. All three mean the same thing here.

    Finding no bundle attachments at all is never a failure: a fresh
    database, or one just after an install and before the next request, has
    nothing to scan and says so.
    """
    version = version if version is not None else analysis_version()
    current = {row.key: row.checksum for row in rows}
    if previous_state is None:
        return ScanVerdict(True, "no previous state", added=tuple(sorted(current)))
    if previous_state.analysis_version != version:
        return ScanVerdict(True, "the analysis version changed")

    previous = dict(previous_state.bundles)
    added = tuple(sorted(key for key in current if key not in previous))
    removed = tuple(sorted(key for key in previous if key not in current))
    changed = tuple(sorted(
        key for key, checksum in current.items()
        if key in previous and previous[key] != checksum
    ))
    reasons: list[str] = []
    if inputs is not None:
        previous_inputs = previous_state.inputs
        if previous_inputs is None:
            reasons.append("the previous state records no generation inputs")
        else:
            if previous_inputs.shipped_rules != inputs.shipped_rules:
                reasons.append("the Shipped rewrites changed")
            if previous_inputs.exceptions != inputs.exceptions:
                reasons.append("the exception list changed")
    if added or changed or removed:
        reasons.append(f"{len(added)} added, {len(changed)} changed, {len(removed)} removed")
    if not reasons:
        return ScanVerdict(False, f"no change across {len(current)} bundles")
    return ScanVerdict(
        True, "; ".join(reasons), added=added, changed=changed, removed=removed,
    )
