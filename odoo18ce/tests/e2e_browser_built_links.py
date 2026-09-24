#!/usr/bin/env python3
"""Live tier: links Odoo builds in the browser carry the Canonical URL (issue #70).

Some Odoo 18 links are absolute addresses assembled in the page, from whatever
is in the address bar, for somebody outside to open. Through Ingress that
address is the Home Assistant host, and the lock on ``web.base.url`` cannot
reach them because the value never passes through the server. ADR 0006 has the
Runtime shim publish the Canonical URL and moves each link onto it with one
exact-expression Literal rewrite.

``test_ingress_browser_built_links.py`` pins those rewrites against captured
bundle bytes. This is the other half: it reads what a running add-on serves.

Three surfaces, and they cost different things to run:

``ingress``
    Opens the add-on through a Home Assistant entrance in a browser and reads
    the invitation link out of the *Invite People* panel -- the value a person
    actually sees. Needs Home Assistant and Odoo credentials. Run it once per
    entrance, the plain http LAN address and the https one, because the
    browser origin differs and only one of them is a secure context.

``public``
    Fetches the same bundles from the Public origin and refuses to find the
    rewrites there, so they stay where the Ingress listener put them.

``supervisor``
    Asks the Supervisor container to fetch the Ingress pages and executes each
    rewritten expression in node. **It needs no credentials at all**: the
    asset route and the login page are both public, and the Ingress listener
    accepts only the Supervisor, which is why the request is made from inside
    that container over ssh. It cannot see the rendered panel, so it proves
    the expression rather than the pixel -- which is the half that survives
    when nobody wants to put credentials on the machine running the check.

What every surface is looking for is the same failure: an unmatched
``sub_filter`` is a silent no-op, so the link is simply wrong and nothing
turns red on its own.

Environment, the same names as the other Live tests:

    ODOO_PUBLIC_URL      the Public origin, which is the expected Canonical URL
                         (required by every surface)
    ADDON_SLUG           the add-on to open; a host may run more than one

    ingress:
    HA_BASE_URL          the Home Assistant entrance under test
    HA_TEST_USER         Home Assistant login
    HA_TEST_PASSWORD     Home Assistant password
    ODOO_TEST_LOGIN      Odoo login
    ODOO_TEST_PASSWORD   Odoo password
    E2E_ARTIFACT_DIR     where the screenshots go

    supervisor:
    HOST_SSH             ssh destination of the Home Assistant host, as
                         `ssh` would take it (no default: a clone of this
                         public repository must never point at a real
                         deployment unless the operator names it)
    ADDON_HOSTNAME       container name of the add-on on the Supervisor
                         network; defaults to ADDON_SLUG with underscores
                         turned into hyphens, which is how Supervisor names it
    ADDON_INGRESS_PORT   the add-on's ingress port (default 5691)
    SSH_BIN              which ssh to run (default the one on PATH)

    python odoo18ce/tests/e2e_browser_built_links.py --surface both
    python odoo18ce/tests/e2e_browser_built_links.py --surface supervisor
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HA_BASE = os.environ.get("HA_BASE_URL", "").rstrip("/")
PUBLIC_BASE = os.environ.get("ODOO_PUBLIC_URL", "").rstrip("/")
HA_USER = os.environ.get("HA_TEST_USER")
HA_PASSWORD = os.environ.get("HA_TEST_PASSWORD")
ODOO_LOGIN = os.environ.get("ODOO_TEST_LOGIN")
ODOO_PASSWORD = os.environ.get("ODOO_TEST_PASSWORD")
ADDON_SLUG = os.environ.get("ADDON_SLUG", "")
HOST_SSH = os.environ.get("HOST_SSH", "")
# Windows ships its own OpenSSH, and some builds of it fail this host's
# transport with "Corrupted MAC on input" where Git's ssh succeeds, so the
# binary is nameable rather than whatever happens to be first on PATH.
SSH_BIN = os.environ.get("SSH_BIN", "ssh")
ADDON_HOSTNAME = os.environ.get("ADDON_HOSTNAME", "") or ADDON_SLUG.replace("_", "-")
ADDON_INGRESS_PORT = os.environ.get("ADDON_INGRESS_PORT", "5691")
GLOBAL_NAME = "__WOOW_CANONICAL_URL__"
STAMP = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
ARTIFACTS = Path(os.environ.get("E2E_ARTIFACT_DIR", "/tmp/odoo-browser-built-links")) / STAMP


def require(value, name):
    if not value:
        sys.exit(f"error: {name} is required in the environment")
    return value


def mask(value):
    """Ingress tokens and channel invitation tokens are secrets; never print them."""
    text = str(value)
    text = re.sub(r"(/api/hassio_ingress/)[^/\s?#\"']+", r"\1<redacted>", text)
    text = re.sub(r"(/chat/\d+/)[^/\s?#\"']+", r"\1<redacted>", text)
    return text


def login_home_assistant(page):
    """Log in, then persist the session the way "keep me logged in" would.

    Home Assistant keeps its tokens in memory unless that box is ticked, and
    the box is a custom element Playwright cannot actuate, so the first full
    navigation would bounce back to the login form. Capture the frontend's own
    token exchange instead and write it back in the shape it reads.
    """
    captured = {}

    def on_response(response):
        if "/auth/token" in response.url and response.status == 200:
            try:
                body = response.json()
            except ValueError:
                return
            if body.get("access_token"):
                captured.update(body)

    page.on("response", on_response)
    page.goto(HA_BASE, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_selector('input[name="username"]', timeout=60_000)
    page.fill('input[name="username"]', HA_USER)
    page.fill('input[name="password"]', HA_PASSWORD)
    page.locator('input[name="password"]').press("Enter")
    for _ in range(120):
        if captured.get("access_token"):
            break
        page.wait_for_timeout(500)
    else:
        raise AssertionError("Home Assistant never completed a token exchange")

    page.evaluate(
        """({ tokens, hassUrl }) => {
            localStorage.setItem("hassTokens", JSON.stringify({
                access_token: tokens.access_token,
                token_type: tokens.token_type || "Bearer",
                refresh_token: tokens.refresh_token,
                expires_in: tokens.expires_in,
                hassUrl,
                clientId: hassUrl + "/",
                expires: Date.now() + (tokens.expires_in || 1800) * 1000,
            }));
        }""",
        {"tokens": captured, "hassUrl": HA_BASE},
    )


def ingress_frame(page):
    frames = [frame for frame in page.frames if "/api/hassio_ingress/" in frame.url]
    if not frames:
        raise AssertionError("no Ingress iframe; url=" + mask(page.url))
    return frames[0]


def open_addon(page):
    """Open one add-on by slug. A host may run several, so never pick by name."""
    page.goto(f"{HA_BASE}/{require(ADDON_SLUG, 'ADDON_SLUG')}", wait_until="domcontentloaded", timeout=120_000)
    for _ in range(120):
        if any("/api/hassio_ingress/" in frame.url for frame in page.frames):
            return ingress_frame(page)
        page.wait_for_timeout(500)
    page.screenshot(path=str(ARTIFACTS / "no-ingress-frame.png"))
    raise AssertionError("the add-on panel never loaded an Ingress iframe; url=" + mask(page.url))


def login_odoo(page, frame):
    if frame.locator('input[name="login"]').count():
        frame.locator('input[name="login"]').fill(ODOO_LOGIN)
        frame.locator('input[name="password"]').fill(ODOO_PASSWORD)
        frame.get_by_role("button", name="Log in", exact=True).click()
        page.wait_for_timeout(8000)
        frame = ingress_frame(page)
    frame.wait_for_selector(".o_main_navbar", timeout=60_000)
    return frame


def invitation_link(page, frame, channel):
    """The literal the Invite People panel shows for one channel."""
    prefix = re.match(r"(https?://[^/]+/api/hassio_ingress/[^/]+)", frame.url).group(1)
    frame.goto(prefix + "/odoo/discuss", wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(9000)
    frame = ingress_frame(page)
    frame.get_by_text(channel, exact=False).first.click()
    page.wait_for_timeout(5000)
    frame = ingress_frame(page)
    frame.locator('button[title="Invite People"]').first.click()
    page.wait_for_timeout(4000)
    frame = ingress_frame(page)
    page.screenshot(path=str(ARTIFACTS / "invite-people.png"))
    links = frame.evaluate(
        """() => Array.from(document.querySelectorAll("input, textarea"))
             .map(el => el.value).filter(v => v && v.includes("/chat/"))"""
    )
    if not links:
        raise AssertionError("the Invite People panel showed no invitation link")
    return links[0]


# The runnable slice of each rewritten expression, as it sits in a served
# bundle, with a driver that turns it into the value a user would be handed.
# The patterns themselves are not repeated here: this reads what the Ingress
# listener actually sent, so a rewrite that failed to match shows up as the
# unrewritten expression producing the Home Assistant host.
EXPRESSIONS = (
    {
        "name": "Discuss invitation link",
        "bundle": "web.assets_backend",
        "slice": ("get invitationLink(){", "get isEmpty(){"),
        "driver": (
            "class Thread{constructor(d){Object.assign(this,d)}\n"
            "__SLICE__\n"
            '}\nresult=new Thread({id:2,uuid:"6f3a",channel_type:"channel"}).invitationLink;'
        ),
        "suffix": "/chat/2/6f3a",
    },
    {
        "name": "Website page URL field",
        "bundle": "web.assets_backend",
        "slice": ("this.serverUrl=", "this.inputRef="),
        "driver": "function f(){__SLICE__\nreturn this.serverUrl}\nresult=f.call({});",
        "suffix": "/",
    },
    {
        "name": "Website share snippet",
        "bundle": "web.assets_frontend",
        # The website editor has its own `const currentUrl=` earlier in the
        # same bundle and the rewrite must leave it alone, so anchor on the
        # share handler first and take the statement after it.
        "after": "ev.preventDefault();ev.stopPropagation();",
        "slice": ("const currentUrl=", "const urlParamFound="),
        "driver": "function f(){__SLICE__\nreturn currentUrl}\nresult=f();",
        "suffix": "/shop/lamp?utm=x#reviews",
    },
)

# Any value $safe_ingress_path accepts. The listener does not check it against
# a live Supervisor session, and the rewrites have to handle it.
PROBE_PREFIX = "/api/hassio_ingress/0123456789abcdefghijklmn"
PROBE_ORIGIN = "https://home-assistant.invalid"

NODE_HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");

for (const { name, program, canonical, origin, prefix, expected } of JSON.parse(process.argv[1])) {
  const pathname = prefix + "/shop/lamp";
  const window = {
    __WOOW_CANONICAL_URL__: canonical,
    location: {
      origin,
      pathname,
      search: "?utm=x",
      hash: "#reviews",
      href: origin + pathname + "?utm=x#reviews",
    },
  };
  const context = vm.createContext({ window, result: undefined });
  vm.runInContext(program, context);
  assert.equal(context.result, expected, `${name}: wrong value`);
}
"""


def over_ssh(command):
    """Run one command on the Home Assistant host. Reads only."""
    result = subprocess.run(
        [SSH_BIN, "-o", "BatchMode=yes", require(HOST_SSH, "HOST_SSH"), command],
        capture_output=True, text=True, check=False, errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(f"ssh failed ({result.returncode}): {mask(result.stderr.strip())}")
    return result.stdout


def through_supervisor(path, scratch):
    """Fetch one Ingress URL from inside the Supervisor container.

    The Ingress listener allows the Supervisor and nobody else, so this is the
    only way to read what it serves without a browser session.
    """
    over_ssh(
        f"docker exec hassio_supervisor curl -s -o {scratch} "
        f"-H 'X-Ingress-Path: {PROBE_PREFIX}' -L "
        f"http://{require(ADDON_HOSTNAME, 'ADDON_HOSTNAME')}:{ADDON_INGRESS_PORT}{path}"
    )
    return over_ssh(f"docker exec hassio_supervisor cat {scratch}")


def runnable(text, expression):
    start = 0
    if expression.get("after"):
        start = text.find(expression["after"])
        if start < 0:
            raise AssertionError(f"{expression['name']}: context anchor missing from the served bundle")
    first = text.find(expression["slice"][0], start)
    if first < 0:
        raise AssertionError(f"{expression['name']}: start anchor missing from the served bundle")
    last = text.find(expression["slice"][1], first)
    if last < 0:
        raise AssertionError(f"{expression['name']}: end anchor missing from the served bundle")
    return text[first:last]


def run_supervisor():
    """Read the Ingress bytes and execute each rewritten expression. No credentials."""
    node = shutil.which("node")
    if not node:
        sys.exit("error: node is required for --surface supervisor")

    html = through_supervisor("/web/login", "/tmp/woow-live-ingress.html")
    published = re.search(r'var U="([^"]*)"', html)
    if not published:
        raise AssertionError(
            "the Ingress page publishes no Canonical URL; the Runtime shim on this "
            "host predates it, or the add-on is not the one under test"
        )
    canonical = published.group(1)
    print(f"  {GLOBAL_NAME} on the Ingress page: {canonical!r}")
    assert canonical == PUBLIC_BASE, (
        f"the Runtime shim published {canonical!r}; expected the Canonical URL {PUBLIC_BASE!r}"
    )

    served = {}
    cases = []
    for expression in EXPRESSIONS:
        bundle = expression["bundle"]
        if bundle not in served:
            served[bundle] = through_supervisor(
                f"/web/assets/1/any/{bundle}.min.js", f"/tmp/woow-live-{bundle}.js"
            )
        program = expression["driver"].replace("__SLICE__", runnable(served[bundle], expression))
        common = {"name": expression["name"], "program": program, "prefix": PROBE_PREFIX}
        cases.append({**common, "canonical": canonical, "origin": PROBE_ORIGIN,
                      "expected": canonical + expression["suffix"]})
        # Without a Canonical URL every rewrite keeps the browser origin, and
        # none of them keeps the Ingress prefix: the share snippet drops it
        # either way rather than hand a Supervisor token to a social network.
        cases.append({**common, "canonical": "", "origin": PROBE_ORIGIN,
                      "expected": PROBE_ORIGIN + expression["suffix"]})

    result = subprocess.run(
        [node, "-e", NODE_HARNESS, json.dumps(cases)],
        capture_output=True, text=True, check=False, errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError((result.stderr or result.stdout).strip())
    for expression in EXPRESSIONS:
        print(f"  {expression['name']}: {canonical + expression['suffix']}")


def run_ingress(browser, channel):
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    login_home_assistant(page)
    frame = open_addon(page)
    page.wait_for_timeout(5000)
    frame = ingress_frame(page)

    # The shim runs on every Ingress page, including the login page, so this
    # is checked before Odoo authentication: an add-on serving it without the
    # global fails here rather than somewhere deep in the web client.
    published = frame.evaluate(f"window.{GLOBAL_NAME}")
    print(f"  {GLOBAL_NAME} on the Ingress page: {published!r}")
    assert published == PUBLIC_BASE, (
        f"the Runtime shim published {published!r}; expected the Canonical URL {PUBLIC_BASE!r}"
    )
    assert not published.endswith("/"), "the Canonical URL must carry no trailing slash"

    frame = login_odoo(page, frame)
    link = invitation_link(page, frame, channel)
    print(f"  Discuss invitation link: {mask(link)}")
    assert link.startswith(PUBLIC_BASE + "/chat/"), (
        f"the invitation link is on the wrong base: {mask(link)}; expected {PUBLIC_BASE}"
    )
    assert "/api/hassio_ingress/" not in link, "the invitation link carries an Ingress token"
    assert not link.startswith(HA_BASE), "the invitation link is still on the Home Assistant host"
    page.context.close()


def run_public(browser):
    """The Public origin serves the bundles as Odoo ships them."""
    page = browser.new_context().new_page()
    for bundle in ("web.assets_backend", "web.assets_frontend"):
        response = page.request.get(f"{PUBLIC_BASE}/web/assets/1/any/{bundle}.min.js", timeout=180_000)
        assert response.ok, f"{bundle}: {response.status} from the Public origin"
        body = response.text()
        assert GLOBAL_NAME not in body, (
            f"{bundle} on the Public origin carries {GLOBAL_NAME}; the rewrites must be Ingress-only"
        )
        print(f"  Public origin {bundle}: unrewritten ({len(body)} bytes)")
    page.context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--surface",
        choices=("ingress", "public", "supervisor", "both", "all"),
        default="both",
        help="both = ingress + public; all adds the credential-free supervisor surface",
    )
    parser.add_argument("--channel", default="Administrators", help="the Discuss channel to read")
    args = parser.parse_args()

    wanted = {
        "ingress": {"ingress"},
        "public": {"public"},
        "supervisor": {"supervisor"},
        "both": {"ingress", "public"},
        "all": {"ingress", "public", "supervisor"},
    }[args.surface]

    # Only what the chosen surfaces need: the point of `supervisor` is that it
    # runs where nobody wants to put credentials.
    require(PUBLIC_BASE, "ODOO_PUBLIC_URL")
    if "ingress" in wanted:
        for name, value in (
            ("HA_BASE_URL", HA_BASE),
            ("HA_TEST_USER", HA_USER),
            ("HA_TEST_PASSWORD", HA_PASSWORD),
            ("ODOO_TEST_LOGIN", ODOO_LOGIN),
            ("ODOO_TEST_PASSWORD", ODOO_PASSWORD),
        ):
            require(value, name)
    if "supervisor" in wanted:
        require(HOST_SSH, "HOST_SSH")
        require(ADDON_HOSTNAME, "ADDON_HOSTNAME or ADDON_SLUG")

    if "supervisor" in wanted:
        print(f"Supervisor surface: {ADDON_HOSTNAME}:{ADDON_INGRESS_PORT} over ssh")
        run_supervisor()

    if wanted & {"ingress", "public"}:
        from playwright.sync_api import sync_playwright

        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        if "ingress" in wanted:
            print(f"Home Assistant entrance: {HA_BASE}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                if "ingress" in wanted:
                    run_ingress(browser, args.channel)
                if "public" in wanted:
                    run_public(browser)
            finally:
                browser.close()
        print(f"PASS  artifacts in {ARTIFACTS}")
    else:
        print("PASS")


if __name__ == "__main__":
    main()
