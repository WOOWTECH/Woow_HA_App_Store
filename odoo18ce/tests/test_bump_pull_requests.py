#!/usr/bin/env python3
"""The weekly bump bot proposes base-image bumps in their own PR (issue #215).

`odoo-bump.yml` used to pin the Odoo nightly and the Debian base-image tag in
one pull request. The base sits below every layer of the image, so a base bump
rebuilds all of them: a Release that carries one is a full ~700 MiB download
for every host, which is the #153 failure. Bundling it with a routine Odoo
bump makes that download the price of the routine bump, so the two are now
proposed separately -- ADR 0013 ("Base-image bumps are split from Odoo bumps")
and the postscript on ADR 0002.

Since issue #156 the Odoo path also merges the new package's `Depends` into
`odoo18ce/odoo-deb-depends.txt`, so the dry runs below cover that third file
as well. The merge itself is `test_odoo_deb_depends.py`.

Two kinds of test live here. The first reads the workflow as a document: two
independent pull-request paths, their branches, labels and bodies. The second
is a dry run -- the mutation steps are lifted out of the workflow by name and
executed, with a stub `curl` and a stub `dpkg-deb`, against a throwaway git
repository holding the real Dockerfile, CHANGELOG and dependency list, so
"each PR changes only its own lines" is proved by running the steps rather
than by reading them.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import test_dockerfile_layers as guard
from conftest import require_bash, require_tool
from test_odoo_deb_depends import field as depends_field
from test_odoo_deb_depends import NEW as GAINED

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ADDON = ROOT.name
BUMP = REPO / ".github/workflows/odoo-bump.yml"
CHANGELOG_SCRIPT = REPO / ".github/scripts/changelog_unreleased.py"
DEPENDS_SCRIPT = REPO / ".github/scripts/odoo_deb_depends.py"
PR_ACTION = "peter-evans/create-pull-request"

ODOO_PR_STEP = "Open or update the Odoo pull request"
BASE_PR_STEP = "Open or update the base-image pull request"
RESET_STEP = "Start the base-image path from a clean tree"
DEPENDS_STEP = "Merge the new package's Depends into the dependency list"

# What the Odoo path rewrites, relative to the add-on directory.
ODOO_FILES = ("Dockerfile", "CHANGELOG.md", "odoo-deb-depends.txt")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def workflow() -> dict:
    document = yaml.safe_load(text(BUMP))
    assert list(document["jobs"]) == ["bump"], "one job still does the whole bump"
    return document


def steps() -> list:
    return workflow()["jobs"]["bump"]["steps"]


def step(name: str) -> dict:
    found = [s for s in steps() if s.get("name") == name]
    assert len(found) == 1, f"expected one step named {name!r}, found {len(found)}"
    return found[0]


def pr_steps() -> list:
    return [s for s in steps() if PR_ACTION in s.get("uses", "")]


# --------------------------------------------------------------------------
# The workflow as a document: two paths.
# --------------------------------------------------------------------------

def test_two_pull_request_paths_one_per_thing_bumped() -> None:
    names = [s.get("name") for s in pr_steps()]
    assert names == [ODOO_PR_STEP, BASE_PR_STEP], (
        "the Odoo pin and the base-image tag are proposed by two "
        f"create-pull-request steps, in that order; got {names}"
    )


def test_each_path_opens_its_own_branch_and_never_a_second_pull_request() -> None:
    branches = {s["name"]: s["with"]["branch"] for s in pr_steps()}
    assert branches[ODOO_PR_STEP] == "chore/odoo-nightly-bump", "the Odoo branch is unchanged"
    assert branches[BASE_PR_STEP] != branches[ODOO_PR_STEP], \
        "the base image gets a branch of its own"
    for name, branch in branches.items():
        # A branch name that varied by run or by tag would open a second
        # pull request every week instead of updating the open one.
        assert "${{" not in branch, f"{name}: the branch is a constant, so the open PR is updated"


def test_each_path_runs_only_when_its_own_thing_changed() -> None:
    conditions = {s["name"]: s["if"] for s in pr_steps()}
    assert conditions[ODOO_PR_STEP] == "steps.odoo.outputs.changed == 'true'"
    assert conditions[BASE_PR_STEP] == "steps.base.outputs.changed == 'true'"


def test_neither_path_mentions_the_other_bump() -> None:
    by_name = {s["name"]: yaml.safe_dump(s["with"]) for s in pr_steps()}
    assert "steps.base.outputs" not in by_name[ODOO_PR_STEP], \
        "the Odoo PR never names the base-image tag: its diff does not carry it"
    assert "steps.odoo.outputs" not in by_name[BASE_PR_STEP], \
        "the base-image PR never names the Odoo pin: its diff does not carry it"


def test_the_base_image_path_is_labelled_base_image() -> None:
    labels = {s["name"]: s["with"]["labels"] for s in pr_steps()}
    assert "base-image" in labels[BASE_PR_STEP]
    assert "base-image" not in labels[ODOO_PR_STEP]
    assert "dependencies" in labels[ODOO_PR_STEP]


def test_the_base_image_body_warns_about_the_full_download_and_names_the_cadence() -> None:
    body = step(BASE_PR_STEP)["with"]["body"].lower()
    assert "every layer" in body, "the body says a base change rebuilds every layer"
    assert "full download" in body, "the body says what that costs every user"
    assert "quarterly" in body and "security" in body, \
        "the body names the cadence: quarterly, or sooner for a security need"


def test_both_bodies_still_leave_the_merge_to_a_human() -> None:
    for name in (ODOO_PR_STEP, BASE_PR_STEP):
        body = step(name)["with"]["body"]
        assert "human" in body.lower() and "0002" in body, \
            f"{name}: the body still points at ADR 0002"


def test_nothing_auto_merges() -> None:
    body = text(BUMP)
    for forbidden in ("gh pr merge", "merge-method", "automerge", "auto-merge",
                      "enable-pull-request-automerge"):
        assert forbidden not in body, f"neither path auto-merges ({forbidden!r} appears)"
    for s in pr_steps():
        assert "merge" not in {k.lower() for k in s["with"]}


def test_the_base_path_starts_from_a_clean_tree() -> None:
    order = [s.get("name") for s in steps()]
    assert (order.index(ODOO_PR_STEP) < order.index(RESET_STEP)
            < order.index("Pin the new base image")), (
        "the working tree is restored between the two paths, or the base-image PR "
        "would carry the Odoo diff as well"
    )
    reset = step(RESET_STEP)
    assert reset["if"] == "steps.base.outputs.changed == 'true'"
    # From HEAD, not from the index: a restore from the index would keep an
    # edit create-pull-request had staged.
    assert "git checkout HEAD --" in reset["run"]


def test_the_odoo_path_merges_the_new_packages_depends_into_the_list() -> None:
    assert DEPENDS_SCRIPT.exists(), f"{DEPENDS_SCRIPT} owns the merge"
    merge = step(DEPENDS_STEP)
    assert merge["if"] == "steps.odoo.outputs.changed == 'true'", \
        "the dependency list is only touched when the Odoo pin moves"
    # The field is read the way odoo-deb-depends.txt documents, out of the
    # same package the step above hashed, and handed to the merge script --
    # never regenerated, which would lose the notes the `.deb` cannot supply.
    assert "dpkg-deb -f /tmp/odoo.deb Depends" in merge["run"]
    assert ".github/scripts/odoo_deb_depends.py" in merge["run"]
    order = [s.get("name") for s in steps()]
    assert (order.index("Pin the new Odoo package") < order.index(DEPENDS_STEP)
            < order.index(ODOO_PR_STEP)), (
        "the merge runs on the package the pin step downloaded, and before "
        "the pull request that carries its diff"
    )
    # The package the pin step left behind is this step's input and this
    # step's to delete; nothing downloads it twice.
    assert "rm -f /tmp/odoo.deb" in merge["run"]
    assert "rm -f /tmp/odoo.deb" not in step("Pin the new Odoo package")["run"]


def test_the_odoo_body_tells_the_reviewer_what_moved_in_the_list() -> None:
    body = step(ODOO_PR_STEP)["with"]["body"]
    assert "odoo-deb-depends.txt" in body, "the body names the file"
    assert "${{ steps.depends.outputs.report }}" in body, (
        "the body carries the merge's own report: a gained dependency is "
        "recorded `deferred` and the static tier stays green (ADR-0013), so "
        "the body is the only place a reviewer hears about it"
    )
    assert "steps.base.outputs" not in body


def test_the_base_path_also_restores_the_dependency_list() -> None:
    # Whatever the Odoo path merged into the list must not ride along in the
    # base-image pull request.
    reset = step(RESET_STEP)["run"]
    for name in ODOO_FILES:
        assert f'"${{ADDON_DIR}}/{name}"' in reset, name


def test_both_paths_record_the_bump_through_the_one_changelog_writer() -> None:
    assert CHANGELOG_SCRIPT.exists(), f"{CHANGELOG_SCRIPT} is the shared CHANGELOG writer"
    for name in ("Record the Odoo bump under Unreleased",
                 "Record the base-image bump under Unreleased"):
        run = step(name)["run"]
        assert ".github/scripts/changelog_unreleased.py" in run
        assert '"${ADDON_DIR}/CHANGELOG.md"' in run


# --------------------------------------------------------------------------
# The shared CHANGELOG writer.
# --------------------------------------------------------------------------

HEAD = "# Changelog\n\n"


def record(tmp_path: Path, body: str, *entries: str) -> str:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(HEAD + body, encoding="utf-8")
    subprocess.run([sys.executable, str(CHANGELOG_SCRIPT), str(path), *entries],
                   check=True, capture_output=True, text=True)
    return text(path)


def test_the_writer_opens_an_unreleased_section_when_there_is_none(tmp_path: Path) -> None:
    out = record(tmp_path, "## 0.4.7 - 2026-09-30\n\n- something\n", "Odoo nightly a -> b.")
    assert out == HEAD + "## Unreleased\n\n### Changed\n- Odoo nightly a -> b.\n\n" \
                         "## 0.4.7 - 2026-09-30\n\n- something\n"


def test_the_writer_adds_changed_to_an_unreleased_section_that_lacks_it(tmp_path: Path) -> None:
    out = record(tmp_path, "## Unreleased\n\n### Added\n- a feature\n",
                 "Debian base image a -> b.")
    assert out == HEAD + "## Unreleased\n\n### Changed\n- Debian base image a -> b.\n\n" \
                         "### Added\n- a feature\n"


def test_the_writer_merges_into_an_existing_changed_section(tmp_path: Path) -> None:
    # The other path's open pull request may have written there first, and a
    # Release collects whatever `## Unreleased` holds (ADR 0002).
    out = record(tmp_path, "## Unreleased\n\n### Changed\n- Debian base image a -> b.\n",
                 "Odoo nightly c -> d.")
    assert out == HEAD + "## Unreleased\n\n### Changed\n- Odoo nightly c -> d.\n" \
                         "- Debian base image a -> b.\n"
    assert out.count("### Changed") == 1


def test_the_writer_refuses_a_changelog_it_does_not_recognise(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("## Unreleased\n", encoding="utf-8")
    done = subprocess.run([sys.executable, str(CHANGELOG_SCRIPT), str(path), "x"],
                          capture_output=True, text=True)
    assert done.returncode != 0 and "# Changelog" in done.stderr


# --------------------------------------------------------------------------
# The dry runs: the workflow's own steps, executed.
# --------------------------------------------------------------------------

NEW_ODOO = "18.0.20991231"
NEW_BASE = "bookworm-2099.12.0"
CURRENT_ODOO = re.search(r'^ARG ODOO_DEB_VERSION="([^"]+)"$',
                         text(ROOT / "Dockerfile"), re.M).group(1)
CURRENT_BASE = re.search(r'^ARG BASE_IMAGE_TAG="([^"]+)"$',
                         text(ROOT / "Dockerfile"), re.M).group(1)

CURL_STUB = """#!/bin/sh
# Enough of curl for the dry run: write bytes to wherever -o points.
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; shift; fi
  shift
done
[ -n "$out" ] || exit 22
printf 'not a real package' > "$out"
"""

DPKG_DEB_STUB = """#!/bin/sh
# Enough of dpkg-deb for the dry run: print the `Depends` field the test left
# beside this stub. The package the real one would read is a stub too.
cat "$(dirname "$0")/Depends"
"""


def stub_dir(root: Path) -> Path:
    """Where the dry run keeps its stand-ins for `curl` and `dpkg-deb`,
    beside the workspace.

    Beside it, not inside it: an untracked file in the workspace is exactly
    what the reset step is supposed to stop on.
    """
    return root.parent / "stub"


def served_depends(root: Path, depends: str) -> None:
    """What the stub `dpkg-deb` reports the new package depends on."""
    (stub_dir(root) / "Depends").write_text(depends, encoding="utf-8")


def step_outputs(root: Path) -> dict:
    """What the dry run's steps appended to `$GITHUB_OUTPUT`.

    Only the `name<<DELIMITER` form, which is the one a multi-line value --
    the dependency report the pull-request body carries -- has to use.
    """
    path = github_output(root)
    found, key, delimiter, buffered = {}, None, None, []
    for line in (path.read_text(encoding="utf-8").splitlines()
                 if path.exists() else []):
        if key is None:
            name, sep, rest = line.partition("<<")
            assert sep, f"not a multi-line output: {line!r}"
            key, delimiter = name, rest
        elif line == delimiter:
            found[key] = "\n".join(buffered) + "\n"
            key, delimiter, buffered = None, None, []
        else:
            buffered.append(line)
    assert key is None, f"unterminated output {key!r}"
    return found


def github_output(root: Path) -> Path:
    return root.parent / "github_output"


def run_git(root: Path, *args: str) -> str:
    done = subprocess.run([require_tool("git"), *args], cwd=root, check=True,
                          capture_output=True, text=True)
    return done.stdout


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """A throwaway repository with the three files the bump rewrites."""
    require_bash()
    require_tool("git")
    root = tmp_path / "workspace"
    (root / ADDON).mkdir(parents=True)
    for name in ODOO_FILES:
        shutil.copy(ROOT / name, root / ADDON / name)
    (root / ".github/scripts").mkdir(parents=True)
    for script in (CHANGELOG_SCRIPT, DEPENDS_SCRIPT):
        shutil.copy(script, root / ".github/scripts" / script.name)
    run_git(root, "init", "-q", ".")
    run_git(root, "config", "user.email", "bump@example.invalid")
    run_git(root, "config", "user.name", "bump")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "base")
    stub = stub_dir(root)
    stub.mkdir()
    for name, body in (("curl", CURL_STUB), ("dpkg-deb", DPKG_DEB_STUB)):
        tool = stub / name
        tool.write_text(body, encoding="utf-8")
        tool.chmod(0o755)
    # The new nightly depends on exactly what the pinned one does, unless a
    # test says otherwise: a bump that moves no dependency is the common one.
    served_depends(root, depends_field())
    return root


def run_step(root: Path, name: str, env: dict | None = None) -> None:
    """Run one step's `run:` script where the runner would run it."""
    declared = set((step(name).get("env") or {}))
    assert declared == set(env or {}), (
        f"{name}: the step declares env {sorted(declared)}; the dry run passes "
        f"{sorted(env or {})}"
    )
    environment = {**os.environ, **workflow().get("env", {}), **(env or {})}
    environment["PATH"] = f"{stub_dir(root)}{os.pathsep}{os.environ['PATH']}"
    # Injected by the runner rather than declared by the step.
    environment["GITHUB_OUTPUT"] = str(github_output(root))
    done = subprocess.run([require_bash(), "-c", step(name)["run"]], cwd=root,
                          env=environment, capture_output=True, text=True)
    assert done.returncode == 0, f"{name} failed:\n{done.stdout}\n{done.stderr}"


def rewritten_args(root: Path) -> list:
    """The Dockerfile lines the dry run changed."""
    before = text(ROOT / "Dockerfile").splitlines()
    after = text(root / ADDON / "Dockerfile").splitlines()
    assert len(before) == len(after), "a bump rewrites lines, it does not add or drop any"
    return [b for a, b in zip(before, after) if a != b]


def added_bullets(root: Path) -> list:
    before = set(text(ROOT / "CHANGELOG.md").splitlines())
    return [line for line in text(root / ADDON / "CHANGELOG.md").splitlines()
            if line.startswith("- ") and line not in before]


def bump_odoo(root: Path) -> None:
    run_step(root, "Pin the new Odoo package", {"NEWEST": NEW_ODOO})
    run_step(root, DEPENDS_STEP, {"NEWEST": NEW_ODOO})
    run_step(root, "Record the Odoo bump under Unreleased",
             {"FROM": CURRENT_ODOO, "TO": NEW_ODOO})


def bump_base(root: Path) -> None:
    run_step(root, "Pin the new base image", {"NEWEST": NEW_BASE})
    run_step(root, "Record the base-image bump under Unreleased",
             {"FROM": CURRENT_BASE, "TO": NEW_BASE})


def test_a_newer_odoo_nightly_alone_changes_only_the_odoo_pins(sandbox: Path) -> None:
    # The common bump: the nightly moved, its dependencies did not. The
    # dependency list is then not in the diff at all.
    bump_odoo(sandbox)
    assert sorted(run_git(sandbox, "diff", "--name-only").split()) == [
        f"{ADDON}/CHANGELOG.md", f"{ADDON}/Dockerfile"]
    changed = rewritten_args(sandbox)
    assert [line.split("=")[0] for line in changed] == \
        ["ARG ODOO_DEB_VERSION", "ARG ODOO_DEB_SHA256"], changed
    assert f'ARG ODOO_DEB_VERSION="{NEW_ODOO}"' in changed
    assert f'ARG BASE_IMAGE_TAG="{CURRENT_BASE}"' in text(sandbox / ADDON / "Dockerfile")
    assert added_bullets(sandbox) == [f"- Odoo nightly package {CURRENT_ODOO} -> {NEW_ODOO}."]
    assert "unchanged" in step_outputs(sandbox)["report"].lower(), \
        "the body still says, in one line, that the list did not move"


def test_a_nightly_that_gained_a_dependency_defers_it_and_stays_green(sandbox: Path) -> None:
    served_depends(sandbox, depends_field(add=(GAINED,)))
    bump_odoo(sandbox)
    listing = sandbox / ADDON / "odoo-deb-depends.txt"
    assert sorted(run_git(sandbox, "diff", "--name-only").split()) == [
        f"{ADDON}/CHANGELOG.md", f"{ADDON}/Dockerfile",
        f"{ADDON}/odoo-deb-depends.txt"]
    notes = dict(guard.read_depends(text(listing)))[GAINED]
    assert NEW_ODOO in notes["deferred"]
    assert re.search(r"\(\d{4}-\d{2}-\d{2}\)", notes["deferred"]), \
        "the note names the bump that gained it"
    # The point of the whole exercise: layer (a) is untouched, so the static
    # tier is green and this pull request still reaches its image build.
    assert guard.guard_failures(text(sandbox / ADDON / "Dockerfile"),
                                text(listing)) == []
    assert [line.split("=")[0] for line in rewritten_args(sandbox)] == \
        ["ARG ODOO_DEB_VERSION", "ARG ODOO_DEB_SHA256"]
    report = step_outputs(sandbox)["report"]
    assert GAINED in report and "deferred" in report


def test_a_nightly_that_dropped_a_dependency_keeps_layer_a_as_it_is(sandbox: Path) -> None:
    served_depends(sandbox, depends_field(drop=("python3-cbor2",)))
    bump_odoo(sandbox)
    listing = text(sandbox / ADDON / "odoo-deb-depends.txt")
    notes = dict(guard.read_depends(listing))["python3-cbor2"]
    assert NEW_ODOO in notes["dropped"]
    # Removing it from layer (a) would re-send ~480 MiB on a routine bump,
    # so the Dockerfile is unchanged apart from the two pins.
    assert [line.split("=")[0] for line in rewritten_args(sandbox)] == \
        ["ARG ODOO_DEB_VERSION", "ARG ODOO_DEB_SHA256"]
    assert guard.guard_failures(text(sandbox / ADDON / "Dockerfile"), listing) == []
    assert "python3-cbor2" in step_outputs(sandbox)["report"]


def test_a_depends_it_cannot_read_costs_the_list_and_not_the_bump(sandbox: Path) -> None:
    # The step must not fail: the steps after a failed one do not run, so the
    # pin would never reach its pull request and the base-image path would
    # never start -- the whole weekly bump lost to a list whose entire cost
    # is layer (b) size (ADR 0013).
    broken = stub_dir(sandbox) / "dpkg-deb"
    broken.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    broken.chmod(0o755)
    bump_odoo(sandbox)
    assert sorted(run_git(sandbox, "diff", "--name-only").split()) == [
        f"{ADDON}/CHANGELOG.md", f"{ADDON}/Dockerfile"], \
        "the list is exactly as it was"
    assert f'ARG ODOO_DEB_VERSION="{NEW_ODOO}"' in rewritten_args(sandbox)
    report = step_outputs(sandbox)["report"]
    assert "needs a human" in report and "could not be read" in report


def test_a_list_it_cannot_merge_costs_the_list_and_not_the_bump(sandbox: Path) -> None:
    # The other half: `dpkg-deb` works and the committed list does not parse.
    # The script itself fails open, so the step is green and the list stands.
    listing = sandbox / ADDON / "odoo-deb-depends.txt"
    listing.write_text(text(listing).replace(
        "python3-cbor2\n", "# a late comment\npython3-cbor2\n", 1),
        encoding="utf-8")
    run_git(sandbox, "commit", "-qam", "a comment the merge cannot carry")
    before = text(listing)
    bump_odoo(sandbox)
    assert text(listing) == before
    assert f'ARG ODOO_DEB_VERSION="{NEW_ODOO}"' in rewritten_args(sandbox)
    assert "needs a human" in step_outputs(sandbox)["report"]


def test_the_reset_clears_a_dependency_list_edit_too(sandbox: Path) -> None:
    served_depends(sandbox, depends_field(add=(GAINED,)))
    bump_odoo(sandbox)
    assert GAINED in text(sandbox / ADDON / "odoo-deb-depends.txt")
    run_step(sandbox, RESET_STEP)
    assert run_git(sandbox, "status", "--porcelain") == "", \
        "the merged list is gone before the base-image path starts"


def test_a_newer_base_tag_alone_changes_only_the_base_pin(sandbox: Path) -> None:
    bump_base(sandbox)
    assert sorted(run_git(sandbox, "diff", "--name-only").split()) == [
        f"{ADDON}/CHANGELOG.md", f"{ADDON}/Dockerfile"]
    assert rewritten_args(sandbox) == [f'ARG BASE_IMAGE_TAG="{NEW_BASE}"']
    assert f'ARG ODOO_DEB_VERSION="{CURRENT_ODOO}"' in text(sandbox / ADDON / "Dockerfile")
    assert added_bullets(sandbox) == [f"- Debian base image {CURRENT_BASE} -> {NEW_BASE}."]


def diff_lines(root: Path) -> list:
    """The lines a pull request off this tree would add or remove."""
    return [line for line in run_git(root, "diff", "-U0").splitlines()
            if re.match(r"^[-+][^-+]", line)]


def test_both_newer_gives_each_path_a_diff_of_its_own(sandbox: Path) -> None:
    bump_odoo(sandbox)
    assert any("ODOO_DEB_VERSION" in line for line in diff_lines(sandbox))
    # create-pull-request commits the tree to its own branch and leaves the
    # workspace on the branch it started from; the reset step makes sure of it.
    run_step(sandbox, RESET_STEP)
    assert run_git(sandbox, "status", "--porcelain") == "", \
        "the Odoo edits are gone before the base-image path starts"
    bump_base(sandbox)
    changed = diff_lines(sandbox)
    assert any("BASE_IMAGE_TAG" in line for line in changed)
    assert not [line for line in changed if "ODOO_DEB" in line], \
        "the base-image PR carries none of the Odoo bump"
    assert added_bullets(sandbox) == [f"- Debian base image {CURRENT_BASE} -> {NEW_BASE}."]


def test_the_reset_clears_the_odoo_edits_even_once_they_are_staged(sandbox: Path) -> None:
    # create-pull-request stages what it commits. A restore from the index
    # would hand the staged Odoo bump to the base-image pull request.
    bump_odoo(sandbox)
    run_git(sandbox, "add", "-A")
    run_step(sandbox, RESET_STEP)
    assert run_git(sandbox, "status", "--porcelain") == ""


def test_the_reset_stops_on_a_change_it_cannot_account_for(sandbox: Path) -> None:
    (sandbox / f"{ADDON}/config.yaml").write_text("version: 9.9.9\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="base-image PR must not include"):
        run_step(sandbox, RESET_STEP)


def test_a_second_run_on_the_same_tag_is_the_same_one_line_diff(sandbox: Path) -> None:
    # The branch is reused, so the next week's run rewrites the same line
    # rather than stacking a second bump on top of the first.
    bump_base(sandbox)
    first = run_git(sandbox, "diff")
    run_step(sandbox, RESET_STEP)
    bump_base(sandbox)
    assert run_git(sandbox, "diff") == first


# --------------------------------------------------------------------------
# The decision record.
# --------------------------------------------------------------------------

def test_adr_0002_records_that_base_bumps_are_proposed_separately() -> None:
    adr = text(REPO / "docs/adr/0002-odoo-nightly-bumps-are-human-merged.md")
    postscript = re.search(r"^## Postscript \(2026-10-01[^)]*\)$(.*)", adr, re.M | re.S)
    assert postscript, "the split is recorded as a dated postscript on ADR 0002"
    tail = postscript.group(1).lower()
    assert "quarterly" in tail and "security" in tail, "the cadence is in the record"
    assert "#153" in postscript.group(1) and "0013" in postscript.group(1)
    # The original decision is untouched.
    assert "the same job proposes Debian base-image updates" in adr
