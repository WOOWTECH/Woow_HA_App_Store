"""Store sidebar-only policy; never rename apps or change their identifiers.

Apply after upstream rsync, including release-pinned sources. This lets a sidebar
metadata correction ship without retagging an application image or modifying an
existing upstream Release. Run with --check in CI, or with directory names after
sync. No arguments applies all entries.
"""
import argparse
from pathlib import Path
import re

TITLES = {
    "n8n": "n8n",
    "omnigent": "Omnigent",
    "odoo18ce": "Odoo",
    "woow-nextcloud-office": "Nextcloud Office",
    "woow-tailscale": "Tailscale",
    "woow-lan-gateway": "LAN Gateway",
    "woow-hermes": "Hermes",
}
ROOT = Path(__file__).resolve().parents[2]


def normalize(text, title):
    pattern = r"(?m)^panel_title:[^\n]*$"
    matches = list(re.finditer(pattern, text))
    if len(matches) > 1:
        raise ValueError("Duplicate panel_title")
    if matches:
        return re.sub(pattern, "panel_title: " + title, text)
    if not re.search(r"(?m)^ingress: true\s*$", text):
        raise ValueError("Refusing to add a sidebar title without ingress")
    return text.replace("ingress: true\n", "ingress: true\npanel_title: " + title + "\n", 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("directories", nargs="*")
    args = parser.parse_args()
    dirty = []
    for directory in args.directories or TITLES:
        if directory not in TITLES:
            continue
        path = ROOT / directory / "config.yaml"
        before = path.read_text()
        after = normalize(before, TITLES[directory])
        if before != after:
            dirty.append(directory)
            if not args.check:
                path.write_text(after)
    if args.check and dirty:
        raise SystemExit("Sidebar title policy mismatch: " + ", ".join(dirty))


if __name__ == "__main__":
    main()
