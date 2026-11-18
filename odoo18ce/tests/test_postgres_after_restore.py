#!/usr/bin/env python3
"""The PostgreSQL cluster a Home Assistant restore gives back is repaired.

Supervisor restores an add-on by copying its backup into /data as root, so
the cluster arrives owned by root and, up to 0.4.12, `00-postgres-init.sh`
stopped at `pg_ctl: could not open PID file ... Permission denied`. Section
1b of the script gives back what is wrong before PostgreSQL starts.

The Build tier starts the image on a restored cluster
(`in_image/postgres_after_restore.sh`). This file is the half that needs no
image: the section runs where the script runs it, it changes only what is
wrong and follows no link -- shown by running the section itself in bash
against a temporary tree, with a `chown` on PATH that records instead of
changing owners -- and the Build tier step exists and can fail.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import require_bash

ROOT = Path(__file__).resolve().parents[1]
POSTGRES_INIT = ROOT / "rootfs/etc/cont-init.d/00-postgres-init.sh"
SMOKE = ROOT / "tests/in_image/postgres_after_restore.sh"
CI_WORKFLOW = ROOT.parent / ".github/workflows/ci.yml"

SECTION_START = "# ---------- 1b. "
SECTION_END = "# ---------- 2. "


def script() -> str:
    return POSTGRES_INIT.read_text(encoding="utf-8")


def repair_section() -> str:
    text = script()
    assert SECTION_START in text and SECTION_END in text, (
        "00-postgres-init.sh lost the headers this file finds the repair by"
    )
    return text[text.index(SECTION_START):text.index(SECTION_END)]


def test_the_repair_runs_after_initdb_and_before_postgresql_starts() -> None:
    text = script()
    initdb = text.index('"${PG_BIN}/initdb"')
    repair = text.index(SECTION_START)
    first_start = text.index('"${PG_BIN}/pg_ctl" start')
    assert initdb < repair < first_start, (
        "the repair must come after initdb, so a new cluster passes through it too, "
        "and before the first pg_ctl start, which is where a restored cluster failed"
    )
    # Outside any branch: it is the only place an existing cluster passes.
    assert repair_section().startswith(SECTION_START) and text[:repair].rstrip().endswith("fi")


def test_the_repair_changes_only_what_is_wrong_and_follows_no_link() -> None:
    section = repair_section()
    commands = [line for line in section.splitlines() if not line.lstrip().startswith("#")]
    code = "\n".join(commands)
    finds = re.findall(r"\bfind\b[^\n]*", code)
    assert finds, "the repair finds what to change with find"
    for find in finds:
        assert re.search(r"\bfind -(?:L|H)\b|-follow\b", find) is None, (
            f"find must not follow symbolic links: {find}"
        )
        assert '\\( ! -user postgres -o ! -group postgres \\)' in find, (
            f"find must select only what is not postgres:postgres: {find}"
        )
    assert "chown -h postgres:postgres {} +" in code, (
        "chown must change a link itself (-h), never what it points to"
    )
    assert "chown -R" not in code and "chmod -R" not in code, (
        "a recursive chown or chmod follows no selection and touches a healthy cluster too"
    )
    assert 'chmod 0700 "${PG_DATA}"' in code


def test_the_smoke_test_looks_for_the_line_the_repair_logs() -> None:
    smoke = SMOKE.read_text(encoding="utf-8")
    match = re.search(r'^REPAIR_LINE="([^"]+)"$', smoke, re.M)
    assert match, "postgres_after_restore.sh must state REPAIR_LINE on a line of its own"
    assert 'declare PG_DATA="/data/postgres"' in script()
    logged = match.group(1).replace("/data/postgres", "${PG_DATA}")
    assert f'bashio::log.info "{logged}' in repair_section(), (
        f"the repair's log line no longer starts with {match.group(1)!r}, which the Build "
        "tier counts; change both together"
    )


# ---------- the section itself, in bash ----------

def owners() -> dict:
    """The test's own user and group, and an existing user and group that are not.

    Linux only: the section uses GNU find and stat, as the image does, and
    `pwd` and `grp` do not exist on Windows.
    """
    if not sys.platform.startswith("linux"):
        pytest.skip("the section uses GNU find and stat, as the image does")
    import grp
    import pwd
    return {
        "me": pwd.getpwuid(os.getuid()).pw_name,
        "my_group": grp.getgrgid(os.getgid()).gr_name,
        "other": next(entry.pw_name for entry in pwd.getpwall() if entry.pw_uid != os.getuid()),
        "other_group": next(entry.gr_name for entry in grp.getgrall() if entry.gr_gid != os.getgid()),
    }


def run_section(tmp_path: Path, cluster: Path, owner: str, group: str) -> tuple:
    """Run section 1b on `cluster`, wanting `owner:group` where it says postgres.

    The test cannot make files that belong to someone else, so it changes
    which owner the section wants instead: with the test's own user nothing
    is wrong, with another user everything is. `chown` is a recorder on PATH
    (find runs it by name), so nothing changes owner; chmod is real.
    Returns (stdout, the arguments each chown call got).
    """
    section = repair_section()
    for spelling in ("-user postgres", "-group postgres", "postgres:postgres"):
        assert spelling in section, f"the section no longer says {spelling!r}; nothing is substituted"
    section = (
        section.replace("-user postgres", f"-user {owner}")
        .replace("-group postgres", f"-group {group}")
        .replace("postgres:postgres", f"{owner}:{group}")
    )
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "chown-calls"
    recorder = stubs / "chown"
    recorder.write_text(
        '#!/bin/sh\nfor arg in "$@"; do printf "%s\\n" "$arg"; done >> "$CHOWN_CALLS"\n'
        'printf -- "--\\n" >> "$CHOWN_CALLS"\n',
        encoding="utf-8",
    )
    recorder.chmod(0o755)
    prelude = 'set -e\nbashio::log.info() { printf "INFO %s\\n" "$*"; }\n'
    result = subprocess.run(
        [require_bash(), "-c", f'{prelude}PG_DATA="{cluster}"\n{section}'],
        capture_output=True, encoding="utf-8", timeout=60,
        env={**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
             "CHOWN_CALLS": str(calls)},
    )
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8").split("--\n")[:-1] if calls.exists() else []
    return result.stdout, [call.splitlines() for call in recorded]


def make_cluster(tmp_path: Path, mode: int) -> tuple:
    """A cluster with a link to a file and a link to a directory outside it."""
    cluster = tmp_path / "postgres"
    (cluster / "base/1").mkdir(parents=True)
    (cluster / "PG_VERSION").write_text("16\n", encoding="utf-8")
    (cluster / "base/1/1259").write_text("", encoding="utf-8")
    outside = tmp_path / "outside"
    (outside / "dir").mkdir(parents=True)
    (outside / "file").write_text("not the cluster's\n", encoding="utf-8")
    (outside / "dir/inside").write_text("not the cluster's\n", encoding="utf-8")
    (cluster / "link-to-file").symlink_to(outside / "file")
    (cluster / "link-to-dir").symlink_to(outside / "dir")
    cluster.chmod(mode)
    return cluster, outside


def test_a_healthy_cluster_is_left_alone_and_nothing_is_logged(tmp_path: Path) -> None:
    who = owners()
    cluster, _ = make_cluster(tmp_path, 0o700)
    stdout, calls = run_section(tmp_path, cluster, who["me"], who["my_group"])
    assert calls == [], "chown ran on a cluster whose owner is right"
    assert stdout == "", "an ordinary start logs no repair"
    assert cluster.stat().st_mode & 0o777 == 0o700


def test_a_restored_cluster_is_given_back_without_following_a_link(tmp_path: Path) -> None:
    who = owners()
    owner, group = who["other"], who["other_group"]
    cluster, outside = make_cluster(tmp_path, 0o755)
    stdout, calls = run_section(tmp_path, cluster, owner, group)
    assert calls, "chown never ran on a cluster nobody wanted owns"
    assert all(call[:2] == ["-h", f"{owner}:{group}"] for call in calls), calls
    changed = sorted(path for call in calls for path in call[2:])
    expected = sorted(str(path) for path in [
        cluster, cluster / "PG_VERSION", cluster / "base", cluster / "base/1",
        cluster / "base/1/1259", cluster / "link-to-file", cluster / "link-to-dir",
    ])
    assert changed == expected, "every entry is given back once, the two links as links"
    assert not any(path.startswith(str(outside)) for path in changed), (
        "the repair went through a link to what it points to"
    )
    assert cluster.stat().st_mode & 0o777 == 0o700
    assert stdout == (
        f"INFO Repaired {cluster} (a restore copies it back owned by root): "
        f"{len(expected)} files given back to {owner}:{group}, mode 755 -> 700\n"
    )


def test_a_wrong_group_alone_is_given_back_too(tmp_path: Path) -> None:
    who = owners()
    cluster, _ = make_cluster(tmp_path, 0o700)
    stdout, calls = run_section(tmp_path, cluster, who["me"], who["other_group"])
    changed = [path for call in calls for path in call[2:]]
    assert len(changed) == 7, "an entry with the right owner and the wrong group was left as it was"
    assert stdout.endswith(f"7 files given back to {who['me']}:{who['other_group']}\n"), stdout


def test_a_cluster_directory_at_another_mode_is_set_back_to_0700(tmp_path: Path) -> None:
    who = owners()
    cluster, _ = make_cluster(tmp_path, 0o750)
    stdout, calls = run_section(tmp_path, cluster, who["me"], who["my_group"])
    assert calls == []
    assert cluster.stat().st_mode & 0o777 == 0o700
    assert stdout == f"INFO Repaired {cluster} (a restore copies it back owned by root): mode 750 -> 700\n"


# ---------- the Build tier step ----------

def restore_step() -> tuple:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["build-amd64"]
    steps = [step for step in job["steps"] if "postgres_after_restore.sh" in step.get("run", "")]
    assert len(steps) == 1, "build (amd64) needs exactly one step running the restore smoke test"
    return workflow, job, steps[0]["run"]


def test_the_smoke_test_runs_on_the_image_every_pull_request_builds() -> None:
    _, job, run = restore_step()
    assert "if" not in job, "build (amd64) must stay unconditional"
    assert "woow-ha-odoo-amd64:ci" in run, "the smoke test must start the image this build produced"


def test_the_smoke_test_step_is_bounded_and_fails_the_build() -> None:
    _, _, run = restore_step()
    assert "timeout" in run, "the step must bound the containers' run time"
    assert "set -euo pipefail" in run
    assert "grep -qx 'postgres-after-restore: ok'" in run, "only the script's last line is a pass"
    assert "::error::" in run, "the step must say what a red smoke test means"


def test_the_smoke_test_is_linted_with_the_rootfs_scripts() -> None:
    workflow, _, _ = restore_step()
    lint = [step["run"] for step in workflow["jobs"]["lint"]["steps"] if step.get("name") == "shellcheck"]
    assert lint and "tests/in_image/postgres_after_restore.sh" in lint[0]
