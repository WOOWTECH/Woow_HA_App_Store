#!/usr/bin/env python3
"""Live tier: two sessions edit one to-do, and what the record keeps (#234).

    python odoo18ce/tests/e2e_collab_peer_snapshot_live.py probe \
        --env-file /projects/Woow_ha_odoo/.env --db odoo_parity
    python odoo18ce/tests/e2e_collab_peer_snapshot_live.py run \
        --env-file /projects/Woow_ha_odoo/.env --db odoo_parity \
        --run-id WOOW-PEER-<UTC timestamp> --out peer.jsonl
    python odoo18ce/tests/e2e_collab_peer_snapshot_live.py report peer.jsonl

**Nothing has run this script.** It is left behind for #243, which owns the
Live-tier row it measures: the Iteration that wrote it was told not to deploy
and not to take the measurement (#234's own comment). The pure functions below
-- the prefix shape, the labelling, the redaction and the verdict -- are driven
by `test_e2e_collab_peer_snapshot.py` at the Static tier; the browser steps are
written from the adapter this repository already uses on this host and have not
been executed against it. Read a failure in the browser steps as this script
being wrong before reading it as the host being wrong.

## What it measures

`project.task.description` is an html field with `'collaborative': true`. The
collaboration transport ships *serialised nodes* -- each attribute's value byte
for byte -- and the peer that joins second is handed the first peer's whole
document as a snapshot. Under Ingress that document's URLs carry the sending
page's prefix, which is `/api/hassio_ingress/<the add-on's ingress token>`. The
receiving session's save is what would write it to the record.

So: session A opens the to-do and types a marker **without saving**. Session B
joins the same to-do, and the run waits for A's unsaved marker to appear in B's
editable -- which is the transport's own evidence, since nothing has stored it.
B then types its own marker and saves, and the run reads `description` back
over ORM and classifies every Ingress prefix left in it.

Two pairs, because they answer different questions:

- `--pair ingress-ingress` (default): both sessions reach the add-on through
  Home Assistant. Their prefixes are **expected to be equal**: the token in the
  path is the add-on's `ingress_token`, one persisted secret per installed
  add-on, while the per-user session is a separate secret carried in the
  `ingress_session` cookie. The run records the two prefixes rather than
  assuming it, because that equality is the reason #210's strip already covers
  this pair -- and if they ever differ, this is the row that says so.
- `--pair ingress-public`: A is an Ingress session, B is the Public origin.
  B has no Runtime shim and no rewrite (ADR 0003 keeps that surface the control
  group), so a prefix it receives is a prefix it stores. This is the pair that
  can put the add-on's token in the record today, and the Ingress strip's part
  in it is healing the record on the next Ingress save, not preventing the
  write.

## What it writes

The to-do's `description` on the database named by `--db`, and nothing else: no
record is created and none is deleted. Both markers carry the run id, so the
record says which run last edited it. `probe` writes nothing at all -- it opens
both sessions, reports their prefixes and whether the transport delivered, and
stops before the save.

**No token ever reaches the output.** Every value is passed through `redact`,
which replaces each Ingress prefix with the label of the session it belongs to
(`<ingress:A>`, `<ingress:B>`, `<ingress:unknown>`) -- so the evidence says
*whose* prefix was stored without carrying the secret, which is the whole point
of reading the field back.

Environment: the names the parity run uses (`--env-file` fills unset ones) --
HA_BASE_URL, HA_TOKEN, ADDON_SLUG, ODOO_PUBLIC_URL, ODOO_TEST_LOGIN,
ODOO_TEST_PASSWORD, PARITY_TARGET, and `IGNORE_HTTPS_ERRORS=1` for a
self-signed certificate. The whole list is required even for
`--pair ingress-ingress`, which never opens the Public origin: this shares the
parity run's `Env`, and that is the parity run's contract. No artifact directory
is used -- `run` appends its one record to `--out`, and `probe` prints and keeps
nothing.

The record is a `woow.peer-snapshot.v1` and deliberately not an
`odoo-parity-evidence/v1`; the parity plan's section 12 says why, and
`test_e2e_collab_peer_snapshot.py` holds the two together.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

from e2e_menu_action_adapter import parse_env_file, sanitize_diagnostic
from e2e_parity_shared_layers_live import TIMEOUT, Env, IngressSide, PublicSide

# The shape of an Ingress prefix, which is nginx's `$safe_ingress_path` map and
# not a guess: a request whose `X-Ingress-Path` does not match it is served
# with no prefix at all. `test_e2e_collab_peer_snapshot.py` derives the same
# shape from the gateway template and refuses a difference, so this constant
# cannot drift away from the add-on it is measuring.
INGRESS_PREFIX_SHAPE = re.compile(r"/api/hassio_ingress/[A-Za-z0-9_-]{16,128}(?![A-Za-z0-9_-])")

# Not `odoo-parity-evidence/v1`. That schema is one record per *plan item*, with
# one column for each of the two **surfaces** a control was observed on; this
# measurement has two **sessions** and, in the `ingress-ingress` pair, only one
# surface -- and what it has to carry is each session's prefix and whose was
# stored, which a parity record has nowhere to put. Registered in the parity
# plan's section 12 beside that schema, and no run here feeds `conservation`.
EVIDENCE_SCHEMA = "woow.peer-snapshot.v1"

CLEAN = "CLEAN"
FOREIGN_PREFIX_STORED = "FOREIGN-PREFIX-STORED"
OWN_PREFIX_STORED = "OWN-PREFIX-STORED"
UNKNOWN_PREFIX_STORED = "UNKNOWN-PREFIX-STORED"
NOT_RUN = "NOT-RUN"

PAIRS = ("ingress-ingress", "ingress-public")

# The html field's editable, and the form's save button.
EDITABLE = ".o_field_html .odoo-editor-editable"
SAVE_BUTTON = ".o_form_button_save"


# --- What a value says, without saying a token ---------------------------------


def ingress_prefixes(value: str) -> list[str]:
    """Every distinct Ingress prefix in `value`, in the order it first occurs."""
    found: list[str] = []
    for match in INGRESS_PREFIX_SHAPE.finditer(value or ""):
        if match.group(0) not in found:
            found.append(match.group(0))
    return found


def redact(value: Any, labels: Mapping[str, str]) -> Any:
    """Replace every Ingress prefix with the label of the session it belongs to.

    A prefix no session claims is `<ingress:unknown>`: it is still a Supervisor
    token, so it is still never printed, and a reader can tell the two cases
    apart -- an unknown prefix in a record is a value this run did not put
    there.
    """
    if isinstance(value, str):
        def name(match: re.Match) -> str:
            return "/api/hassio_ingress/<ingress:%s>" % labels.get(match.group(0), "unknown")

        return INGRESS_PREFIX_SHAPE.sub(name, value)
    if isinstance(value, Mapping):
        return {key: redact(child, labels) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(child, labels) for child in value)
    return value


def classify(stored: str, labels: Mapping[str, str], saver: str) -> tuple[str, list[str]]:
    """The verdict for one stored value, and the labels of the prefixes in it.

    `saver` is the label of the session that wrote the value. Its own prefix
    surviving means the strip that #210 added did not run; another session's
    means the strip ran and did not recognise what it was given, which is what
    #234 is about; one nobody claims is a token this run cannot account for and
    is read the same way as a foreign one -- a prefix in a record is the harm
    whoever put it there.
    """
    present = [labels.get(prefix, "unknown") for prefix in ingress_prefixes(stored)]
    if not present:
        return CLEAN, []
    if any(label == "unknown" for label in present):
        return UNKNOWN_PREFIX_STORED, present
    if any(label != saver for label in present):
        return FOREIGN_PREFIX_STORED, present
    return OWN_PREFIX_STORED, present


def evidence_record(
    *,
    run_id: str,
    database: str,
    target: str,
    pair: str,
    task_id: int | None,
    prefixes: Mapping[str, str | None],
    transport: Mapping[str, Any],
    stored: str | None,
    labels: Mapping[str, str],
    saver: str,
    notes: str = "",
) -> dict[str, Any]:
    """One run's record. `verdict` is NOT-RUN until a value was read back."""
    if stored is None:
        verdict, present = NOT_RUN, []
    else:
        verdict, present = classify(stored, labels, saver)
    record = {
        "schema": EVIDENCE_SCHEMA,
        "run_id": run_id,
        "database": database,
        "target": target,
        "issue": 234,
        "pair": pair,
        "field": "project.task.description",
        "task_id": task_id,
        "saver": saver,
        # The prefixes the two sessions were served, redacted to their labels.
        # Equal prefixes are the expected reading of `ingress-ingress`, and the
        # record says so rather than leaving a reader to infer it from one line.
        "prefixes": {
            label: (redact(prefix, labels) if prefix else None)
            for label, prefix in prefixes.items()
        },
        "prefixes_equal": _equal_prefixes(prefixes),
        "transport": dict(transport),
        "stored": redact(stored, labels),
        "stored_prefixes": present,
        "verdict": verdict,
        "notes": notes,
    }
    return record


def _equal_prefixes(prefixes: Mapping[str, str | None]) -> bool | None:
    values = [prefix for prefix in prefixes.values() if prefix]
    if len(values) < 2:
        return None
    return len(set(values)) == 1


def report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the run found, and what #234's own criteria make of it."""
    verdicts = [record.get("verdict") for record in records]
    escalate = [
        record for record in records
        if record.get("verdict") in (FOREIGN_PREFIX_STORED, UNKNOWN_PREFIX_STORED)
    ]
    return {
        "records": len(records),
        "verdicts": {verdict: verdicts.count(verdict) for verdict in sorted(set(verdicts))},
        "transport_delivered": sorted(
            {bool((record.get("transport") or {}).get("delivered")) for record in records}
        ),
        # #234's acceptance criteria: a stored foreign token makes it a blocker
        # (parity plan section 1.3, token leak). Said by the report rather than
        # left to whoever reads the JSONL.
        "escalate_issue_234_to_blocker": bool(escalate),
        "pairs": sorted({record.get("pair") for record in records}),
    }


# --- The two sessions ----------------------------------------------------------


def _side_env(env: Env) -> Env:
    """A copy of `env`, so each session owns its own prefix and its own masker.

    `IngressSide.start` writes the prefix it was served onto the Env it was
    given, and two sessions sharing one Env would overwrite each other's -- so
    the second session's evidence would be masked with the first one's prefix.
    The secrets list is copied too, not shared: each session's masker is told
    about the other's prefix, and a shared list would make that one list.
    """
    copied = copy.copy(env)
    copied.extra_secrets = list(env.extra_secrets)
    return copied


def open_pair(env: Env, browser, pair: str, *, viewport=(1600, 1000)):
    """Session A first, then session B: the second to join is the receiver."""
    context_args: dict[str, Any] = {
        # The spelling every other script in this directory uses.
        "ignore_https_errors": os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1",
    }
    first = IngressSide(_side_env(env), browser, viewport=viewport, **context_args)
    if pair == "ingress-public":
        second = PublicSide(_side_env(env), browser, viewport=viewport, **context_args)
    else:
        second = IngressSide(_side_env(env), browser, viewport=viewport, **context_args)
    first.start()
    second.start()
    # Each side's masker must know the other's prefix as a secret of its own,
    # or a diagnostic from one session could print the other's token.
    for side, other in ((first, second), (second, first)):
        if other.env.prefix:
            side.env.extra_secrets.append(other.env.prefix)
    return first, second


def find_todo(side) -> int:
    """The to-do Odoo creates for every user: a personal task with no project.

    `_ensure_onboarding_todo()` copies `project_todo`'s `todo_user_onboarding`
    template into its description, so it is the record that carries the two
    pictures #210 was measured on. The lowest id is that one; a `--task-id`
    overrides this when a host has been edited into a different state.
    """
    ids = side.rpc("project.task", "search", [[["project_id", "=", False]]],
                   {"limit": 1, "order": "id asc"})
    if not ids:
        raise RuntimeError(
            "no personal to-do on this database: open the To-do app once as the test user, "
            "or name one with --task-id"
        )
    return int(ids[0])


def open_todo(side, task_id: int) -> None:
    side.goto("/odoo/project.task/%d" % task_id)
    side.wait_webclient()
    side.root.locator(EDITABLE).first.wait_for(timeout=TIMEOUT)


def type_marker(side, marker: str) -> None:
    """Type into the editable, which is what makes a collaboration step."""
    editable = side.root.locator(EDITABLE).first
    editable.click()
    side.page.keyboard.press("Control+End")
    side.page.keyboard.type(" " + marker)


def editable_html(side) -> str:
    return side.root.locator(EDITABLE).first.evaluate("node => node.innerHTML")


def wait_for_transport(side, marker: str, *, seconds: int = 30) -> dict[str, Any]:
    """Wait for the *other* session's unsaved marker to arrive in this one.

    Nothing has stored that marker, so its presence here is the collaboration
    transport and not a reload. Its absence is a finding of its own and not a
    failure of the run: it says the two sessions never became peers, which is
    the reading that rewrites the rest of #234.
    """
    for attempt in range(seconds * 2):
        html = editable_html(side)
        if marker in html:
            return {"delivered": True, "waited_seconds": attempt / 2.0}
        side.page.wait_for_timeout(500)
    return {
        "delivered": False,
        "waited_seconds": seconds,
        "detail": "the other session's unsaved marker never arrived; the two sessions "
                  "did not become collaboration peers",
    }


def save_form(side) -> None:
    button = side.root.locator(SAVE_BUTTON).first
    button.wait_for(timeout=TIMEOUT)
    button.click()
    side.root.locator(SAVE_BUTTON).first.wait_for(state="hidden", timeout=TIMEOUT)
    side.settle()


def read_description(side, task_id: int) -> str:
    [record] = side.rpc("project.task", "read", [[task_id], ["description"]])
    return record.get("description") or ""


def labels_for(first, second) -> dict[str, str]:
    labels: dict[str, str] = {}
    for label, side in (("A", first), ("B", second)):
        if side.env.prefix:
            labels[side.env.prefix] = label
    return labels


# --- Commands -----------------------------------------------------------------


def stage(env: Env, browser, pair: str, task_id: int | None, marker: str):
    """Both commands' common half, up to the point where only `run` saves.

    Session A opens the to-do and types `marker` **without saving**; session B
    joins the same record; the run waits for that marker to reach B. Everything
    after this differs: `probe` prints and stops, `run` types B's own marker,
    saves and reads the field back. A failure in here leaves the two contexts
    to `browser.close()` in `main`, which is the last thing either command does.
    """
    first, second = open_pair(env, browser, pair)
    labels = labels_for(first, second)
    task_id = task_id or find_todo(first)
    open_todo(first, task_id)
    type_marker(first, marker)
    open_todo(second, task_id)
    return first, second, labels, task_id, wait_for_transport(second, marker)


def do_probe(env: Env, browser, pair: str, task_id: int | None) -> int:
    """Open both sessions, report what they were served, and stop before saving."""
    first, second, labels, task_id, transport = stage(
        env, browser, pair, task_id, "WOOW-PEER-PROBE")
    try:
        print(json.dumps({
            "pair": pair,
            "task_id": task_id,
            "prefixes": {label: redact(side.env.prefix, labels)
                         for label, side in (("A", first), ("B", second))},
            "prefixes_equal": _equal_prefixes(
                {"A": first.env.prefix, "B": second.env.prefix}
            ),
            "transport": transport,
            "second_session_editable": redact(editable_html(second), labels)[:2000],
            "saved": False,
        }, indent=2, ensure_ascii=False))
        return 0 if transport["delivered"] else 1
    finally:
        # Nothing is saved. Leaving a dirty form may make Odoo ask to discard;
        # Playwright dismisses that dialog, and the record is as it was found
        # either way, because only a save writes the field.
        for side in (first, second):
            try:
                side.goto("/odoo")
            except Exception:  # noqa: BLE001 -- the report is already printed
                pass
            side.close()


def do_run(env: Env, browser, pair: str, task_id: int | None, run_id: str, out_path: str) -> int:
    first, second, labels, task_id, transport = stage(
        env, browser, pair, task_id, "%s-A" % run_id)
    try:
        type_marker(second, "%s-B" % run_id)
        save_form(second)
        stored = read_description(second, task_id)
        record = evidence_record(
            run_id=run_id,
            database=env.db,
            target=env.target,
            pair=pair,
            task_id=task_id,
            prefixes={"A": first.env.prefix, "B": second.env.prefix},
            transport=transport,
            stored=stored,
            labels=labels,
            saver="B",
            notes="" if transport["delivered"] else
                  "the receiving session never saw the sender's unsaved marker, so the "
                  "stored value is not evidence about the peer transport",
        )
        with open(out_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0 if record["verdict"] == CLEAN else 1
    finally:
        for side in (first, second):
            side.close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "run"):
        sub = commands.add_parser(name)
        sub.add_argument("--env-file")
        sub.add_argument("--db", required=True, help="the database the sessions must serve")
        sub.add_argument("--pair", choices=PAIRS, default=PAIRS[0])
        sub.add_argument("--task-id", type=int, help="the project.task to edit; default: the "
                                                    "test user's own onboarding to-do")
        sub.add_argument("--headed", action="store_true")
        if name == "run":
            sub.add_argument("--run-id", required=True,
                             help="the marker both sessions type, e.g. WOOW-PEER-<UTC timestamp>")
            sub.add_argument("--out", required=True, help="JSONL file; the record is appended")
    report_command = commands.add_parser("report")
    report_command.add_argument("records")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "report":
        with open(args.records, encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        result = report(records)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result["escalate_issue_234_to_blocker"] else 0

    if args.env_file:
        with open(args.env_file, encoding="utf-8") as handle:
            parse_env_file(handle, os.environ)
    os.environ["ODOO_DB"] = args.db
    env = Env(args.db)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headed,
            # The collaboration transport is WebRTC; the fake device flags are
            # what the parity run already launches with.
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        )
        try:
            if args.command == "probe":
                return do_probe(env, browser, args.pair, args.task_id)
            return do_run(env, browser, args.pair, args.task_id, args.run_id, args.out)
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 -- never print an unmasked secret
        message = sanitize_diagnostic(str(error))
        # The prefix shape is a credential wherever it appears, including in a
        # traceback from a session whose Env never loaded.
        message = redact(message, {})
        try:
            message = Env(os.environ.get("ODOO_DB", "")).mask(message)
        except Exception:  # noqa: BLE001 -- a missing variable was the failure
            pass
        print("peer-snapshot run failed: %s" % message, file=sys.stderr)
        sys.exit(2)
