"""Shared helpers for running the add-on's production nginx.conf in tests."""

from __future__ import annotations

from pathlib import Path


def replace_once(config: str, old: str, new: str) -> str:
    assert config.count(old) == 1, f"expected one config seam: {old}"
    return config.replace(old, new)


MIME_INCLUDE = "include /etc/nginx/mime.types;"
FALLBACK_MIME_TYPES = """types {
    text/html html;
    text/css css;
    application/javascript js;
    image/png png;
}
"""


def portable_nginx(config: str, tmp: Path) -> str:
    """Run the production config from any nginx build without root paths.

    Uses the distribution mime.types when present (else a minimal table) and
    keeps nginx's temporary files inside the test directory.
    """
    if not Path("/etc/nginx/mime.types").exists():
        fallback = tmp / "mime.types"
        fallback.write_text(FALLBACK_MIME_TYPES)
        config = replace_once(config, MIME_INCLUDE, f"include {fallback};")
    temp_paths = "".join(
        f"    {kind}_temp_path {tmp / (kind + '_temp')};\n"
        for kind in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi")
    )
    return replace_once(config, "http {\n", "http {\n" + temp_paths)
