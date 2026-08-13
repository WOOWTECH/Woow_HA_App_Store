"""Parse blueprint YAML files and extract input definitions at runtime."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

_LOGGER = logging.getLogger(__name__)


class _BlueprintLoader(yaml.SafeLoader):
    """YAML loader that handles HA-specific tags like !input, !include."""


# Register constructors for HA-specific tags
for _tag in ("!input", "!include", "!include_dir_list", "!include_dir_named",
             "!include_dir_merge_list", "!include_dir_merge_named", "!secret",
             "!env_var"):
    _BlueprintLoader.add_constructor(
        _tag, lambda loader, node: f"<<{node.tag} {loader.construct_scalar(node)}>>"
    )


def parse_blueprint_inputs(yaml_path: Path) -> dict[str, Any]:
    """Parse a blueprint YAML and extract structured input definitions.

    Returns dict with:
      - inputs: list of input field definitions
      - input_sections: list of collapsed section groups
      - description: blueprint description text
      - name: blueprint display name
      - domain: automation or script
    """
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.load(f, Loader=_BlueprintLoader)  # noqa: S506
    except Exception:
        _LOGGER.exception("Failed to parse blueprint YAML: %s", yaml_path)
        return {"inputs": [], "input_sections": [], "description": "", "name": "", "domain": ""}

    bp = data.get("blueprint", {})
    raw_inputs = bp.get("input", {}) or {}

    inputs: list[dict[str, Any]] = []
    input_sections: list[dict[str, Any]] = []

    for key, value in raw_inputs.items():
        if not isinstance(value, dict):
            continue

        # Check if this is a collapsed section (has nested input:)
        if "input" in value and isinstance(value["input"], dict):
            section_inputs = _parse_section_inputs(value["input"])
            input_sections.append({
                "key": key,
                "name": value.get("name", key),
                "icon": value.get("icon", ""),
                "collapsed": value.get("collapsed", False),
                "input_keys": [inp["key"] for inp in section_inputs],
            })
            inputs.extend(section_inputs)
        else:
            # Direct input field
            inputs.append(_parse_single_input(key, value))

    return {
        "inputs": inputs,
        "input_sections": input_sections,
        "description": bp.get("description", ""),
        "name": bp.get("name", ""),
        "domain": bp.get("domain", "automation"),
    }


def _parse_single_input(key: str, value: dict) -> dict[str, Any]:
    """Parse a single input field definition."""
    selector = value.get("selector", {})
    default = value.get("default")

    # Determine if required (no default = required)
    required = default is None and "default" not in value

    return {
        "key": key,
        "name": value.get("name", key),
        "description": value.get("description", ""),
        "required": required,
        "selector": selector,
        "default": default,
    }


def _parse_section_inputs(section_inputs: dict) -> list[dict[str, Any]]:
    """Parse inputs within a collapsed section."""
    result = []
    for key, value in section_inputs.items():
        if isinstance(value, dict):
            result.append(_parse_single_input(key, value))
    return result
