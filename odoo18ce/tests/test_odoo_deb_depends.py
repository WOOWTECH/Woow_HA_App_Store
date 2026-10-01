#!/usr/bin/env python3
"""The bump bot keeps `odoo-deb-depends.txt` current, as a merge (issue #156).

The weekly `odoo-bump` already downloads the new Odoo nightly `.deb` to hash
it. It now reads the same package's `Depends` and folds it into the committed
`odoo18ce/odoo-deb-depends.txt`.

Why that is a merge and never a regenerate: the committed file carries state
the `.deb` cannot supply. Which member of an alternatives group apt resolves
on the pinned base image is a fact about bookworm (`python3-lxml-html-clean |
python3-lxml` resolves to the *second* name); `satisfied-by` records that
layer (a) installs a metapackage instead; and `deferred`/`dropped` are what
keep a routine bump to layer (b) and the small layers under it -- about
380 MiB -- instead of re-sending layer (a) as well (ADR 0013, whose
`.deb`-download figures are not the compressed layers a host downloads).
A naive regenerate loses all four and turns the guard test red.

So the rules under test are:

* **Gained** -- the `.deb` names a package the file does not: append it with a
  `deferred` note naming the bump. apt installs it into layer (b), layer (a)
  is not touched, and `test_dockerfile_layers.py` stays **green**, because a
  red static tier would cost the bump pull request its image build (ADR 0013,
  ADR 0002).
* **Lost** -- the `.deb` stops naming a package the file holds: the entry goes
  only when layer (a) does not install it. When (a) does, it stays with a
  `dropped` note, because removing it would rebuild the big layer.
* **Normalized** -- `python3:any` is recorded as `python3` plus a `qualifier`
  note, a version constraint as a `version` note, and an alternatives group as
  the member the file already records plus an `alternatives` note.
* **Undecidable** -- a group the file cannot resolve (no recorded member, or
  two) is the one case the bot must not decide: `apt-cache policy` inside the
  base image answers it, so the entry is left alone and the pull request body
  says so.
"""
import difflib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import test_dockerfile_layers as guard

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SCRIPT = REPO / ".github/scripts/odoo_deb_depends.py"
FIELDS = Path(__file__).resolve().parent / "fixtures/depends"

DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMMITTED = (ROOT / "odoo-deb-depends.txt").read_text(encoding="utf-8")

# The `.deb` the image is built from -- the one criterion 3's no-op is about.
DEB_VERSION = re.search(r'^ARG ODOO_DEB_VERSION="([^"]+)"$',
                        DOCKERFILE, re.M).group(1)

# The bump the tests pretend to be: a version no nightly will ever carry.
VERSION = "18.0.20991231"
DATE = "2099-12-31"

NEW = "python3-brand-new"


def load():
    spec = importlib.util.spec_from_file_location("odoo_deb_depends", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bot = load()


def newest_field() -> Path:
    captured = sorted(FIELDS.glob("odoo_*_all.deb.Depends"))
    assert captured, f"{FIELDS} holds the `Depends` of at least one nightly"
    return captured[-1]


def pinned_field() -> str:
    return newest_field().read_text(encoding="utf-8")


def pinned_version() -> str:
    return re.fullmatch(r"odoo_(.+)_all\.deb\.Depends", newest_field().name).group(1)


def field(*, add: tuple = (), drop: tuple = (), replace: tuple = ()) -> str:
    """The pinned package's `Depends`, with entries added, dropped or swapped.

    The fixture is the real field of a real nightly, so every case below is a
    mutation of something the bot will actually be handed.
    """
    entries = bot.split_field(pinned_field())
    for old, new in replace:
        assert old in entries, old
        entries[entries.index(old)] = new
    for one in drop:
        assert one in entries, one
        entries.remove(one)
    return ", ".join(entries + list(add)) + "\n"


def merge(depends: str, *, listing: str = COMMITTED, version: str = VERSION,
          dockerfile: str = DOCKERFILE):
    return bot.merge(listing, depends, dockerfile=dockerfile,
                     deb_version=version, date=DATE)


def entries(text: str) -> dict:
    """The merged list read back through the guard test's own parser."""
    return dict(guard.read_depends(text))


def names(text: str) -> list:
    return [name for name, _ in guard.read_depends(text)]


def layer_a() -> list:
    """The packages layer (a) installs, read by the guard test."""
    instructions = guard.instructions(DOCKERFILE)
    run = next(one for one in instructions
               if one.startswith("RUN ")
               and "postgresql-16" in guard.apt_packages(one))
    return guard.apt_packages(run)


# --------------------------------------------------------------------------
# The no-op: the pinned package against the committed list.
# --------------------------------------------------------------------------

def test_the_pinned_package_and_the_committed_list_already_agree() -> None:
    """Extract, normalize and merge, run on the pair in the tree: a no-op.

    The raw field is *not* equal to the file -- it spells `python3:any`, it
    writes the two alternatives groups as groups, and it is in the `.deb`'s
    own order. Equality holds only after the normalizations, which is what
    makes this the real test of them.

    "The pinned `.deb`" is `ARG ODOO_DEB_VERSION`, not the list's own
    `# source:` line: the bot leaves `# source:` behind on a bump that moved
    no dependency, so keying off it would let this assert an older pair for
    ever. When the captured field is behind the pin this skips instead of
    failing -- `fixtures/depends/README.md` says why a red static tier is not
    an option on a bump, and how to recapture.
    """
    if DEB_VERSION != pinned_version():
        pytest.skip(
            f"the Dockerfile pins odoo_{DEB_VERSION}_all.deb and the newest "
            f"captured field is odoo_{pinned_version()}_all.deb; recapture "
            f"it as {FIELDS}/odoo_{DEB_VERSION}_all.deb.Depends")
    done = merge(pinned_field(), version=DEB_VERSION)
    assert done.text == COMMITTED, "".join(difflib.unified_diff(
        COMMITTED.splitlines(True), done.text.splitlines(True),
        fromfile="committed", tofile="merged"))
    assert not done.changed
    assert guard.guard_failures(DOCKERFILE, done.text) == []


def test_the_raw_field_on_its_own_is_not_the_committed_list() -> None:
    # The claim the merge rests on: a regenerate-from-`.deb` is a different
    # file, so the no-op above is about the normalizations and not about the
    # `.deb` happening to be written the way the file is.
    raw = sorted(bot.split_field(pinned_field()))
    assert raw != names(COMMITTED)
    assert "python3:any" in raw
    assert "python3-lxml-html-clean | python3-lxml" in raw


# --------------------------------------------------------------------------
# A gained dependency.
# --------------------------------------------------------------------------

def test_a_gained_dependency_is_deferred_and_the_guard_stays_green() -> None:
    done = merge(field(add=(NEW,)))
    assert done.added == [NEW]
    notes = entries(done.text)[NEW]
    assert set(notes) == {"deferred"}
    assert VERSION in notes["deferred"] and DATE in notes["deferred"]
    # The whole point: layer (a) is untouched, so the static tier is green
    # and the bump pull request still reaches its image build.
    assert guard.guard_failures(DOCKERFILE, done.text) == []
    assert NEW not in layer_a()


def test_a_gained_dependency_leaves_every_other_entry_untouched() -> None:
    done = merge(field(add=(NEW,)))
    before, after = entries(COMMITTED), entries(done.text)
    assert set(after) - set(before) == {NEW}
    for name, notes in before.items():
        assert after[name] == notes, name


def test_a_gained_dependency_sorts_into_place_with_lc_all_c() -> None:
    done = merge(field(add=("Zed-uppercase", "adduser-extra", NEW)))
    got = names(done.text)
    assert got == sorted(got, key=lambda one: one.encode()), got
    # LC_ALL=C, so an uppercase name sorts before every lowercase one.
    assert got[0] == "Zed-uppercase"


# --------------------------------------------------------------------------
# A lost dependency.
# --------------------------------------------------------------------------

def test_a_lost_dependency_layer_a_installs_keeps_its_line_and_says_why() -> None:
    done = merge(field(drop=("python3-cbor2",)))
    notes = entries(done.text)["python3-cbor2"]
    assert done.marked_dropped == ["python3-cbor2"] and done.deleted == []
    assert VERSION in notes["dropped"] and DATE in notes["dropped"]
    # Taking it out of (a) is what the note buys time for: that edit would
    # re-send layer (a) on a routine weekly bump, on top of the bump's own
    # ~380 MiB (ADR 0013).
    assert "python3-cbor2" in layer_a()
    assert guard.guard_failures(DOCKERFILE, done.text) == []


def test_a_lost_dependency_already_explained_is_left_exactly_as_it_is() -> None:
    reason = "dropped: gone since the 0.4.7 bump; out at the next base bump"
    listing = COMMITTED.replace("python3-cbor2\n", f"python3-cbor2  # {reason}\n", 1)
    done = merge(field(drop=("python3-cbor2",)), listing=listing)
    assert done.text == listing, "a note that already says why is not rewritten"
    assert done.marked_dropped == [] and not done.changed


def test_a_lost_dependency_layer_a_never_installed_is_removed() -> None:
    # A `deferred` entry: recorded, not installed in (a). Dropping it from
    # the list costs nothing, so it goes rather than collecting a note.
    listing = COMMITTED.replace(
        "python3-cbor2\n",
        f"{NEW}  # deferred: not in (a) yet; folded in at the next base bump\n"
        "python3-cbor2\n", 1)
    assert guard.guard_failures(DOCKERFILE, listing) == []
    done = merge(pinned_field(), listing=listing)
    assert done.deleted == [NEW] and done.marked_dropped == []
    assert NEW not in entries(done.text)
    assert guard.guard_failures(DOCKERFILE, done.text) == []


def test_a_deferred_dependency_the_deb_still_names_stays_deferred() -> None:
    # It is still a dependency and (a) still does not install it, so the
    # note has to survive the merge -- losing it is one of the three ways a
    # regenerate turns the guard red.
    listing = COMMITTED.replace(
        "python3-cbor2\n",
        f"{NEW}  # deferred: not in (a) yet; folded in at the next base bump\n"
        "python3-cbor2\n", 1)
    done = merge(field(add=(NEW,)), listing=listing)
    assert done.text == listing and not done.changed


def test_a_name_the_nightly_names_again_loses_its_dropped_note() -> None:
    # The mirror of the mirror: (a) installs it and the `.deb` depends on it
    # again, so there is nothing left to explain.
    listing = COMMITTED.replace(
        "python3-cbor2\n",
        "python3-cbor2  # dropped: gone from Depends; out at the next bump\n", 1)
    done = merge(pinned_field(), listing=listing)
    assert done.unmarked_dropped == ["python3-cbor2"]
    assert entries(done.text)["python3-cbor2"] == {}
    # Back to the committed file, bar the provenance line: the entries moved,
    # so this merge records the `.deb` it read them from.
    assert done.text == bot.rewrite_source(COMMITTED, VERSION)


# --------------------------------------------------------------------------
# The normalizations.
# --------------------------------------------------------------------------

def test_the_python3_any_qualifier_is_recorded_as_a_note() -> None:
    done = merge(pinned_field())
    assert "python3:any" not in done.text
    assert entries(done.text)["python3"]["qualifier"] == ":any"


def test_a_version_constraint_is_recorded_and_not_enforced() -> None:
    done = merge(field(replace=(("python3-babel", "python3-babel (>= 2.10)"),)))
    notes = entries(done.text)["python3-babel"]
    assert notes["version"] == "(>= 2.10)"
    assert guard.guard_failures(DOCKERFILE, done.text) == []
    # A constraint is not a new name, so (a) is unchanged and nothing defers.
    assert done.added == [] and done.deleted == []


def test_an_alternatives_group_keeps_the_member_the_file_records() -> None:
    # The group the real `.deb` carries. apt on bookworm resolves the second
    # name, because the first does not exist there -- the one decision the
    # file holds and the `.deb` cannot.
    done = merge(pinned_field())
    notes = entries(done.text)["python3-lxml"]
    assert notes["alternatives"] == "python3-lxml-html-clean | python3-lxml"
    assert "python3-lxml-html-clean\n" not in done.text


def test_an_alternatives_group_the_deb_respells_is_re_recorded() -> None:
    respelt = "python3-lxml-html-clean | python3-lxml | python3-lxml-ng"
    done = merge(field(replace=(
        ("python3-lxml-html-clean | python3-lxml", respelt),)))
    assert entries(done.text)["python3-lxml"]["alternatives"] == respelt
    assert done.regrouped == ["python3-lxml"]
    assert done.undecided == []
    assert guard.guard_failures(DOCKERFILE, done.text) == []


def test_an_alternatives_group_the_file_cannot_resolve_is_left_to_a_human() -> None:
    # The recorded member is gone from the group, so which name apt resolves
    # is a question for `apt-cache policy` in the base image. The bot must
    # not guess: it leaves the entry and the pull request body asks.
    gone = "python3-lxml-html-clean | python3-lxml6"
    done = merge(field(replace=(
        ("python3-lxml-html-clean | python3-lxml", gone),)))
    assert [one.spelling for one in done.undecided] == [gone]
    # Untouched, both ways: the old entry is neither rewritten nor dropped,
    # and neither new member is added.
    assert entries(done.text)["python3-lxml"] == entries(COMMITTED)["python3-lxml"]
    assert done.deleted == [] and done.marked_dropped == [] and done.added == []
    assert done.text == COMMITTED
    assert guard.guard_failures(DOCKERFILE, done.text) == []


def test_an_alternatives_group_with_no_recorded_member_is_left_to_a_human() -> None:
    done = merge(field(add=("python3-new-a | python3-new-b",)))
    assert [one.spelling for one in done.undecided] == \
        ["python3-new-a | python3-new-b"]
    assert done.added == [] and done.text == COMMITTED
    # Nothing breaks by leaving it out: apt resolves the group when it
    # installs the `.deb` in layer (b), where it costs a few MiB.
    assert guard.guard_failures(DOCKERFILE, done.text) == []


def test_a_group_two_of_whose_members_are_recorded_is_left_to_a_human() -> None:
    ambiguous = "python3-lxml | python3-cbor2"
    done = merge(field(replace=(
        ("python3-lxml-html-clean | python3-lxml", ambiguous),)))
    assert [one.spelling for one in done.undecided] == [ambiguous]
    assert done.text == COMMITTED


# --------------------------------------------------------------------------
# The file around the entries.
# --------------------------------------------------------------------------

def test_the_source_line_names_the_package_the_field_came_from() -> None:
    done = merge(field(add=(NEW,)))
    assert bot.source_version(done.text) == VERSION
    assert f"# source: odoo_{VERSION}_all.deb" in done.text


def test_the_comment_header_is_carried_over_word_for_word() -> None:
    done = merge(field(add=(NEW,)))
    head = COMMITTED.split("\n# source:")[0]
    assert done.text.startswith(head)


def test_the_merge_refuses_a_list_whose_comments_it_cannot_carry() -> None:
    # Comments live above the entries. One between them would be silently
    # dropped by a rewrite, so the bot stops instead.
    listing = COMMITTED.replace("python3-cbor2\n",
                                "# a late comment\npython3-cbor2\n", 1)
    with pytest.raises(ValueError, match="comment"):
        merge(pinned_field(), listing=listing)


def test_the_merge_is_idempotent_on_what_it_just_wrote() -> None:
    once = merge(field(add=(NEW,)))
    twice = merge(field(add=(NEW,)), listing=once.text)
    assert twice.text == once.text and not twice.changed


# --------------------------------------------------------------------------
# The two readings of one artifact.
#
# The script writes the list and the Dockerfile's layer (a) decides what it
# may write; the guard test reads both and holds them equal. Criterion 5 of
# issue #156 keeps `test_dockerfile_layers.py` untouched, so the script
# carries its own readers -- and these tests hold the two readings equal, so
# that a note kind or a parser rule added to one and not the other is red
# here rather than invisible.
# --------------------------------------------------------------------------

def test_the_script_and_the_guard_test_know_the_same_note_kinds() -> None:
    assert set(bot.NOTE_ORDER) == guard.NOTE_KINDS, (
        "a note kind the script writes and the guard test does not document "
        "is reported as undocumented on the next bump"
    )


NOTE_LINES = (
    "plain",
    "python3  # qualifier: :any",
    "postgresql-client  # satisfied-by: postgresql-client-16",
    "python3-lxml  # alternatives: python3-lxml-html-clean | python3-lxml",
    "name  # deferred: not in (a) yet; folded in at the next base bump",
    "name  # alternatives: a | b; deferred: later",
    "name  # version: (>= 1.2); qualifier: :any; dropped: gone; still in (a)",
    "name  # defered: a misspelled kind is not prose",
)


def test_the_script_and_the_guard_test_read_a_note_line_the_same_way() -> None:
    for line in NOTE_LINES:
        assert bot.read_entry(line) == guard.read_depends(line)[0], line


def test_the_script_and_the_guard_test_read_the_source_line_the_same_way() -> None:
    assert bot.source_version(COMMITTED) == guard.source_deb(COMMITTED)
    assert bot.source_version("# source: nothing\n") is None
    assert guard.source_deb("# source: nothing\n") is None


def test_the_script_joins_the_dockerfiles_runs_the_way_the_guard_test_does() -> None:
    # The `RUN`s only: the guard test also replaces the four pinned `ARG`
    # values with placeholders, which the script has no reason to do.
    def runs(read) -> list:
        return [one for one in read(DOCKERFILE) if one.startswith("RUN ")]

    assert runs(bot.instructions) == runs(guard.instructions)


def test_the_script_reads_layer_a_the_way_the_guard_test_does() -> None:
    # The removal rule asks whether layer (a) installs a name. Two readings
    # of the same `RUN` that disagreed would make the bot write a file the
    # guard rejects.
    assert bot.layer_a_packages(DOCKERFILE) == layer_a()


# --------------------------------------------------------------------------
# The report the pull request body carries.
# --------------------------------------------------------------------------

def test_the_report_is_one_line_when_nothing_changed() -> None:
    body = bot.report(merge(pinned_field()))
    assert len([line for line in body.strip().splitlines() if line.strip()]) == 1
    assert "unchanged" in body.lower()


def test_the_report_names_what_was_added_removed_and_deferred() -> None:
    body = bot.report(merge(field(add=(NEW,), drop=("python3-cbor2",))))
    assert NEW in body and "deferred" in body
    assert "python3-cbor2" in body and "dropped" in body


def test_the_report_asks_the_human_about_a_group_it_would_not_decide() -> None:
    gone = "python3-lxml-html-clean | python3-lxml6"
    body = bot.report(merge(field(replace=(
        ("python3-lxml-html-clean | python3-lxml", gone),))))
    assert gone in body
    assert "apt-cache policy" in body, "the body says where the answer is"
    assert "untouched" in body.lower()


# --------------------------------------------------------------------------
# The command the workflow runs.
# --------------------------------------------------------------------------

def run_script(tmp_path: Path, depends: str, *extra: str,
               version: str = VERSION) -> subprocess.CompletedProcess:
    listing = tmp_path / "odoo-deb-depends.txt"
    if not listing.exists():
        listing.write_text(COMMITTED, encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(DOCKERFILE, encoding="utf-8")
    field_file = tmp_path / "Depends"
    field_file.write_text(depends, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--list", str(listing),
         "--dockerfile", str(dockerfile), "--depends-field", str(field_file),
         "--deb-version", version, "--date", DATE, *extra],
        capture_output=True, text=True)


def test_the_command_fails_open_on_a_list_it_cannot_merge(tmp_path: Path) -> None:
    """A list the merge refuses must not fail the step.

    The steps after a failed one do not run, so the weekly bump would lose
    its pull request -- and the image build ADR 0002's merge decision rests
    on -- over a list whose entire cost is layer (b) size (ADR 0013). So the
    command succeeds, leaves the file exactly as it was, and says so where a
    reviewer reads it.
    """
    listing = tmp_path / "odoo-deb-depends.txt"
    unmergeable = COMMITTED.replace("python3-cbor2\n",
                                    "# a late comment\npython3-cbor2\n", 1)
    listing.write_text(unmergeable, encoding="utf-8")
    report = tmp_path / "report.md"
    done = run_script(tmp_path, field(add=(NEW,)), "--report", str(report))
    assert done.returncode == 0, done.stderr
    assert listing.read_text(encoding="utf-8") == unmergeable
    body = report.read_text(encoding="utf-8")
    assert "needs a human" in body and "comment" in body
    assert "::warning::" in done.stderr, "the run's log flags it too"


def test_the_command_fails_open_on_a_list_with_no_source_line(tmp_path: Path) -> None:
    listing = tmp_path / "odoo-deb-depends.txt"
    without = "".join(line for line in COMMITTED.splitlines(keepends=True)
                      if not line.startswith("# source:"))
    listing.write_text(without, encoding="utf-8")
    done = run_script(tmp_path, field(add=(NEW,)))
    assert done.returncode == 0, done.stderr
    assert listing.read_text(encoding="utf-8") == without
    assert "source" in done.stdout


def test_the_command_writes_the_list_and_the_report(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    done = run_script(tmp_path, field(add=(NEW,)), "--report", str(report))
    assert done.returncode == 0, done.stderr
    written = (tmp_path / "odoo-deb-depends.txt").read_text(encoding="utf-8")
    assert NEW in written
    assert NEW in report.read_text(encoding="utf-8")
    assert guard.guard_failures(DOCKERFILE, written) == []


def test_the_command_leaves_an_unchanged_list_untouched(tmp_path: Path) -> None:
    listing = tmp_path / "odoo-deb-depends.txt"
    listing.write_text(COMMITTED, encoding="utf-8")
    before = os.stat(listing).st_mtime_ns
    done = run_script(tmp_path, pinned_field(),
                      version=bot.source_version(COMMITTED))
    assert done.returncode == 0, done.stderr
    assert listing.read_text(encoding="utf-8") == COMMITTED
    assert os.stat(listing).st_mtime_ns == before, \
        "an unchanged file is not rewritten, so the pull request has no diff"
