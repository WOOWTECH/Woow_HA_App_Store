#!/usr/bin/env python3
"""Hash-guarded Omnigent 0.16.0 shared-tools compatibility patch.

Run at image build with that runtime's Python, never against the session host.
The generated changes only activate when WOOW_OMNIGENT_SHARED_TOOLS=1.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sysconfig

HASHES = {
    "inner/codex_executor.py": "aa4ccd1220ae5a287411868d05c5e69c2d40d0db1907ee3889bdb76a350f49dd",
    "inner/pi_settings.py": "5f93e9acd0923898a65817b3828cb6b7d47f30cbf99cfd8643d672086e60f157",
    "harnesses/pi_native/credentials.py": "371b3d604a26d5e1e64bb75fcc99d29b10a1c601edc596ea48ee32e6198d23c5",
}
MARKER = "WOOW_SHARED_TOOLS_V1"


def replace_once(source, anchor, replacement):
    if source.count(anchor) != 1:
        raise ValueError("Omnigent patch anchor changed")
    return source.replace(anchor, replacement, 1)


def transformed(name, source):
    if name == "inner/codex_executor.py":
        return replace_once(source,
            '    Path("rules"),\n)\n_CODEX_MINIMAL_CONFIG_ENV',
            '    Path("rules"),\n    # WOOW_SHARED_TOOLS_V1: keep skills in each private native session.\n'
            '    *((Path("skills"),) if os.environ.get("WOOW_OMNIGENT_SHARED_TOOLS") == "1" else ()),\n'
            ')\n_CODEX_MINIMAL_CONFIG_ENV')
    if name == "harnesses/pi_native/credentials.py":
        return replace_once(source,
            '    for provider_id, payload in _read_json_object(root / "models-store.json").items():\n',
            '    catalog = _read_json_object(root / "models-store.json")\n'
            '    # WOOW_SHARED_TOOLS_V1: include authenticated custom Pi providers.\n'
            '    if os.environ.get("WOOW_OMNIGENT_SHARED_TOOLS") == "1":\n'
            '        custom = _read_json_object(root / "models.json").get("providers")\n'
            '        if _is_str_object_dict(custom):\n'
            '            for provider_id, payload in custom.items():\n'
            '                if not _is_str_object_dict(payload):\n'
            '                    continue\n'
            '                models = payload.get("models")\n'
            '                if not isinstance(models, list):\n'
            '                    continue\n'
            '                original = catalog.get(provider_id)\n'
            '                existing = original.get("models") if _is_str_object_dict(original) else None\n'
            '                catalog[provider_id] = {"models": (existing if isinstance(existing, list) else []) + models}\n'
            '    for provider_id, payload in catalog.items():\n')
    if name != "inner/pi_settings.py":
        raise ValueError("Unknown Omnigent patch target: " + name)
    source = replace_once(source, 'import logging\n', 'import logging\nimport os\n')
    source = replace_once(source,
        '    agent_root = global_agent_dir if global_agent_dir is not None else DEFAULT_PI_AGENT_DIR\n',
        '    agent_root = global_agent_dir if global_agent_dir is not None else DEFAULT_PI_AGENT_DIR\n'
        '    # WOOW_SHARED_TOOLS_V1: the deployment root can differ from ~/.pi/agent.\n'
        '    if global_agent_dir is None and os.environ.get("WOOW_OMNIGENT_SHARED_TOOLS") == "1":\n'
        '        agent_root = Path(os.environ.get("PI_CODING_AGENT_DIR") or DEFAULT_PI_AGENT_DIR)\n')
    return replace_once(source,
        '    _symlink_agent_resource_dirs(managed_dir, agent_root)\n',
        '    _symlink_agent_resource_dirs(managed_dir, agent_root)\n'
        '    if os.environ.get("WOOW_OMNIGENT_SHARED_TOOLS") == "1":\n'
        '        for name in ("skills", "extensions", "prompts", "mcp.json"):\n'
        '            source, target = agent_root / name, managed_dir / name\n'
        '            if not source.exists() or source.resolve() == target.resolve():\n'
        '                continue\n'
        '            if target.exists() or target.is_symlink():\n'
        '                raise ValueError("Managed Pi shared-tools path conflicts: " + name)\n'
        '            target.symlink_to(source.resolve(), target_is_directory=source.is_dir())\n')


def patch(site_packages):
    package = Path(site_packages) / "omnigent"
    receipt_path = package / ".woow-shared-tools-v1.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    prepared = []
    for name, expected in HASHES.items():
        file = package / name
        raw = file.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        source = raw.decode()
        if MARKER in source:
            if receipt.get(name, {}).get("original") != expected or receipt.get(name, {}).get("patched") != actual:
                raise ValueError("Omnigent patched source receipt mismatch: " + name)
            continue
        if actual != expected:
            raise ValueError("Omnigent 0.16.0 source hash changed: " + name)
        replacement = transformed(name, source)
        compile(replacement, str(file), "exec")
        prepared.append((file, replacement))
        receipt[name] = {"original": expected, "patched": hashlib.sha256(replacement.encode()).hexdigest()}
    for file, replacement in prepared:
        file.write_text(replacement)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-packages", default=sysconfig.get_paths()["purelib"])
    args = parser.parse_args()
    if importlib.metadata.version("omnigent") != "0.16.0":
        raise SystemExit("Only Omnigent 0.16.0 is supported")
    patch(args.site_packages)
    print("WOOW_SHARED_TOOLS_V1 applied")
