#!/usr/bin/env python3
"""The Canonical URL catch-up: the default website's domain, written after
a start for a `website` module that arrived after it (issue #164).

The maintenance bootstrap writes the Canonical URL into `web.base.url` for
every database on every start and mirrors it into the default website's
`domain` -- but only when the `website` module is in the registry at that
moment. A `website` installed later, through the Apps screen, keeps an
empty domain until the next restart, and under Ingress Odoo then builds the
home page's canonical, `og:url` and `og:image` links from the request
address instead of the Canonical URL (P-5, U-D8 in the parity plan).

This module is the second step of the Rewrite scan service's round. Per
database it makes one cheap decision through `psql` -- the same listing the
scan uses (`rewrite_scan.DATABASE_LIST_SQL`, `IS_ODOO_SQL`), then whether
the `website` table exists and what the default website's domain holds --
and only for a database that needs it runs the maintenance library through
`odoo shell`, exactly as the bootstrap does. In the steady state every
database is up to date and a round costs three queries per database and no
registry load at all (ADR 0007's reason for reading through `psql`).

The Canonical URL is the one this start settled on: `canonical_url()` in
the maintenance library, fed the same three inputs the bootstrap feeds it.
Nothing here asks the Supervisor (ADR 0006: one start, one address). With
no Canonical URL this start there is nothing to write and nothing is said,
because the bootstrap already said "unprotected" once, and saying it again
every five minutes would be noise.

`literal_rewrite_auto` does not gate this step: that option freezes
Generated rewrites, not the Canonical URL.

Every line printed is either the maintenance library's own
``maintenance db=<name>: ...`` line, forwarded as it came, or a line in that
shape carrying ``WARNING``; the wrapper CLI forwards them at the level the
bootstrap uses. Every line goes through `mask()`: a `psql` error comes back
verbatim, and a stored domain is never repeated in a reason.

A failure of any kind -- the listing, one database's read, one `odoo
shell` -- is a warning and a non-zero exit, never an exception out of
`main`: the service loop is the retry (ADR 0009).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping, Sequence

# The siblings ship beside this one and are imported by name, the way
# rewrite_apply.py imports them, so the Static tier gets one copy of each.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import literal_rewrite_gate as gate  # noqa: E402
import rewrite_scan as scan  # noqa: E402

#: The writer. Piped into `odoo shell`, as odoo-maintenance-bootstrap:120 does.
MAINTENANCE_LIB = _HERE / "odoo-maintenance.py"
#: The Odoo configuration the bootstrap passes to `odoo shell`.
ODOO_CONF = "/data/odoo.conf"
#: A registry load takes a few seconds (ADR 0007 measured 4.7 s). One that
#: has not returned after a whole interval is a failed catch-up, so a hung
#: shell can cost this round and never the ones after it.
SHELL_TIMEOUT_SECONDS = 300

#: Is the `website` module installed? Its table exists once it is. Asked
#: first, because selecting from a table that does not exist is an error
#: rather than an empty answer.
HAS_WEBSITE_SQL = "SELECT to_regclass('public.website') IS NOT NULL"

#: The default website's domain: the record `website.default_website` when
#: the xmlid exists, else the lowest id -- the order the maintenance library
#: uses to pick the record it writes. The id is selected too so that an
#: empty domain still yields a record, which is how an empty domain and no
#: record are told apart.
DEFAULT_WEBSITE_DOMAIN_SQL = """SELECT w.id, COALESCE(w.domain, '')
FROM website w
LEFT JOIN ir_model_data d
  ON d.model = 'website' AND d.res_id = w.id
  AND d.module = 'website' AND d.name = 'default_website'
ORDER BY d.id IS NULL, w.id
LIMIT 1"""

ACTION_CATCH_UP = "catch-up"
ACTION_SKIP = "skip"
ACTION_FAILED = "failed"

#: `(database, conf, environment) -> CompletedProcess`: how the writer runs.
ShellRunner = Callable[[str, str, Mapping[str, str]], subprocess.CompletedProcess]


# --- the decision, pure -------------------------------------------------------

def needs_catchup(domain: str | None, canonical: str) -> tuple[bool, str]:
    """Does this domain need the Canonical URL written over it?

    `domain` is what the default website holds, or None when there is no
    website record at all. A trailing slash on either side is ignored, as
    `canonical_url()` strips one from `public_url`. The reason for a
    difference never repeats the stored value: it could carry an Ingress
    token, and this reason may reach the add-on log.
    """
    if domain is None:
        return False, "no website record"
    current = domain.strip().rstrip("/")
    if not current:
        return True, "website.domain is empty"
    if current == canonical.strip().rstrip("/"):
        return False, "website.domain already equals the Canonical URL"
    return True, "website.domain differs from the Canonical URL"


@dataclass(frozen=True)
class Verdict:
    """What one database needs."""

    database: str
    action: str     # ACTION_CATCH_UP | ACTION_SKIP | ACTION_FAILED
    reason: str


@dataclass(frozen=True)
class Plan:
    """What the cluster needs, per database."""

    verdicts: tuple[Verdict, ...] = ()
    error: str = ""     # the database listing itself failed

    @property
    def due(self) -> tuple[str, ...]:
        return tuple(v.database for v in self.verdicts if v.action == ACTION_CATCH_UP)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(v.database for v in self.verdicts if v.action == ACTION_FAILED)


def decide_database(run_query: scan.QueryRunner, database: str, canonical: str) -> Verdict:
    """One database's verdict; a read that raises is a failed verdict, not a raise."""
    try:
        if run_query(database, HAS_WEBSITE_SQL).strip() != "t":
            return Verdict(database, ACTION_SKIP, "website module not installed")
        output = run_query(database, DEFAULT_WEBSITE_DOMAIN_SQL)
    except Exception as error:      # noqa: BLE001 - one database, not the round
        return Verdict(database, ACTION_FAILED, str(error))
    # Not `rewrite_scan.records`: it strips each record, and Python's strip
    # treats the field separator as whitespace, which would swallow an
    # empty domain field at the end of the row. The row is read as psql
    # wrote it; a query with no row prints nothing.
    record = output.split(scan.RECORD_SEPARATOR)[0]
    domain: str | None = None
    if record.strip():
        fields = record.split(scan.FIELD_SEPARATOR)
        if len(fields) != 2:
            return Verdict(
                database, ACTION_FAILED, f"the website row has {len(fields)} fields, expected 2"
            )
        domain = fields[1]
    needed, reason = needs_catchup(domain, canonical)
    return Verdict(database, ACTION_CATCH_UP if needed else ACTION_SKIP, reason)


def plan(
    run_query: scan.QueryRunner,
    canonical: str,
    databases: Sequence[str] | None = None,
) -> Plan:
    """Every Odoo database's verdict; one failure never hides the rest."""
    if databases is None:
        try:
            databases = scan.list_databases(run_query)
        except Exception as error:      # noqa: BLE001 - reported, never raised
            return Plan(error=f"the databases could not be listed: {error}")
    return Plan(tuple(decide_database(run_query, name, canonical) for name in databases))


# --- the inputs and the writer ------------------------------------------------

def canonical_url_from_environment() -> str | None:
    """This start's Canonical URL, by the maintenance library's own rule.

    The inputs are the three the bootstrap exports, under the same names;
    the wrapper CLI puts them in the environment from the same places.
    """
    spec = importlib.util.spec_from_file_location("odoo_maintenance", MAINTENANCE_LIB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.canonical_url(
        os.environ.get("ODOO_MAINT_PUBLIC_URL"),
        os.environ.get("ODOO_MAINT_LAN_IPV4"),
        os.environ.get("ODOO_MAINT_PORT"),
    )


def odoo_shell(
    database: str,
    conf: str,
    environment: Mapping[str, str],
    *,
    runner: Callable = subprocess.run,
) -> subprocess.CompletedProcess:
    """Run the maintenance library for one database, the way the bootstrap does.

    `s6-setuidgid odoo /usr/bin/odoo shell -c <conf> -d <db> --no-http`
    with the library on stdin (odoo-maintenance-bootstrap:120-121). Both
    streams are captured: the library's lines are on stdout, and Odoo's own
    logging plus any traceback on stderr, of which a failure reports the
    last line.
    """
    return runner(
        ["s6-setuidgid", "odoo", "/usr/bin/odoo", "shell",
         "-c", conf, "-d", database, "--no-http"],
        input=MAINTENANCE_LIB.read_text(encoding="utf-8"),
        env=dict(environment),
        capture_output=True,
        text=True,
        timeout=SHELL_TIMEOUT_SECONDS,
    )


def catch_up(
    database: str,
    conf: str,
    run_shell: ShellRunner,
    out: Callable[[str], None],
) -> bool:
    """Write one database through the maintenance library; say what it said."""
    environment = dict(os.environ, ODOO_MAINT_DB=database)
    try:
        finished = run_shell(database, conf, environment)
    except Exception as error:      # noqa: BLE001 - a timeout, or no such binary
        out(gate.mask(f"maintenance db={database}: WARNING Canonical URL catch-up failed: {error}"))
        return False
    for line in finished.stdout.splitlines():
        if line.strip():
            out(gate.mask(line))
    if finished.returncode != 0:
        detail = finished.stderr.strip().splitlines()
        cause = detail[-1] if detail else f"odoo shell exited {finished.returncode}"
        out(gate.mask(f"maintenance db={database}: WARNING Canonical URL catch-up failed: {cause}"))
        return False
    return True


# --- the step -----------------------------------------------------------------

#: `main`'s default for `canonical`: read this start's inputs from the
#: environment. A test passes a value, or None for "no Canonical URL".
FROM_ENVIRONMENT = object()


def main(
    argv=None,
    run_query: scan.QueryRunner | None = None,
    run_shell: ShellRunner | None = None,
    canonical: str | None | object = FROM_ENVIRONMENT,
    out: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(
        prog="odoo-canonical-catchup",
        description="Write the Canonical URL into the default website's domain "
                    "of every database that gained the website module after the "
                    "add-on started.",
    )
    parser.add_argument("--conf", default=ODOO_CONF,
                        help="the Odoo configuration odoo shell reads")
    arguments = parser.parse_args(argv)

    if canonical is FROM_ENVIRONMENT:
        canonical = canonical_url_from_environment()
    if not canonical:
        # No Canonical URL this start: the bootstrap said so once, at start.
        return 0

    result = plan(run_query or scan.psql_query, canonical)
    if result.error:
        out(gate.mask(f"maintenance: WARNING Canonical URL catch-up skipped: {result.error}"))
        return 1

    failures = 0
    for verdict in result.verdicts:
        if verdict.action == ACTION_FAILED:
            out(gate.mask(
                f"maintenance db={verdict.database}: WARNING Canonical URL catch-up "
                f"could not read the website domain: {verdict.reason}"
            ))
            failures += 1
        elif verdict.action == ACTION_CATCH_UP:
            if not catch_up(verdict.database, arguments.conf, run_shell or odoo_shell, out):
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
