"""Fail when mcp-runtime/vendor/ differs from mcp-runtime/VENDOR.json (edited, added or missing files).

Also checks that the hash-pinned wheel lists pin exactly the *.in versions, and that every file_sources entry (a
vendored file taken from another source commit, vendor.sh <file>=<sha>) names a vendored file and a full sha. Run from
the repository root:
    python3 mcp-runtime/tests/verify_vendor.py
"""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'VENDOR.json').read_text())
errors = []
if not re.fullmatch(r'[0-9a-f]{40}', manifest.get('source_commit', '')):
    errors.append('source_commit is not a full sha')
vendor = ROOT / 'vendor'
actual = {str(p.relative_to(vendor)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(vendor.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
expected = manifest.get('files', {})
sources = manifest.get('file_sources', {})
if not isinstance(sources, dict):
    errors.append('file_sources is not an object')
    sources = {}
for name, commit in sorted(sources.items()):
    if name not in expected:
        errors.append('file_sources names a file that is not vendored: ' + name)
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        errors.append('file_sources commit is not a full sha: ' + name)
    elif commit == manifest.get('source_commit'):
        errors.append('file_sources repeats source_commit: ' + name)
for name in sorted(set(actual) | set(expected)):
    if name not in expected:
        errors.append('unlisted vendored file: ' + name)
    elif name not in actual:
        errors.append('missing vendored file: ' + name)
    elif actual[name] != expected[name]:
        errors.append('modified vendored file: ' + name)
for name in ('management', 'child'):
    pins = sorted(line.strip() for line in (ROOT / 'requirements' / (name + '.in')).read_text().splitlines() if line.strip())
    locked = sorted(re.findall(r'^([a-z0-9_.-]+==\S+)', (ROOT / 'requirements' / (name + '.txt')).read_text(), re.M))
    if pins != locked:
        errors.append(name + '.txt does not pin exactly ' + name + '.in')
    if '--hash=sha256:' not in (ROOT / 'requirements' / (name + '.txt')).read_text():
        errors.append(name + '.txt is not hash-pinned')
if errors:
    print('\n'.join(errors), file=sys.stderr)
    sys.exit(1)
print('built-in MCP vendor: %d files match %s' % (len(actual), manifest['source_commit'])
      + ''.join('; %s from %s' % item for item in sorted(sources.items())))
