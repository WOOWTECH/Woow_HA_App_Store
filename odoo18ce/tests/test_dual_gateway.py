#!/usr/bin/env python3
"""Manifest, config-script and nginx gateway contracts.

Ported from the former tests/test-dual-gateway.sh. Every assertion here is a
contract about the shipped files; nothing needs a live Odoo.
"""
import re
import subprocess
from pathlib import Path

import yaml

from conftest import require_tool
from test_ingress_router_rewrite import resolve_splices

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
DOCKERFILE = ROOT / "Dockerfile"
CONFIG_SCRIPT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"
POSTGRES_INIT = ROOT / "rootfs/etc/cont-init.d/00-postgres-init.sh"
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
BOOTSTRAP = ROOT / "rootfs/usr/local/bin/odoo-maintenance-bootstrap"
# Odoo imports this module in every process through server_wide_modules; it
# is installed in no database. See tests/test_base_url_guard.py.
SERVER_ADDONS_DIR = "/opt/woow-server-addons"
GUARD_MODULE = "woow_base_url_guard"
# The file nginx includes the Generated rewrites from (ADR 0005). It lives on
# /data because the running add-on rewrites it between starts.
GENERATED_REWRITES = "/data/nginx-generated-rewrites.conf"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_manifest_contract() -> None:
    c = yaml.safe_load(read(CONFIG))
    assert c["ingress"] is True
    assert c["ingress_port"] == 5691
    assert c["ingress_entry"] == "odoo"
    assert c["ingress_stream"] is True
    # The origin ports are published so the LAN can reach Odoo directly; the
    # privilege split is enforced by source address inside nginx, not by
    # hiding the ports.
    assert c["ports"]["8069/tcp"] == 8069
    assert c["ports"]["8072/tcp"] == 8072
    assert c["schema"]["lan_networks"] == "str?"
    assert c["options"]["lan_networks"] == "192.168.0.0/16 10.0.0.0/8 172.16.0.0/12"
    # 8072 only carries the gevent WebSocket while Odoo runs multi-process.
    assert c["options"]["workers"] > 0
    # Supervisor API access is on since 0.4.2: the maintenance bootstrap reads
    # the host LAN address and the published 8069 port for the Ingress-only
    # Canonical URL. The default role is enough for those two /info calls.
    assert c["hassio_api"] is True
    assert "hassio_role" not in c
    assert all("backup" not in str(x) for x in c["map"])
    assert c["schema"]["public_url"] == "url?"
    assert "public_url" not in c["options"]


def test_dockerfile_pins() -> None:
    d = read(DOCKERFILE)
    assert re.search(r'ARG ODOO_DEB_VERSION="18\.0\.\d{8}"', d)
    assert re.search(r'ARG ODOO_DEB_SHA256="[0-9a-f]{64}"', d)
    assert re.search(r'ARG WOOW_ADDONS_REF="[0-9a-f]{40}"', d)
    assert "odoo-jsonrpc-filter" in d


def test_config_script_contract() -> None:
    s = read(CONFIG_SCRIPT)
    # gevent must not sit on 8072: nginx owns that port so the gate applies there.
    assert "gevent_port = 8073" in s
    assert "WS_PORT=8073" in s
    assert "gevent_port = 8072" not in s
    assert "http_interface = 127.0.0.1" in s
    assert "http_port = 8070" in s
    assert "proxy_mode = True" in s
    # Operator-supplied CIDRs are rendered straight into an nginx geo block, so
    # anything malformed has to fail start-up rather than inject a directive.
    assert "lan_networks entry is not an IPv4/IPv6 CIDR" in s
    assert "exit 1" in s
    for placeholder in ["%%LAN_NETWORKS%%", "%%PUBLIC_HOST_MAP%%", "%%DENY_STATUS%%"]:
        assert placeholder in s, placeholder
    # Without public_url no Host may reach the public tier, and off-LAN is 503.
    assert "PUBLIC_HOST_MAP=''" in s
    assert "DENY_STATUS='503'" in s
    assert "DENY_STATUS='444'" in s
    # Odoo's own web.base.url guess is disabled by a server-wide module, so
    # the maintenance bootstrap stays the only writer of the Canonical URL.
    assert f"server_wide_modules = base,web,{GUARD_MODULE}" in s
    # The module is imported by name, so the directory holding it has to be
    # on the rendered addons_path and has to ship in the image.
    base_addons = re.search(r'^BASE_ADDONS="([^"]+)"', s, re.M)
    assert base_addons, "BASE_ADDONS is not one double-quoted, comma-separated list"
    assert SERVER_ADDONS_DIR in base_addons.group(1).split(",")
    shipped = ROOT / "rootfs" / SERVER_ADDONS_DIR.lstrip("/") / GUARD_MODULE
    assert (shipped / "__manifest__.py").is_file()
    assert (shipped / "__init__.py").is_file()
    # nginx refuses to start while the included file is missing, so a fresh
    # install needs an empty one. An existing file is the last good generation
    # the running add-on wrote and is never truncated here.
    assert f'GENERATED_REWRITES="{GENERATED_REWRITES}"' in s
    assert 'if [ ! -e "${GENERATED_REWRITES}" ]; then\n' in s
    truncations = re.findall(r'^[ \t]*: > "\$\{GENERATED_REWRITES\}"', s, re.M)
    assert len(truncations) == 1, "the include file may only be created, never overwritten"
    assert s.index('if [ ! -e "${GENERATED_REWRITES}" ]') < s.index(': > "${GENERATED_REWRITES}"')


def test_nginx_template_contract() -> None:
    n = read(TEMPLATE)
    for text in [
        "listen 8069",
        "listen 5691",
        "server 127.0.0.1:%%WS_PORT%%",
        "/web/database/",
        "http_x_ingress_path",
        "HTMLFormElement",
    ]:
        assert text in n, text

    # --- 8069 origin: LAN tier vs Cloudflare tunnel ---
    # The tunnel reaches this listener from the add-on network, and the default
    # LAN list (172.16.0.0/12) contains that network. This single carve-out is
    # what keeps the tunnel off the LAN tier, so assert it literally.
    assert "172.30.32.0/23      0;" in n, "hassio IPv4 carve-out missing"
    assert "fd0c:ac1e:2100::/48 0;" in n, "hassio IPv6 carve-out missing"
    # The bridge address must never be promoted back into the LAN tier: the
    # Cloudflare tunnel is host-networked on real deployments and arrives from
    # it, which would publish the database manager to the internet.
    geo = n.split("geo $woow_lan_src")[1].split("}")[0]
    lan_entries = re.findall(r"^\s*([0-9a-fA-F.:]+/\d+)\s+1;", geo, re.M)
    assert not any(
        e.startswith("172.30.32.") or e.startswith("172.30.33.") for e in lan_entries
    ), f"bridge/add-on network must not be LAN: {lan_entries}"
    assert "%%LAN_NETWORKS%%" in n

    # Database lifecycle is LAN-only; every entry point must be gated.
    for loc in ["location ^~ /web/database/", "location = /xmlrpc/db", "location = /xmlrpc/2/db"]:
        i = n.index(loc)
        assert 'if ($woow_origin_gate != "lan") { return 404; }' in n[i : i + 220], loc

    # Off-LAN callers that present no recognised Host are dropped outright, on
    # the WebSocket origin as well as the HTTP one.
    assert n.count('if ($woow_origin_gate = "deny") { return %%DENY_STATUS%%; }') == 2
    # Odoo binds gevent to loopback, so nginx has to own the published 8072
    # port and the worker has to sit on an internal one.
    assert "listen 8072 default_server;" in n
    # An unset public_url must not leave a Host that maps to the public tier.
    assert "map $http_host $woow_public_host" in n
    assert "%%PUBLIC_HOST_MAP%%" in n
    # The LAN talks to Odoo directly; the tunnel keeps the RPC policy filter.
    assert '"lan"   "127.0.0.1:8070";' in n
    assert 'default "127.0.0.1:8071";' in n
    assert "proxy_pass http://$woow_jsonrpc_upstream;" in n
    # A Secure cookie over plain LAN http is never returned by the browser, so
    # the tunnel's pinned scheme -- and not the LAN's -- is what makes the
    # cookie Secure. This map is the only source of that decision; which
    # locations apply it is pinned by
    # test_every_odoo_location_rewrites_the_session_cookie.
    assert "map $woow_origin_proto $woow_origin_cookie_secure" in n
    assert '"https" "secure";' in n
    assert 'default "nosecure";' in n
    assert "proxy_set_header X-Forwarded-Proto $woow_origin_proto;" in n
    # The old unconditional guard must be gone, not merely bypassed.
    assert "%%PUBLIC_HOST_GUARD%%" not in n
    assert "location ^~ /web/database/ { return 404; }" not in n
    for placeholder in ["%%DENY_STATUS%%", "%%PUBLIC_HOST_MAP%%", "%%PUBLIC_PROTO%%"]:
        assert placeholder in n

    # --- ingress adapter ---
    assert "while(q.indexOf(P+P)===0)" in n
    assert "absolute_redirect off;" in n
    assert "(?<odoo_redirect>/.*)" in n
    assert "window.SharedWorker=function" in n
    assert 'Object.defineProperty(navigator.serviceWorker,"controller"' in n
    assert "sub_filter '&#39;/web/login&#39;'" in n
    assert "sub_filter '<head>'" in n
    assert "u instanceof URL" in n
    assert "location ^~ /web/assets/" in n
    assert "translationURL" in n
    assert 'browser.location.origin+"$safe_ingress_path"+router.stateToUrl' in n
    assert "params.serverURL}$safe_ingress_path/bus/websocket_worker_bundle" in n
    assert 'serverURL.replace("http", "ws")}$safe_ingress_path/websocket' in n
    assert 'serverURL:window.origin+"$safe_ingress_path"' not in n
    assert "odoo:websocket_shared_worker_%%INGRESS_CACHE_VERSION%%" in n
    assert "websocket_worker_bundle?woow_ingress=%%INGRESS_CACHE_VERSION%%&v=" in n
    assert "%%INGRESS_CACHE_VERSION%%" in n
    assert 'Cache-Control "no-store, no-cache, must-revalidate"' in n
    assert "navigator.serviceWorker.getRegistrations" in n
    assert 'r.scope.indexOf("/odoo")' in n
    assert "woow-odoo-sw-clean-%%INGRESS_CACHE_VERSION%%" in n
    assert "sub_filter '\"src\": \"/'" in n
    assert "sub_filter '\"/my/'" in n
    assert "sub_filter '\"/calendar/'" in n
    assert "sub_filter '\"/base_setup/'" in n
    assert "sub_filter '\"icon\":\"/'" in n
    assert "sub_filter '\"imgurl\":\"/'" in n
    assert ".settings_tab a.tab" not in n
    assert 'if(u.charAt(0)==="#")return u' in n
    assert "href^='#'" not in n
    assert 'HTMLImageElement.prototype,"srcset"' in n
    # Group A of the #169 decision: the injection ways the shim covers. Each is
    # one wrapper in the shim's existing pattern, and the SVG <use> reference
    # is covered through both APIs that set it.
    assert "navigator.sendBeacon=function" in n
    assert "window.EventSource=function" in n
    assert "window.EventSource.prototype=ES.prototype" in n
    assert "window.EventSource.CONNECTING=ES.CONNECTING" in n
    assert "Element.prototype.setAttributeNS=function" in n
    assert 'n==="xlink:href"' in n
    # Media sources (#159): the `Audio` constructor and the `src` setters of the
    # media and `<source>` prototypes, through the same path() and prop() helpers.
    assert "window.Audio=function" in n
    assert "window.Audio.prototype=AU.prototype" in n
    assert 'prop(window.HTMLMediaElement&&HTMLMediaElement.prototype,"src")' in n
    assert 'prop(window.HTMLSourceElement&&HTMLSourceElement.prototype,"src")' in n
    # They are the tail of the prefix script's closure, spliced in by variable
    # reference because that script nearly fills nginx's parameter buffer -- and
    # so is the URL helper the shim publishes for the `location` writes a
    # Literal rewrite has to prefix itself (#174), which closes the closure.
    assert "$ingress_injection_hooks_shim$ingress_url_global_shim})()" in n
    assert 'Object.defineProperty(window,"__WOOW_INGRESS_URL__"' in n
    assert "return 302 $safe_ingress_path/odoo" not in n
    assert n.count("proxy_set_header X-Forwarded-Proto $ingress_proto;") >= 3
    assert "proxy_set_header Origin $ingress_proto://$http_host;" in n
    assert "map $ingress_proto $ingress_cookie_secure" in n
    assert "proxy_hide_header X-Frame-Options;" in n
    assert "location = /xmlrpc/2/db" in n
    assert "window.WebSocket.OPEN=W.OPEN" in n
    assert "$request_method $uri $server_protocol" in n
    assert "$http_referer" not in n
    assert "$sent_http_x_frame_options" in n
    assert "$upstream_http_x_frame_options" in n
    assert (ROOT / "tests/e2e_adversarial.py").is_file()

    # --- generated rewrites (ADR 0005) ---
    # Exactly one include, inside the Ingress asset location and written after
    # the hand-written rules, so the block reads Shipped first then Generated.
    # Precedence does not come from that order: the two sets never hold the
    # same prefix, which is what keeps them from competing.
    assert n.count(f"include {GENERATED_REWRITES};") == 1
    ingress = n[n.index("# HA Supervisor Ingress adapter.") :]
    assets_start = ingress.index("location ^~ /web/assets/ {")
    assets = ingress[assets_start : ingress.index("\n        location / {", assets_start)]
    assert f"include {GENERATED_REWRITES};" in assets
    assert assets.rindex("include ") > assets.rindex("sub_filter ")
    # Everything before the Ingress adapter -- the 8069 origin listener and
    # the 8072 websocket listener -- stays untouched by the generated file.
    listeners = n[n.index("# Origin listener.") : n.index("# HA Supervisor Ingress adapter.")]
    assert "listen 8072 default_server;" in listeners
    assert GENERATED_REWRITES not in listeners

    # --- entity-quoted url(...) in page HTML (issue #166) ---
    # QWeb escapes attribute values, so a website snippet's inline background
    # arrives as style="background-image: url(&#39;/web/image/...&#39;)". The
    # three raw-quote rules match none of those forms, so each form the
    # escaper can produce carries a rule of its own in the generic HTML
    # location -- and only there: bundles hold no HTML entities.
    generic = ingress[ingress.index("\n        location / {") :]
    raw_url_rules = [
        "sub_filter 'url(/' 'url($safe_ingress_path/';",
        "sub_filter \"url('/\" \"url('$safe_ingress_path/\";",
        "sub_filter 'url(\"/' 'url(\"$safe_ingress_path/';",
    ]
    entity_url_rules = [
        "sub_filter 'url(&#39;/' 'url(&#39;$safe_ingress_path/';",
        "sub_filter 'url(&#34;/' 'url(&#34;$safe_ingress_path/';",
        "sub_filter 'url(&quot;/' 'url(&quot;$safe_ingress_path/';",
        "sub_filter 'url(&#x27;/' 'url(&#x27;$safe_ingress_path/';",
    ]
    for rule in raw_url_rules:
        assert rule in generic, rule
        assert rule in assets, rule
    for rule in entity_url_rules:
        assert rule in generic, rule
        assert rule not in assets, rule
        assert rule not in listeners, rule

    # --- a website form's success page (issue #167) ---
    # A website form carries its confirmation target as an attribute of the
    # server-rendered page -- data-success-page="/contactus-thank-you" -- and
    # the form script assigns that path to the page location once the submit
    # RPC answers. The five attribute rules rewrite href/src/action/data-src/
    # srcset and nothing else, so the value arrived bare and the thank-you page
    # was asked of the Home Assistant root. The rule is one more member of that
    # group, in the generic HTML location where page HTML is served, and on the
    # Ingress listener only.
    srcset_rule = "sub_filter 'srcset=\"/' 'srcset=\"$safe_ingress_path/';"
    # Two spellings: the attribute Odoo 18 writes, and the one a form saved
    # before Odoo 14 left in the arch, which the form script still falls back
    # to when `data-success-mode` is absent.
    success_rules = [
        "sub_filter 'data-success-page=\"/' 'data-success-page=\"$safe_ingress_path/';",
        "sub_filter 'data-success_page=\"/' 'data-success_page=\"$safe_ingress_path/';",
    ]
    masked = mask_strings_and_comments(ingress)
    generic_start = ingress.index("\n        location / {")
    opener = masked.index("location / {", generic_start)
    generic_only = ingress[generic_start : block_end(masked, opener + len("location / {") - 1) + 1]
    written = [
        line.strip()
        for line in generic_only.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]
    # Beside the attribute group they belong to, and written after it so the
    # group keeps reading as one thing.
    at = written.index(srcset_rule) + 1
    assert written[at : at + len(success_rules)] == success_rules, written
    for rule in success_rules:
        assert rule not in assets, "page HTML only: no bundle carries the attribute"
        assert rule not in listeners, "ingress listener only"
        # The action-load copy of the generic location carries them too, because
        # that location is the generic one plus its escaped-quote rules; the
        # equality in test_ingress_action_help.py is what pins that.
        assert ingress.count(rule) == 2, rule


# --- cookie flags per location (issue #165) ---
# Odoo saves the session on its websocket route too and answers the handshake
# with its own `Set-Cookie: session_id`. Cookie flag treatment is therefore a
# property of the surface, not of one location: every location that proxies to
# Odoo has to rewrite that cookie the way its surface's `location /` does, or
# the first bus socket replaces the browser's good cookie with a bare one.
ORIGIN_COOKIE_FLAGS = "proxy_cookie_flags session_id $woow_origin_cookie_secure httponly samesite=lax;"
INGRESS_COOKIE_FLAGS = "proxy_cookie_flags session_id $ingress_cookie_secure httponly samesite=lax;"
INGRESS_COOKIE_PATH = "proxy_cookie_path / $safe_ingress_path/;"
# Every `proxy_pass` in this template goes to Odoo -- `odoo_http`,
# `odoo_websocket`, or `$woow_jsonrpc_upstream`, which maps to the Odoo HTTP
# worker or to the RPC policy filter in front of it. So the rule reads every
# proxying location rather than an allow-list of upstream names: a location
# added with a target this file has not seen has to be decided on, not
# silently skipped.


def mask_strings_and_comments(text: str) -> str:
    """Blank out quoted parameters and comments, keeping every byte offset.

    The Ingress locations carry sub_filter rules whose JavaScript holds braces,
    so the block structure is only readable once quoted text is out of the way.
    """
    out = []
    quote = None
    comment = False
    escaped = False
    for ch in text:
        if comment:
            comment = ch != "\n"
            out.append(ch if ch == "\n" else " ")
        elif quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            out.append(ch if ch == "\n" else " ")
        elif ch in "'\"":
            quote = ch
            out.append(" ")
        elif ch == "#":
            comment = True
            out.append(" ")
        else:
            out.append(ch)
    assert quote is None, "unterminated quoted parameter in the template"
    return "".join(out)


def block_end(masked: str, brace: int) -> int:
    depth = 0
    for i in range(brace, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("unbalanced braces in the template")


def proxying_locations(template: str) -> list:
    """(listen port, location header, body) per location that proxies upstream."""
    masked = mask_strings_and_comments(template)
    found = []
    for server in re.finditer(r"\bserver\s*\{", masked):
        start, end = server.end() - 1, block_end(masked, server.end() - 1)
        listen = re.search(r"\blisten\s+(\S+)", masked[start:end])
        assert listen, "a server block with no listen directive"
        port = listen.group(1).rstrip(";")
        for loc in re.finditer(r"\blocation\s+([^{]+?)\s*\{", masked[start:end]):
            loc_start = start + loc.end() - 1
            body = template[loc_start : block_end(masked, loc_start) + 1]
            if re.search(r"\bproxy_pass\s", body):
                found.append((port, f"location {loc.group(1)}", body))
    return found


def cookie_flag_violations(template: str) -> list:
    """Locations whose cookie rewriting does not match their surface's."""
    violations = []
    for port, header, body in proxying_locations(template):
        required = [INGRESS_COOKIE_FLAGS, INGRESS_COOKIE_PATH] if port == "5691" else [ORIGIN_COOKIE_FLAGS]
        for directive in required:
            if directive not in body:
                violations.append(f"{port} {header}: missing {directive}")
    return violations


def test_every_odoo_location_rewrites_the_session_cookie() -> None:
    template = read(TEMPLATE)
    # Pin the inventory as well as the rule: a parser that found nothing would
    # satisfy the rule vacuously, and a new Odoo location has to be decided on.
    assert sorted((port, header) for port, header, _ in proxying_locations(template)) == [
        ("5691", "location /"),
        # The one action-dict route it is safe to rewrite: a copy of the
        # Ingress `location /` plus the action-help rules (issue #158).
        ("5691", "location = /web/action/load"),
        ("5691", "location = /websocket"),
        ("5691", "location ^~ /web/assets/"),
        ("8069", "location /"),
        ("8069", "location = /jsonrpc"),
        ("8069", "location = /websocket"),
        ("8069", "location = /xmlrpc/2/db"),
        ("8069", "location = /xmlrpc/db"),
        ("8069", "location ^~ /web/database/"),
        ("8072", "location /"),
    ]
    assert cookie_flag_violations(template) == []


def test_a_location_that_drops_the_cookie_flags_is_caught() -> None:
    # The gap this rule closes, reintroduced: the 8069 websocket handshake
    # answers with Odoo's own `session_id`, without Secure and without
    # SameSite, and the browser replaces the cookie `location /` had set.
    template = read(TEMPLATE)
    websocket = template.index("location = /websocket")
    flagless = template[:websocket] + template[websocket:].replace(f"\n            {ORIGIN_COOKIE_FLAGS}", "", 1)
    assert flagless != template
    assert cookie_flag_violations(flagless) == [f"8069 location = /websocket: missing {ORIGIN_COOKIE_FLAGS}"]

    # A location added with a target this file has not seen -- an address
    # rather than one of the named upstreams -- is read by the same rule.
    added = template.replace(
        "        location = /jsonrpc {",
        "        location = /web/login {\n            proxy_pass http://127.0.0.1:8070;\n        }\n        location = /jsonrpc {",
        1,
    )
    assert cookie_flag_violations(added) == [f"8069 location = /web/login: missing {ORIGIN_COOKIE_FLAGS}"]


def test_maintenance_bootstrap_contract() -> None:
    # String presence only; the decision logic is covered by
    # test_maintenance_bootstrap.py.
    m = read(BOOTSTRAP)
    assert "/usr/local/lib/odoo-maintenance.py" in m
    assert "web.base.url.freeze" in read(ROOT / "rootfs/usr/local/lib/odoo-maintenance.py")
    assert "bootstrap-user.json" in m
    assert "root:600" in m
    assert "must contain at least 20 characters" in m
    account = read(ROOT / "rootfs/usr/local/lib/odoo-maintenance-account.py")
    assert "base.group_system" in account
    assert "base.group_erp_manager" in account


def test_postgres_init_contract() -> None:
    pg = read(POSTGRES_INIT)
    assert "local   all       all                  peer" in pg
    assert "--auth-local=peer" in pg


def runtime_shim_source() -> str:
    source = read(TEMPLATE)
    map_start = source.index("map $upstream_http_content_type $ingress_runtime_shim {")
    map_end = source.index("\n    }", map_start)
    runtime_shim = source[map_start:map_end]
    assert '"~*^text/html(?:;|$)"' in runtime_shim, "runtime shim must be limited to HTML upstream responses"
    match = re.search(r"<script>(.*?)</script>';", runtime_shim, re.S)
    assert match, "HTML runtime shim not found"
    # The injection-way hooks (#169) are spliced in from a map of their own,
    # so the script the page gets is longer than the one written here.
    script = resolve_splices(source, match.group(1))
    return script.replace("$safe_ingress_path", "/P").replace("%%INGRESS_CACHE_VERSION%%", "V")


def test_runtime_shim_is_valid_javascript(tmp_path: Path) -> None:
    node = require_tool("node")
    shim = tmp_path / "shim.js"
    shim.write_text(runtime_shim_source(), encoding="utf-8")
    result = subprocess.run([node, "--check", str(shim)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


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


def render_scenarios(test_dir: Path, include_text: str = "") -> dict:
    """Render the template for both real-world shapes: public_url set and unset.

    The Generated rewrite file is redirected into `test_dir` and written with
    `include_text`, so a rendering run never depends on a container's /data.
    """
    template = read(TEMPLATE)
    generated = test_dir / "generated-rewrites.conf"
    generated.write_text(include_text, encoding="utf-8")
    common = {
        "%%WS_PORT%%": "8070",
        "%%PUBLIC_PROTO%%": "https",
        "%%LAN_NETWORKS%%": "192.168.0.0/16 1; 10.0.0.0/8 1; 172.16.0.0/12 1;",
        "%%INGRESS_CACHE_VERSION%%": "test",
    }
    scenarios = {
        "public": dict(common, **{
            "%%PUBLIC_HOST_MAP%%": '"odoo-test.invalid" 1; "odoo-test.invalid:443" 1;',
            "%%DENY_STATUS%%": "444",
            "%%CANONICAL_URL%%": "https://odoo-test.invalid",
        }),
        # public_url unset: the host map is empty, so no Host reaches the
        # public tier and every off-LAN caller falls through to the deny status.
        # The Canonical URL is then the host's LAN address with the published
        # Odoo port (RFC 5737 documentation address).
        "lanonly": dict(common, **{
            "%%PUBLIC_HOST_MAP%%": "",
            "%%DENY_STATUS%%": "503",
            "%%CANONICAL_URL%%": "http://192.0.2.10:8069",
        }),
        # public_url unset and the Supervisor reported no LAN address: there
        # is no Canonical URL at all, and the Runtime shim renders an empty
        # global. nginx has to accept that value too (issue #70).
        "lanonly-noaddr": dict(common, **{
            "%%PUBLIC_HOST_MAP%%": "",
            "%%DENY_STATUS%%": "503",
            "%%CANONICAL_URL%%": "",
        }),
    }
    rendered = {}
    for name, replacements in scenarios.items():
        config = template
        for placeholder, value in replacements.items():
            assert placeholder in template, f"missing template placeholder: {placeholder}"
            config = config.replace(placeholder, value)
        assert "%%" not in config, f"unrendered placeholder remains in {name}"
        assert config.count(f"include {GENERATED_REWRITES};") == 1
        config = config.replace(f"include {GENERATED_REWRITES};", f"include {generated};")
        config = config.replace("pid /var/run/nginx.pid;", f"pid {test_dir}/{name}.pid;")
        config = config.replace("error_log /dev/stderr info;", f"error_log {test_dir}/{name}-error.log info;")
        config = config.replace("access_log /dev/stdout safe;", f"access_log {test_dir}/{name}-access.log safe;")
        # nginx -t opens listener sockets. Use paths inside the unique temporary
        # directory rather than probing and releasing TCP ports, which has a
        # TOCTOU race with other processes.
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


def test_rendered_gateway_configs_are_valid_nginx(tmp_path: Path) -> None:
    nginx = require_tool("nginx")
    # A fresh install has an empty Generated rewrite file; a running one has
    # whatever the Rewrite scan last wrote. Both have to load.
    for variant, include_text in (("empty", ""), ("two-prefix", TWO_PREFIX_INCLUDE)):
        variant_dir = tmp_path / variant
        variant_dir.mkdir()
        for name, config in render_scenarios(variant_dir, include_text).items():
            result = subprocess.run(
                [nginx, "-t", "-p", str(variant_dir), "-c", str(config)],
                capture_output=True, text=True, check=False,
            )
            assert result.returncode == 0, f"{variant}/{name}: {result.stderr}"

def test_prebuilt_image_and_health_contract() -> None:
    c = yaml.safe_load(read(CONFIG))
    # Supervisor pulls the published image; on-device builds ended in 0.4.0.
    assert c["image"] == "ghcr.io/woowtech/woow-ha-odoo-{arch}"
    # With Ingress on, the manifest webui URL is redundant and the add-on
    # linter rejects it; watchdog is replaced by the container HEALTHCHECK.
    assert "webui" not in c
    assert "watchdog" not in c
    d = read(DOCKERFILE)
    assert re.search(r"^HEALTHCHECK .*--start-period=600s", d, re.M)
    assert "http://127.0.0.1:8069/web/login" in d
