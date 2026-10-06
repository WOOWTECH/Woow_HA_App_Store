#!/usr/bin/env python3
"""Live tier: two sessions edit one to-do, and what the record keeps (#234).

    python odoo18ce/tests/e2e_collab_peer_snapshot_live.py probe \
        --env-file /projects/Woow_ha_odoo/.env --db odoo_parity
    python odoo18ce/tests/e2e_collab_peer_snapshot_live.py run \
        --env-file /projects/Woow_ha_odoo/.env --db odoo_parity \
        --run-id WOOW-PEER-<UTC timestamp> --out peer.jsonl
    python odoo18ce/tests/e2e_collab_peer_snapshot_live.py report peer.jsonl

`probe` takes `--run-id` too and mints one when it is not given
(`WOOW-PEER-PROBE-<UTC timestamp>`, printed with its report): the marker it
types must be unique to the run, for the reason under **What it measures**.

**#243 has run this script**, on 2026-10-02 against Release 0.4.10, and its two
records are in `docs/testing/evidence/2026-10-02-issue-243/peer.jsonl`: `CLEAN`
on both pairs, and the transport delivered on neither, so those verdicts are
about the save path and not about a delivered peer snapshot. That run was also
every browser step's first execution, and it found three defects here. Two were
fixed under #263 and are worth knowing before trusting a reading from this file:
`probe` wrote the field it reported it did not, and its marker was a constant,
which made `delivered` unfalsifiable once the field had ever held it.

**The third is why nothing was ever delivered, and it was this script's (#265).**
The receiving session was never focused, and with no view setting
`collaborative_trigger` the collaboration plugin joins the peer network on the
editable's `focus` event and nowhere else -- while a session that has not joined
silently discards every signalling notification it is sent, the other session's
`ptp_join` included. So the sending session joined by accident, because typing
needs focus, and the receiving one never did; both pairs were predicted to time
out by the source before the host was involved. `focus_editable` is the step that
was missing, `transport_diagnosis` is what now attributes the outcome instead of
leaving it to be inferred from a timeout, and `heal_under_ingress` is the second
reading on the `ingress-public` pair that #243's run could not take because
nothing had been delivered to heal.

The pure functions below -- the prefix shape, the labelling, the redaction, the
wait's judgement, the probe's verdict and the report -- are driven by
`test_e2e_collab_peer_snapshot.py` at the Static tier. The browser steps are not,
and the two defects above are what that costs: both were mistakes about what a
*step* does, which no Static tier can see. So the steps are pinned there by
shape instead, and a failure in them should still be read as this script being
wrong before it is read as the host being wrong.

## What it measures

`project.task.description` is an html field with `'collaborative': true`. The
collaboration transport ships *serialised nodes* -- each attribute's value byte
for byte -- and the peer that joins second is handed the first peer's whole
document as a snapshot. Under Ingress that document's URLs carry the sending
page's prefix, which is `/api/hassio_ingress/<the add-on's ingress token>`. The
receiving session's save is what would write it to the record.

So: session A opens the to-do, the run reads A's editable **before anything is
typed** -- the baseline, which is the document both sessions load -- and A then
types a marker **without saving**. Session B joins the same to-do, **focuses its
editable** -- which is what joins it to the peer network, and the step whose
absence made #243's run deliver nothing -- and the run waits for A's unsaved
marker to appear in B's editable. That arrival is the transport's own evidence
only because the marker is unique to the run and the pair and was not in the
baseline: a marker
some earlier run stored would otherwise be read out of the *loaded* value on the
first poll and reported as an instant delivery, which is the false positive #263
found on a `delivered` of 0.0 seconds. B then types its own marker and saves, and
the run reads `description` back over ORM and classifies every Ingress prefix left
in it.

**And the run says why the transport did what it did.** `delivered: false` with
nothing beside it is what #243's run left, and the account that went into three
documents afterwards -- "the two sessions never became collaboration peers" --
was an inference from a timeout. So both commands now read each session's own
state (`collaboration_reading`) and count the signalling it posted
(`SignallingCount`), and `transport_diagnosis` names the first rung that holds:
the field is not collaborative, the bus is not connected on that surface, the two
sessions are on different channels, a session never joined the peer network, or
they joined and no data channel opened. Those are the three questions #265 asks,
answered by the run rather than by the next reader.

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
  write. So this pair is measured **twice**: once after B saves, which may carry
  the prefix, and once after A has loaded that value and saved it under Ingress,
  which must be clean (`heal_under_ingress`). `verdict` is the first reading and
  `healing.verdict` the second; `final_verdict` is the one #234's escalation rule
  is applied to, because the harm that Issue is about is a token left **in** the
  record. A prefix stored and then healed inside one run is not lost for that --
  `report` names it as `foreign_prefix_healed`, which is the fix doing the only
  thing it can do here.

## What it writes

`run` writes the to-do's `description` on the database named by `--db`, and
nothing else: no record is created and none is deleted. Every marker carries the
run id and the pair (`marker`), so the record says which run last edited it and
the two pairs of one run cannot type the same string. On `ingress-ingress` A's form
is discarded once B has saved, so the stored value is exactly what B saved. On
`ingress-public` A discards that leftover and then **saves once on purpose**: that
save is the healing half of the measurement, so the value the record ends with is
the one an Ingress session stored after loading what the Public peer wrote.

`probe` writes nothing -- and **discarding is what makes that true**, not
declining to save. Navigating away from a dirty To-do form persists the
editable's content: two `probe` runs left their marker in the stored description
twice (#263, found by #243's run on 0.4.10). So `probe` clicks the form's own
Discard on both sessions before it leaves, which reloads the record from the
database, and then reads `description` back over ORM and reports
`wrote_nothing`. The claim is measured and carried in the output rather than
asserted here, and a `probe` that did write exits non-zero. `discard_form` holds
the mechanism and why each of its three load-bearing details is not defensive --
the single frame resolve (#292), the wait on the form coming clean, and the
visibility check ahead of the click.

**What a delivering `probe` measured about B's form** (#265): B holds the sending
session's whole document, marker included, and its form reports itself **clean**
-- `discarded: {"B": {"dirty": false}}` on both pairs of the first run that
delivered. A collaboration reset is not a user edit, so the html field raises no
`FIELD_IS_DIRTY` for it, and B's discard goes on having nothing to do even now
that something arrives. It stays, because "nothing to discard" is a reading taken
on each run and not a property to rely on: `probe` reports `dirty` per session
precisely so that a change here shows up as a changed reading rather than as a
write.

**The read-back is the guarantee, and the discard is only the means** -- which is
deliberate, because this measurement cannot remove every way the form writes
itself. Odoo saves a form on `visibilitychange` as well as on unload
(`web/static/src/views/form/form_controller.js:483`), that handler is **not**
gated on the record being dirty, and it calls a full `save()`. A session whose
page is backgrounded while its form is dirty therefore writes with no navigation
at all -- and session A is *necessarily* dirty while session B opens, since A's
unsaved marker is the thing B is waiting for. The two sessions get their own
browser contexts, which is the arrangement least likely to hide either page, but
"least likely" is not a guarantee and this module will not claim one. So the
field is read back on every `probe` and the result reported: a write that happens
anyway is **detected and named** rather than assumed away, and the record then
needs the marker stripped the way #243's run stripped two.

**No token ever reaches the output.** Every value is passed through `redact`,
which replaces each Ingress prefix with the label of the session it belongs to
(`<ingress:A>`, `<ingress:B>`, `<ingress:unknown>`) -- so the evidence says
*whose* prefix was stored without carrying the secret, which is the whole point
of reading the field back.

**The ambient rows a run leaves are counted by the run** (#256, #264). Both
commands count `website.track` and `website.visitor` over session A's own RPC
once both sessions are logged in and again on the way out, and `run` appends the
delta to `--out`'s name with `.ambient.json` for its extension (`peer.jsonl` ->
`peer.ambient.json`) -- counts only, no URL and no visitor identity. This driver
opens `/odoo/...` backend routes only, so the expected delta is zero; the point
is that **a zero that is read is a reading and a zero that is assumed is not**,
which is the distinction #256 draws about the adapter's `crawl`. `probe` keeps
no file, so its figure is printed on stderr and not written -- it is still read.
The counts come over the session and never over `ssh`, and the denominator is
every document GET either session's browser context made under its own base.

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
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from e2e_menu_action_adapter import (
    AMBIENT_BASIS_DOCUMENTS,
    RunInfo,
    SessionAmbientDriver,
    ambient_accounting,
    parse_env_file,
    sanitize_diagnostic,
)
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

# The pair `run` measures twice: the Public peer stores what it is handed and the
# Ingress strip can only heal the record on the next Ingress save, so one reading
# of that pair is half a measurement (`heal_under_ingress`).
HEALING_PAIR = "ingress-public"
PAIRS = ("ingress-ingress", HEALING_PAIR)

# `probe`'s run id when the command line does not give one. It is a *run* id and
# not a constant marker: #263.
PROBE_RUN_PREFIX = "WOOW-PEER-PROBE"

# The html field's editable, the form's save button, its discard button, and the
# indicator that says the form is dirty. The discard button is in the DOM on a
# clean form too, hidden behind `o_form_status_indicator_buttons.invisible`, so
# it is clicked only when it is visible -- #238's run lost a measurement to
# exactly that (clicking the hidden save button).
EDITABLE = ".o_field_html .odoo-editor-editable"
SAVE_BUTTON = ".o_form_button_save"
DISCARD_BUTTON = ".o_form_button_cancel"
UNSAVED = ".o_form_status_indicator_buttons:not(.invisible)"

# The signalling route the collaboration plugin's `broadcastAll` posts to
# (`html_editor/controllers/main.py:578`). Counted per session, because it is the
# one piece of this measurement that does not depend on the client telling the
# truth about itself: a session that joined the peer network posted a `ptp_join`
# here, and a session that never joined posted nothing at all.
BUS_BROADCAST_ROUTE = "/html_editor/bus_broadcast"

# What a session says about its own collaboration, read out of the live
# component tree. `odoo.__WOWL_DEBUG__.root` is set for every web client and not
# only in debug mode (`web/static/src/env.js:195`), the html field keeps its
# editor in `this.editor` (`html_editor/static/src/fields/html_field.js:225`),
# and the plugin's id is static (`collaboration_odoo_plugin.js:47`).
#
# Only counts and flags come back -- no peer id, no URL, no document. The channel
# name is `editor_collaboration:<model>:<field>:<id>`
# (`collaboration_odoo_plugin.js:134`), which carries the record's id and nothing
# secret; it is in the reading because "do the two sessions share the
# collaboration channel at all" is one of the questions #265 asks.
COLLABORATION_STATE_JS = """() => {
  const fields = (node, found = []) => {
    if (node.component?.constructor?.name === "HtmlField") found.push(node.component);
    for (const key in node.children) fields(node.children[key], found);
    return found;
  };
  const root = window.odoo?.__WOWL_DEBUG__?.root;
  if (!root) return {unread: "no __WOWL_DEBUG__ root on this page"};
  const field = fields(root.__owl__)[0];
  if (!field) return {unread: "no HtmlField is mounted"};
  const plugin = field.editor?.plugins?.find(
    (one) => one.constructor.id === "collaborationOdoo");
  const bus = root.env.services?.bus_service;
  return {
    is_collaborative: Boolean(field.props.isCollaborative),
    display_readonly: Boolean(field.displayReadonly),
    res_id: field.props.record?.resId ?? null,
    plugin_present: Boolean(plugin),
    channel: plugin?.collaborationChannelName ?? null,
    ptp_joined: plugin ? Boolean(plugin.ptpJoined) : null,
    ptp_created: plugin ? Boolean(plugin.ptp) : null,
    peers: plugin?.ptp ? Object.keys(plugin.ptp.peersInfos).length : null,
    connected_peers: plugin?.ptp?.getConnectedPeerIds?.()?.length ?? null,
    bus_worker_state: bus?.workerState ?? null,
    bus_connection_lost:
      root.env.services?.["bus.monitoring_service"]?.isConnectionLost ?? null,
  };
}"""

# What the ladder in `transport_diagnosis` can conclude, named rather than
# spelled out at each `return`: a slug is what an Issue or a plan row quotes.
DELIVERED = "delivered"
MARKER_COLLISION = "marker-collision"
NOT_COLLABORATIVE = "field-not-collaborative"
BUS_NOT_CONNECTED = "bus-not-connected"
DIFFERENT_CHANNEL = "different-collaboration-channel"
NOT_JOINED = "peer-network-not-joined"
NO_DATA_CHANNEL = "no-peer-data-channel"
UNATTRIBUTED = "unattributed"


# --- What a run calls its markers ----------------------------------------------


def marker(run_id: str, label: str, pair: str) -> str:
    """The marker session `label` types, which **both** commands get from here.

    A marker has to be unique to the run, because the whole argument for reading
    its arrival as a delivery is that nothing has stored it. `probe` used to type
    the constant `WOOW-PEER-PROBE`; once a probe had written that string into the
    field -- which probes did, see the module docstring -- the next probe found it
    in the receiving editable on the first poll and reported `delivered: true` at
    0.0 seconds while nothing had been delivered (#263). One helper, so the two
    commands cannot drift apart on it again.

    **The pair is in it, not only the run id** (#265, found by the first run that
    delivered). A run is one `--run-id` over *both* pairs -- that is the evidence
    discipline every Live script here shares -- and `run` stores its marker, so the
    second pair opened a record that already held the first pair's
    `<run-id>-A`. `await_marker`'s baseline guard caught it and reported
    `marker_pre_existing: true`, which is the guard working and a void reading of
    the transport all the same: it returns without waiting. The run id makes a
    marker unique across runs and the pair makes it unique within one.

    What it still does not cover is the same pair run twice under one run id. That
    is the guard's remaining job, and a rerun takes a new `--run-id`.
    """
    return "%s-%s-%s" % (run_id, pair, label)


def mint_run_id(now: datetime, prefix: str = PROBE_RUN_PREFIX) -> str:
    """A run id in the shape `run` takes on the command line, for `probe`.

    `probe` is the step a reader runs by hand first, so it must not need a run id
    typed to be safe. `now` is passed in rather than read here, which is what
    lets the Static tier pin the shape.
    """
    return "%s-%sZ" % (prefix, now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S"))


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


def stored_prefix_labels(stored: str, labels: Mapping[str, str]) -> list[str]:
    """Which sessions' prefixes are in a value, in order, without judging them.

    Separate from `classify` because a reading and a verdict are not the same
    thing, and one caller has no verdict to give: `probe` saves nothing, so there
    is no saver for a saver-relative verdict to be relative *to*. It reports this
    instead (#263).

    Note what `labels` does on the `ingress-ingress` pair: both sessions are
    served the add-on's one `ingress_token`, so the two prefixes are equal and
    `labels_for` collapses to a single entry -- whichever session it wrote last.
    A label from here is therefore "a session whose prefix this is", not reliably
    *which* one, on the pair where the two are indistinguishable by construction.
    That is exactly why `prefixes_equal` is recorded separately.
    """
    return [labels.get(prefix, "unknown") for prefix in ingress_prefixes(stored)]


def classify(stored: str, labels: Mapping[str, str], saver: str) -> tuple[str, list[str]]:
    """The verdict for one stored value, and the labels of the prefixes in it.

    `saver` is the label of the session that wrote the value. Its own prefix
    surviving means the strip that #210 added did not run; another session's
    means the strip ran and did not recognise what it was given, which is what
    #234 is about; one nobody claims is a token this run cannot account for and
    is read the same way as a foreign one -- a prefix in a record is the harm
    whoever put it there.
    """
    present = stored_prefix_labels(stored, labels)
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
    collaboration: Mapping[str, Any] | None = None,
    healing: Mapping[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """One run's record. `verdict` is NOT-RUN until a value was read back.

    `verdict` is the value **the peer's save** left, which on the
    `ingress-public` pair is deliberately not the end of the measurement:
    `healing` carries the second reading, after the Ingress session has loaded
    that value and saved it once (`healing_read`). `final_verdict` is the one the
    escalation rule reads, and it is the healing verdict wherever there is one.
    """
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
        # Why the transport did what it did, so a `delivered: false` is attributed
        # by the run that read it and not by the next reader's inference (#265).
        "collaboration": redact(dict(collaboration or {}), labels),
        "stored": redact(stored, labels),
        "stored_prefixes": present,
        "verdict": verdict,
        "healing": redact(dict(healing), labels) if healing else None,
        "notes": notes,
    }
    return record


def _equal_prefixes(prefixes: Mapping[str, str | None]) -> bool | None:
    values = [prefix for prefix in prefixes.values() if prefix]
    if len(values) < 2:
        return None
    return len(set(values)) == 1


HEALED_NOTE = (
    "the peer's save stored an Ingress prefix and the next Ingress save removed it, which is the "
    "whole of what the Ingress fix can do on this pair -- it cannot prevent that write"
)
UNHEALED_NOTE = (
    "a prefix the Public peer stored is still in the record after an Ingress save, so the strip "
    "did not heal it"
)


def healing_read(*, loaded: str, stored: str, labels: Mapping[str, str],
                 saver: str) -> dict[str, Any]:
    """The second half of the `ingress-public` measurement: did the Ingress save heal it?

    ADR 0004's refinement, which #243's run left with no implementation: *read the
    field after the Public peer saves (it may carry the prefix), then save once
    under Ingress and read again (it must be clean)*. The two readings are not one
    reading taken twice -- the Public origin serves no shim and no rewrite (ADR
    0003 keeps it the control group), so a prefix it is handed is a prefix it
    stores, and the Ingress strip's part is **healing the record on the next
    Ingress save and not preventing the write**. A record with only the first
    reading cannot tell those two apart.

    `loaded` is the Ingress session's editable *before* it saves, and it is a
    reading in its own right: it says the healing save had a subject. A `CLEAN`
    after a save that loaded nothing to strip is a weaker statement than one after
    a save that loaded a prefix, and the record keeps the difference rather than
    leaving both as the same `CLEAN`.

    **Any prefix in the loaded value is a subject, including this session's own.**
    That is what the first run to deliver measured, and it is not the shape this
    function first assumed: the `ingress-public` pair's two sessions are served
    *one* token, the add-on's, so the prefix the Public peer stored is the Ingress
    session's own and a subject test of "whose label is it" called the central case
    "nothing foreign to strip". What makes it the harm is the token being in a
    record at all, whoever's session it travelled through -- the same reason
    `classify` treats `OWN-PREFIX-STORED` as a defect and not as a pass.
    """
    verdict, present = classify(stored, labels, saver)
    loaded_prefixes = stored_prefix_labels(loaded, labels)
    if verdict == CLEAN and loaded_prefixes:
        notes = HEALED_NOTE
    elif verdict in (FOREIGN_PREFIX_STORED, UNKNOWN_PREFIX_STORED):
        notes = UNHEALED_NOTE
    elif verdict == CLEAN:
        notes = ("the Ingress save left the field clean, and it had nothing to strip: the value "
                 "it loaded carried no Ingress prefix at all")
    else:
        notes = ""
    return {
        "performed": True,
        "saver": saver,
        "loaded_prefixes": loaded_prefixes,
        "stored": redact(stored, labels),
        "stored_prefixes": present,
        "verdict": verdict,
        "notes": notes,
    }


def healing_not_performed(reason: str) -> dict[str, Any]:
    """No second reading, and why -- never a silently absent one.

    `final_verdict` then falls back to the peer's save, which is the fail-closed
    direction: a pair whose heal could not be measured escalates on what *was*
    measured rather than on a missing `CLEAN`.
    """
    return {"performed": False, "reason": reason}


def final_verdict(record: Mapping[str, Any]) -> str | None:
    """The verdict for the value the record **ends** with.

    Which is the healing verdict wherever the healing save ran, and the peer's
    save otherwise. This is the reading #234's escalation rule is applied to
    (#265): the harm that Issue is about is a Supervisor token sitting in
    `project.task.description`, so what decides it is what is in the field when
    the run is done -- not an intermediate value the run then removed on purpose.
    An intermediate foreign prefix is not thrown away for that: `report` names it
    separately, so "the Public peer stored one and the Ingress save healed it"
    cannot be read as "nothing was ever stored".
    """
    healing = record.get("healing") or {}
    if healing.get("performed"):
        return healing.get("verdict")
    return record.get("verdict")


def _delivered(record: Mapping[str, Any]) -> bool:
    return bool((record.get("transport") or {}).get("delivered"))


ISSUE_234_RULE = (
    "#234's criterion is a *confirmed* stored foreign token, so this reads every value the run "
    "read and not only the last one: a prefix the run then removed was still in the record, and "
    "a rule that only looked at the end would answer 'no' to the measurement that proves the "
    "escape exists. Whether a token that is confirmed **and** healed moves #234's severity is "
    "#234's decision; what a report may not do is hide the confirmation behind the heal."
)


def escalating_readings(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every reading in one record that confirms a stored foreign or unclaimed prefix.

    `ISSUE_234_RULE` is why this is every reading and not `final_verdict`. The
    distinction cost a review: the first spelling of this read the value the record
    ends with, so a run that had just measured the Public peer writing a Supervisor
    token into `project.task.description` -- the exact escape #234 exists for --
    printed `escalate_issue_234_to_blocker: false`, because the next Ingress save
    had healed it. The heal is a reading of its own and it is reported as one
    (`foreign_prefix_healed`); it is not a reason to answer "nothing was
    confirmed".
    """
    confirmed = (FOREIGN_PREFIX_STORED, UNKNOWN_PREFIX_STORED)
    healing = record.get("healing") or {}
    readings = [("the peer's save", record.get("verdict"))]
    if healing.get("performed"):
        readings.append(("the Ingress healing save", healing.get("verdict")))
    return [{"pair": record.get("pair"), "verdict": verdict, "reading": where}
            for where, verdict in readings if verdict in confirmed]


def report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the run found, and what #234's own criteria make of it.

    **A `CLEAN` is reported with the transport it was read under** (#265). #243's
    run recorded two of them while the collaboration transport delivered on
    neither pair, and every document that then quoted "measured, `CLEAN`" --
    ADR 0004's postscript, the parity plan's row, the evidence README -- was
    quoting a measurement of the *save path* as if it were a measurement of a
    delivered peer snapshot. The two are separated here so the shorter sentence
    cannot be written again by accident.
    """
    verdicts = [record.get("verdict") for record in records]
    finals = [final_verdict(record) for record in records]
    clean_delivered = sorted(record.get("pair") for record in records
                             if final_verdict(record) == CLEAN and _delivered(record))
    clean_undelivered = sorted(record.get("pair") for record in records
                               if final_verdict(record) == CLEAN and not _delivered(record))
    escalate = [reading for record in records for reading in escalating_readings(record)]
    healed = [record for record in records
              if record.get("verdict") in (FOREIGN_PREFIX_STORED, UNKNOWN_PREFIX_STORED)
              and final_verdict(record) == CLEAN]
    return {
        "records": len(records),
        # The peer's save, which is what this key has always counted.
        "verdicts": {verdict: verdicts.count(verdict) for verdict in sorted(set(verdicts))},
        # And the value each record ends with, which is what the rule below reads.
        "final_verdicts": {verdict: finals.count(verdict)
                           for verdict in sorted(set(finals), key=str)},
        "transport_delivered": sorted(
            {_delivered(record) for record in records}
        ),
        "clean": {
            "with_a_delivered_transport": clean_delivered,
            "with_no_delivery": clean_undelivered,
        },
        "clean_means": clean_means(clean_delivered, clean_undelivered),
        # Named rather than folded into the clean count: on the `ingress-public`
        # pair this is the fix working as ADR 0004 says it can -- the Public
        # peer's write happened and the next Ingress save removed it.
        "foreign_prefix_healed": [
            {"pair": record.get("pair"), "stored_by": record.get("saver"),
             "healed_by": (record.get("healing") or {}).get("saver"),
             "notes": HEALED_NOTE}
            for record in healed
        ],
        "healing": {
            "performed": sorted(record.get("pair") for record in records
                                if (record.get("healing") or {}).get("performed")),
            "not_performed": {record.get("pair"): (record.get("healing") or {}).get("reason")
                              for record in records
                              if record.get("healing") and
                              not record["healing"].get("performed")},
        },
        "transport_causes": {record.get("pair"): (record.get("collaboration") or {}).get("cause")
                             for record in records},
        # #234's acceptance criteria: a stored foreign token makes it a blocker
        # (parity plan section 1.3, token leak). Said by the report rather than
        # left to whoever reads the JSONL, and said of **every** reading the run
        # took -- `ISSUE_234_RULE` is why, and what reading it the other way cost.
        "escalate_issue_234_to_blocker": bool(escalate),
        "escalated_on": escalate,
        "escalation_rule": ISSUE_234_RULE,
        # Whether anything is still in the field now, which is the question the
        # escalation is *not* asking: a run can confirm the write and leave none.
        "foreign_prefix_still_stored": [
            record.get("pair") for record in records
            if final_verdict(record) in (FOREIGN_PREFIX_STORED, UNKNOWN_PREFIX_STORED)
        ],
        "pairs": sorted({record.get("pair") for record in records}),
    }


def clean_means(delivered: Sequence[str], undelivered: Sequence[str]) -> str:
    """The sentence that keeps a `CLEAN` from being quoted as more than it is."""
    if not delivered and not undelivered:
        return "no record here reads CLEAN"
    said = []
    if delivered:
        said.append("on %s the receiving session was handed a peer snapshot before it saved, so "
                    "CLEAN there is about a delivered snapshot" % ", ".join(delivered))
    if undelivered:
        said.append("on %s the transport delivered nothing, so CLEAN there is about the save "
                    "path only and says nothing about a delivered peer snapshot (#265)"
                    % ", ".join(undelivered))
    return "; ".join(said)


# --- What a wait and a probe conclude ------------------------------------------
#
# Pure, and pinned at the Static tier with the rest: these two are where #263's
# two false readings were decided, and neither needs a browser to be wrong.

PRE_EXISTING_DETAIL = (
    "the marker was already in the editable before the other session typed it, so a "
    "match here would be a value something had stored and not a delivery"
)
NEVER_ARRIVED_DETAIL = (
    "the other session's unsaved marker never arrived; the two sessions did not become "
    "collaboration peers"
)


def await_marker(
    read: Callable[[], str],
    marker_text: str,
    *,
    baseline: str | None,
    sleep: Callable[[int], Any],
    seconds: int = 30,
) -> dict[str, Any]:
    """Poll `read` for `marker_text`, refusing a match that was already there.

    `baseline` is the editable as it read **before** the other session typed --
    the loaded document, which is what both sessions start from. A marker already
    in it cannot have been delivered, so this does not wait for one: it says so
    and stops. That is the guard #263 asked for, and the run id in the marker is
    the other half of it -- the guard catches a collision, the run id makes one
    almost impossible.

    `waited_seconds` of 0.0 with `delivered` true is a legitimate reading and not
    a contradiction of any of this: the receiving session joins *after* the sender
    typed, so the snapshot it is handed can carry the marker on the first poll.
    It is still the shape to look at twice, which is why the number is recorded
    rather than reduced to a boolean (parity plan section 12).
    """
    if marker_text in (baseline or ""):
        return {
            "delivered": False,
            "waited_seconds": 0.0,
            "marker_pre_existing": True,
            "detail": PRE_EXISTING_DETAIL,
        }
    for attempt in range(seconds * 2):
        if marker_text in (read() or ""):
            return {
                "delivered": True,
                "waited_seconds": attempt / 2.0,
                "marker_pre_existing": False,
            }
        sleep(500)
    return {
        "delivered": False,
        "waited_seconds": float(seconds),
        "marker_pre_existing": False,
        "detail": NEVER_ARRIVED_DETAIL,
    }


def transport_note(transport: Mapping[str, Any]) -> str:
    """What a record has to say about its own value when nothing was delivered.

    A delivered transport needs no note. An undelivered one does, and *which*
    way it failed changes the sentence: "the marker never arrived" and "the
    marker was already there" are different findings, and the second one says the
    run id collided, which makes the whole record suspect rather than just its
    transport half. So the wait's own detail is carried through instead of one
    fixed sentence -- the old note said "never saw the sender's marker" either
    way, which would have been a false account of the second case.
    """
    if transport.get("delivered"):
        return ""
    detail = transport.get("detail") or "the marker did not arrive"
    return "%s -- so the stored value is not evidence about the peer transport" % detail


JOIN_ON_FOCUS_DETAIL = (
    "the collaboration plugin joins the peer network on the editable's `focus` event when no "
    "view sets `collaborative_trigger` (`collaboration_odoo_plugin.js:91-99`), and a session "
    "that has not joined discards every signalling notification it receives, including the "
    "other session's `ptp_join` (`:156-158`) -- so an unfocused receiver cannot be delivered to"
)


def _reading_value(reading: Mapping[str, Any] | None, key: str) -> Any:
    """One value out of a session's reading, or `None` if there is no reading."""
    if not isinstance(reading, Mapping) or reading.get("unread"):
        return None
    return reading.get(key)


def transport_diagnosis(
    *,
    transport: Mapping[str, Any],
    sessions: Mapping[str, Mapping[str, Any]],
    signalling: Mapping[str, int],
) -> dict[str, Any]:
    """Why the transport did or did not deliver, from what the two sessions said.

    #265 is this function's reason to exist: #243's run recorded `delivered:
    false` on both pairs with nothing beside it, so "the two sessions never became
    collaboration peers" was the only account available and it was an inference
    from a timeout. The three questions that Issue asks -- is the field
    collaborative on this build, is the bus reachable on each surface, do the two
    sessions share the collaboration channel -- are each a value in `sessions`
    here, so a run answers them instead of leaving them to be guessed.

    A ladder and not a set of flags, because the readings are ordered by what they
    make the later ones worth: with no bus there is nothing to conclude from a
    peer count, and with a field that is not collaborative there is no plugin to
    read a channel off. The first rung that holds is the `cause`; everything read
    is in the record either way.

    Pure, so the Static tier drives it: this is a judgement about readings, and
    the readings are what the browser is for.
    """
    labels = sorted(sessions)
    channels = {label: _reading_value(sessions.get(label), "channel") for label in labels}
    unread = [label for label in labels
              if not isinstance(sessions.get(label), Mapping)
              or sessions[label].get("unread")]
    diagnosis: dict[str, Any] = {
        "sessions": {label: dict(sessions[label]) for label in labels if label in sessions},
        "signalling_posts": {label: int(signalling.get(label, 0)) for label in labels},
        "signalling_route": BUS_BROADCAST_ROUTE,
        "shared_channel": (None if None in channels.values()
                           else len(set(channels.values())) == 1),
    }

    def conclude(cause: str, detail: str) -> dict[str, Any]:
        diagnosis["cause"] = cause
        diagnosis["detail"] = detail
        return diagnosis

    if transport.get("delivered"):
        return conclude(DELIVERED, "")
    if transport.get("marker_pre_existing"):
        # Read before every rung below, because on this one the readings are not
        # evidence about anything: `await_marker` returns without waiting, so the
        # sessions may well have been peers and the transport may well have
        # delivered -- the run simply cannot say. Naming it is the point; the first
        # run that hit it recorded `unattributed` beside two sessions that were
        # plainly connected, which reads as a mystery rather than as a void reading.
        return conclude(MARKER_COLLISION,
                        "the marker was already in the loaded document, so the wait returned "
                        "without measuring anything: this reading is void rather than negative, "
                        "and the next run needs a marker unique to the run *and* the pair")
    not_collaborative = [label for label in labels
                         if _reading_value(sessions.get(label), "is_collaborative") is False
                         or _reading_value(sessions.get(label), "plugin_present") is False]
    if not_collaborative:
        return conclude(NOT_COLLABORATIVE,
                        "session(s) %s mounted an html field that is not collaborative, so "
                        "there is no peer network to join on that surface"
                        % ", ".join(not_collaborative))
    no_bus = [label for label in labels
              if _reading_value(sessions.get(label), "bus_worker_state") not in (None, "CONNECTED")]
    if no_bus:
        return conclude(BUS_NOT_CONNECTED,
                        "the bus worker is not connected on session(s) %s, and the signalling "
                        "this transport needs goes over the bus -- nothing can be negotiated "
                        "without it" % ", ".join(no_bus))
    if diagnosis["shared_channel"] is False:
        return conclude(DIFFERENT_CHANNEL,
                        "the two sessions subscribed to different collaboration channels, so "
                        "neither one's signalling reaches the other")
    not_joined = [label for label in labels
                  if _reading_value(sessions.get(label), "ptp_joined") is False]
    if not_joined:
        return conclude(NOT_JOINED,
                        "session(s) %s never joined the peer network: %s"
                        % (", ".join(not_joined), JOIN_ON_FOCUS_DETAIL))
    no_peers = [label for label in labels
                if _reading_value(sessions.get(label), "connected_peers") == 0]
    if no_peers:
        return conclude(NO_DATA_CHANNEL,
                        "session(s) %s joined and signalled but hold no connected peer, so the "
                        "WebRTC data channel the steps travel over never opened -- the bus "
                        "carries the negotiation and never the content" % ", ".join(no_peers))
    return conclude(UNATTRIBUTED,
                    "nothing in the readings accounts for the absence%s"
                    % (" (session(s) %s could not be read)" % ", ".join(unread) if unread else ""))


def probe_verdict(
    *,
    transport: Mapping[str, Any],
    stored: str,
    run_id: str,
    discarded: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Whether `probe`'s claims held: it delivered, it wrote nothing, and it can say so.

    `wrote_nothing` is read back off the record rather than asserted, because
    asserting it is exactly what went wrong: the docstring, `docs/agents/
    live-tier.md` and the `finally` block all said the field was untouched while
    two runs' markers sat in it (#263). The marker carries the run id, so this
    looks for *this* probe's write and not for a previous one's leftovers.

    **A form left dirty fails the probe even when the read-back is clean**, and
    that is not belt-and-braces. The read-back can only see writes that have
    already happened; a session still holding unsaved content can be written
    afterwards, by the `visibilitychange` save or by the unload, both of which
    outlive this function. On that path a clean read-back means "not yet", not
    "not at all" -- so the one thing the probe must not do is report
    `wrote_nothing` and exit 0 while leaving the write armed.
    """
    wrote_nothing = run_id not in (stored or "")
    left_dirty = sorted(
        label for label, outcome in discarded.items()
        if outcome.get("dirty") and not outcome.get("discarded")
    )
    if not wrote_nothing:
        detail = ("this probe's own run id is in the stored value, so the probe wrote the "
                  "field it reports it did not: the record needs the marker removed, and "
                  "the discard step did not hold")
    elif left_dirty:
        detail = ("the field read back clean, but session(s) %s were left with unsaved "
                  "content: a dirty form is still written on the way out, so this says "
                  "'not yet' and not 'not at all' -- read the field again on the host"
                  % ", ".join(left_dirty))
    else:
        detail = ""
    return {
        "wrote_nothing": wrote_nothing,
        "forms_left_dirty": left_dirty,
        "detail": detail,
        "exit_code": 0 if (transport.get("delivered") and wrote_nothing and not left_dirty)
                     else 1,
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


class SignallingCount:
    """Every collaboration signalling POST one session's context made.

    The corroborating half of the diagnosis, and the reason it is here rather than
    read off the page: `collaboration_reading` asks the client about itself, and a
    client that never joined the peer network is exactly the client whose own
    account of joining is worth least. This counts what went over the wire
    instead. A session that joined posted a `ptp_join` to
    `BUS_BROADCAST_ROUTE`; a session that never focused its editable posted
    nothing at all, which is the shape #265 is about.

    Counted per context off Playwright's `request` event, the way
    `NavigationCount` counts documents (`e2e_menu_action_adapter.py`), and for the
    same reason: the requests are not calls this code makes. A listener that
    raised would raise inside Playwright's dispatch on whatever call happened to
    be waiting, so it cannot.
    """

    def __init__(self, context) -> None:
        self.posts = 0
        context.on("request", self._seen)

    def _seen(self, request) -> None:
        try:
            if request.method == "POST" and BUS_BROADCAST_ROUTE in request.url:
                self.posts += 1
        except Exception:  # noqa: BLE001 -- an accounting listener may not break a run
            pass


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
    # Before the login, so no signalling post can fall outside the count. The
    # counter is attached to the session because every reader of it already holds
    # one and the figure belongs to that context, the way `extra_secrets` below
    # belongs to its Env.
    for side in (first, second):
        side.signalling = SignallingCount(side.context)
    first.start()
    second.start()
    # Each side's masker must know the other's prefix as a secret of its own,
    # or a diagnostic from one session could print the other's token.
    for side, other in ((first, second), (second, first)):
        if other.env.prefix:
            side.env.extra_secrets.append(other.env.prefix)
    return first, second


# What this run's ambient denominator counted, on top of the shared sentence.
AMBIENT_BASIS = AMBIENT_BASIS_DOCUMENTS + (
    " Both sessions are counted and the row counts come over session A's RPC: the two models are "
    "database-wide, so a row cannot be attributed to one of two sessions that were both open, and a "
    "denominator over one of them would be a fraction of the window the counts are taken over."
)


def ambient_figure(first, second) -> SessionAmbientDriver:
    """The ambient-row figure for this run's two sessions (#256, #264).

    The expected delta here is zero -- this driver opens `/odoo/project.task/<id>`
    and nothing else, and a backend route renders no tracked page -- and that is
    the reason to read it rather than to skip it: a zero that is read is a
    reading, and a zero that is assumed is not. A reason that reaches the record
    is masked with the session's own masker and `redact`, because the record is
    quoted in a pull request and a Playwright message carries both the host and
    the prefix.
    """
    return SessionAmbientDriver(first, second,
                                mask=lambda value: first.env.mask(redact(value, {})))


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


def type_marker(side, marker_text: str) -> None:
    """Type into the editable, which is what makes a collaboration step."""
    editable = side.root.locator(EDITABLE).first
    editable.click()
    side.page.keyboard.press("Control+End")
    side.page.keyboard.type(" " + marker_text)


def focus_editable(side) -> None:
    """Focus the editable, which is what makes this session a collaboration peer.

    **This is the step #243's run did not have, and the whole of why its transport
    delivered nothing** (#265). With no view setting `collaborative_trigger` --
    neither `project.view_task_form2`, the form `/odoo/project.task/<id>` serves,
    nor `project_todo`'s -- the collaboration plugin does not join the peer
    network on mount: it registers a one-shot `focus` listener on the editable and
    joins there (`collaboration_odoo_plugin.js:91-99`). Until that runs,
    `ptpJoined` is false, and the bus listener drops *every* notification it
    receives on that condition -- including the other session's `ptp_join`
    (`:156-158`). No log, no error, nothing in the DOM: a receiving session that
    was never focused simply waits out the whole 30 seconds.

    So the sending session joined by accident, because typing needs a focused
    editable, and the receiving session never did: it only loaded the form and
    read `innerHTML`. Both pairs were predicted to fail by the source before the
    host was involved at all.

    `focus()` and not `click()`: a click lands in the middle of the loaded
    document, and the onboarding to-do's middle is a checklist whose items toggle
    through `/web_editor/checklist` -- a write, on the command whose whole claim is
    that it makes none. Focusing fires the event the plugin listens for and
    touches no content.
    """
    side.root.locator(EDITABLE).first.focus()
    # The join is asynchronous from here (`joinPeerToPeer` waits on
    # `peerToPeerLoading`, which waits on the ICE-server RPC), so the reading that
    # says whether it finished is `collaboration_reading`, not this call.
    side.page.wait_for_timeout(500)


def collaboration_reading(side) -> dict[str, Any]:
    """What this session says about its own collaboration, or why it said nothing.

    Never raises: a reading that failed is a reason in the record, the way
    `AmbientReading.none` is. A diagnosis is worth a run and not the other way
    round -- and the run this is read during costs a deploy, a host and two
    30-second waits.
    """
    try:
        reading = side.root.evaluate(COLLABORATION_STATE_JS)
    except Exception as error:  # noqa: BLE001 -- the reason belongs in the record
        return {"unread": sanitize_diagnostic(str(error))}
    if isinstance(reading, dict):
        return reading
    return {"unread": sanitize_diagnostic("the page answered %r" % (reading,))}


def editable_html(side) -> str:
    return side.root.locator(EDITABLE).first.evaluate("node => node.innerHTML")


def wait_for_transport(side, marker_text: str, *, baseline: str | None,
                       seconds: int = 30) -> dict[str, Any]:
    """Wait for the *other* session's unsaved marker to arrive in this one.

    The waiting and the judgement are `await_marker`'s, which the Static tier
    drives; this is only the two browser verbs it needs. `baseline` must be the
    editable as it read before the sending session typed -- see `stage`.
    """
    return await_marker(
        lambda: editable_html(side),
        marker_text,
        baseline=baseline,
        sleep=side.page.wait_for_timeout,
        seconds=seconds,
    )


def save_form(side) -> None:
    button = side.root.locator(SAVE_BUTTON).first
    button.wait_for(timeout=TIMEOUT)
    button.click()
    side.root.locator(SAVE_BUTTON).first.wait_for(state="hidden", timeout=TIMEOUT)
    side.settle()


def discard_form(side) -> dict[str, Any]:
    """Throw this session's unsaved editor content away, and say what happened.

    **This is what makes `probe` write nothing**, and declining to save is not.
    Two `probe` runs left their marker in `project.task.description`, 32
    characters of it, while every docstring involved said the record was
    untouched (#263, found by #243's run). The mechanism, read from the pinned
    package (`ODOO_DEB_VERSION`, 18.0.20260930) rather than guessed:

    - `useSetupAction` registers a `beforeunload` listener for every form
      controller, which always passes the handler
      (`web/static/src/search/action_hook.js:76`,
      `web/static/src/views/form/form_controller.js:289`), and a real document
      navigation -- which `page.goto` is -- fires it;
    - the handler calls `record.urgentSave()`
      (`web/static/src/views/form/form_controller.js:508`), which raises
      `WILL_SAVE_URGENTLY`; the html field answers it by committing the editor's
      content into the record (`html_editor/static/src/fields/html_field.js:77`),
      which is the typed marker that had never been committed;
    - the urgent path then **writes with `navigator.sendBeacon`**
      (`web/static/src/model/relational_model/record.js:1033`), which no request
      interception sees and nothing can cancel.

    So "only a save writes the field", the reason the old `finally` gave for being
    safe, was never true of this form. Discard is the form's own undo -- it resets
    the record's changes and remounts the editor from the stored value -- and
    after it the field reports itself clean, so the same `beforeunload` harvests
    nothing and the save short-circuits with no RPC at all.

    Three details are load-bearing, not defensive:

    - **The resolve.** All three steps below go through one `side.root_now`, and
      never `side.root`: on `IngressSide` the latter resolves a frame that
      reports detached to the replacement the panel has since mounted, which
      answers every question here about a form it does not have -- including
      "was it dirty" (#292, and the comment on the resolve below).
    - **The wait.** `FormController.discard()` is asynchronous, and Playwright's
      `click()` returns long before it resolves. Navigating in that window leaves
      the field still dirty and the beacon still fires, so this blocks on the
      indicator going clean rather than clicking and moving on.
    - **The visibility check.** The button is in the DOM on a clean form too,
      behind `o_form_status_indicator_buttons.invisible`
      (`.../form_status_indicator/form_status_indicator.xml:6`), and `click()`
      waits for visibility rather than failing fast -- a clean form would spend
      the whole timeout here. On a readonly form the button is absent entirely,
      which is why presence is checked as well as visibility.

    `dirty` is reported because it is a reading in its own right: a `probe` whose
    forms were never dirty exercised nothing.
    """
    # `side.root_now` and not `side.root`, resolved once and worked through
    # rather than reached for at each of the three steps below (#292). `root` is
    # a property, and on `IngressSide` it is a *search*: it re-enters
    # `_find_frame(wait_s=60)` whenever the held Ingress frame reports detached.
    #
    # What that costs here is the reading, not the minute. The frame an add-on
    # panel leaves behind when it re-mounts its Ingress iframe is detached, so a
    # read of `root` resolves to the **replacement** frame -- a freshly loaded
    # document with none of this form in it. At the entry read below that counts
    # zero `UNSAVED` matches and returns `{"dirty": False, "discarded": False}`,
    # "the form was never dirty", for a form that went with its frame -- and that
    # detach is exactly when `beforeunload` fires the uninterceptable
    # `sendBeacon` save this function exists to head off. The same door is open at
    # the confirmation wait, where a replacement frame has no indicator to go
    # hidden and so reports a discard that never happened as `True`.
    #
    # `root_now` shuts both: it hands back the frame the side is already holding
    # without asking whether it is detached, so a frame that has gone raises at
    # the first locator call, and `discard_quietly` turns that into `dirty: True,
    # discarded: False` -- unknown reported as dirty, the direction the verdict
    # must fail in. On the Public side `root_now` is `root` itself. #280 took
    # these same three reaches out of the markup driver's
    # `_discard_unsaved_form`, and #288 shut this door there.
    root = side.root_now
    # The indicator is the earliest faithful signal there is -- the html field
    # raises `FIELD_IS_DIRTY` on the first keystroke, before `record.dirty` is
    # set (`html_field.js:225`, `form_status_indicator.js:16`).
    dirty = root.locator(UNSAVED).count() > 0
    # `>> visible=true` rather than `.first`, which is this repository's idiom for
    # the same button (`e2e_parity_shared_layers_live.py:1805`). `.first` picks the
    # first match in the DOM whatever its state, so one hidden earlier indicator --
    # a dialog's, a sub-form's -- would pass the `button.count()` check below on an
    # element no click can reach and silently skip the real button, which is the
    # failure this function exists to prevent.
    button = root.locator(DISCARD_BUTTON + " >> visible=true").first
    if not dirty or not button.count():
        return {"dirty": dirty, "discarded": False}
    button.click()
    # The indicator carries `invisible` again once the record is clean, so this
    # selector stops matching; a locator with no element counts as hidden.
    root.locator(UNSAVED).first.wait_for(state="hidden", timeout=TIMEOUT)
    side.settle()
    return {"dirty": True, "discarded": True}


def discard_quietly(side) -> dict[str, Any]:
    """`discard_form`, but a failure here never costs the run its report.

    Discarding is cleanup, and the readings it protects are expensive: a Live run
    needed a deploy and a host, and the transport wait alone takes 30 seconds. A
    `wait_for` that times out because the form will not go clean -- an invalid
    record keeps the indicator up, so it never does -- must not throw away the
    measurement that was already taken. So the outcome is recorded and returned,
    and `probe` treats a form it could not discard as a failure *in the report*
    rather than as an exception that prevents one.
    """
    try:
        return discard_form(side)
    except Exception as error:  # noqa: BLE001 -- the reading matters more
        return {"dirty": True, "discarded": False, "error": type(error).__name__}


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


def stage(first, second, task_id: int | None, marker_text: str):
    """Both commands' common half, up to the point where only `run` saves.

    Session A opens the to-do and types `marker_text` **without saving**; session
    B joins the same record, **focuses its editable** so that it joins the peer
    network at all, and the run waits for that marker to reach B. It then reads
    both sessions' own account of the collaboration, which is what attributes the
    outcome either way. Everything after this differs: `probe` discards both forms
    and stops, `run` types B's own marker, saves and reads the field back.

    The two sessions are opened by the caller (`open_pair`) and not here, for two
    reasons that arrived together. The ambient figure's window opens at its first
    reading and that reading goes over a session's own RPC, so it cannot be taken
    until both sessions exist -- and everything this function navigates has to be
    inside the window. And a failure in here used to leave both contexts to
    `browser.close()` in `main`; now the caller's `finally` closes them whether
    staging reached its end or not.

    **A's editable is read before A types**, and that reading is what the wait is
    judged against. It is the loaded document, so a marker found in it was stored
    by something and cannot have been delivered -- the distinction #263 asked for.
    It is read from A rather than from B because B has not joined yet at that
    point, and both sessions load the same stored value.
    """
    labels = labels_for(first, second)
    task_id = task_id or find_todo(first)
    open_todo(first, task_id)
    baseline = editable_html(first)
    type_marker(first, marker_text)
    open_todo(second, task_id)
    # The receiving session joins the peer network here and nowhere else, and
    # until #265 nothing did it at all -- `focus_editable` has the mechanism and
    # what its absence cost #243's run.
    focus_editable(second)
    transport = wait_for_transport(second, marker_text, baseline=baseline)
    # Read before anything discards or saves: a discard remounts the editor and
    # takes the plugin's state with it, and this reading is the only thing that
    # attributes the transport's outcome (#265).
    diagnosis = transport_diagnosis(
        transport=transport,
        sessions={"A": collaboration_reading(first), "B": collaboration_reading(second)},
        signalling={"A": _signalling_posts(first), "B": _signalling_posts(second)},
    )
    return labels, task_id, transport, diagnosis


def _signalling_posts(side) -> int:
    """This session's signalling count, or zero if the pair was opened without one."""
    return getattr(getattr(side, "signalling", None), "posts", 0)


def do_probe(env: Env, browser, pair: str, task_id: int | None, run_id: str) -> int:
    """Open both sessions, report what they were served, and leave the record alone.

    It does not merely decline to save -- it clicks the form's own **Discard** on
    both sessions and then reads `description` back to say so. `wrote_nothing` in
    the output is that reading, and a false one exits non-zero: the whole of #263
    is that this step's claim was never checked.

    It keeps no file, so its ambient figure is printed and not written (#264).
    The figure is still read: this command is the one a reader runs first and by
    hand, and "it writes nothing" is a claim about the field, never about the rows
    a page view leaves.
    """
    probe_marker = marker(run_id, "A", pair)
    first, second = open_pair(env, browser, pair)
    try:
        with ambient_accounting(ambient_figure(first, second),
                                RunInfo(run_id=run_id, target=env.target, database=env.db),
                                pair, None, command="probe", navigation_basis=AMBIENT_BASIS):
            labels, task_id, transport, diagnosis = stage(first, second, task_id, probe_marker)
            # Read B's editable before discarding: after a discard it holds the stored
            # value, and what a reader needs from it is what the transport delivered.
            second_editable = redact(editable_html(second), labels)[:2000]
            # Both sessions, each independently: A's discard failing must not leave B
            # dirty *and* unreported. `discard_quietly` says why a failure here is a
            # line in the report rather than an exception instead of one.
            discarded = {label: discard_quietly(side)
                         for label, side in (("A", first), ("B", second))}
            stored = read_description(first, task_id)
            verdict = probe_verdict(transport=transport, stored=stored, run_id=run_id,
                                    discarded=discarded)
            print(json.dumps({
                "pair": pair,
                "run_id": run_id,
                "task_id": task_id,
                "prefixes": {label: redact(side.env.prefix, labels)
                             for label, side in (("A", first), ("B", second))},
                "prefixes_equal": _equal_prefixes(
                    {"A": first.env.prefix, "B": second.env.prefix}
                ),
                "transport": transport,
                # Why it did or did not deliver, read off both sessions. `probe`
                # is the step a failure is attributed from, and until #265 it
                # reported the outcome with nothing beside it.
                "collaboration": redact(diagnosis, labels),
                "second_session_editable": second_editable,
                "saved": False,
                "discarded": discarded,
                "wrote_nothing": verdict["wrote_nothing"],
                "forms_left_dirty": verdict["forms_left_dirty"],
                # The labels of the prefixes in the field, and deliberately **no**
                # verdict: `classify` is relative to the session that saved, and no
                # session saved here. Asking it anyway read every prefix as
                # `FOREIGN-PREFIX-STORED` on the `ingress-ingress` pair -- the pair
                # where both sessions share one prefix, so `labels` has one entry and
                # any `saver` passed to it mismatches. That is the verdict the parity
                # plan escalates #234 to `blocker` on, for a value `probe` never wrote.
                "stored_prefixes": stored_prefix_labels(stored, labels),
                "notes": verdict["detail"],
            }, indent=2, ensure_ascii=False))
            exit_code = verdict["exit_code"]
        # Outside the accounting, the way the adapter returns its own exit code. A
        # `return` from inside it leaves the body exception-free, so an accounting
        # failure is raised as "the run's only failure" (#256) -- and `main`'s
        # catch-all would turn a measured `wrote_nothing: false` into exit 2,
        # collapsing the signal #263 exists to carry into "harness error".
        return exit_code
    finally:
        for side in (first, second):
            side.close()


NO_HEAL_ON_THIS_PAIR = (
    "the ingress-ingress pair has no foreign write to heal: both sessions are served the "
    "add-on's one prefix and both save through the same strip, so the peer's save is the whole "
    "measurement (parity plan section 12)"
)


def heal_under_ingress(first, task_id: int, labels: Mapping[str, str],
                       marker_text: str) -> dict[str, Any]:
    """Load what the Public peer stored under Ingress, save once, and read again.

    The second half of the `ingress-public` measurement (`healing_read` says why
    there has to be one). Four steps, and the order is the measurement:

    - **A's own leftover goes first.** A is still dirty with the marker it typed
      before B joined. Navigating a dirty To-do form persists the editor's content
      through a `sendBeacon` nothing can intercept (#263, `discard_form`), so
      reloading A without discarding would write A's stale document over B's save
      and heal nothing -- it would *overwrite* the value under measurement.
    - **A reloads the record.** A discard resets the form to the values the client
      already held, which are the ones A loaded before B saved. Only a fresh
      `web_read` hands A the value B stored, and the whole question is whether an
      Ingress save strips a prefix that arrived *in the loaded value*.
    - **The loaded editable is read**, before anything is typed into it. That
      reading is what says the healing save had a subject.
    - **A types and saves once.** The strip sits on the field's one write
      (`HtmlField.updateValue`, #210/#238), and a clean form makes no write at
      all, so there has to be a change for there to be a save. The marker carries
      the run id like every other marker here.
    """
    discard_quietly(first)
    open_todo(first, task_id)
    loaded = editable_html(first)
    type_marker(first, marker_text)
    save_form(first)
    return healing_read(loaded=loaded, stored=read_description(first, task_id),
                        labels=labels, saver="A")


def do_run(env: Env, browser, pair: str, task_id: int | None, run_id: str, out_path: str) -> int:
    """Stage both sessions, let B save, and write the record and the run's figure.

    On the `ingress-public` pair there is a **second** reading after that: the
    Public peer's save is the one the Ingress fix cannot prevent, so the record
    also says what the next Ingress save did with it (`heal_under_ingress`). The
    verdict the escalation rule reads is `final_verdict`, which is that second one
    wherever it was taken.

    The ambient figure is appended beside `out_path` (`peer.jsonl` ->
    `peer.ambient.json`), appended because the records are: this command is run
    once per pair and an evidence directory keeps every line.
    """
    first, second = open_pair(env, browser, pair)
    try:
        with ambient_accounting(ambient_figure(first, second),
                                RunInfo(run_id=run_id, target=env.target, database=env.db),
                                pair, out_path, command="run", append=True,
                                navigation_basis=AMBIENT_BASIS):
            labels, task_id, transport, diagnosis = stage(first, second, task_id,
                                                          marker(run_id, "A", pair))
            type_marker(second, marker(run_id, "B", pair))
            save_form(second)
            stored = read_description(second, task_id)
            if pair != HEALING_PAIR:
                # A's form is still dirty with A's own marker, and leaving it that way
                # writes it on the way out (#263). What this command is documented to
                # store is what B saved, so A's leftover is discarded. B's form is
                # clean; the save is what made it clean.
                #
                # This sits before the record is written, where the old ordering put it
                # after, and `discard_quietly` is what makes that safe: it returns the
                # outcome for a discard that raised instead of raising. Cleanup must
                # never be what loses a measurement that cost a deploy, a host and a
                # 30-second wait, and `discard_form` does raise -- its `wait_for` times
                # out whenever the form will not go clean.
                discard_quietly(first)
                healing = healing_not_performed(NO_HEAL_ON_THIS_PAIR)
            else:
                # The healing half is a measurement and not cleanup, but it is taken
                # **after** the one above, so it is guarded the way cleanup is: a
                # second reading that could not be taken is a reason in the record,
                # never a lost first reading. This run has already cost a deploy, a
                # host and a 30-second wait by the time it gets here, and every step
                # in it can time out (`discard_form`'s wait on a form that will not go
                # clean, a save button that never hides).
                try:
                    healing = heal_under_ingress(first, task_id, labels,
                                                 marker(run_id, "A-heal", pair))
                except Exception as error:  # noqa: BLE001 -- the first reading matters more
                    healing = healing_not_performed(
                        "the Ingress healing save could not be taken: %s"
                        % sanitize_diagnostic(str(error)))
            record = evidence_record(
                run_id=run_id,
                database=env.db,
                target=env.target,
                pair=pair,
                task_id=task_id,
                prefixes={"A": first.env.prefix, "B": second.env.prefix},
                transport=transport,
                collaboration=diagnosis,
                stored=stored,
                labels=labels,
                saver="B",
                healing=healing,
                notes=transport_note(transport),
            )
            with open(out_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            print(json.dumps(record, indent=2, ensure_ascii=False))
            # Two questions, and the exit code answers both: did this run confirm a
            # stored foreign prefix anywhere (`escalating_readings`, which is #234's
            # rule as #234 wrote it), and does the record end clean. A `run` on the
            # `ingress-public` pair of this host answers "yes" to the first, so it
            # exits non-zero even though the heal worked -- that is the signal, not a
            # fault in it: the command just measured a Supervisor token reaching a
            # record. `report` says the same thing with the heal beside it.
            clean = final_verdict(record) == CLEAN and not escalating_readings(record)
        # Outside the accounting, for `do_probe`'s reason: a verdict this run
        # measured must not be turned into a harness error by the figure's own
        # failure.
        return 0 if clean else 1
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
        # Both commands take a run id, because both type a marker and a marker
        # has to be unique to the run (#263). Only `run` requires one: `probe` is
        # the step a reader runs first and by hand, so it mints its own.
        sub.add_argument("--run-id", required=(name == "run"),
                         help="the run both markers carry, e.g. WOOW-PEER-<UTC timestamp>"
                              + ("" if name == "run" else
                                 "; default: a minted %s-<UTC timestamp>" % PROBE_RUN_PREFIX))
        if name == "run":
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
                run_id = args.run_id or mint_run_id(datetime.now(timezone.utc))
                return do_probe(env, browser, args.pair, args.task_id, run_id)
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
