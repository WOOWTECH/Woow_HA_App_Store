#!/usr/bin/env python3
"""Validate the GHCR image contract used by Home Assistant Supervisor."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ADDON_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = ADDON_DIR.parent
WORKFLOWS = REPOSITORY_DIR / ".github/workflows"
PUBLISH = WORKFLOWS / "publish-n8n-addon-images.yml"
CI = WORKFLOWS / "ci.yml"
EXPECTED_IMAGE = "ghcr.io/woowtech/woow-ha-n8n-{arch}"
# Third-party actions run with registry credentials; pin them to a commit.
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def assert_actions_pinned(path: Path) -> None:
    text = path.read_text()
    for use in re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", text, re.MULTILINE):
        if use.startswith("./") or use.startswith("WOOWTECH/"):
            continue
        assert PINNED_ACTION.match(use), f"{path.name}: action not pinned to a commit SHA: {use}"


def main() -> None:
    config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(config["version"])), config["version"]
    assert config["image"] == EXPECTED_IMAGE
    assert config["arch"] == ["aarch64", "amd64"]
    assert not (ADDON_DIR / "build.yaml").exists(), (
        "Supervisor must pull the configured GHCR image, not client-build build.yaml"
    )

    workflow = PUBLISH.read_text()
    required_fragments = (
        "workflow_dispatch:",
        "push:",
        "- n8n/config.yaml",
        "contents: read",
        "packages: write",
        "context: ./n8n",
        "file: ./n8n/Dockerfile",
        "push: true",
        "BUILD_ARCH=${{ matrix.arch }}",
        "BUILD_VERSION=${{ steps.addon.outputs.version }}",
        "BUILD_REF=${{ github.sha }}",
        "BUILD_REPOSITORY=${{ github.repository }}",
        "registry: ghcr.io",
        "password: ${{ secrets.GITHUB_TOKEN }}",
        "uses: ./.github/workflows/ci.yml",
        "needs: validate",
    )
    missing = [fragment for fragment in required_fragments if fragment not in workflow]
    assert not missing, f"release workflow is missing: {missing}"
    assert re.search(
        r"matrix:\n\s+include:\n\s+- arch: amd64\n\s+platform: linux/amd64"
        r"\n\s+- arch: aarch64\n\s+platform: linux/arm64",
        workflow,
    ), "workflow must publish separate native amd64 and aarch64 images"
    assert (
        "ghcr.io/woowtech/woow-ha-n8n-${{ matrix.arch }}:${{ steps.addon.outputs.version }}"
        in workflow
    ), "workflow image tags must use the configured image template and add-on version"
    assert re.search(
        r"awk -F': ' '\$1 == \"version\" \{ print \$2; exit \}' n8n/config.yaml",
        workflow,
    ), "workflow must derive its tag from n8n/config.yaml"

    # Published tags are immutable: the existence check must run before the
    # build, and every build step must be skipped when the tag already exists.
    guard = workflow.index("- name: Refuse to overwrite a published tag")
    build = workflow.index("- name: Build and push image")
    assert guard < build, "the tag guard must run before the image is built"
    assert "docker buildx imagetools inspect" in workflow[guard:build]
    assert "exit 1" in workflow[guard:build], "an existing foreign tag must fail the run"
    for step in ("Set up QEMU", "Set up Docker Buildx", "Build and push image"):
        section = workflow[workflow.index(f"- name: {step}"):]
        section = section[: section.index("uses:")]
        assert "if: steps.tag.outputs.exists != 'true'" in section, (
            f"{step} must be skipped for an already published tag"
        )

    ci = CI.read_text()
    for fragment in (
        "pull_request:",
        "workflow_call:",
        "bash n8n/test/run-tests.sh",
        "--build-arg BUILD_ARCH=amd64",
        "python smoke-container.py local/woow-n8n:ci --browser",
    ):
        assert fragment in ci, f"ci.yml is missing {fragment!r}"

    for path in WORKFLOWS.glob("*.yml"):
        assert_actions_pinned(path)

    docs = (ADDON_DIR / "DOCS.md").read_text()
    assert "Use **Run workflow** on the release revision to rebuild its images" not in docs, (
        "DOCS.md must not tell maintainers to rebuild a published tag"
    )

    print(
        "prebuilt image release test passed: config image/version, no client build, "
        "CI gate, immutable tags, pinned actions, architecture tags and build inputs verified"
    )


if __name__ == "__main__":
    main()
