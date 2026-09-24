#!/usr/bin/env python3
"""Static-tier contracts for where the base image is pinned (issue #124).

Supervisor deprecated `build.yaml` and passes a modernized build only
`BUILD_ARCH` (issue #110). The per-arch base image is therefore pinned in
the Dockerfile itself — `ARG BASE_IMAGE_TAG` composed into `FROM` with
`BUILD_ARCH` — and every consumer that used to read `build_from` reads or
writes that line instead: the publish action, both CI build jobs and the
weekly `odoo-bump`. These tests read the files as text, the way the other
workflow-shape tests do.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DOCKERFILE = ROOT / "Dockerfile"
CI = REPO / ".github/workflows/ci.yml"
BUMP = REPO / ".github/workflows/odoo-bump.yml"
PUBLISH = REPO / ".github/actions/publish-image/action.yml"

TAG = re.compile(r'^ARG BASE_IMAGE_TAG="(bookworm-\d{4}\.\d{2}\.\d+)"$', re.M)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_dockerfile_pins_the_base_image_by_arch_and_dated_tag() -> None:
    head = text(DOCKERFILE).split("SHELL ", 1)[0]
    assert re.search(r"^ARG BUILD_ARCH$", head, re.M), \
        "no default: a build that forgot the arch fails instead of building amd64 anywhere"
    assert TAG.search(head), "the tag is one dated Debian base tag"
    assert "FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:${BASE_IMAGE_TAG}" in head
    assert "BUILD_FROM" not in text(DOCKERFILE)


def test_build_yaml_is_gone_and_nothing_reads_it() -> None:
    assert not (ROOT / "build.yaml").exists()
    # Workflows, the action and the linter config must not read the file
    # or its keys; the Dockerfile and the docs may still say why it is gone.
    readers = [*REPO.glob(".github/**/*.yml"), REPO / ".hadolint.yaml", ROOT / "config.yaml"]
    offenders = [p.relative_to(REPO).as_posix() for p in readers if "build.yaml" in text(p)]
    assert offenders == [], offenders
    # docs/adr is history and is corrected by its own Issue (#123); the
    # CHANGELOG records what changed and may name the old key.
    everywhere = [*readers, DOCKERFILE, ROOT / "DOCS.md", ROOT / "README.md",
                  REPO / "README.md", REPO / "CONTEXT.md",
                  *(REPO / "docs").rglob("*.md")]
    everywhere = [p for p in everywhere if p.exists() and "docs/adr" not in p.as_posix()]
    offenders = [p.relative_to(REPO).as_posix() for p in everywhere
                 if "build_from" in text(p) or "BUILD_FROM" in text(p)]
    assert offenders == [], offenders


def test_ci_builds_each_arch_from_the_dockerfile_pin() -> None:
    ci = text(CI)
    amd64 = ci.split("build-amd64:", 1)[1].split("build-aarch64:", 1)[0]
    aarch64 = ci.split("build-aarch64:", 1)[1]
    assert "BUILD_ARCH=amd64" in amd64 and "BUILD_ARCH=aarch64" in aarch64
    assert "Resolve base image" not in ci and "yq" not in amd64 + aarch64


def test_the_publish_action_passes_only_the_arch() -> None:
    publish = text(PUBLISH)
    assert "BUILD_ARCH=${{ inputs.arch }}" in publish
    assert "base_image" not in publish


def test_odoo_bump_reads_and_writes_the_dockerfile_pin() -> None:
    bump = text(BUMP)
    read = re.search(r"sed -nE 's/\^ARG BASE_IMAGE_TAG=\"\(bookworm-[^']*'\s+\"\$\{ADDON_DIR\}/Dockerfile\"", bump)
    assert read, "the current tag is read from the Dockerfile ARG"
    write = [line for line in bump.splitlines()
             if 'sed -i -E "s/^ARG BASE_IMAGE_TAG=' in line
             and 'ARG BASE_IMAGE_TAG=\\"${NEWEST}\\"' in line
             and '"${ADDON_DIR}/Dockerfile"' in line]
    assert len(write) == 1, "the new tag is written to the same ARG line"
    assert "grep -E '^ARG BASE_IMAGE_TAG='" in bump, "the PR log shows the line it changed"


def test_the_bump_regex_matches_the_pin_as_written() -> None:
    # The sed pattern the bump reads the tag with, taken from the workflow
    # itself, must match the Dockerfile line: a hand edit that the bump
    # could no longer read fails here, not on the next Monday.
    bump = text(BUMP)
    pattern = re.search(r"sed -nE 's/(\^ARG BASE_IMAGE_TAG=[^']*?)/\\1/p'", bump).group(1)
    match = re.search(pattern, text(DOCKERFILE), re.M)
    assert match, pattern
    assert match.group(1) == TAG.search(text(DOCKERFILE)).group(1)
    # And the write step checks its own work.
    assert 'grep -qE "^ARG BASE_IMAGE_TAG=\\"${NEWEST}\\"$"' in bump
