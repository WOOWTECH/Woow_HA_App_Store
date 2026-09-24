#!/usr/bin/env python3
"""Contracts for the links Odoo builds in the browser (issue #70, ADR 0006).

Some Odoo 18 links are absolute addresses assembled in the page, from whatever
is in the address bar, for somebody outside to open. Through Ingress that
address is the Home Assistant host: the Discuss invitation link and the
website page URL field show a host the recipient cannot use, and the website
share snippet hands the social network the Supervisor token along with it. The
lock the maintenance bootstrap puts on ``web.base.url`` cannot reach any of
them, because these values never pass through the server.

The Runtime shim publishes the Canonical URL as ``__WOOW_CANONICAL_URL__``
(``test_ingress_canonical_url_global.py``), and one exact-expression Literal
rewrite moves each link onto that base. What is pinned here:

- **The rewrite matches the bundle.** An unmatched ``sub_filter`` is a silent
  no-op, so every pattern is checked against bytes captured from a bundle the
  control group actually serves, kept under ``fixtures/bundles/``.
- **The rewritten expression behaves.** Each one is executed in node, with a
  Canonical URL and without one, and compared against the same expression
  before the rewrite -- so a rule that changes nothing fails rather than
  passes quietly.
- **Ingress only.** ``ingress_rule`` refuses a rule found outside the Ingress
  asset location, which would change what the Public origin serves.
"""
import json
import subprocess
from pathlib import Path

import pytest

from test_ingress_router_rewrite import TEMPLATE, ingress_rule

FIXTURES = Path(__file__).resolve().parent / "fixtures/bundles"

# Documentation addresses only (RFC 2606); no real host here.
CANONICAL = "https://odoo.example.test"
HA_ORIGIN = "https://ha.example.test"
INGRESS_PREFIX = "/api/hassio_ingress/token"

# Each link: the fixture it was measured in, the exact expression the Ingress
# asset location rewrites, the slice of the fixture that can be executed, and
# a driver that turns that slice into the value a user would see.
LINKS = {
    "Discuss invitation link": {
        "fixture": "discuss_invitation_link.js",
        "source": "window.location.origin}/chat/",
        "slice": ("get invitationLink(){", "get isEmpty(){"),
        "driver": (
            "class Thread{constructor(d){Object.assign(this,d)}\n"
            "__SLICE__\n"
            '}\nresult=new Thread({id:2,uuid:"6f3a",channel_type:"channel"}).invitationLink;'
        ),
        "before": HA_ORIGIN + "/chat/2/6f3a",
        "after": CANONICAL + "/chat/2/6f3a",
    },
    "Website page URL field": {
        "fixture": "website_page_url_field.js",
        "source": "window.location.origin}/`;",
        "slice": ("this.serverUrl=", "this.inputRef="),
        "driver": "function f(){__SLICE__\nreturn this.serverUrl}\nresult=f.call({});",
        "before": HA_ORIGIN + "/",
        "after": CANONICAL + "/",
    },
    "Website share snippet": {
        "fixture": "website_share_snippet.js",
        "source": "const currentUrl=window.location.href;",
        "slice": ("const currentUrl=", "const urlParamFound="),
        "driver": "function f(){__SLICE__\nreturn currentUrl}\nresult=f();",
        # Today the share snippet posts the Ingress token to the social
        # network along with the address; that is what the rewrite removes.
        "before": HA_ORIGIN + INGRESS_PREFIX + "/shop/lamp?utm=x#reviews",
        "after": CANONICAL + "/shop/lamp?utm=x#reviews",
        # The one rewrite that does not simply keep today's behaviour when
        # there is no Canonical URL: the link stays on the browser origin, as
        # broken as it was, but the Supervisor token is gone. Handing a token
        # to a third party is not a behaviour worth preserving.
        "empty": HA_ORIGIN + "/shop/lamp?utm=x#reviews",
    },
}

HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");

for (const { name, scenario, program, expected } of JSON.parse(process.argv[1])) {
  const window = {
    __WOOW_CANONICAL_URL__: scenario.canonical,
    location: {
      origin: scenario.origin,
      pathname: scenario.pathname,
      search: scenario.search,
      hash: scenario.hash,
      href: scenario.origin + scenario.pathname + scenario.search + scenario.hash,
    },
  };
  const context = vm.createContext({ window, result: undefined });
  vm.runInContext(program, context);
  assert.equal(context.result, expected, `${name} (${scenario.label})`);
}
"""

SCENARIO = {
    "label": "under Ingress",
    "canonical": CANONICAL,
    "origin": HA_ORIGIN,
    "pathname": INGRESS_PREFIX + "/shop/lamp",
    "search": "?utm=x",
    "hash": "#reviews",
}
NO_CANONICAL = dict(SCENARIO, label="under Ingress with no Canonical URL", canonical="")


def fixture(link: dict) -> str:
    return (FIXTURES / link["fixture"]).read_text(encoding="utf-8")


def runnable(text: str, link: dict) -> str:
    """The part of the fixture that can be executed, between its two anchors."""
    start, end = link["slice"]
    first = text.index(start)
    return text[first : text.index(end, first)]


def program(link: dict, text: str) -> str:
    return link["driver"].replace("__SLICE__", runnable(text, link))


def rewritten(link: dict) -> str:
    """The fixture as the Ingress asset location serves it."""
    template = TEMPLATE.read_text(encoding="utf-8")
    replacement = ingress_rule(template, link["source"], link["fixture"])
    assert "__WOOW_CANONICAL_URL__" in replacement, (
        "the rewrite must take its base from the global the Runtime shim publishes"
    )
    return fixture(link).replace(link["source"], replacement)


def run(cases: list[dict]) -> None:
    from conftest import require_tool

    result = subprocess.run(
        [require_tool("node"), "-e", HARNESS, json.dumps(cases)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("name", LINKS)
def test_the_rewrite_matches_the_bundle_exactly_once(name: str) -> None:
    """A pattern that does not match is a silent no-op, so measure it."""
    link = LINKS[name]
    text = fixture(link)
    assert text.count(link["source"]) == 1, (
        f"{name}: the captured bundle holds {text.count(link['source'])} occurrences of "
        f"{link['source']!r}; re-capture the fixture and re-measure the rewrite"
    )


@pytest.mark.parametrize("name", LINKS)
def test_the_link_carries_the_home_assistant_host_without_the_rewrite(name: str) -> None:
    """The starting point: the bundle as Odoo ships it, run under Ingress."""
    link = LINKS[name]
    run([{
        "name": name,
        "scenario": SCENARIO,
        "program": program(link, fixture(link)),
        "expected": link["before"],
    }])


@pytest.mark.parametrize("name", LINKS)
def test_the_rewrite_moves_the_link_onto_the_canonical_url(name: str) -> None:
    link = LINKS[name]
    run([{
        "name": name,
        "scenario": SCENARIO,
        "program": program(link, rewritten(link)),
        "expected": link["after"],
    }])


@pytest.mark.parametrize("name", LINKS)
def test_without_a_canonical_url_the_link_keeps_the_browser_origin(name: str) -> None:
    """Ingress-only with no LAN address: every rewrite keeps the browser origin.

    That is today's behaviour for two of the three. The share snippet also
    drops the Ingress prefix, because the alternative is posting a Supervisor
    token to a social network; its `empty` value says so.
    """
    link = LINKS[name]
    expected = link.get("empty", link["before"])
    assert expected.startswith(HA_ORIGIN), "the fallback must stay on the browser origin"
    run([{
        "name": name,
        "scenario": NO_CANONICAL,
        "program": program(link, rewritten(link)),
        "expected": expected,
    }])


def test_the_share_snippet_never_publishes_the_token_even_without_a_canonical_url() -> None:
    """The reason the share snippet is allowed to differ from today's behaviour."""
    link = LINKS["Website share snippet"]
    assert INGRESS_PREFIX in link["before"], "today's link carries the token"
    assert INGRESS_PREFIX not in link["empty"], "the rewritten one must not, with or without a base"
    run([{
        "name": "Website share snippet",
        "scenario": NO_CANONICAL,
        "program": program(link, rewritten(link)),
        "expected": link["empty"],
    }])


def test_the_share_snippet_no_longer_publishes_the_ingress_token() -> None:
    """The one link of the three that leaks rather than merely misdirects."""
    link = LINKS["Website share snippet"]
    assert INGRESS_PREFIX in link["before"], "the fixture scenario must be a real Ingress URL"
    assert INGRESS_PREFIX not in link["after"]
    run([{
        "name": "Website share snippet",
        "scenario": SCENARIO,
        "program": program(link, rewritten(link)),
        "expected": link["after"],
    }])


def test_every_rewrite_is_ingress_only() -> None:
    """A rule on the 8069 listener would change the links the Public origin serves."""
    template = TEMPLATE.read_text(encoding="utf-8")
    for name, link in LINKS.items():
        ingress_rule(template, link["source"], name)
