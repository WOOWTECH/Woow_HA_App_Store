#!/usr/bin/env python3
"""Validate the GHCR image contract used by Home Assistant Supervisor."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ADDON_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = ADDON_DIR.parent
WORKFLOW = REPOSITORY_DIR / ".github/workflows/publish-n8n-addon-images.yml"
EXPECTED_IMAGE = "ghcr.io/woowtech/woow-ha-n8n-{arch}"
EXPECTED_VERSION = "2.12.16"


def main() -> None:
    config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    assert config["version"] == EXPECTED_VERSION
    assert config["image"] == EXPECTED_IMAGE
    assert config["arch"] == ["aarch64", "amd64"]
    assert not (ADDON_DIR / "build.yaml").exists(), (
        "Supervisor must pull the configured GHCR image, not client-build build.yaml"
    )

    workflow = WORKFLOW.read_text()
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
        "BUILD_REPOSITORY=${{ github.repository }}",
        "docker/setup-qemu-action@v3",
        "docker/login-action@v3",
        "registry: ghcr.io",
        "password: ${{ secrets.GITHUB_TOKEN }}",
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

    print(
        "prebuilt image release test passed: config image/version, no client build, "
        "GHCR workflow triggers, permissions, architecture tags, and build inputs verified"
    )


if __name__ == "__main__":
    main()
