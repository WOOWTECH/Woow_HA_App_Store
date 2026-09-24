#!/usr/bin/env python3
"""The Rewrite scan's apply path: findings become the nginx include file
(issue #93, ADR 0005 and ADR 0008).

`rewrite_scan.py` (issue #92) says which bundles a host serves and whether
they moved. This module is the half that acts on that: it reads the bytes,
classifies them with `literal_rewrite_gate.py`, writes the Generated
rewrites, validates the candidate with `nginx -t` and reloads the running
nginx. It is the risky half -- both historical breakages (0.3.10 and
0.3.34) were rewrite rules and `services.d/nginx/finish` halts the
container -- so every step here is written to leave the last good file in
place when anything is not certain.

Four refusals, in the order a round meets them:

- **An incomplete scan is never applied.** The include file is the union
  over databases, so a database that could not be read makes the union
  *smaller*: the generated text genuinely differs, the byte comparison
  passes it through, and a Generated rewrite that was working is removed.
  The operator then gets a Prefix escape caused by a failed read. A bundle
  whose bytes are missing from the filestore fails its database for the
  same reason (`read_bundles`).
- **An unchanged generation is not written.** `generate_include` is
  byte-stable, so equal text means equal rules, and nginx is not reloaded
  for a file that did not move.
- **A candidate that nginx does not accept is not moved into place.** The
  candidate is validated the way the Static tier validates a rendered
  gateway (`test_dual_gateway.py`): a temporary `nginx.conf` whose include
  line points at the candidate, listeners moved to unix sockets, then
  `nginx -t -c`. `nginx -t` opens listener sockets and the running nginx
  holds 8069, 8072 and 5691, so validating with the real listeners would
  fail on every host that is actually serving.
- **`literal_rewrite_auto = false` freezes application.** The scan runs and
  reports, and the include file is not touched. Rules already in place stay
  live: the option stops new rules, it does not roll back.

The state (`rewrite_scan.save_state`) is written here, and only after a
complete scan that was applied or that needed no change. A state written
from a scan that was not applied would make the next round believe the
include file already holds those rules. While application is off nothing
is written and the cheap "nothing changed" skip is not taken either, so the
report keeps saying what would be rewritten instead of going silent.

`report` is the other half of a round, and the only half an operator ever
sees (issue #94, ADR 0009). The s6 service runs this CLI every five
minutes and what it prints *is* that round's entry in the add-on log, so a
round that printed nothing would be an add-on that silently stopped
updating its rules. Every round therefore says what each database answered and whether
the scan was complete, and every round that actually read bundles adds the
per-bundle, per-level summary with its exception hits. Every line goes
through `gate.mask`, because a bundle can hold an Ingress token and the
add-on log is copied into issues and screenshots.

Only `validate`, `reload_nginx`, `notify` and the file moves reach out of
the process; the rest is pure over strings, so the Static tier drives all
four refusals with a fake runner and a temporary filestore.

`notification` is what the operator sees outside the log (issue #78): one
Home Assistant persistent notification when a round added Generated
rewrites or when its generation, validation or reload failed, and nothing
otherwise. `round_event` decides which, `notification` words it masked,
and `notify` is the thin adapter to the Supervisor, whose failure is
logged and never changes the round.

The module must import with the standard library alone, plus PyYAML for the
exception list, which ADR 0008 puts in the image.
"""
from __future__ import annotations

import argparse
import collections
from dataclasses import dataclass, field, replace
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable, Iterable, Mapping
import urllib.request

# The two modules ship beside this one. They are imported by name rather
# than by path so the Static tier, which loads all three out of the
# repository, gets one copy of each and one set of dataclasses.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import literal_rewrite_gate as gate     # noqa: E402  (after the path fix above)
import rewrite_scan as scan             # noqa: E402

#: The rendered gateway configuration, the one the running nginx loaded.
#: Read, never written: the Generated rewrites go in the include file.
NGINX_CONF_PATH = "/etc/nginx/nginx.conf"
#: Where the nginx master writes its pid (`nginx.conf.template:2`).
NGINX_PID_PATH = "/var/run/nginx.pid"
#: The exception list shipped in the image, which ADR 0005 keeps applying.
EXCEPTIONS_PATH = str(_HERE / "literal_rewrite_exceptions.yaml")

NGINX_BINARY = "nginx"
#: A `nginx -t` or a reload that never returns would stall every later
#: round of the five-minute loop, so both are bounded.
NGINX_TIMEOUT_SECONDS = 30

#: What a round did. `applied` and `unchanged` are the two states in which
#: the include file on disk agrees with the bundles that were read, and the
#: only two after which the state is written.
STATUS_APPLIED = "applied"
STATUS_UNCHANGED = "unchanged"
STATUS_UP_TO_DATE = "up to date"
STATUS_OFF = "application off"
STATUS_INCOMPLETE = "incomplete"
STATUS_INVALID = "invalid"

#: The statuses a round is allowed to end on without the operator having to
#: act. The CLI's exit status follows this.
HEALTHY_STATUSES = (STATUS_APPLIED, STATUS_UNCHANGED, STATUS_UP_TO_DATE, STATUS_OFF)

#: How a process is run. An argument everywhere, so the Static tier can
#: watch what would have been run without running it.
Runner = Callable[..., "subprocess.CompletedProcess"]


# --- the bytes ----------------------------------------------------------------

@dataclass(frozen=True)
class BundleRead:
    """The bundle bytes, and the scan result as reading them leaves it."""

    result: "scan.ScanResult"
    texts: Mapping[tuple[str, str], str] = field(default_factory=dict)
    missing: tuple = ()      # rows whose file could not be read


def read_bundles(result, filestore: str = scan.FILESTORE_DIR) -> BundleRead:
    """Read every readable bundle; a file that is gone fails its database.

    `rewrite_scan` reads rows, not bytes, so a bundle listed in
    `ir_attachment` whose filestore file is missing is met here first. It is
    the same danger as a failed database and gets the same answer: the union
    would be short by exactly the rules that bundle earns, and applying it
    would delete rules that were working. The measurement behind ADR 0007
    found 0 missing files of 20, so refusing the round costs little.

    A row `rewrite_scan` had to skip -- content kept in the database rather
    than the filestore (`ir_attachment.location = db`) -- fails its database
    here for the same reason. `rewrite_scan` reports that database as `ok`
    with the skips recorded, because a skip is reportable there; here it is
    a bundle nobody scanned, and an all-clear read off a short union is
    exactly what deletes a working rule.

    A database that already failed, or that serves no bundles, is carried
    through untouched.
    """
    texts: dict[tuple[str, str], str] = {}
    missing: list = []
    scans: list = []
    for database in result.databases:
        if database.status != scan.STATUS_OK:
            scans.append(database)
            continue
        errors: list[str] = [
            f"{row.url}: unsupported storage (ir_attachment.location = db), "
            "nothing to read"
            for row in database.skipped
        ]
        for row in database.rows:
            path = scan.bundle_path(row, filestore)
            try:
                # `errors="replace"` because a bundle is served as bytes and
                # nothing promises it decodes: a mis-decoded character must
                # not raise past a whole database's findings.
                texts[row.key] = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                missing.append(row)
                errors.append(f"{row.url}: {error}")
        if errors:
            # The findings of the bundles that *were* read are dropped with
            # the rest: a partial database is what makes a short union, and
            # the result is refused as a whole anyway.
            for row in database.rows:
                texts.pop(row.key, None)
            joined = "; ".join(errors)
            scans.append(replace(
                database, status=scan.STATUS_FAILED,
                error=f"{database.error}; {joined}" if database.error else joined,
            ))
        else:
            scans.append(database)
    return BundleRead(replace(result, databases=tuple(scans)), texts, tuple(missing))


# --- the text -----------------------------------------------------------------

def shipped_rules(nginx_conf: str) -> dict:
    """The Literal rewrite rules the image ships, from the rendered gateway.

    Read from the running configuration rather than from the template
    because the template is not on the host in rendered form anywhere else,
    and the rules are what nginx actually substitutes.

    The Generated rewrites are deliberately *not* merged in, although
    `nginx.conf` includes them: a generated rule read back as a shipped one
    would cover the finding that earned it, the next generation would drop
    it as covered, the round after that would add it again, and the rules
    would flap. `include_rules` and `merge_rules` exist for the gate's
    outside-in view of a host, which is a different question.
    """
    return gate.rewrite_rules(nginx_conf)


def load_exceptions(path: str | os.PathLike = EXCEPTIONS_PATH) -> set:
    """The approved exception list shipped in the image (ADR 0005)."""
    return gate.load_exceptions(Path(path).read_text(encoding="utf-8"))


def generation_inputs(rules: Mapping, exceptions: Iterable) -> "scan.GenerationInputs":
    """The fingerprint of the Shipped rewrites and the exception list (issue #135).

    What the state compares so that a Release changing either one makes a
    pass due, although no bundle and no analysis module moved. Each is
    hashed in a sorted form, so reordering the `sub_filter` lines or
    re-indenting the template changes nothing that `shipped_rules` does not
    see.

    `rules` is `shipped_rules`' answer and never the Generated rewrites:
    fingerprinting the include file would make every application a change
    of the inputs, and the rules would flap (ADR 0008).
    """
    def digest(value) -> str:
        return hashlib.sha256(json.dumps(value).encode("utf-8")).hexdigest()

    return scan.GenerationInputs(
        shipped_rules=digest(sorted(
            [prefix, sorted(quotes)] for prefix, quotes in rules.items()
        )),
        exceptions=digest(sorted([prefix, level] for prefix, level in exceptions)),
    )


def scan_bundles(texts: Mapping[tuple[str, str], str]) -> dict:
    """The findings of every bundle, one regex pass each.

    The pass is taken here, once, and both halves of a round are built from
    what it returns: `build_include` selects the rules and
    `evaluate_bundles` summarises the same findings for the log. Scanning
    again for the second half would double the four seconds of analysis a
    round costs, which is the cost ADR 0007 measured and the reason the
    scan keeps a state at all.
    """
    return {key: gate.scan_bundle(text) for key, text in texts.items()}


def build_include(scanned: Mapping[tuple[str, str], list], rules: Mapping, exceptions: Iterable) -> str:
    """The include text for these bundles: the union of their findings.

    The selection is `generate_include`'s alone -- navigation-level literals
    (`FAIL`) that no shipped rule covers and no exception excuses. This
    ticket adds no rule of its own, which is why `rewrite_apply.py` is not
    in `rewrite_scan.ANALYSIS_MODULES`: it cannot change what a scan finds.

    Note that this takes `scan_bundles`' findings and not the bundle texts,
    and that it is deliberately *not* built from the log summary's
    `GateReport` instead. The summary drops what `is_covered` answers for
    one literal and the quote it is written in; generation asks the coarser
    `_shipped_covers` about the prefix. The two differ for a CSS `url(/x)`
    literal, and reading the selection off the summary would quietly change
    which rules a host gets.
    """
    findings: list = []
    for bundle in scanned.values():
        findings.extend(bundle)
    return gate.generate_include(findings, rules, exceptions)


def bundle_label(key: tuple[str, str]) -> str:
    """How one bundle is named in the log: its database and its URL.

    The whole key, never the name. One database serves the same bundle name
    under a website-scoped URL and an unscoped one with different content
    (`rewrite_scan.BundleRow.key`), so a name-keyed summary would report
    two different bundles as one.
    """
    database, url = key
    return f"{database} {url}"


def evaluate_bundles(
    texts: Mapping[tuple[str, str], str],
    scanned: Mapping[tuple[str, str], list],
    rules: Mapping,
    exceptions: Iterable,
) -> "gate.GateReport":
    """The same findings again, per bundle and per level, for the log.

    `build_include` answers "which prefixes earn a rule" and throws the rest
    away; this answers "what did each bundle actually contain", which is
    what the round reports. Both are built from the one pass `scan_bundles`
    took, and both measure coverage against the Shipped rewrites alone, so
    a `FAIL` row in the summary is what earned an entry in the include
    file.

    Merging the Generated rewrites in first would make the log read as
    though nothing was ever found -- every rule the add-on wrote would
    cover the finding that earned it -- which is the same trap
    `shipped_rules` avoids for generation.

    The texts are still wanted for their length alone: a report prints each
    bundle's size and a finding does not carry the bundle it came from.
    """
    return gate.evaluate_findings(
        {
            bundle_label(key): (len(texts[key]), findings)
            for key, findings in scanned.items()
        },
        rules,
        exceptions,
    )


def include_prefixes(text: str) -> tuple:
    """The prefixes an include text rewrites, for the log and the report."""
    return tuple(sorted(gate.include_rules(text)))


# --- validation ---------------------------------------------------------------

# A listener line in the rendered configuration. Matched rather than listed
# literally so a template that gains or moves a listener does not need this
# file changed with it.
_LISTEN = re.compile(r"^(?P<indent>[ \t]*)listen\s+(?P<address>[^\s;]+)(?P<options>[^;]*);", re.M)
_PID = re.compile(r"^pid\s+[^;]+;", re.M)


def render_test_config(nginx_conf: str, candidate: str | os.PathLike, work_dir: str | os.PathLike) -> str:
    """A configuration that loads `candidate` instead of the live include file.

    `nginx -t` against the live configuration cannot validate a candidate:
    the include path in the template is fixed text
    (`nginx.conf.template:342`), so it would validate the file already in
    place. The Static tier already renders around that
    (`test_dual_gateway.py:324-325`) and this is the same move.

    Every listener becomes a unix socket inside `work_dir`. `nginx -t` opens
    listener sockets (`test_dual_gateway.py:329-337`) and the running nginx
    holds 8069, 8072 and 5691, so a test that kept the real listeners would
    pass in CI, where nothing is serving, and fail on every host that is.
    """
    work_dir = Path(work_dir)
    include = f"include {scan.GENERATED_REWRITES_PATH};"
    if nginx_conf.count(include) != 1:
        raise ValueError(
            f"expected exactly one {include!r} in the rendered configuration, "
            f"found {nginx_conf.count(include)}"
        )
    config = nginx_conf.replace(include, f"include {candidate};")

    numbers = itertools.count(1)

    def socket(match: "re.Match[str]") -> str:
        return (
            f"{match.group('indent')}listen "
            f"unix:{work_dir}/listen-{next(numbers)}.sock{match.group('options')};"
        )

    config = _LISTEN.sub(socket, config)
    if next(numbers) == 1:
        raise ValueError("the rendered configuration has no listener to move")
    # The running master owns the real pid file; a test run must not be able
    # to touch it whatever a future nginx does with it in test mode.
    # Both replacements are callables, so a path is inserted as it is: a
    # plain string would have its backslashes read as group references.
    config = _PID.sub(lambda match: f"pid {work_dir}/nginx.pid;", config)
    return config


def validate(
    candidate: str | os.PathLike,
    nginx_conf: str,
    work_dir: str | os.PathLike,
    runner: Runner = subprocess.run,
) -> tuple[bool, str]:
    """Does nginx accept this candidate? The message is masked either way."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    config = work_dir / "nginx.conf"
    try:
        config.write_text(
            render_test_config(nginx_conf, candidate, work_dir), encoding="utf-8"
        )
        finished = runner(
            [NGINX_BINARY, "-t", "-p", str(work_dir), "-c", str(config)],
            capture_output=True, text=True, timeout=NGINX_TIMEOUT_SECONDS,
        )
    except Exception as error:      # noqa: BLE001 - a failure to validate is a failure
        return False, gate.mask(f"the candidate could not be validated: {error}")
    output = (finished.stderr or finished.stdout or "").strip()
    return finished.returncode == 0, gate.mask(output)


# --- the running nginx --------------------------------------------------------

def nginx_master(pid_path: str | os.PathLike = NGINX_PID_PATH) -> int | None:
    """The pid of the running nginx master, or None when none is running.

    At start the Rewrite scan can easily win the race against the nginx
    service, which waits for Odoo's HTTP port first (`services.d/nginx/run`).
    Then the file is written and validated and there is simply nobody to
    reload; nginx loads it when it starts.

    Only POSIX asks the process whether it is alive: `os.kill` on Windows
    terminates rather than probes, and the Static tier is run on developer
    machines as well as in CI.
    """
    try:
        pid = int(Path(pid_path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if os.name != "posix":
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def reload_nginx(runner: Runner = subprocess.run) -> tuple[bool, str]:
    """Send `nginx -s reload` to the running master."""
    try:
        finished = runner(
            [NGINX_BINARY, "-s", "reload"],
            capture_output=True, text=True, timeout=NGINX_TIMEOUT_SECONDS,
        )
    except Exception as error:      # noqa: BLE001 - reported, never raised
        return False, gate.mask(f"the reload could not be run: {error}")
    output = (finished.stderr or finished.stdout or "").strip()
    return finished.returncode == 0, gate.mask(output)


# --- applying -----------------------------------------------------------------

@dataclass(frozen=True)
class ApplyResult:
    """What one round did, and whether its state may be kept."""

    status: str
    detail: str = ""
    include_text: str = ""
    # The prefixes the round leaves rewritten: the generation it produced,
    # or -- for a round that generated nothing, because no pass was due or
    # the scan was refused -- what the file on disk already held
    # (`live_prefixes`). The exception is `application off`, where it is
    # what *would* be rewritten, and the detail says so.
    prefixes: tuple = ()
    wrote: bool = False
    reloaded: bool = False
    # A running nginx refused the reload. Not the same as `not reloaded`:
    # before nginx has started there is nobody to reload, and that is fine.
    reload_failed: bool = False
    state_saved: bool = False
    scan: "scan.ScanResult | None" = None
    verdict: "scan.ScanVerdict | None" = None
    # None means no bundle was read this round, which is the ordinary case:
    # the state said nothing moved, or the scan was refused before the
    # bytes were opened. An empty report would claim a pass that never ran.
    findings: "gate.GateReport | None" = None

    @property
    def healthy(self) -> bool:
        return self.status in HEALTHY_STATUSES

    @property
    def agrees_with_disk(self) -> bool:
        """Does the include file now hold the rules these bundles earn?

        The one condition under which the state may be written: anything
        else would let the next round believe a generation that was never
        applied is already in place.
        """
        return self.status in (STATUS_APPLIED, STATUS_UNCHANGED)


def apply_include(
    text: str,
    nginx_conf: str,
    *,
    include_path: str | os.PathLike = scan.GENERATED_REWRITES_PATH,
    pid_path: str | os.PathLike = NGINX_PID_PATH,
    work_dir: str | os.PathLike | None = None,
    runner: Runner = subprocess.run,
    running: Callable[[], bool] | None = None,
) -> ApplyResult:
    """Write, validate and move the include file, then reload nginx.

    The candidate is written beside the file it may replace, because
    `os.replace` is atomic only inside one filesystem and the include file
    lives on the /data volume.
    """
    include = Path(include_path)
    prefixes = include_prefixes(text)
    try:
        current = include.read_text(encoding="utf-8")
    except OSError:
        # No file at all counts as different: `10-odoo-config.sh:257-267`
        # creates it empty, so an absent one means somebody removed it and
        # nginx is refusing to start until it is back.
        current = None

    if current == text:
        return ApplyResult(
            STATUS_UNCHANGED,
            f"the file already holds these {len(prefixes)} prefixes; "
            "nothing written, nginx not reloaded",
            include_text=text, prefixes=prefixes,
        )

    candidate = include.with_name(include.name + ".candidate")
    try:
        candidate.write_text(text, encoding="utf-8")
        # cont-init runs under `umask 077`, and nginx reads this file as the
        # user it drops to, so the mode is set here as it is for the real file.
        os.chmod(candidate, 0o644)
    except Exception as error:
        # The candidate could not even be written: nothing has moved.
        discard(candidate)
        raise RoundError(STEP_APPLY, error)

    try:
        if work_dir is None:
            with tempfile.TemporaryDirectory(prefix="rewrite-apply-") as temporary:
                accepted, message = validate(candidate, nginx_conf, temporary, runner)
        else:
            accepted, message = validate(candidate, nginx_conf, work_dir, runner)
    except Exception as error:
        # Nothing has moved: the include file is what it was.
        discard(candidate)
        raise RoundError(STEP_VALIDATION, error)

    if not accepted:
        candidate.unlink(missing_ok=True)
        return ApplyResult(
            STATUS_INVALID,
            f"nginx refused the candidate, so {include} stays as it is: {message}",
            include_text=text, prefixes=prefixes,
        )

    try:
        os.replace(candidate, include)
    except Exception as error:
        # `os.replace` is atomic: if it raised, the file did not move.
        discard(candidate)
        raise RoundError(STEP_APPLY, error)

    # Neither of the two calls below raises: `nginx_master` answers None for
    # anything it cannot read, and `reload_nginx` reports instead of raising.
    alive = nginx_master(pid_path) is not None if running is None else running()
    if not alive:
        return ApplyResult(
            STATUS_APPLIED,
            f"{len(prefixes)} prefixes written to {include}; "
            "nginx is not running yet, so it was not reloaded",
            include_text=text, prefixes=prefixes, wrote=True,
        )

    reloaded, reload_message = reload_nginx(runner)
    detail = f"{len(prefixes)} prefixes written to {include}"
    if not reloaded:
        # The file is valid and in place, so nginx loads it at its next
        # start whatever happened here; saying so is better than pretending
        # the rules are live.
        return ApplyResult(
            STATUS_APPLIED,
            f"{detail}, but the reload failed and the rules are not live yet: "
            f"{reload_message}",
            include_text=text, prefixes=prefixes, wrote=True, reload_failed=True,
        )
    return ApplyResult(
        STATUS_APPLIED, f"{detail} and nginx was reloaded",
        include_text=text, prefixes=prefixes, wrote=True, reloaded=True,
    )


def live_prefixes(include_path: str | os.PathLike = scan.GENERATED_REWRITES_PATH) -> tuple:
    """The prefixes the include file on disk rewrites right now.

    What a round reports when it generated nothing of its own: an
    up-to-date round and a refused one both leave the file exactly as it
    was, and "which Generated rewrites are live" is the question an
    operator is actually asking. Without it, every round after the first
    application would stop naming them, and a host doing its job would read
    like a host that had forgotten how.

    An unreadable file answers nothing rather than raising: this is a line
    of a log, and the round it belongs to has already said what it did. A
    file that is not UTF-8 is unreadable too; the round regenerates it.
    """
    try:
        return include_prefixes(Path(include_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ()


def _incomplete(result) -> str:
    """Why nothing was applied, with the database that failed named."""
    reason = result.error or (
        "databases that could not be read: " + ", ".join(
            f"{database.database} ({database.error})" if database.error else database.database
            for database in result.databases
            if database.status == scan.STATUS_FAILED
        )
    )
    return (
        "nothing written and nginx not reloaded, because the scan is "
        f"incomplete: {reason}"
    )


def apply_round(
    result,
    *,
    auto: bool = True,
    previous_state=None,
    force: bool = False,
    filestore: str = scan.FILESTORE_DIR,
    include_path: str | os.PathLike = scan.GENERATED_REWRITES_PATH,
    nginx_conf_path: str | os.PathLike = NGINX_CONF_PATH,
    exceptions_path: str | os.PathLike = EXCEPTIONS_PATH,
    state_path: str | os.PathLike | None = scan.STATE_PATH,
    pid_path: str | os.PathLike = NGINX_PID_PATH,
    version: str | None = None,
    runner: Runner = subprocess.run,
    running: Callable[[], bool] | None = None,
) -> ApplyResult:
    """One whole round over a scan result: read, generate, apply, remember.

    Completeness is tested twice, and the first test comes before the
    verdict: the verdict compares the previous state with a union that is
    short by the bundles nobody read, so a failed database reads there as a
    removal that never happened. The second test is after the bytes are
    read, because a bundle whose file is missing fails its database too and
    that is only visible once somebody tries to open it.

    Between the two sits the skip, which is why the bytes are read after the
    verdict and not before: reading and classifying them is the four seconds
    a round costs (ADR 0007), and the whole point of the state is not to pay
    it when nothing moved.

    The rendered gateway and the exception list are read before the
    verdict, though: they are what the include file is built from besides
    the bundles, and a Release that changes either must make a pass due
    (issue #135). Reading them is cheap; the bundles are what costs.
    """
    if not result.complete:
        return ApplyResult(
            STATUS_INCOMPLETE, _incomplete(result), scan=result,
            prefixes=live_prefixes(include_path),
        )

    nginx_conf = Path(nginx_conf_path).read_text(encoding="utf-8")
    rules = shipped_rules(nginx_conf)
    exceptions = load_exceptions(exceptions_path)
    inputs = generation_inputs(rules, exceptions)

    verdict = scan.scan_state(result.rows, previous_state, version=version, inputs=inputs)
    # The skip is an optimisation for a host whose rules are already in
    # place, and it is taken only while application is on. With the option
    # off nothing is ever applied, so a skip there would silence exactly the
    # report the option exists to keep.
    if auto and not force and not verdict.rescan:
        return ApplyResult(
            STATUS_UP_TO_DATE,
            f"no pass was due ({verdict.reason}); the include file is untouched",
            scan=result, verdict=verdict, prefixes=live_prefixes(include_path),
        )

    read = read_bundles(result, filestore)
    if not read.result.complete:
        return ApplyResult(
            STATUS_INCOMPLETE, _incomplete(read.result), scan=read.result, verdict=verdict,
            prefixes=live_prefixes(include_path),
        )

    # The one pass over the bytes, and the four seconds ADR 0007 prices.
    # Both the include file and the round's summary are built from it.
    scanned = scan_bundles(read.texts)
    text = build_include(scanned, rules, exceptions)
    prefixes = include_prefixes(text)
    findings = evaluate_bundles(read.texts, scanned, rules, exceptions)

    if not auto:
        return ApplyResult(
            STATUS_OFF,
            f"literal_rewrite_auto is false: application is off and "
            f"{include_path} is not touched. The scan found {len(prefixes)} "
            "prefixes that would be rewritten; rules already in place stay live",
            include_text=text, prefixes=prefixes, scan=read.result, verdict=verdict,
            findings=findings,
        )

    outcome = apply_include(
        text, nginx_conf,
        include_path=include_path, pid_path=pid_path, runner=runner, running=running,
    )
    outcome = replace(outcome, scan=read.result, verdict=verdict, findings=findings)

    if outcome.agrees_with_disk and state_path is not None:
        # Only now: the file on disk holds the rules these bundles earn, so
        # "this is what was served when the include file was last built" is
        # true. A state written from a refused or frozen round would make
        # the next one skip the pass that would have fixed it.
        try:
            scan.save_state(
                state_path, scan.state_from_rows(read.result.rows, version, inputs=inputs),
            )
        except Exception as error:
            # The include file is the new one and nginx has it (or loads it
            # at its next start); only the memory of this round is missing,
            # so the next round regenerates and lands on `unchanged`. A
            # reload nginx refused before this is carried along: that round
            # will not retry it either, so this is the one place to say so.
            raise RoundError(
                STEP_APPLY, error, replaced=outcome.wrote,
                prefixes=outcome.prefixes, reload_failed=outcome.reload_failed,
            )
        outcome = replace(outcome, state_saved=True)
    return outcome


# --- the log summary ----------------------------------------------------------

def database_lines(result) -> list[str]:
    """What each database answered, and whether the round may be believed.

    Every database is named with its status, including the ones that
    answered nothing, because the three outcomes mean different things and
    only one of them is a problem: `no bundles` is a fresh database, `ok`
    is a database that was read, and `failed` is a database that was not.

    A round that was incomplete says so in two ways on purpose. `complete:
    no` is the fact, and the sentence after it is the consequence, because
    an operator reading "incomplete" alone cannot tell whether the rules on
    disk moved. Without that sentence #93's refusal to apply an incomplete
    scan looks from outside like an add-on that quietly stopped updating
    its rules.
    """
    counts = collections.Counter(database.status for database in result.databases)
    lines = [
        f"  databases: {len(result.databases)} "
        f"(ok {counts[scan.STATUS_OK]}, "
        f"no bundles {counts[scan.STATUS_NO_BUNDLES]}, "
        f"failed {counts[scan.STATUS_FAILED]}), "
        f"bundles {len(result.rows)}, skipped {len(result.skipped)}, "
        f"complete: {'yes' if result.complete else 'no'}"
    ]
    if result.error:
        lines.append(f"  {result.error}")
    for database in result.databases:
        header = f"  {database.database}: {database.status}"
        lines.append(f"{header} -- {database.error}" if database.error else header)
    if not result.complete:
        lines.append(
            "  incomplete: this round read less than the whole cluster, so "
            "no Generated rewrite was added or removed and the rules already "
            "in place stay live"
        )
    return lines


def finding_lines(findings) -> list[str]:
    """One round's bundles, per bundle and per level, with its exception hits.

    Coverage is measured against the Shipped rewrites alone, the way
    `build_include` selects, so a `FAIL` row here is precisely what earns a
    Generated rewrite and the `prefixes:` line below says which ones the
    file now holds. A literal the template already rewrites is not a
    finding and is not printed.

    The gate's own `format_report` is not reused. It prints the outside-in
    view of a host under the name the glossary reserves for that run, and
    this is the in-container round going into the add-on log every five
    minutes. `FAIL` and `WARN` are counted the way it counts them -- one
    (bundle, prefix) pair each, exception hits excluded -- so the two
    reports never disagree about how much was found at the levels that
    decide anything. `INFO` is counted the same way here rather than as
    distinct prefixes across bundles, because this report is one host's
    round: "which bundle" is the useful half of an INFO count here and is
    not there.

    `FAIL` and `WARN` rows carry the snippet the finding was cut from,
    because a prefix alone does not say which line of a minified bundle to
    look at. `INFO` is listed as counts on one line: it is everything the
    Runtime shim already intercepts, and a host serves a lot of it.
    """
    totals = {level: 0 for level in gate.LEVELS}
    hits: set[tuple[str, str]] = set()
    blocks: list[str] = []
    for name, bundle in findings.bundles.items():
        excused = {finding.key for finding in bundle.exception_hits}
        hits.update(excused)
        blocks.append(f"  == {name} ({bundle.size:,} B)")
        if not bundle.findings:
            blocks.append("       every root-relative literal is covered")
            continue
        for level in gate.LEVELS:
            counts = bundle.counts(level)
            totals[level] += sum(
                1 for prefix in counts if (prefix, level) not in excused
            )
            if not counts:
                continue
            if level == "INFO":
                listed = ", ".join(
                    f"{prefix} x{count}" for prefix, count in sorted(counts.items())
                )
                blocks.append(f"       INFO      {listed}")
                continue
            shown: set[str] = set()
            for finding in bundle.findings:
                if finding.level != level or finding.prefix in shown:
                    continue
                shown.add(finding.prefix)
                tag = "exception" if finding.key in excused else level
                blocks.append(
                    f"       {tag:<9} {finding.prefix:<20} "
                    f"x{counts[finding.prefix]:<4} {finding.snippet}"
                )
    summary = (
        f"  findings: {len(findings.bundles)} bundles, "
        f"FAIL {totals['FAIL']}, WARN {totals['WARN']}, INFO {totals['INFO']} "
        "uncovered by the Shipped rewrites"
    )
    lines = [summary, *blocks]
    if hits:
        listed = ", ".join(f"{prefix} {level}" for prefix, level in sorted(hits))
        lines.append(f"  exception hits: {listed}")
    return lines


# --- the notification ---------------------------------------------------------

# ADR 0005 lets a Generated rewrite go live without a human reading it, and
# names this notification and the log line as the review (issue #78). So the
# operator hears about exactly two things, and nothing on a round that
# changed nothing: rewrites were added, or a step failed.
EVENT_ADDED = "added"
EVENT_FAILED = "failed"

#: The step a failed round names. An incomplete scan is a failed generation:
#: nothing was generated from it, because the union would have been short.
#: `state` and `scan` are the two reads before generation; `apply` is the
#: writes: the candidate, the move into place and the state write. Whether
#: the move had happened when the step failed is what `RoundError.replaced`
#: says (issue #120).
STEP_STATE = "state"
STEP_SCAN = "scan"
STEP_GENERATION = "generation"
STEP_VALIDATION = "validation"
STEP_APPLY = "apply"
STEP_RELOAD = "reload"


class RoundError(Exception):
    """A step of the round raised; which one, and whether the include file
    had already been replaced when it did.

    `main` turns this into the failure notification. Without it, every
    exception out of `apply_round` read as a failed generation, and the
    notification promised that the rules on disk were untouched even when
    `os.replace` had already succeeded and only the state write failed.
    """

    def __init__(self, step: str, cause: BaseException, *, replaced: bool = False,
                 prefixes: tuple = (), reload_failed: bool = False):
        super().__init__(f"{step}: {cause}")
        self.step = step
        self.replaced = replaced
        # After a replace: the prefixes the new file holds, and whether a
        # running nginx had refused to load it before the step failed.
        self.prefixes = prefixes
        self.reload_failed = reload_failed
        self.__cause__ = cause


def discard(candidate: Path) -> None:
    """Remove a candidate that will not be used; a candidate that cannot be
    removed is not a second failure worth replacing the first with."""
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        pass

#: Home Assistant's own API, reached through the Supervisor proxy with the
#: token every add-on is given. It needs `homeassistant_api` in config.yaml.
NOTIFY_URL = "http://supervisor/core/api/services/persistent_notification/create"
NOTIFY_TIMEOUT_SECONDS = 10
#: The notification ids (`notification_id`). A failure that repeats every
#: round replaces its own notification instead of stacking one every five
#: minutes; each set of added rules gets its own, so neither a failure nor a
#: later addition replaces the notification that named them.
NOTIFICATION_IDS = {
    EVENT_ADDED: "odoo18ce_generated_rewrites_added",
    EVENT_FAILED: "odoo18ce_generated_rewrites_failed",
}


@dataclass(frozen=True)
class RoundEvent:
    """Something a round did that the operator is told about."""

    kind: str
    # The prefixes this round added. A failed reload carries them too: the
    # file is in place and the state saved, so no later round names them.
    prefixes: tuple = ()
    step: str = ""           # EVENT_FAILED: which step failed
    detail: str = ""
    # EVENT_ADDED: nginx was reloaded, so the rules are live now. False
    # when the scan beat nginx at start: the file is written and nginx
    # loads it when it starts.
    live: bool = True
    # EVENT_FAILED: the include file had already been replaced when the
    # step failed, so the rules on disk are the new ones, not the old.
    replaced: bool = False
    # EVENT_FAILED after a replace: a running nginx refused to load the new
    # file before the step failed, so the rules are not live either.
    reload_failed: bool = False


def notification_id(event: RoundEvent) -> str:
    """The id Home Assistant keys the notification on (`NOTIFICATION_IDS`)."""
    if event.kind != EVENT_ADDED:
        return NOTIFICATION_IDS[event.kind]
    digest = hashlib.sha256(" ".join(event.prefixes).encode("utf-8")).hexdigest()
    return f"{NOTIFICATION_IDS[EVENT_ADDED]}_{digest[:12]}"


def round_event(outcome: ApplyResult, before: Iterable = (), auto: bool = True) -> RoundEvent | None:
    """The event a round is, or None when it is not worth a notification.

    `before` is what the include file rewrote before the round, so only the
    prefixes this round *added* are named; a round that only removed rules
    sends nothing. With application off nothing is sent at all, not even
    for a failed round: the option freezes the rules, and the log still
    says what the scan found.
    """
    if not auto:
        return None
    if outcome.status == STATUS_INCOMPLETE:
        return RoundEvent(EVENT_FAILED, step=STEP_GENERATION, detail=outcome.detail)
    if outcome.status == STATUS_INVALID:
        return RoundEvent(EVENT_FAILED, step=STEP_VALIDATION, detail=outcome.detail)
    if outcome.status != STATUS_APPLIED:
        return None
    known = set(before)
    added = tuple(prefix for prefix in outcome.prefixes if prefix not in known)
    if outcome.reload_failed:
        return RoundEvent(EVENT_FAILED, prefixes=added, step=STEP_RELOAD, detail=outcome.detail)
    if added:
        return RoundEvent(EVENT_ADDED, prefixes=added, live=outcome.reloaded)
    return None


def raised_event(error: RoundError) -> RoundEvent:
    """The event a round that raised is: which step, and what is on disk.

    After a replace the prefixes now on disk are named, because no later
    round will: the file is in place, so the next one lands on `unchanged`.
    """
    return RoundEvent(
        EVENT_FAILED, prefixes=error.prefixes, step=error.step,
        detail=str(error.__cause__), replaced=error.replaced,
        reload_failed=error.reload_failed,
    )


def notification(event: RoundEvent) -> tuple[str, str]:
    """The title and body of the notification for one event, masked.

    A prefix is bundle text and a detail can quote nginx or psql, so either
    could carry an Ingress token; a notification is as easily screenshotted
    as the log.
    """
    listed = "\n".join(f"- `{prefix}`" for prefix in event.prefixes)
    if event.kind == EVENT_ADDED:
        title = "Woow Odoo: Generated rewrites added"
        effect = (
            "now rewrites them under Ingress" if event.live
            else "wrote the rules; they take effect under Ingress when nginx starts"
        )
        body = (
            "The Rewrite scan found navigation prefixes no Shipped rewrite "
            f"covers and {effect}:\n\n{listed}\n\n"
            "The add-on log has the bundles they were found in. "
            "Set `literal_rewrite_auto` to false to freeze the rules."
        )
    elif event.step == STEP_RELOAD:
        # The one failure after which the file has moved: it is valid and in
        # place, and the state is saved, so no later round retries.
        title = "Woow Odoo: Generated rewrite reload failed"
        body = (
            "The Rewrite scan wrote a new Generated rewrite file that nginx "
            "accepted, but the reload failed, so the new rules are not live "
            "yet. nginx loads them at its next start; restarting the add-on "
            "does that now. Odoo is untouched."
            + (f"\n\nPrefixes added:\n\n{listed}" if event.prefixes else "")
            + f"\n\n{event.detail}"
        )
    elif event.replaced:
        # The failure came after `os.replace`: the new file is what nginx
        # has, or loads at its next start, and the state was not saved.
        title = f"Woow Odoo: Generated rewrite {event.step} failed"
        loaded = (
            "nginx refused to reload before this, so they are not live yet "
            "and no round retries the reload; restarting the add-on loads them"
            if event.reload_failed
            else "nginx has them, or loads them at its next start"
        )
        body = (
            f"The Rewrite scan's {event.step} step failed after the new "
            "Generated rewrite file was put in place, so the rules on disk "
            f"are the new ones: {loaded}. Odoo is untouched. The next round "
            "runs in five minutes and regenerates them."
            + (f"\n\nPrefixes now on disk:\n\n{listed}" if event.prefixes else "")
            + f"\n\n{event.detail}"
        )
    else:
        title = f"Woow Odoo: Generated rewrite {event.step} failed"
        body = (
            f"The Rewrite scan's {event.step} step failed, so the Generated "
            "rewrites already in place stay as they are and Odoo is untouched. "
            "The next round runs in five minutes.\n\n"
            f"{event.detail}"
        )
    return gate.mask(title), gate.mask(body)


def notify(
    note: tuple[str, str],
    *,
    notification_id: str,
    token: str | None = None,
    opener: Callable = urllib.request.urlopen,
    log: Callable[[str], None] = print,
    source: str = "Rewrite scan",
) -> bool:
    """Create the persistent notification through the Supervisor.

    A failure is logged and never raised: a notification that could not be
    sent must not change what the round did or how it exits. `source` names
    the caller in those log lines; the start-time self-check sends its
    failure through here too (issue #79).
    """
    if token is None:
        token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        log(f"{source}: no SUPERVISOR_TOKEN, so the notification was not sent")
        return False
    title, message = note
    request = urllib.request.Request(
        NOTIFY_URL,
        data=json.dumps({
            "title": title, "message": message, "notification_id": notification_id,
        }).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=NOTIFY_TIMEOUT_SECONDS):
            pass
    except Exception as error:      # noqa: BLE001 - reported, never raised
        log(gate.mask(f"{source}: the notification could not be sent: {error}"))
        return False
    return True


def send_notification(event: RoundEvent | None, notifier: Callable, log: Callable[[str], None]) -> None:
    """Hand one event to the adapter; whatever the adapter does stays here."""
    if event is None:
        return
    try:
        notifier(notification(event), notification_id=notification_id(event), log=log)
    except Exception as error:      # noqa: BLE001 - a broken adapter must not end the round
        log(gate.mask(f"Rewrite scan: the notification could not be sent: {error}"))


# --- the command --------------------------------------------------------------

def report(outcome: ApplyResult, state_note: str, out=print) -> None:
    """One round in the add-on log, Ingress tokens masked.

    The masking is here rather than at each call site: a caller that forgot
    would put an Ingress token in the add-on log, which is what gets copied
    into an issue or a screenshot.
    """
    def line(text: str = "") -> None:
        out(gate.mask(text))

    line(f"Rewrite scan (apply): {outcome.status}")
    line(f"  {outcome.detail}")
    line(f"  state: {state_note}" + (" (written)" if outcome.state_saved else ""))
    if outcome.scan is not None:
        for text in database_lines(outcome.scan):
            line(text)
    if outcome.findings is not None:
        for text in finding_lines(outcome.findings):
            line(text)
    if outcome.prefixes:
        line(f"  prefixes: {' '.join(outcome.prefixes)}")


def main(argv=None, run_query=None, out=print, notifier: Callable = notify) -> int:
    parser = argparse.ArgumentParser(
        prog="odoo-rewrite-apply",
        description="Run one Rewrite scan round and apply its findings as the "
                    "Generated rewrite include file.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--auto", dest="auto", action="store_true", default=True,
                       help="apply the findings (the default)")
    group.add_argument("--no-auto", dest="auto", action="store_false",
                       help="scan and report, but never touch the include file")
    parser.add_argument("--force", action="store_true",
                        help="scan even when the state says nothing changed")
    parser.add_argument("--state", default=scan.STATE_PATH,
                        help="the state kept by the last applied pass")
    parser.add_argument("--include", default=scan.GENERATED_REWRITES_PATH,
                        help="the Generated rewrite include file")
    parser.add_argument("--nginx-conf", default=NGINX_CONF_PATH,
                        help="the rendered gateway configuration to validate against")
    parser.add_argument("--filestore", default=scan.FILESTORE_DIR,
                        help="the filestore's parent directory")
    parser.add_argument("--exceptions", default=EXCEPTIONS_PATH,
                        help="the approved exception list")
    arguments = parser.parse_args(argv)

    # Read before the round, so the notification names only what it added.
    # Unreadable answers nothing rather than raising (`live_prefixes`).
    before = live_prefixes(arguments.include)
    step = STEP_STATE
    failure: RoundError | None = None
    try:
        loaded = scan.load_state(arguments.state, arguments.include)
        state_note = loaded.reason or f"{arguments.state}, {len(loaded.state.bundles)} bundles"
        step = STEP_SCAN
        result = scan.scan_databases(run_query or scan.psql_query)
        step = STEP_GENERATION
        outcome = apply_round(
            result,
            auto=arguments.auto,
            previous_state=loaded.state,
            force=arguments.force,
            filestore=arguments.filestore,
            include_path=arguments.include,
            nginx_conf_path=arguments.nginx_conf,
            exceptions_path=arguments.exceptions,
            state_path=arguments.state,
        )
    except Exception as error:
        # A `RoundError` knows its step and whether the include file had
        # already moved; anything else is the step this frame was in when
        # it was raised: a rendered configuration or an exception list that
        # cannot be read stops generation before anything is written. The
        # operator is told either way (issue #120), in the log as well as
        # in the notification, because the service's own line only says
        # that the round failed.
        failure = error if isinstance(error, RoundError) else RoundError(step, error)
        out(gate.mask(
            f"Rewrite scan (apply): the {failure.step} step raised; the include file "
            + ("now holds the new rules" if failure.replaced else "keeps the rules it already had")
        ))
        if arguments.auto:
            send_notification(raised_event(failure), notifier, out)
    if failure is not None:
        # Raised here, outside the handler, so the exception the step raised
        # reaches the log with its own chain and nothing added: the carrier
        # is for the notification, not the log.
        raise failure.__cause__
    report(outcome, state_note, out)
    send_notification(round_event(outcome, before, auto=arguments.auto), notifier, out)
    return 0 if outcome.healthy else 1


if __name__ == "__main__":
    sys.exit(main())
