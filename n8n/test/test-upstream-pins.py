#!/usr/bin/env python3
"""Keep every reference to the wrapped upstream n8n release consistent.

The upstream release lives in one place, the Dockerfile's
N8N_UPSTREAM_VERSION. The editor image, the runners image (and the task
runner launcher copied from it) and addon_info.yaml must all follow it, and
the add-on version in config.yaml must belong to the same upstream line.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ADDON_DIR = Path(__file__).resolve().parents[1]


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    assert match, f"not an X.Y.Z version: {value!r}"
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def main() -> None:
    dockerfile = (ADDON_DIR / "Dockerfile").read_text()
    config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())
    addon_info = yaml.safe_load((ADDON_DIR / "addon_info.yaml").read_text())

    upstream = re.findall(r"^ARG N8N_UPSTREAM_VERSION=(\S+)$", dockerfile, re.MULTILINE)
    assert len(upstream) == 1, f"expected one N8N_UPSTREAM_VERSION, got {upstream}"
    upstream_version = upstream[0]
    upstream_tuple = parse_version(upstream_version)

    assert re.search(
        r"^ARG BUILD_FROM=docker\.io/n8nio/n8n:\$\{N8N_UPSTREAM_VERSION\}$",
        dockerfile,
        re.MULTILINE,
    ), "BUILD_FROM must be the n8n image of N8N_UPSTREAM_VERSION"
    assert re.search(
        r"^FROM docker\.io/n8nio/runners:\$\{N8N_UPSTREAM_VERSION\} AS runner$",
        dockerfile,
        re.MULTILINE,
    ), "the runner stage must be the runners image of N8N_UPSTREAM_VERSION"
    assert (
        "COPY --from=runner --chown=root:root /usr/local/bin/task-runner-launcher "
        "/usr/local/bin/task-runner-launcher" in dockerfile
    ), "the task runner launcher must come from the same runners image"
    assert "LAUNCHER_VERSION" not in dockerfile, (
        "a separately pinned launcher can drift from the runners it starts"
    )
    # The Python runner keeps the interpreter its venv was built for.
    assert "FROM runner AS runner-python" in dockerfile
    assert "COPY --from=runner-python /woow-python/ /" in dockerfile
    assert "ln -sf /usr/bin/python3 /opt/runners/task-runner-python/.venv/bin/python" not in dockerfile, (
        "the Python runner venv must not be re-pointed at the base image's python3"
    )

    current = addon_info["source"]["current_version"]
    assert current == f"n8n@{upstream_version}", (
        f"addon_info.yaml current_version {current!r} != n8n@{upstream_version}"
    )

    addon_version = str(config["version"])
    addon_tuple = parse_version(addon_version)
    assert addon_tuple[:2] == upstream_tuple[:2] and addon_tuple[2] >= upstream_tuple[2], (
        f"add-on {addon_version} is not a release of the n8n "
        f"{upstream_tuple[0]}.{upstream_tuple[1]} line at or after {upstream_version}"
    )
    build_version = re.findall(r"^ARG BUILD_VERSION=(\S+)$", dockerfile, re.MULTILINE)
    assert build_version == [addon_version], (
        f"Dockerfile BUILD_VERSION default {build_version} != config.yaml {addon_version}"
    )

    print(
        f"upstream pin test passed: n8n {upstream_version} (editor, runners, launcher, "
        f"addon_info) wrapped by add-on {addon_version}"
    )


if __name__ == "__main__":
    main()
