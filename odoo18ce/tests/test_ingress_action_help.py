#!/usr/bin/env python3
"""Contracts for the Ingress action-help rewrite (issue #158).

A window action's ``help`` field is HTML kept in the database, and Odoo's own
help carries root-relative attributes: the Surveys screen of an empty list
(``ir.actions.act_window`` 930) shows four
``<img src="/survey/static/src/img/survey_sample_*.png">`` tiles. The web
client reads that field out of the ``/web/action/load`` JSON-RPC response,
hands it to ``markup()``, and inserts it as markup -- so the Runtime shim,
which wraps APIs and not ``innerHTML``, never sees the URL. Under Ingress the
browser asked the Home Assistant root for the four pictures and got 404: eight
**Prefix escapes** per screen.

ADR 0004's 2026-09-28 postscript decides markup insertion stays *uncovered* by
the shim -- the HTML editor saves record content back through the same path, so
a hook would write the token-bearing Ingress prefix into the database -- and
sends a screen that hits it to a route-scoped **Literal rewrite** instead. That
is what these contracts guard:

* the rules live in an exact-match ``location`` for ``/web/action/load`` and
  nowhere else, so no other JSON response sees them (ADR 0004's second
  rejected option, and the reason 0.3.34 had to stop rewriting JSON
  wholesale);
* ``/web/action/run`` and ``/web/dataset/call_button/<model>/<method>`` deliver
  markup()'d help too and are **still left alone**, because they answer with an
  action computed at call time, and a computed action carries record content in
  its ``context`` as wizard defaults. ``marketing_card``'s ``action_share()``
  is the shipped proof: its ``context.default_body_arch`` holds
  ``<img src="/web/image/card.campaign/…">``, which the user then saves into
  ``mailing.mailing``. Prefixing it would put the Supervisor token in the
  database -- the harm this whole decision exists to avoid. A stored action
  record, which is what ``/web/action/load`` answers with, has no such field;
* the location is otherwise the Ingress ``location /`` -- proxy headers, cookie
  path and flags, ``X-Frame-Options`` removal, buffering, timeouts and every
  rule it carries. The comparison is by directive, so drift in either body
  fails here rather than quietly changing the route;
* the rules run, over the real template's directives, against a live nginx: an
  escaped-quote attribute URL is prefixed, one that already carries the prefix
  is left alone, and the routes above plus the generic location still touch
  neither.
"""
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from test_dual_gateway import TEMPLATE, block_end, mask_strings_and_comments, read

PREFIX = "/api/hassio_ingress/aaaabbbbccccdddd"
CACHE_VERSION = "test"

# The Surveys screen's help, plus the shapes the rules have to leave alone.
HELP_HTML = (
    "<p>"
    '<img src="/survey/static/src/img/survey_sample_survey.png">'
    '<img src="/survey/static/src/img/survey_sample_assessment.png">'
    '<img src="/survey/static/src/img/survey_sample_custom.png">'
    '<img src="/survey/static/src/img/survey_sample_live_session.png">'
    '<a href="/odoo/surveys/new">new</a>'
    '<form action="/survey/submit"></form>'
    '<img data-src="/web/image/1" srcset="/web/image/2 2x">'
    '<img srcset="/web/image/3 1x, /web/image/4 2x">'
    '<img src="//cdn.example/protocol-relative.png">'
    '<link href="/web/assets/1/web.assets_backend.min.css">'
    f'<img src="{PREFIX}/survey/static/src/img/already.png">'
    '<img src="https://cdn.example/remote.png">'
    '<img src="survey/static/relative.png">'
    "</p>"
)


# What a *computed* action carries that a stored one does not: record content
# as a wizard default. This is `marketing_card`'s `action_share()`, shortened --
# a button method returning an act_window whose context holds a mail body the
# user edits and saves into `mailing.mailing.body_arch`. Prefixing these two
# URLs would write the Ingress prefix, Supervisor token and all, into the
# database, so no route that can answer with one of these may be rewritten.
COMPUTED_CONTEXT = {
    "default_subject": "Send Cards",
    "default_body_arch": (
        '<div class="o_layout">'
        '<a href="/cards/4/preview">'
        '<img src="/web/image/card.campaign/4/image_preview" class="img-fluid"/>'
        "</a></div>"
    ),
}


class Upstream(BaseHTTPRequestHandler):
    """Odoo's answer to an action load: JSON-RPC around the action dict."""

    def respond(self) -> None:
        action = {
            "id": 930,
            "type": "ir.actions.act_window",
            "res_model": "survey.survey",
            "help": HELP_HTML,
            # A stored action's context is the static string a developer wrote
            # into the action definition, not record content.
            "context": "{'search_default_my_surveys': 1}",
        }
        if self.path != "/web/action/load":
            # Everything else stands in for a route that answers with an action
            # computed at call time.
            action = dict(action, context=COMPUTED_CONTEXT)
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": action})
        # Inside JSON the attribute quote is escaped, which is the whole reason
        # the generic location's raw-quote rules never matched a byte of it.
        assert r'src=\"/survey/static/src/img/survey_sample_survey.png\"' in payload
        assert 'src="/survey' not in payload
        body = payload.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = respond
    do_POST = respond

    def log_message(self, _format: str, *_args: object) -> None:
        pass


# --- reading the template ----------------------------------------------------


def server_block(template: str, listen: str) -> str:
    """The body of the server block on `listen`, as written."""
    masked = mask_strings_and_comments(template)
    for server in re.finditer(r"\bserver\s*\{", masked):
        brace = server.end() - 1
        end = block_end(masked, brace)
        if re.search(rf"\blisten\s+{re.escape(listen)}\b", masked[brace:end]):
            return template[brace : end + 1]
    raise AssertionError(f"no server block listening on {listen}")


def location_block(block: str, header: str) -> str:
    """The `location <header> {...}` block inside `block`, braces included."""
    masked = mask_strings_and_comments(block)
    needle = f"location {header} {{"
    start = masked.index(needle)
    brace = start + len(needle) - 1
    return block[start : block_end(masked, brace) + 1]


def directives(location: str) -> list:
    """The directive lines of a location body: no comments, no blank lines."""
    lines = location.split("\n")
    assert lines[0].lstrip().startswith("location ") and lines[-1].strip() == "}"
    return [
        line.strip()
        for line in lines[1:-1]
        if line.strip() and not line.strip().startswith("#")
    ]


# The rules the route-scoped locations add to the generic body. Identity rules
# first: sub_filter settles two patterns matching at the same byte by the order
# they are written, so the identity rule has to be the earlier one for an
# already-prefixed URL to survive.
ATTRIBUTES = ("href", "src", "action", "data-src", "srcset")
ACTION_HELP_RULES = [
    f"sub_filter '{a}=\\\\\"$safe_ingress_path/' '{a}=\\\\\"$safe_ingress_path/';"
    for a in ATTRIBUTES
] + [
    f"sub_filter '{a}=\\\\\"/' '{a}=\\\\\"$safe_ingress_path/';" for a in ATTRIBUTES
]
ACTION_LOCATION = "= /web/action/load"
ACTION_LOCATIONS = (ACTION_LOCATION,)


def test_action_routes_clone_the_generic_ingress_location() -> None:
    ingress = server_block(read(TEMPLATE), "5691")
    generic = directives(location_block(ingress, "/"))
    # A body the parser failed to read would satisfy the comparison vacuously.
    assert "proxy_pass http://odoo_http;" in generic
    assert "proxy_cookie_flags session_id $ingress_cookie_secure httponly samesite=lax;" in generic
    for header in ACTION_LOCATIONS:
        found = directives(location_block(ingress, header))
        assert found == generic + ACTION_HELP_RULES, header


def test_a_route_that_drifts_from_the_generic_location_is_caught() -> None:
    # The two bodies are written out twice each, so the drift this rule exists
    # to catch is one of them losing a directive the other keeps.
    ingress = server_block(read(TEMPLATE), "5691")
    generic = directives(location_block(ingress, "/"))
    dropped = location_block(ingress, ACTION_LOCATIONS[0]).replace(
        "\n            proxy_cookie_flags session_id $ingress_cookie_secure httponly samesite=lax;",
        "",
        1,
    )
    assert directives(dropped) != generic + ACTION_HELP_RULES


def test_action_help_rules_are_ingress_only() -> None:
    template = read(TEMPLATE)
    ingress = server_block(template, "5691")
    for header in ACTION_LOCATIONS:
        assert f"location {header} {{" in ingress
    # Neither the route nor its rules reach the origin listeners, and the
    # generic Ingress locations are left as they were: an escaped-quote rule
    # there would be the broad JSON rewriting ADR 0004 rejects.
    blocks = [location_block(ingress, header) for header in ACTION_LOCATIONS]
    scoped = "\n".join(blocks)
    elsewhere = template
    for block in blocks:
        assert elsewhere.count(block) == 1
        elsewhere = elsewhere.replace(block, "")
    for header in ACTION_LOCATIONS:
        assert f"location {header} {{" not in elsewhere
    for rule in ACTION_HELP_RULES:
        assert rule in scoped, rule
        assert rule not in elsewhere, rule


# --- the rules, run ----------------------------------------------------------


def harness_config(root: Path, socket: Path, upstream_port: int) -> Path:
    """A live config carrying the template's own directives, not a copy of them.

    The maps the Ingress locations read come from the template too, so
    `$safe_ingress_path` is derived here the way the Supervisor's
    `X-Ingress-Path` header derives it in the add-on.
    """
    template = read(TEMPLATE)
    ingress = server_block(template, "5691")
    masked = mask_strings_and_comments(template)
    maps = "\n".join(
        template[template.index(head) : block_end(masked, template.index(head) + len(head) - 1) + 1]
        for head in (
            "map $http_x_forwarded_proto $ingress_proto {",
            "map $ingress_proto $ingress_cookie_secure {",
            "map $http_x_ingress_path $safe_ingress_path {",
        )
    )
    locations = "\n".join(
        location_block(ingress, header) for header in (*ACTION_LOCATIONS, "/")
    )
    config = root / "nginx.conf"
    config.write_text(
        f"""daemon off;
master_process off;
pid {root / "nginx.pid"};
error_log {root / "error.log"} notice;
events {{}}
http {{
  access_log off;
{maps}
  # The shape of the template's own map: keyed on the upstream content type,
  # so a JSON response gets an empty replacement and an HTML one gets the
  # script. A `default ""` stand-in would make the "no shim in JSON" assertion
  # below vacuous -- and 0.3.34, which injected the shim into JSON and blanked
  # the Document Layout preview, is exactly what that assertion guards.
  map $upstream_http_content_type $ingress_runtime_shim {{
    default "";
    "~*^text/html(?:;|$)" '<script>window.__INGRESS_PATH__="$safe_ingress_path";</script>';
  }}
  upstream odoo_http {{ server 127.0.0.1:{upstream_port}; }}
  server {{
    listen unix:{socket};
{locations}
  }}
}}
""".replace("%%INGRESS_CACHE_VERSION%%", CACHE_VERSION),
        encoding="utf-8",
    )
    return config


def request(socket: Path, route: str) -> str:
    return subprocess.run(
        [
            "curl", "--fail", "--silent", "--unix-socket", str(socket),
            "--header", f"X-Ingress-Path: {PREFIX}",
            f"http://localhost{route}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def assert_help_is_prefixed(body: str) -> None:
    help_html = json.loads(body)["result"]["help"]
    for name in ("survey", "assessment", "custom", "live_session"):
        want = f'<img src="{PREFIX}/survey/static/src/img/survey_sample_{name}.png">'
        assert want in help_html, (want, help_html)
    assert f'<a href="{PREFIX}/odoo/surveys/new">' in help_html, help_html
    assert f'<form action="{PREFIX}/survey/submit">' in help_html, help_html
    assert f'data-src="{PREFIX}/web/image/1"' in help_html, help_html
    assert f'srcset="{PREFIX}/web/image/2 2x"' in help_html, help_html
    # The two limits of a plain-string pattern, pinned so they stay known
    # rather than becoming a surprise (issue #166 owns fixing them, for every
    # such rule in the template at once):
    #   * `srcset` is a list, and only its first candidate sits behind the
    #     attribute opener, so the second one still escapes;
    #   * a protocol-relative reference is prefixed, and breaks.
    assert f'srcset="{PREFIX}/web/image/3 1x, /web/image/4 2x"' in help_html, help_html
    assert f'<img src="{PREFIX}//cdn.example/protocol-relative.png">' in help_html, help_html
    # The escaped `/web/assets/` rule the generic body already carried is ahead
    # of the new ones and answers first; its result is the same.
    assert f'href="{PREFIX}/web/assets/1/web.assets_backend.min.css"' in help_html, help_html
    # No double prefix: a URL that already carries the prefix is left alone.
    assert f'<img src="{PREFIX}/survey/static/src/img/already.png">' in help_html, help_html
    assert PREFIX + PREFIX not in help_html, help_html
    # Nothing that is not root-relative is touched.
    assert '<img src="https://cdn.example/remote.png">' in help_html, help_html
    assert '<img src="survey/static/relative.png">' in help_html, help_html


def main() -> None:
    nginx = shutil.which("nginx")
    assert nginx, "nginx is required for the ingress action-help response tests"
    test_action_routes_clone_the_generic_ingress_location()
    test_a_route_that_drifts_from_the_generic_location_is_caught()
    test_action_help_rules_are_ingress_only()

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="odoo-action-help-nginx-") as directory:
            root = Path(directory)
            socket = root / "ingress.sock"
            config = harness_config(root, socket, upstream.server_port)
            subprocess.run(
                [nginx, "-t", "-p", str(root), "-c", str(config)],
                check=True, capture_output=True, text=True,
            )
            process = subprocess.Popen(
                [nginx, "-p", str(root), "-c", str(config)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                for _ in range(100):
                    if socket.exists():
                        break
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        raise AssertionError(f"nginx action-help harness exited: {stdout}{stderr}")
                    time.sleep(0.02)
                else:
                    raise AssertionError("nginx action-help harness socket did not become ready")

                body = request(socket, "/web/action/load")
                assert_help_is_prefixed(body)
                # The response is still JSON, and the Runtime shim -- a
                # text/html replacement -- is not injected into it.
                assert json.loads(body)["result"]["id"] == 930
                assert "__INGRESS_PATH__" not in body

                # Every other route on the same listener falls through to the
                # generic location, which has no escaped-quote rule but the
                # /web/assets/ one, so the help HTML comes back as Odoo wrote
                # it -- and, decisively, so does the record content a computed
                # action carries as a wizard default. `/web/action/run` and
                # `/web/dataset/call_button/...` deliver markup()'d help too;
                # they are left alone *because* of that context, which a user
                # edits and saves. `/web/dataset/call_kw` is the same story one
                # step plainer, and `/web/action/load_breadcrumbs` needs
                # nothing.
                for route in (
                    "/web/action/run",
                    "/web/dataset/call_button/card.campaign/action_share",
                    "/web/dataset/call_kw/survey.survey/web_read",
                    "/web/action/load_breadcrumbs",
                ):
                    result = json.loads(request(socket, route))["result"]
                    help_html = result["help"]
                    assert '<img src="/survey/static/src/img/survey_sample_survey.png">' in help_html, route
                    assert f'<a href="{PREFIX}/odoo/surveys/new">' not in help_html, route
                    assert f'href="{PREFIX}/web/assets/1/web.assets_backend.min.css"' in help_html, route
                    # The reason these routes are out: the wizard default is
                    # record content, and a prefix written into it is a
                    # Supervisor token written into the database.
                    body_arch = result["context"]["default_body_arch"]
                    assert body_arch == COMPUTED_CONTEXT["default_body_arch"], route
                    assert PREFIX not in body_arch, route
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        upstream.shutdown()
        upstream.server_close()


if __name__ == "__main__":
    main()


def test_ingress_action_help_rewrite() -> None:
    from conftest import require_tool

    require_tool("nginx")
    require_tool("curl")
    main()
