#!/usr/bin/env python3
"""Static-tier contract for the folders the add-on maps (issue #126).

Supervisor 2026.07.1 renamed the app-scoped map types: `addon_config` became
`app_config`, and the old names are logged as legacy on every build. The
manifest uses the new name with the same `rw` access, so the container
still sees its config folder at `/config`. Older Supervisors reject
`app_config`; the CHANGELOG states that minimum.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEGACY_MAP_TYPES = {"addon_config", "addons", "all_addon_configs"}


def map_entries() -> list:
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    return [str(entry) for entry in config["map"]]


def test_the_config_folder_is_mapped_once_as_app_config_rw() -> None:
    app_config = [entry for entry in map_entries() if entry.split(":", 1)[0] == "app_config"]
    assert app_config == ["app_config:rw"], app_config


def test_share_stays_mapped_rw() -> None:
    assert "share:rw" in map_entries()


def test_no_legacy_map_type_is_listed() -> None:
    offenders = [entry for entry in map_entries() if entry.split(":", 1)[0] in LEGACY_MAP_TYPES]
    assert offenders == [], offenders
