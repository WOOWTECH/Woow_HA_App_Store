#!/usr/bin/env python3
"""Render the gateway template the way cont-init does, for nginx to read.

`rootfs/etc/cont-init.d/10-odoo-config.sh` substitutes seven placeholders into
`nginx.conf.template` at every container start, and nginx then parses the
result. The budget in `test_nginx_parameter_budget.py` reasons about the file
nginx parses rather than the file a developer edits, and
`test_dual_gateway.py` asserts that the result loads -- so the rendering rule
has to exist once, in one place, or the two tiers measure different files.

This module is that place, and it holds nothing but stdlib on purpose: the
in-image probe (`in_image/gateway_config_loads.py`) imports it inside the
add-on image, where pytest and PyYAML are not installed.

The scenarios are the shapes a real start produces, not invented ones:

  public          `public_url` is set, so a Host map exists and off-LAN
                  callers that miss it get the deny status.
  lanonly         `public_url` is unset. The Host map is empty, so no Host
                  reaches the public tier, and the Canonical URL is the
                  host's LAN address with the published Odoo port.
  lanonly-noaddr  `public_url` is unset and the Supervisor reported no LAN
                  address, so there is no Canonical URL at all and the
                  Runtime shim renders an empty global. nginx has to accept
                  that too (issue #70).

`render` takes the template's *text*, not a path, because the two callers read
it from different places: the Static tier from the repository, the in-image
probe from `/etc/nginx/nginx.conf.template` in the image it is proving.
"""
from __future__ import annotations

from pathlib import Path

# Where the template includes what the Rewrite scan generates. A rendering run
# redirects it into the run's own directory so it never depends on a
# container's /data.
GENERATED_REWRITES = "/data/nginx-generated-rewrites.conf"

# What the Rewrite scan writes for two uncovered navigation prefixes, in the
# byte-for-byte shape generate_include emits (tests/test_literal_rewrite_gate.py).
TWO_PREFIX_INCLUDE = (
    'sub_filter \'"/forum/\' \'"$safe_ingress_path/forum/\';\n'
    'sub_filter "\'/forum/" "\'$safe_ingress_path/forum/";\n'
    'sub_filter \'`/forum/\' \'`$safe_ingress_path/forum/\';\n'
    'sub_filter \'"/livechat/\' \'"$safe_ingress_path/livechat/\';\n'
    'sub_filter "\'/livechat/" "\'$safe_ingress_path/livechat/";\n'
    'sub_filter \'`/livechat/\' \'`$safe_ingress_path/livechat/\';\n'
)

_COMMON = {
    "%%WS_PORT%%": "8070",
    "%%PUBLIC_PROTO%%": "https",
    "%%LAN_NETWORKS%%": "192.168.0.0/16 1; 10.0.0.0/8 1; 172.16.0.0/12 1;",
    "%%INGRESS_CACHE_VERSION%%": "test",
}

SCENARIOS = {
    "public": dict(_COMMON, **{
        "%%PUBLIC_HOST_MAP%%": '"odoo-test.invalid" 1; "odoo-test.invalid:443" 1;',
        "%%DENY_STATUS%%": "444",
        "%%CANONICAL_URL%%": "https://odoo-test.invalid",
    }),
    "lanonly": dict(_COMMON, **{
        "%%PUBLIC_HOST_MAP%%": "",
        "%%DENY_STATUS%%": "503",
        # RFC 5737 documentation address.
        "%%CANONICAL_URL%%": "http://192.0.2.10:8069",
    }),
    "lanonly-noaddr": dict(_COMMON, **{
        "%%PUBLIC_HOST_MAP%%": "",
        "%%DENY_STATUS%%": "503",
        "%%CANONICAL_URL%%": "",
    }),
}


def canonical_url_of(length: int) -> str:
    """A Canonical URL of exactly `length` bytes, in the shape cont-init allows.

    `10-odoo-config.sh` drops a value that is not a bare `http(s)` origin, so a
    probe that wants a long one has to build a long *legal* one: a hostname of
    the characters the shape check permits.
    """
    prefix = "https://"
    assert length > len(prefix) + len(".invalid"), "too short to be an origin"
    filler = "a" * (length - len(prefix) - len(".invalid"))
    value = f"{prefix}{filler}.invalid"
    assert len(value) == length
    return value


def scenario_with_canonical_url(name: str, url: str) -> dict:
    """One of `SCENARIOS` with its Canonical URL replaced."""
    return dict(SCENARIOS[name], **{"%%CANONICAL_URL%%": url})


def render(template: str, test_dir: Path, include_text: str = "", scenarios=None) -> dict:
    """Render every scenario into `test_dir`; return `{name: path}`.

    Four substitutions beyond cont-init's own make the result loadable without
    a container: the Generated rewrite include, the pid and log paths, and the
    three TCP listeners. The listeners become unix sockets inside `test_dir`
    because `nginx -t` opens them, and probing for a free TCP port would race
    every other process on the machine.
    """
    generated = test_dir / "generated-rewrites.conf"
    generated.write_text(include_text, encoding="utf-8")
    rendered = {}
    for name, replacements in (scenarios or SCENARIOS).items():
        config = template
        for placeholder, value in replacements.items():
            assert placeholder in template, f"missing template placeholder: {placeholder}"
            config = config.replace(placeholder, value)
        # cont-init substitutes every placeholder the template carries. One
        # left here is a placeholder nothing fills, which nginx would read as
        # literal text -- so it fails the render rather than the parse.
        assert "%%" not in config, f"unrendered placeholder remains in {name}"
        assert config.count(f"include {GENERATED_REWRITES};") == 1
        config = config.replace(f"include {GENERATED_REWRITES};", f"include {generated};")
        config = config.replace("pid /var/run/nginx.pid;", f"pid {test_dir}/{name}.pid;")
        config = config.replace("error_log /dev/stderr info;", f"error_log {test_dir}/{name}-error.log info;")
        config = config.replace("access_log /dev/stdout safe;", f"access_log {test_dir}/{name}-access.log safe;")
        for original, replacement in [
            ("listen 8069 default_server;", f"listen unix:{test_dir}/{name}-public.sock default_server;"),
            ("listen 8072 default_server;", f"listen unix:{test_dir}/{name}-ws.sock default_server;"),
            ("listen 5691;", f"listen unix:{test_dir}/{name}-ingress.sock;"),
        ]:
            assert config.count(original) == 1, f"expected one listener to replace: {original}"
            config = config.replace(original, replacement)
        path = test_dir / f"nginx-{name}.conf"
        path.write_text(config, encoding="utf-8")
        rendered[name] = path
    return rendered
