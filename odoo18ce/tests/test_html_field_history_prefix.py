#!/usr/bin/env python3
"""Which write puts an Ingress prefix in an html field's history (`G-10`, #296).

#282's mutating Live run opened the Version History dialog of
`project.task(5).description` on both surfaces. The field itself was `CLEAN`
-- 0 prefixes, a state-bounding reading (#289) -- and on the **Public** origin
the dialog nevertheless drew both onboarding pictures as
`/api/hassio_ingress/<token>/project_todo/static/img/…`, `loaded: false`,
verdict `ESCAPED`. The Public origin has no shim and no rewrite (ADR 0003), so
the prefix can only have come out of the stored history. Registered as `G-10`
in section 11 of the parity plan.

The first reading of it got the author backwards, and this file is where the
corrected one is executed rather than argued. `html.field.history.mixin.write`
stores `generate_patch(new_content, old_content)`, and `_patch_generator`
embeds `old_content_lines` -- the patch that `apply_patch` walks the *current*
value **backwards** with. A revision therefore carries the value as it was
*before* its own write, which inverts everything that follows from it:

- the Public peer's save, which puts the prefix in the field (`G-08`), records
  a **clean** revision, because the value it replaced was clean;
- the next Ingress save, the one #234's strip makes clean and which *heals*
  the field, is the write that deposits the **prefixed** revision.

So the residue is written by the heal, it recurs once per `G-08` store-and-heal
cycle rather than being one historical accident, and it is bounded rather than
permanent: `_html_field_history_size_limit = 300` evicts it once 300 further
revisions exist on that field. None of that moves `G-08`'s severity -- a
prefixed live field indefinitely is worse than a clean field plus one ageing
history entry -- and #234's standing sentence is amended, not re-graded.

What is pinned here:

- **The direction, driven.** `generate_patch` and `apply_patch` are pure
  (`diff_utils` imports only `re` and `difflib`), so the captured module is
  loaded by path and run: the store patch carries no prefix, the heal patch
  carries both pictures, and `apply_patch` reconstructs a prefixed document
  from the clean value the field holds today. That last line is what the
  dialog does, and why `ESCAPED` is a faithful reading.
- **The measured document, not an invented one.** The input is
  `project.task(5).description` byte-for-byte as #282's `markup.jsonl`
  recorded it, and a test holds the fixture to that record.
- **The host's revision shape, replayed offline.** Two store-and-heal pairs
  leave the prefix in the *second* revision of each pair -- revisions 13 and
  16 of 17 on the host, each heal some 30 s after its store.
- **The source shape the direction rests on**, with `ast` rather than text, so
  a comment cannot satisfy it: the pre-write capture happens before
  `super().write(vals)`, `generate_patch` is called new-then-old,
  `_patch_generator` appends only `old_content_lines`, and the reconstruction
  starts from the current field value.
- **That the history is not writable through an ordinary write.** `create`
  and `write` both drop `html_field_history` out of the incoming vals, so any
  correction of the two existing revisions would need `super()` or raw SQL.
  #296 decided against one: editing the store a reading comes from is the move
  ADR 0014 refuses a stored-prefix valve under, with fewer witnesses. The two
  revisions on the host are left untouched.

Nothing here is a fix, because there is no admissible Ingress-side fix: the
prefixed value is in the field the moment the Public peer saves it, and ADR
0003 keeps that surface unchanged. What the add-on's code decides is only
whether the field stays prefixed too.
"""
import ast
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from test_ingress_clipboard_fallback import INGRESS_PREFIX
from test_ingress_todo_description import TODO_PICTURES

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures/server"
DIFF_UTILS = FIXTURES / "web_editor_diff_utils.py"
MIXIN = FIXTURES / "web_editor_html_field_history_mixin.py"
DESCRIPTION = FIXTURES / "project_task_5_description.html"
EVIDENCE = ROOT / "docs/testing/evidence/2026-10-04-issue-282/markup.jsonl"

# The field value as the run read it out of the database, and the same value
# with the two pictures carrying the prefix a Public-origin peer was handed.
CLEAN = DESCRIPTION.read_text(encoding="utf-8")
PREFIXED = CLEAN.replace('src="/project_todo/', 'src="%s/project_todo/' % INGRESS_PREFIX)


def load_diff_utils():
    """The pinned `web_editor/models/diff_utils.py`, executed from its capture."""
    spec = importlib.util.spec_from_file_location("woow_pinned_diff_utils", DIFF_UTILS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diff_utils = load_diff_utils()
generate_patch = diff_utils.generate_patch
apply_patch = diff_utils.apply_patch


def as_stored(content: str) -> str:
    """What the patch helpers compare and reconstruct.

    Both ends strip newlines and `data-last-history-steps`, so a round trip
    is equal to this normalisation of the value rather than to its bytes.
    """
    return diff_utils._remove_html_attribute(
        content.replace("\n", ""), diff_utils.HTML_ATTRIBUTES_TO_REMOVE
    )


def mixin_tree() -> ast.Module:
    return ast.parse(MIXIN.read_text(encoding="utf-8"))


def function_of(tree: ast.Module, name: str) -> ast.FunctionDef:
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, "%s is defined %d times" % (name, len(found))
    return found[0]


def size_limit() -> int:
    """`_html_field_history_size_limit`, read out of the captured class."""
    for node in ast.walk(mixin_tree()):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_html_field_history_size_limit"
            for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("the captured mixin has no _html_field_history_size_limit")


def write_revision(history: list[dict], old_content: str, new_content: str,
                   limit: int) -> list[dict]:
    """`html.field.history.mixin.write`'s revision loop, lines 80-107.

    Newest first, the patch generated new-then-old, the list cut to `limit`
    from the front. Every one of those choices is held to the captured source
    by `test_the_replayed_revision_loop_is_the_captured_one` below, because
    the two replay tests read their answer out of this replica.
    """
    if new_content == old_content:
        return history
    revision_id = (history[0]["revision_id"] + 1) if history else 1
    history.insert(0, {
        "patch": generate_patch(new_content, old_content),
        "revision_id": revision_id,
    })
    return history[:limit]


def content_at_revision(history: list[dict], current: str, revision_id: int) -> str:
    """`html_field_history_get_content_at_revision`, lines 115-135."""
    content = current or ""
    for revision in [r for r in history if r["revision_id"] >= revision_id]:
        content = apply_patch(content, revision["patch"])
    return content


def replay(values) -> tuple[list[dict], str]:
    """Write `values` over the measured field in order, newest revision first."""
    limit = size_limit()
    history: list[dict] = []
    current = CLEAN
    for value in values:
        history = write_revision(history, current, value, limit)
        current = value
    return history, current


# The two store-and-heal pairs of #265's window: a Public-origin peer stores
# the prefix, the next Ingress save strips it, twice.
TWO_PAIRS = (PREFIXED, CLEAN, PREFIXED, CLEAN)


# --- the captured document ---------------------------------------------------

def test_the_captured_description_is_the_one_the_run_measured() -> None:
    """The fixture is #282's record, not a document written to suit the test."""
    measured = [
        json.loads(line)["stored_values"]["project.task.description"]
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("check") == "readonly-plain"
    ]
    assert measured, "the run's readonly-plain records are gone from the evidence"
    assert all(value == CLEAN for value in measured), \
        "the fixture has drifted from the stored_values the run recorded"


def test_the_field_itself_carries_no_prefix() -> None:
    """`G-10` is a reading about the history; the field was `CLEAN`."""
    assert "hassio_ingress" not in CLEAN
    assert all('src="%s"' % picture in CLEAN for picture in TODO_PICTURES)
    assert PREFIXED.count(INGRESS_PREFIX) == len(TODO_PICTURES) == 2


# --- the direction, driven ---------------------------------------------------

def test_the_public_peers_store_records_a_clean_revision() -> None:
    """The write that puts the prefix in the field records the value it replaced."""
    store = generate_patch(PREFIXED, CLEAN)
    assert "hassio_ingress" not in store
    assert store.count(TODO_PICTURES[0]) == 1 and store.count(TODO_PICTURES[1]) == 1


def test_the_ingress_heal_records_the_prefixed_revision() -> None:
    """And the write that *removes* the prefix is the one that stores it."""
    heal = generate_patch(CLEAN, PREFIXED)
    assert heal.count(INGRESS_PREFIX) == 2, heal
    assert all(INGRESS_PREFIX + picture in heal for picture in TODO_PICTURES)


def test_the_dialog_reconstructs_a_prefixed_document_from_the_clean_field() -> None:
    """Why `readonly-plain` reads `ESCAPED` on a record whose field is clean."""
    heal = generate_patch(CLEAN, PREFIXED)
    restored = apply_patch(CLEAN, heal)
    assert restored == as_stored(PREFIXED)
    assert restored.count(INGRESS_PREFIX) == 2


def test_the_store_patch_walks_a_prefixed_field_back_to_a_clean_document() -> None:
    """The mirror image, so the direction is pinned from both ends."""
    store = generate_patch(PREFIXED, CLEAN)
    assert apply_patch(PREFIXED, store) == as_stored(CLEAN)


# --- the host's revision shape -----------------------------------------------

def test_each_store_and_heal_pair_leaves_one_prefixed_revision() -> None:
    """Two pairs, and in each it is the *second* write that carries the prefix.

    The host read 17 revisions on `project.task(5).description` with exactly
    two carrying `hassio_ingress` -- revision 13 (06:29:43) and revision 16
    (06:36:32), each some 30 s after a clean one. This replays that window.
    """
    history, current = replay(TWO_PAIRS)

    assert [r["revision_id"] for r in history] == [4, 3, 2, 1]
    carriers = sorted(r["revision_id"] for r in history if "hassio_ingress" in r["patch"])
    assert carriers == [2, 4], "the heal of each pair is the revision that carries it"
    assert current == CLEAN, "the field is left clean, which is what #234's strip buys"


def test_opening_a_heal_revision_shows_the_pictures_the_run_could_not_load() -> None:
    history, current = replay(TWO_PAIRS)

    seen = {
        revision_id: INGRESS_PREFIX in content_at_revision(history, current, revision_id)
        for revision_id in (1, 2, 3, 4)
    }
    assert seen == {1: False, 2: True, 3: False, 4: True}


def test_the_prefixed_revision_is_evicted_once_the_limit_is_reached() -> None:
    """Append-only for removal, but bounded: 300 further revisions age it out."""
    limit = size_limit()
    assert limit == 300
    history, current = replay(TWO_PAIRS[:2])
    assert any("hassio_ingress" in r["patch"] for r in history)

    # Any further writes of the field; the text they carry is irrelevant.
    for index in range(limit):
        value = CLEAN.replace("</ul>\n", "<p>edit %d</p></ul>\n" % index)
        history = write_revision(history, current, value, limit)
        current = value

    assert len(history) == limit
    assert not any("hassio_ingress" in r["patch"] for r in history)


# --- the source shape the direction rests on ---------------------------------

def test_the_pre_write_value_is_captured_before_super_write() -> None:
    """`old_content` is the value the write replaced, which is the whole claim."""
    write = function_of(mixin_tree(), "write")
    captures = [n.lineno for n in ast.walk(write)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Name) and t.value.id == "rec_db_contents"
                        for t in n.targets)]
    supers = [n.lineno for n in ast.walk(write)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "write"
              and isinstance(n.func.value, ast.Call)
              and isinstance(n.func.value.func, ast.Name) and n.func.value.func.id == "super"]
    assert captures and supers
    assert min(captures) < min(supers), \
        "the capture must precede super().write, or the diff is against the new value"


def test_the_replayed_revision_loop_is_the_captured_one() -> None:
    """`write_revision` is a replica, and a replica is only worth its pins.

    The two replay tests read the host's revision shape out of it, so the
    three choices that shape rests on are taken from the captured source
    rather than from this file: the new revision goes in at the **front**,
    its id is the front one's plus 1, and the cut keeps the front `limit`.
    A re-capture that does not re-derive the replica turns these red.
    """
    statements = [ast.unparse(n) for n in ast.walk(function_of(mixin_tree(), "write"))
                  if isinstance(n, (ast.Assign, ast.Expr))]
    assert any(re.fullmatch(r"history_revs\[field\]\.insert\(0, \{.*\}\)", line, re.S)
               for line in statements), "the revision is inserted at the front"
    assert "revision_id = history_revs[field][0]['revision_id'] + 1 if history_revs[field] else 1" \
        in statements, "the id counts up from the front one"
    assert "history_revs[field] = history_revs[field][:limit]" in statements, \
        "the cut keeps the newest `limit`, so the oldest is the one evicted"


def test_the_patch_is_generated_new_content_then_old_content() -> None:
    calls = [n for n in ast.walk(function_of(mixin_tree(), "write"))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "generate_patch"]
    assert len(calls) == 1
    assert [a.id for a in calls[0].args] == ["new_content", "old_content"]


def test_the_patch_generator_embeds_only_the_old_content_lines() -> None:
    """The one line that decides which value a revision carries."""
    generator = function_of(ast.parse(DIFF_UTILS.read_text(encoding="utf-8")),
                            "_patch_generator")
    appends = [n for n in ast.walk(generator)
               if isinstance(n, ast.For)
               and any(isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                       and isinstance(stmt.value.func, ast.Attribute)
                       and stmt.value.func.attr == "append"
                       and isinstance(stmt.value.func.value, ast.Name)
                       and stmt.value.func.value.id == "patch_content_line"
                       for stmt in n.body)]
    assert len(appends) == 1
    source = appends[0].iter
    assert isinstance(source, ast.Subscript) and isinstance(source.value, ast.Name)
    assert source.value.id == "old_content_lines"


def test_the_reconstruction_starts_from_the_current_field_value() -> None:
    getter = function_of(mixin_tree(), "html_field_history_get_content_at_revision")
    starts = [n for n in ast.walk(getter)
              if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "content" for t in n.targets)
              and isinstance(n.value, ast.BoolOp)]
    assert starts, "the walk must start from the field's own value"
    first = starts[0].value.values[0]
    assert isinstance(first, ast.Subscript) and isinstance(first.value, ast.Name)
    assert first.value.id == "self" and first.slice.id == "field_name"
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "apply_patch" for n in ast.walk(getter))


def test_the_history_cannot_be_set_through_an_ordinary_write() -> None:
    """So a correction of the two existing revisions needs `super()` or SQL.

    #296 decided against one, and the two revisions on `project.task(5)` are
    left as #282 recorded them.
    """
    tree = mixin_tree()
    create = ast.unparse(function_of(tree, "create"))
    write = ast.unparse(function_of(tree, "write"))
    assert "vals.pop('html_field_history', None)" in create
    assert "if 'html_field_history' in vals" in write and "del vals['html_field_history']" in write


# --- the capture itself ------------------------------------------------------

@pytest.mark.parametrize("fixture", [DIFF_UTILS, MIXIN])
def test_the_captured_sources_are_the_bytes_the_readme_recorded(fixture: Path) -> None:
    """A capture nobody can re-check is a copy, not evidence.

    Every claim in this file is driven from these two files, so an edit to
    one -- a re-capture that reformats, or a line changed to make an
    assertion come out right -- would quietly move the thing being measured.
    The digests are the README's, taken from the package itself.
    """
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    row = [line for line in readme.splitlines() if "`%s`" % fixture.name in line]
    assert len(row) == 1, "the README has no single table row for %s" % fixture.name
    recorded = re.search(r"`([0-9a-f]{64})`", row[0])
    assert recorded, "the row records no sha256"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == recorded.group(1), \
        "%s is not the bytes the README recorded; re-capture it from the pinned deb" % fixture.name
    assert "Part of Odoo" in fixture.read_text(encoding="utf-8")


def test_the_capture_names_the_deb_the_image_still_pins() -> None:
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    version = (ROOT / "odoo18ce/Dockerfile").read_text(encoding="utf-8")
    pinned = re.search(r'ARG ODOO_DEB_VERSION="([^"]+)"', version)
    assert pinned, "the Dockerfile no longer pins a deb version"
    assert pinned.group(1) in readme, \
        "the deb pin moved to %s; re-capture these fixtures and update the README" % pinned.group(1)
