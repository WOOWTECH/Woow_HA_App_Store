#!/usr/bin/env python3
"""Contracts for the Runtime shim's clipboard fallback (issue #60).

Opening Home Assistant over plain http on the LAN is a supported usage. That
page is not a secure context, so ``navigator.clipboard`` does not exist inside
the Ingress iframe and every Odoo copy button throws ``TypeError`` on
``writeText``. The Runtime shim must supply a ``writeText`` backed by
``document.execCommand("copy")`` in that case, and must leave a real
``navigator.clipboard`` alone.

The Runtime shim is two scripts. The clipboard script lives in its own nginx
map, ``$ingress_clipboard_shim``, spliced into ``$ingress_runtime_shim`` by
variable reference, because nginx reads each quoted parameter into a
4096-byte buffer and the prefix script alone is close to that limit. Both
scripts are executed here, in injection order, in a node ``vm`` context
against a minimal DOM stand-in, so the contract covers the Runtime shim as it
is in the template rather than an excerpt.
"""
import json
import re
import subprocess

from test_ingress_router_rewrite import TEMPLATE, map_block, runtime_shim

CLIPBOARD_MAP = "map $upstream_http_content_type $ingress_clipboard_shim {"
RUNTIME_MAP = "map $upstream_http_content_type $ingress_runtime_shim {"
INGRESS_PREFIX = "/api/hassio_ingress/token"
# ngx_conf_read_token() reports "too long parameter" once a single parameter
# fills NGX_CONF_BUFFER, so a quoted value must stay strictly below it.
NGX_CONF_BUFFER = 4096

HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const shim = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";

function makeContext(options) {
  const execCalls = [];
  const bodyChildren = [];
  const button = { focusCalls: 0, focus() { this.focusCalls += 1; } };
  const body = {
    appendChild(el) { bodyChildren.push(el); el.parentNode = body; return el; },
    removeChild(el) {
      const index = bodyChildren.indexOf(el);
      assert.notEqual(index, -1, "removeChild of an element that is not attached");
      bodyChildren.splice(index, 1);
      el.parentNode = null;
      return el;
    },
  };
  const document = {
    body,
    documentElement: body,
    activeElement: button,
    createElement(tag) {
      return {
        tagName: tag.toUpperCase(),
        value: "",
        style: {},
        attributes: {},
        parentNode: null,
        selected: false,
        setAttribute(name, value) { this.attributes[name] = String(value); },
        select() { this.selected = true; },
        setSelectionRange() {},
      };
    },
    execCommand(command) {
      execCalls.push({
        command,
        attached: bodyChildren.map((el) => ({ tag: el.tagName, value: el.value, selected: el.selected })),
      });
      return options.execCommand();
    },
  };
  const navigator = { serviceWorker: undefined };
  if (options.clipboard) navigator.clipboard = options.clipboard;
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype.open = function () {};
  function History() {}
  History.prototype.pushState = function () {};
  History.prototype.replaceState = function () {};
  function Element() {}
  Element.prototype.setAttribute = function () {};
  function WebSocket() {}
  const context = {
    document,
    navigator,
    location: { href: "http://ha.example:8123" + P + "/odoo", origin: "http://ha.example:8123", host: "ha.example:8123", reload() {} },
    sessionStorage: { getItem() { return null; }, setItem() {} },
    fetch() {},
    open() {},
    XMLHttpRequest,
    History,
    Element,
    WebSocket,
    URL,
    Request: function () {},
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(shim, context, { filename: "ingress-runtime-shim.js" });
  return { context, execCalls, bodyChildren, button };
}

(async () => {
  // Absent clipboard: writeText resolves through execCommand("copy") within
  // the caller's stack (user-gesture requirement), the textarea is gone and
  // the copy button that had focus gets it back.
  {
    const { context, execCalls, bodyChildren, button } = makeContext({ execCommand: () => true });
    assert.equal(typeof context.navigator.clipboard, "object");
    assert.equal(typeof context.navigator.clipboard.writeText, "function");
    assert.equal(context.navigator.clipboard.write, undefined, "write() must stay absent so Odoo keeps its own catch");
    const pending = context.navigator.clipboard.writeText("https://ha.example/chat/2/abc");
    assert.equal(execCalls.length, 1, "execCommand must run synchronously inside writeText");
    assert.equal(execCalls[0].command, "copy");
    assert.deepEqual(execCalls[0].attached, [{ tag: "TEXTAREA", value: "https://ha.example/chat/2/abc", selected: true }]);
    assert.equal(await pending, undefined);
    assert.deepEqual(bodyChildren, [], "temporary textarea must be removed");
    assert.equal(button.focusCalls, 1, "focus must return to the element that had it");
  }
  // Present clipboard: same reference, untouched.
  {
    const original = { writeText() { return Promise.resolve(); } };
    const { context, execCalls } = makeContext({ execCommand: () => true, clipboard: original });
    assert.equal(context.navigator.clipboard, original);
    assert.equal(context.navigator.clipboard.writeText, original.writeText);
    await context.navigator.clipboard.writeText("x");
    assert.deepEqual(execCalls, []);
  }
  // execCommand returns false: reject, textarea removed, focus restored.
  {
    const { context, execCalls, bodyChildren, button } = makeContext({ execCommand: () => false });
    await assert.rejects(context.navigator.clipboard.writeText("x"));
    assert.equal(execCalls.length, 1);
    assert.deepEqual(bodyChildren, []);
    assert.equal(button.focusCalls, 1);
  }
  // execCommand throws: reject, textarea removed, focus restored.
  {
    const { context, bodyChildren, button } = makeContext({ execCommand: () => { throw new Error("blocked"); } });
    await assert.rejects(context.navigator.clipboard.writeText("x"));
    assert.deepEqual(bodyChildren, []);
    assert.equal(button.focusCalls, 1);
  }
  // The prefix script still ran after the clipboard script.
  {
    const { context } = makeContext({ execCommand: () => true });
    assert.equal(context.window.__INGRESS_PATH__, P);
    assert.equal(typeof context.window.fetch, "function");
    assert.notEqual(context.window.fetch.toString(), "fetch() {}", "prefix script must have wrapped fetch");
  }
})().catch((error) => { console.error(error); process.exit(1); });
"""


def directive_lines(template: str) -> list[tuple[int, str]]:
    """Template lines that nginx parses, numbered; comment lines are dropped."""
    return [
        (number, line)
        for number, line in enumerate(template.splitlines(), start=1)
        if not line.lstrip().startswith("#")
    ]


def clipboard_shim(template: str) -> str:
    """Return the clipboard script declared in its own map, injected for every value."""
    match = re.search(r"default '<script>(.*?)</script>';", map_block(template, CLIPBOARD_MAP), re.S)
    assert match, "clipboard script not found in its map"
    assert "$" not in match.group(1), "clipboard script must not reference nginx variables"
    return match.group(1)


def assert_single_splice(template: str) -> None:
    """The clipboard script is spliced in front of the prefix script, under its text/html gate."""
    runtime_map = map_block(template, RUNTIME_MAP)
    assert "'$ingress_clipboard_shim" in runtime_map, (
        "the Runtime shim map must splice $ingress_clipboard_shim in by variable reference"
    )
    # Other scripts may be spliced in between (issue #70's Canonical URL
    # script is), but the clipboard script keeps its place ahead of the
    # prefix script so a copy button never runs before its fallback exists.
    assert runtime_map.index("$ingress_clipboard_shim") < runtime_map.index(
        "<script>window.__INGRESS_PATH__="
    ), "the clipboard script must stay in front of the prefix script"
    references = [
        number
        for number, line in directive_lines(template)
        if "$ingress_clipboard_shim" in line and not line.lstrip().startswith("map ")
    ]
    assert len(references) == 1, (
        f"$ingress_clipboard_shim must be referenced only inside $ingress_runtime_shim, "
        f"found it on lines {references}"
    )


def template_shim(template: str) -> str:
    """Both Runtime shim scripts in injection order, with placeholders rendered."""
    return "\n".join(
        script.replace("$safe_ingress_path", INGRESS_PREFIX).replace("%%INGRESS_CACHE_VERSION%%", "V")
        for script in (clipboard_shim(template), runtime_shim(template))
    )


def assert_quoted_parameters_fit(template: str) -> None:
    """Every single-quoted nginx parameter must fit the config token buffer.

    The rendered file is never longer than the template: each %%PLACEHOLDER%%
    becomes a shorter add-on value, and $variables stay as written.
    """
    for number, line in directive_lines(template):
        for value in re.findall(r"'([^']*)'", line):
            size = len(value.encode("utf-8"))
            assert size < NGX_CONF_BUFFER, (
                f"nginx.conf.template:{number}: quoted parameter is {size} bytes; "
                f"nginx rejects a parameter of {NGX_CONF_BUFFER} bytes or more "
                "('too long parameter'). Move the addition into its own map and "
                "splice it in by variable reference, as $ingress_clipboard_shim is."
            )


def main(node: str = "node") -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    assert_single_splice(template)
    assert_quoted_parameters_fit(template)
    result = subprocess.run(
        [node, "-e", HARNESS, json.dumps(template_shim(template))],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


if __name__ == "__main__":
    main()


def test_ingress_shim_quoted_parameters_fit_nginx_token_buffer() -> None:
    assert_quoted_parameters_fit(TEMPLATE.read_text(encoding="utf-8"))


def test_ingress_clipboard_fallback_contracts() -> None:
    from conftest import require_tool

    main(require_tool("node"))
