#!/usr/bin/env python3
"""Contracts for ingress transformations of Odoo's OWL URL router."""
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
SOURCE_PREFIX = "function urlToState(urlObj){const{pathname,hash,search}=urlObj;"
CLICK_HANDLER_PREFIX = (
    'browser.location.host===url.host&&browser.location.pathname.startsWith("/odoo")'
    '&&(["/web","/odoo"].includes(url.pathname)||url.pathname.startsWith("/odoo/"))'
    '&&ev.target.target!=="_blank"){ev.preventDefault();state=router.urlToState(url);'
    'if(url.pathname.startsWith("/odoo")&&url.hash)'
)


def ingress_assets_block(template: str) -> tuple[int, int]:
    """Select the ingress asset location using unambiguous nginx line markers."""
    ingress_server = template.index("# HA Supervisor Ingress adapter.")
    assets_location = template.index("location ^~ /web/assets/ {", ingress_server)
    next_ingress_location = template.index("\n        location / {", assets_location)
    assert assets_location < next_ingress_location
    return assets_location, next_ingress_location


def ingress_rule(template: str, source: str, description: str) -> str:
    rule = re.compile(r"sub_filter '" + re.escape(source) + r"' '([^']+)';")
    matches = list(rule.finditer(template))
    assets_start, assets_end = ingress_assets_block(template)
    outside = [match for match in matches if not assets_start <= match.start() < assets_end]
    assert not outside, (
        f"{description} sub_filter must be ingress-only in the HA server "
        "location ^~ /web/assets/; found the rule outside that location "
        "(for example, the public listener), which would change public routing"
    )
    assert len(matches) == 1, f"missing ingress-only {description} sub_filter"
    return matches[0].group(1).replace(
        "$safe_ingress_path", "/api/hassio_ingress/token"
    )


def assert_public_rule_is_rejected(template: str) -> None:
    public_rule = "sub_filter '%s' 'normalized';" % SOURCE_PREFIX
    public_template = template.replace(
        "listen 8069 default_server;",
        "listen 8069 default_server;\n        " + public_rule,
        1,
    )
    try:
        ingress_rule(public_template, SOURCE_PREFIX, "urlToState normalization")
    except AssertionError as error:
        assert "public listener" in str(error), str(error)
    else:
        raise AssertionError("urlToState normalization sub_filter in public listener was accepted")


def assert_prefix_guard(template: str) -> None:
    """Only the validated non-empty HA ingress prefix may trigger cloning."""
    replacement = ingress_rule(template, SOURCE_PREFIX, "urlToState normalization")
    guard = 'if("/api/hassio_ingress/token"&&urlObj.pathname.indexOf("/api/hassio_ingress/token/")===0)'
    assert guard in replacement, "urlToState must require a non-empty safe ingress prefix"
    assert "~^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$" in template, (
        "safe_ingress_path must remain restricted to validated HA ingress tokens"
    )


def assert_shim_fragments(template: str, node: str) -> None:
    """Fragment anchors must remain local so Odoo's Router owns their click."""
    match = re.search(
        r"sub_filter '<head>' '<head><script>(.*?)</script>';", template, re.S
    )
    assert match, "ingress shim not found"
    shim = match.group(1).replace("$safe_ingress_path", "/api/hassio_ingress/token")
    assert ".settings_tab a.tab" not in shim, (
        "Settings-specific document click workaround must be absent"
    )
    path_match = re.search(r"var path=function\(u\)\{(.*?)\};var F=", shim)
    assert path_match, "ingress shim path() function not found"
    harness = """
const assert = require("node:assert/strict");
const P = "/api/hassio_ingress/token";
const location = { href: "https://ha.example" + P + "/odoo/settings", origin: "https://ha.example" };
const path = function(u){%s};
assert.equal(path("#calendar"), "#calendar");
assert.equal(path("/web/image"), P + "/web/image");
assert.equal(path("https://external.example/x"), "https://external.example/x");
""" % path_match.group(1)
    result = subprocess.run([node, "-e", harness], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout


def main() -> None:
    node = shutil.which("node")
    assert node, "node is required for ingress router VM contract tests"
    template = TEMPLATE.read_text(encoding="utf-8")
    assert_public_rule_is_rejected(template)
    assert_prefix_guard(template)
    assert_shim_fragments(template, node)
    router_replacement = ingress_rule(template, SOURCE_PREFIX, "urlToState normalization")
    click_replacement = ingress_rule(template, CLICK_HANDLER_PREFIX, "router click handler")
    source = """
function parseSearchQuery() { return {}; }
function urlToState(urlObj){const{pathname,hash,search}=urlObj;const state=parseSearchQuery(search);const[prefix,...splitPath]=urlObj.pathname.split("/").filter(Boolean);if(["odoo","scoped_app"].includes(prefix)){state.action=splitPath[splitPath.length-1];}return state;}
let state;
function routeClick(browser,router,ev,url){if(browser.location.host===url.host&&browser.location.pathname.startsWith("/odoo")&&(["/web","/odoo"].includes(url.pathname)||url.pathname.startsWith("/odoo/"))&&ev.target.target!=="_blank"){ev.preventDefault();state=router.urlToState(url);if(url.pathname.startsWith("/odoo")&&url.hash){browser.history.pushState({},"",url.href);}return state;}return null;}
"""
    transformed = source.replace(SOURCE_PREFIX, router_replacement, 1).replace(
        CLICK_HANDLER_PREFIX, click_replacement, 1
    )
    harness = """
const assert = require("node:assert/strict");
%s
const prefix = "/api/hassio_ingress/token";
const ingress = new URL("https://ha.example" + prefix + "/odoo/settings");
assert.deepEqual(urlToState(ingress), { action: "settings" });
assert.equal(ingress.pathname, prefix + "/odoo/settings");
assert.deepEqual(urlToState(new URL("https://ha.example" + prefix + "/odoo/discuss")), { action: "discuss" });
const browser = {
  location: new URL("https://ha.example" + prefix + "/odoo/settings"),
  history: { pushed: [], pushState(_state, _title, href) { this.pushed.push(href); } },
};
const calendar = new URL("https://ha.example" + prefix + "/odoo/settings#calendar");
const event = { target: { target: "" }, prevented: false, preventDefault() { this.prevented = true; } };
assert.deepEqual(routeClick(browser, { urlToState }, event, calendar), { action: "settings" });
assert.equal(event.prevented, true);
assert.deepEqual(browser.history.pushed, [calendar.href]);
assert.equal(browser.history.pushed[0], "https://ha.example" + prefix + "/odoo/settings#calendar");
for (const url of [
  new URL("https://external.example" + prefix + "/odoo/settings#calendar"),
  new URL("https://ha.example" + prefix + "/website/page"),
]) {
  const rejected = { target: { target: "" }, prevented: false, preventDefault() { this.prevented = true; } };
  assert.equal(routeClick(browser, { urlToState }, rejected, url), null);
  assert.equal(rejected.prevented, false);
}
const odooxBrowser = {
  location: new URL("https://ha.example" + prefix + "/odoox/settings"),
  history: { pushed: [], pushState(_state, _title, href) { this.pushed.push(href); } },
};
const odoox = new URL("https://ha.example" + prefix + "/odoox/settings#calendar");
const odooxEvent = { target: { target: "" }, prevented: false, preventDefault() { this.prevented = true; } };
assert.equal(routeClick(odooxBrowser, { urlToState }, odooxEvent, odoox), null);
assert.equal(odooxEvent.prevented, false);
assert.deepEqual(odooxBrowser.history.pushed, []);
const validOdooUrlFromOdoox = new URL("https://ha.example" + prefix + "/odoo/settings#calendar");
const odooxCurrentEvent = { target: { target: "" }, prevented: false, preventDefault() { this.prevented = true; } };
assert.equal(routeClick(odooxBrowser, { urlToState }, odooxCurrentEvent, validOdooUrlFromOdoox), null);
assert.equal(odooxCurrentEvent.prevented, false);
assert.deepEqual(odooxBrowser.history.pushed, []);
""" % transformed
    result = subprocess.run(["node", "-e", harness], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout


if __name__ == "__main__":
    main()
