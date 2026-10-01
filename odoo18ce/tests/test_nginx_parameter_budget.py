#!/usr/bin/env python3
"""The gateway template's quoted parameters fit nginx's token buffer.

nginx reads its configuration a token at a time into a fixed 4096-byte
buffer, so a single quoted parameter longer than that is refused at parse
time with `too long parameter`. The Runtime shim is one such parameter: the
whole prefix script is one single-quoted string in
``map $upstream_http_content_type $ingress_runtime_shim``, and every Issue
that adds a wrapper to it makes that string longer.

Nothing measured that until now. What stood in for a measurement was a
comment: the template said beside ``$ingress_url_global_shim`` that the
script was "~200 bytes short of nginx's 4096-byte parameter buffer" when
#174 wrote it, and later "a few hundred bytes short of" it, while #169,
#210 and the rest spent that margin down to 148. The only thing between
the next addition and a build that will not start was ``nginx -t`` in
``test_dual_gateway.py``, which fails with nginx's own parse error and says
nothing about a budget. Both comments now point here, and
``test_no_comment_states_the_headroom_in_prose`` keeps it that way.

So this file measures it and fails early, with the escape valve in the
message. That valve is the reason the cliff is cheap to step back from:
nginx concatenates variables into a parameter at *runtime*, after parsing,
so moving a part of the script into a ``map`` of its own costs the parameter
only the ~28 bytes of the variable reference while taking hundreds out of
it. ``$ingress_injection_hooks_shim``, ``$ingress_url_global_shim`` and
``$ingress_markup_global_shim`` are each that move already made, and each of
those maps has thousands of bytes free.

The limit is not asserted from the source of nginx: the last test drives a
real nginx with a token at the limit and a token one byte over it, so the
constant here is a measurement. What it measures is the nginx the Static
tier runs -- the one on the runner's PATH, installed from the runner's own
base and not from the image's -- so it pins the constant against a real
nginx without proving it is the one the image ships. A build of nginx with
a different buffer would be caught here only if the Static tier ran that
build; in the image it surfaces on a Deploy, as an add-on that does not
start.
"""
import re
import subprocess
from pathlib import Path

from conftest import require_tool

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
CONT_INIT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"

# The longest token nginx will read, quotes included. Measured against a real
# nginx by `test_the_token_limit_is_the_one_nginx_enforces` below.
TOKEN_LIMIT = 4096

# How close to the limit a parameter may come before this test fails. The
# cliff itself is a parse error nobody can act on without knowing the rule;
# this reserve turns it into a failure one Iteration earlier, while there is
# still room to make the change that was being attempted.
RESERVE = 64

# What `rootfs/etc/cont-init.d/10-odoo-config.sh` substitutes into the
# template before nginx ever reads it, at the longest each value can be --
# because the budget belongs to the file nginx parses and not to the file a
# developer edits. Only placeholders that occur inside a quoted parameter are
# listed: `%%LAN_NETWORKS%%` and `%%PUBLIC_HOST_MAP%%` are bare and expand to
# whole blocks of their own, so they are many tokens and not one.
#
# `%%INGRESS_CACHE_VERSION%%` is the add-on version, or the literal `unknown`
# when `bashio::addon.version` cannot answer; both are shorter than the
# placeholder, so substituting it only ever buys headroom back.
#
# Every entry but one is bounded by what the value can be: a port is five
# digits, a protocol is `https`. The Canonical URL is bounded by nothing of its
# own -- `public_url` is an add-on option, and cont-init's check reads the
# value's shape and not its length -- so cont-init caps it, and
# `test_the_canonical_url_worst_case_is_a_cap_cont_init_keeps` holds the two
# numbers together. A worst case here that nothing enforces there would be this
# file reporting headroom it does not have.
PLACEHOLDER_WORST_CASE = {
    "%%INGRESS_CACHE_VERSION%%": len("unknown"),
    "%%CANONICAL_URL%%": 2048,
    "%%PUBLIC_PROTO%%": len("https"),
    "%%DENY_STATUS%%": len("444"),
    "%%WS_PORT%%": len("65535"),
}

# The parameter this file exists for, named so its failure says which one it
# is before anyone has counted bytes.
SHIM_MAP = "map $upstream_http_content_type $ingress_runtime_shim {"

# The cap cont-init puts on the one value no other rule bounds.
CANONICAL_URL_CAP = re.compile(r"^CANONICAL_URL_MAX=(\d+)$", re.MULTILINE)


def quoted_parameters(text):
    """Every quoted configuration parameter, as ``(line, raw)``.

    ``raw`` is the bytes between the quotes exactly as they sit in the file,
    escapes included, because nginx's buffer holds what it read and not what
    the escapes mean. A quote only opens a string where a token may start,
    which is how nginx reads one too -- so a quote inside a parameter, and
    the `#` of an entity like `&#39;`, are text and not syntax.
    """
    index, line, end = 0, 1, len(text)
    at_token_start = True
    while index < end:
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
            at_token_start = True
        elif char in " \t":
            index += 1
            at_token_start = True
        elif char == "#" and at_token_start:
            newline = text.find("\n", index)
            index = end if newline < 0 else newline
        elif char in "'\"" and at_token_start:
            opened_on, cursor, raw = line, index + 1, []
            while cursor < end:
                here = text[cursor]
                if here == "\\" and cursor + 1 < end:
                    raw.append(text[cursor : cursor + 2])
                    cursor += 2
                    continue
                if here == char:
                    break
                if here == "\n":
                    line += 1
                raw.append(here)
                cursor += 1
            assert cursor < end, f"unterminated quoted parameter opened on line {opened_on}"
            yield opened_on, "".join(raw)
            index = cursor + 1
            at_token_start = False
        else:
            index += 1
            at_token_start = char in "{};("


def rendered_length(raw: str) -> int:
    """The token's length once cont-init has substituted its placeholders."""
    length = len(raw) + 2  # the two quote characters are part of the token
    for placeholder, worst_case in PLACEHOLDER_WORST_CASE.items():
        occurrences = raw.count(placeholder)
        if occurrences:
            length += occurrences * (worst_case - len(placeholder))
    return length


def budgeted_length(raw: str) -> int:
    """What this parameter costs, taking the template and the rendered file.

    A placeholder that shrinks makes the rendered token smaller than the one
    in the template; the larger of the two is the one to budget, so a rule
    stays honest whichever file a future reader measures.
    """
    return max(len(raw) + 2, rendered_length(raw))


def shim_parameter(text: str) -> str:
    """The Runtime shim's prefix script, as the one parameter it is."""
    start = text.index(SHIM_MAP)
    block = text[start : text.index("\n    }", start)]
    for _, raw in quoted_parameters(block):
        if "__INGRESS_PATH__" in raw:
            return raw
    raise AssertionError(f"{SHIM_MAP} has no parameter carrying the prefix script")


def test_every_quoted_parameter_fits_nginx_token_buffer():
    template = TEMPLATE.read_text(encoding="utf-8")
    over = [
        (line, budgeted_length(raw))
        for line, raw in quoted_parameters(template)
        if budgeted_length(raw) > TOKEN_LIMIT
    ]
    assert not over, (
        "a quoted parameter is longer than nginx's "
        f"{TOKEN_LIMIT}-byte token buffer, so nginx refuses the rendered config with "
        "`too long parameter` and the add-on does not start: "
        + ", ".join(f"line {line} is {length} bytes" for line, length in over)
        + ". Move part of it into a `map` of its own and splice that map's variable in "
        "where the text was -- nginx concatenates variables after parsing, so the "
        "reference costs the parameter its own length and nothing more."
    )


def test_the_runtime_shim_keeps_a_reserve_against_the_cliff():
    shim = shim_parameter(TEMPLATE.read_text(encoding="utf-8"))
    length = budgeted_length(shim)
    headroom = TOKEN_LIMIT - length
    assert headroom >= RESERVE, (
        f"the Runtime shim's prefix script is {length} bytes of nginx's "
        f"{TOKEN_LIMIT}-byte token buffer, leaving {headroom} -- under the {RESERVE} this "
        "test holds in reserve, so the next wrapper added to it is the one that stops the "
        "add-on from starting. Before adding anything else, move a part of the script into "
        "a `map` of its own -- `$ingress_injection_hooks_shim`, `$ingress_url_global_shim` "
        "and `$ingress_markup_global_shim` are each that move already made, each with "
        "thousands of bytes free -- and splice the variable in at the end of the IIFE, "
        "where `path` is still in scope. Do not raise the reserve to make this pass."
    )


def test_the_shim_is_the_parameter_worth_watching():
    """The reserve guards the shim because the shim is the one near the cliff.

    If some other parameter ever overtakes it, the reserve above is guarding
    the wrong one and this says so rather than letting it go unnoticed.
    """
    template = TEMPLATE.read_text(encoding="utf-8")
    shim = shim_parameter(template)
    longest = max(budgeted_length(raw) for _, raw in quoted_parameters(template))
    assert budgeted_length(shim) == longest, (
        "the Runtime shim is no longer the longest quoted parameter in the template "
        f"({budgeted_length(shim)} bytes against {longest}); whichever one overtook it "
        "needs the reserve this file holds for the shim."
    )


def test_the_canonical_url_worst_case_is_a_cap_cont_init_keeps():
    """The Canonical URL's worst case is enforced where it is substituted.

    `%%CANONICAL_URL%%` is the only placeholder whose value nothing else
    bounds. `public_url` is an add-on option typed `url?`, and cont-init's
    check at the point of substitution reads the value's shape, not its
    length -- so a long enough origin would pass that check and take the
    rendered parameter over nginx's token buffer, which is the failure this
    whole file exists to catch early. cont-init therefore drops a value over
    the cap the way it drops a misshapen one, and this reads the cap out of
    the script: a number in `PLACEHOLDER_WORST_CASE` that cont-init does not
    enforce is an assumption dressed as a measurement.
    """
    cont_init = CONT_INIT.read_text(encoding="utf-8")
    found = CANONICAL_URL_CAP.search(cont_init)
    assert found, (
        "cont-init must cap the Canonical URL's length in a `CANONICAL_URL_MAX=<n>` "
        "assignment of its own, because PLACEHOLDER_WORST_CASE budgets the nginx "
        "parameter against that number and nothing else bounds the value"
    )
    assert int(found.group(1)) == PLACEHOLDER_WORST_CASE["%%CANONICAL_URL%%"], (
        f"cont-init caps the Canonical URL at {found.group(1)} bytes while this file "
        f"budgets {PLACEHOLDER_WORST_CASE['%%CANONICAL_URL%%']}; the budget is measuring a "
        "cliff that is not where the cap puts it. Change both or neither."
    )
    # The cap has to be applied, not only declared, and applied the way the
    # shape check is: drop the value, warn, let the shim publish nothing.
    assert '[ "${#CANONICAL_URL}" -gt "${CANONICAL_URL_MAX}" ]' in cont_init, (
        "CANONICAL_URL_MAX must be compared against the value's length"
    )
    applied = cont_init.index('[ "${#CANONICAL_URL}" -gt "${CANONICAL_URL_MAX}" ]')
    rendered = cont_init.index("s#%%CANONICAL_URL%%#${CANONICAL_URL}#g")
    assert applied < rendered, "the cap must be applied before the value is rendered"


def test_the_token_limit_is_the_one_nginx_enforces(tmp_path: Path):
    """A token at `TOKEN_LIMIT` parses and one byte more does not.

    The constant is a measurement, not a reading of nginx's source. It is a
    measurement of the nginx on this runner's PATH, which is the Static
    tier's and not the image's -- see the limit of that in this file's
    docstring.
    """
    nginx = require_tool("nginx")

    def parses(token_length: int) -> bool:
        body = "x" * (token_length - 2)  # the quotes are part of the token
        root = tmp_path / str(token_length)
        root.mkdir()
        config = root / "probe.conf"
        # The pid and the error log go inside the temporary directory: `nginx
        # -t` writes both, and the packaged defaults are paths the test user
        # cannot open, which would fail the probe for a reason that is not
        # the one it is measuring.
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
        result = subprocess.run(
            [nginx, "-t", "-p", str(root), "-c", str(config)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
        assert "too long parameter" in result.stderr, (
            f"a {token_length}-byte token failed for a reason that is not its length: "
            f"{result.stderr.strip()}"
        )
        return False

    assert parses(TOKEN_LIMIT), (
        f"this nginx refuses a {TOKEN_LIMIT}-byte token, so TOKEN_LIMIT is too high and "
        "every budget in this file is measured against a cliff that is nearer than it says"
    )
    assert not parses(TOKEN_LIMIT + 1), (
        f"this nginx accepts a {TOKEN_LIMIT + 1}-byte token, so TOKEN_LIMIT is too low and "
        "this file is refusing parameters nginx would have taken"
    )


def test_no_comment_states_the_headroom_in_prose():
    """The margin is stated where it is measured, and nowhere else.

    The comment beside `$ingress_url_global_shim` said the script was "~200
    bytes short of nginx's 4096-byte parameter buffer" when #174 wrote it,
    then "a few hundred bytes short of" it -- and went on saying so through
    the Issues that spent that margin down to the double digits. A number in
    a comment is read as a measurement and nothing makes it one, so the
    template points at this file instead of carrying a figure of its own.
    """
    template = TEMPLATE.read_text(encoding="utf-8")
    claims = [
        line.strip()
        for line in template.splitlines()
        if re.search(r"short of .*(buffer|4096)|bytes? short of", line)
    ]
    headroom = TOKEN_LIMIT - budgeted_length(shim_parameter(template))
    assert not claims, (
        "a comment in the template states how much of nginx's token buffer is left: "
        + " | ".join(claims)
        + f". The measurement is {headroom} bytes and it lives in "
        f"{Path(__file__).name}; say 'see that file' in the comment rather than a figure "
        "that goes stale the next time the shim grows."
    )
