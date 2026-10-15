#!/usr/bin/env python3
"""Check the ingress rewrites against the editor bundle n8n actually serves.

The ingress nginx rewrites a few literal strings in n8n's responses. Those
strings come from n8n's build output, so every n8n upgrade must prove they
still exist where the rewrite expects them, and nowhere else.

Usage: test-ingress-bundle-seam.py <public-dir>

<public-dir> is n8n's processed static directory copied out of a running
add-on container (``/root/.cache/n8n/public``), i.e. the files with the
``{{BASE_PATH}}`` placeholders already resolved for the root path.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parents[1]
NGINX_CONFIG = ADDON_DIR / "rootfs/etc/nginx/nginx.conf"

ROOT_BUILDER_BODY = "function(e){return`/`+e}"
PREFIX_BUILDER_BODY = "function(e){return(window.BASE_PATH||`/`)+e}"
BASE_PATH_ASSIGNMENT = "window.BASE_PATH = '/';"
# Vite's preload helper: `<a>=`modulepreload`,<b>=function(e){return`/`+e}`.
PRELOAD_HELPER = re.compile(
    r"[A-Za-z_$][\w$]*=`modulepreload`,[A-Za-z_$][\w$]*="
    + re.escape(ROOT_BUILDER_BODY)
)
TEXT_SUFFIXES = {".js", ".mjs", ".css", ".html"}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    public = Path(sys.argv[1])
    files = [
        path
        for path in sorted(public.rglob("*"))
        if path.is_file() and path.suffix in TEXT_SUFFIXES
    ]
    assert files, f"no editor assets under {public}"
    texts = {path: path.read_text(errors="replace") for path in files}

    nginx = NGINX_CONFIG.read_text()
    assert (
        f"sub_filter '{ROOT_BUILDER_BODY}' '{PREFIX_BUILDER_BODY}';" in nginx
    ), "nginx no longer carries the preload builder rewrite this test checks"

    builder_hits = {
        str(path.relative_to(public)): text.count(ROOT_BUILDER_BODY)
        for path, text in texts.items()
        if ROOT_BUILDER_BODY in text
    }
    assert sum(builder_hits.values()) == 1, (
        "the preload URL builder must occur exactly once in the served bundle "
        f"(found {builder_hits}); review the ingress rewrite before upgrading"
    )
    helper_hits = [
        str(path.relative_to(public))
        for path, text in texts.items()
        if PRELOAD_HELPER.search(text)
    ]
    assert helper_hits == list(builder_hits), (
        "the only root builder is not Vite's preload helper: "
        f"builder in {builder_hits}, helper in {helper_hits}"
    )

    base_path_hits = [
        str(path.relative_to(public))
        for path, text in texts.items()
        if BASE_PATH_ASSIGNMENT in text
    ]
    assert base_path_hits, (
        f"no response assigns {BASE_PATH_ASSIGNMENT!r}; the ingress prefix "
        "would never reach window.BASE_PATH"
    )

    index = public / "index.html"
    assert index.is_file(), "index.html missing from the served bundle"
    html = texts[index]
    assert "</head>" in html, "index.html has no </head> for the ingress shim"
    assert 'href="/' in html and 'src="/' in html, (
        "index.html no longer uses root-absolute asset URLs"
    )

    print(
        "ingress bundle seam test passed: preload builder unique in "
        f"{helper_hits[0]}, BASE_PATH assigned in {base_path_hits}, "
        f"{len(files)} served text assets scanned"
    )


if __name__ == "__main__":
    main()
