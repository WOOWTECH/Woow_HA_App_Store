#!/usr/bin/env python3
"""The shipped gateway config loads under the image's own nginx.

Run inside the built add-on image, with the repository's `tests/` mounted:

    docker run --rm -v "$PWD/odoo18ce/tests:/tests:ro" \\
      --entrypoint python3 woow-ha-odoo-amd64:ci /tests/in_image/gateway_config_loads.py

The Static tier already renders `nginx.conf.template` and runs `nginx -t` on
the result (`test_dual_gateway.py`), and budgets every quoted parameter against
nginx's fixed token buffer (`test_nginx_parameter_budget.py`). Both use the nginx
on the runner's PATH, which comes from the runner's base image and not from
this one. So neither can say that the config the add-on actually ships loads
under the nginx the add-on actually ships, and neither can say that this
nginx's token buffer is the size the budget assumes. A difference would have
surfaced on a Deploy, as an add-on that does not start.

Three things are checked here, in the image, against `/usr/sbin/nginx`:

1. The token buffer is `TOKEN_LIMIT` bytes -- a token at the limit parses and
   one byte more does not. This is the budget's constant, pinned to this nginx.
2. Every rendered scenario loads, for an empty Generated rewrite file and for
   a populated one.
3. A Canonical URL of exactly `CANONICAL_URL_MAX` bytes -- the cap
   `10-odoo-config.sh` applies, and the worst case the budget assumes -- still
   loads, and one far over the cliff does not. The second half is also what
   shows this probe can go red.

Every number comes from the file that owns it: `TOKEN_LIMIT` out of the budget
test, `CANONICAL_URL_MAX` out of the shipped cont-init script. A probe with its
own copies would agree with itself while the add-on disagreed.

Output is one `gateway-config: ...` line per result, and a non-zero exit on the
first failure. Nothing is written outside a temporary directory, no database,
Supervisor or credential is read, and no listener binds a TCP port.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path("/tests")
sys.path.insert(0, str(TESTS))

import gateway_render  # noqa: E402  (the mount is the import path)

NGINX = "/usr/sbin/nginx"
TEMPLATE = Path("/etc/nginx/nginx.conf.template")
CONT_INIT = Path("/etc/cont-init.d/10-odoo-config.sh")
BUDGET_TEST = TESTS / "test_nginx_parameter_budget.py"

# How far over the cliff the negative case goes. Any value that takes the
# parameter past the buffer will do; this one is far enough that it does not
# depend on how long the rest of the parameter is.
WAY_OVER = 3


def fail(message: str) -> None:
    print(f"gateway-config: FAIL {message}")
    raise SystemExit(1)


def read_number(path: Path, pattern: str, what: str) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"{what} is not readable in the image ({error})")
    found = re.search(pattern, text, re.MULTILINE)
    if not found:
        fail(f"{what} does not state {pattern!r}")
    return int(found.group(1))


def nginx_t(prefix: Path, config: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NGINX, "-t", "-p", str(prefix), "-c", str(config)],
        capture_output=True, text=True, check=False,
    )


def parses_token(work: Path, token_length: int) -> bool:
    """Whether this nginx reads a quoted token of `token_length` bytes."""
    root = work / f"token-{token_length}"
    root.mkdir()
    config = root / "probe.conf"
    body = "x" * (token_length - 2)  # the quotes are part of the token
    config.write_text(
        f"pid {root}/nginx.pid;\n"
        f"error_log {root}/error.log;\n"
        "events {}\n"
        "http {\n"
        "    access_log off;\n"
        "    map $http_host $probe {\n"
        f"        default '{body}';\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return nginx_t(root, config).returncode == 0


def main() -> None:
    if not Path(NGINX).exists():
        fail(f"{NGINX} is not in the image")
    version = subprocess.run([NGINX, "-v"], capture_output=True, text=True, check=False)
    print(f"gateway-config: image nginx is {(version.stderr or version.stdout).strip()}")

    token_limit = read_number(BUDGET_TEST, r"^TOKEN_LIMIT = (\d+)$", "the budget test")
    cap = read_number(CONT_INIT, r"^CANONICAL_URL_MAX=(\d+)$", "the shipped cont-init script")
    template = TEMPLATE.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)

        # 1. The buffer this nginx has, against the one the budget assumes.
        if not parses_token(work, token_limit):
            fail(f"this nginx refuses a {token_limit}-byte token, so the budget's TOKEN_LIMIT is "
                 f"larger than the buffer the image's nginx has; every parameter the Static tier "
                 f"passed may be over the real cliff")
        if parses_token(work, token_limit + 1):
            fail(f"this nginx accepts a {token_limit + 1}-byte token, so its buffer is larger than "
                 f"the budget's TOKEN_LIMIT; the budget is holding a reserve against the wrong "
                 f"number")
        print(f"gateway-config: token buffer is {token_limit} bytes, as the budget assumes")

        # 2. The shipped template, rendered as cont-init renders it.
        for variant, include_text in (("empty", ""), ("two-prefix", gateway_render.TWO_PREFIX_INCLUDE)):
            variant_dir = work / variant
            variant_dir.mkdir()
            for name, config in gateway_render.render(template, variant_dir, include_text).items():
                result = nginx_t(variant_dir, config)
                if result.returncode != 0:
                    fail(f"the shipped template does not load in the image "
                         f"({variant}/{name}):\n{result.stderr}")
            print(f"gateway-config: shipped template loads for every scenario ({variant} rewrites)")

        # 3. The Canonical URL cap, which is the budget's worst case.
        for length, must_load in ((cap, True), (token_limit * WAY_OVER, False)):
            case = work / f"canonical-{length}"
            case.mkdir()
            scenario = gateway_render.scenario_with_canonical_url(
                "public", gateway_render.canonical_url_of(length)
            )
            config = gateway_render.render(
                template, case, scenarios={"public": scenario}
            )["public"]
            loaded = nginx_t(case, config).returncode == 0
            if must_load and not loaded:
                fail(f"a Canonical URL of {length} bytes -- the cap cont-init applies, and the "
                     f"worst case the budget assumes -- does not load in the image; the budget is "
                     f"measuring a cliff that is nearer than it reports")
            if not must_load and loaded:
                fail(f"a Canonical URL of {length} bytes loads, so this probe cannot go red and "
                     f"the token buffer is not bounding the parameter at all")
        print(f"gateway-config: a {cap}-byte Canonical URL loads and a "
              f"{token_limit * WAY_OVER}-byte one is refused")

    print("gateway-config: ok")


if __name__ == "__main__":
    main()
