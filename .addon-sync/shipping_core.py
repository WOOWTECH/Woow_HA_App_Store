"""The Store copy of the shipping Core version (#217) and the HA Core version parser. Standard library only: the upgrade
comparison (upgrade_check.py) and the mock Supervisor (mock_supervisor.py, #225) both read it, and the mock runs in a
python:3.12-alpine container without PyYAML.

The Store keeps a copy of the shipping Core version (woow_ha_version_control's ha-core.json, private, so the Store CI
cannot read it) in SHIPPING_CORE, {"version": "YYYY.M.P"}; woow_ha_version_control's drift check fails when this copy is
newer than ha-core.json. Read it with shipping_core_version(): the Core requirement check (#217), the HA Core version the
mock Supervisor reports and the test HA Core image's tag (#225) all follow it.
"""
from __future__ import annotations
import json, pathlib, re

SHIPPING_CORE=pathlib.Path(__file__).resolve().with_name('shipping-core.json')
_CALVER=re.compile(r'(\d{4})\.(\d{1,2})\.(\d+)')

def calver(text, what):
    """(year, month, patch) of an HA Core version YYYY.M.P, compared part by part as numbers. A ValueError naming `what`
    for anything else (a beta, YYYY.M, or a number YAML read from an unquoted 2026.10, which would be 2026.1)."""
    m=_CALVER.fullmatch(text) if isinstance(text,str) else None
    if not m:raise ValueError(f'{what} is {text!r}, not an HA Core version YYYY.M.P (quote it in YAML)')
    return tuple(int(x) for x in m.groups())

def shipping_core_version(path=SHIPPING_CORE):
    """The shipping Core version the Store keeps (SHIPPING_CORE's `version`), checked to be YYYY.M.P; a ValueError when the
    file cannot be read or parsed, so the upgrade comparison never passes on a broken copy."""
    try:data=json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError) as e:raise ValueError(f'the Store copy of the shipping Core version ({pathlib.Path(path).name}) cannot be read: {e}') from None
    version=data.get('version') if isinstance(data,dict) else None
    calver(version,f'the Store copy of the shipping Core version ({pathlib.Path(path).name})')
    return version
