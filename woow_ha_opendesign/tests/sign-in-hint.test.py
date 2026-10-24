#!/usr/bin/env python3
"""ha-patches/sign-in-hint.py: replaces the core's PaaS sign-in hints exactly once and fails closed."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ha-patches/sign-in-hint.py"
spec = importlib.util.spec_from_file_location("sign_in_hint", SCRIPT)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


def chunk(entries):
    return "".join('{"chat.runError.signInMessage.other":"%s","x":1};' % text for text in entries)


def run(files):
    with tempfile.TemporaryDirectory() as out:
        chunks = Path(out, "_next/static/chunks")
        chunks.mkdir(parents=True)
        for name, text in files.items():
            (chunks / name).write_text(text, encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), out], capture_output=True, text=True)
        return result, {p.name: p.read_text(encoding="utf-8") for p in chunks.iterdir()}


core = [old for _, old, _ in patch.EDITS]
ha = [new for _, _, new in patch.EDITS]
others = ["Connectez-vous d’abord à {agent}, puis réessayez."]

result, files = run({"i18n.js": chunk(core + others), "other.js": "console.log(1);", "i18n.js.map": chunk(core)})
check(result.returncode == 0, f"core chunk must patch cleanly: {result.stderr}")
check(files["i18n.js"] == chunk(ha + others), "every core hint must become the HA text, other locales untouched")
check(files["i18n.js.map"] == chunk(core), "source maps are not executed and must stay untouched")
check(all(any(name in text for name in ("CLI 終端機", "CLI 终端", "CLI Terminal")) for text in ha), "HA hints must name the built-in CLI Terminal plugin")
check(not any(bad in text for text in ha for bad in patch.FORBIDDEN), "HA hints must not keep PaaS-only wording")
check("「外掛」頁" in ha[0] and "「CLI 終端機」" in ha[0] and "/login" in ha[0], "zh-TW hint must point at 外掛 → CLI 終端機 and claude /login")

result, _ = run({"i18n.js": chunk(core[1:])})
check(result.returncode != 0 and "zh-TW" in result.stderr, "a missing core text must fail the build")
result, _ = run({"a.js": chunk(core), "b.js": chunk(core[:1])})
check(result.returncode != 0, "an ambiguous core text (two matches) must fail the build")
result, _ = run({"i18n.js": chunk(core), "help.js": '"x":"請在本服務網址後加上 /console/"'})
check(result.returncode != 0 and "網址後加上" in result.stderr, "remaining PaaS wording must fail the build")
result, _ = run({"i18n.js": chunk(core), "plugin.js": '"path":"/console/"'})
check(result.returncode == 0, "the /console/ path itself (the CLI Terminal plugin) is allowed")

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("sign-in hint patch: OK")
