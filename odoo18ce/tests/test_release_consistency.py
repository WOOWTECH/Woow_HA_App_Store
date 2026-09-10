"""Release bookkeeping that CI enforces so a Release cannot be half-done.

- config.yaml carries a semantic version.
- The CHANGELOG's first version heading matches it, and headings descend.
- An `## Unreleased` section may sit on top only while the version is
  unchanged; a version bump must fold it in (RELEASE_CHECK_STRICT=1).
- Both translation files cover exactly the option schema.
"""
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEADING_RE = re.compile(r"^## (?P<title>.+?)(?: — (?P<date>\d{4}-\d{2}-\d{2}))?\s*$", re.M)


def config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def changelog_headings() -> list:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return [(m.group("title"), m.group("date")) for m in HEADING_RE.finditer(text)]


def as_tuple(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def test_version_is_semantic() -> None:
    version = str(config()["version"])
    assert VERSION_RE.match(version), f"config.yaml version must be x.y.z, got {version!r}"


def test_changelog_leads_with_the_current_version() -> None:
    version = str(config()["version"])
    headings = changelog_headings()
    assert headings, "CHANGELOG.md has no '## ' headings"
    strict = os.environ.get("RELEASE_CHECK_STRICT") == "1"
    first_title, first_date = headings[0]
    if first_title == "Unreleased":
        assert not strict, (
            "the version changed but CHANGELOG.md still has an '## Unreleased' section; "
            f"rename it to '## {version} — <date>'"
        )
        assert len(headings) > 1, "CHANGELOG.md has only an Unreleased section"
        current_title, current_date = headings[1]
    else:
        current_title, current_date = first_title, first_date
    assert current_title == version, (
        f"config.yaml is {version} but the first CHANGELOG version heading is {current_title!r}"
    )
    assert current_date, f"CHANGELOG heading for {version} needs a date: '## {version} — YYYY-MM-DD'"


def test_changelog_versions_descend() -> None:
    versions = [title for title, _ in changelog_headings() if title != "Unreleased"]
    for title in versions:
        assert VERSION_RE.match(title), f"CHANGELOG heading is not a version: {title!r}"
    parsed = [as_tuple(v) for v in versions]
    assert parsed == sorted(parsed, reverse=True), "CHANGELOG versions must be in descending order"
    assert len(parsed) == len(set(parsed)), "CHANGELOG has a duplicated version heading"


def test_translations_cover_the_schema_exactly() -> None:
    schema_keys = set(config()["schema"])
    for name in ["en", "zh-Hant"]:
        path = ROOT / "translations" / f"{name}.yaml"
        entries = yaml.safe_load(path.read_text(encoding="utf-8"))["configuration"]
        keys = set(entries)
        assert keys == schema_keys, (
            f"{path.name}: missing {sorted(schema_keys - keys)}, extra {sorted(keys - schema_keys)}"
        )
        for key, entry in entries.items():
            assert entry.get("name") and entry.get("description"), f"{path.name}: {key} needs name and description"
