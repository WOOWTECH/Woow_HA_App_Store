#!/usr/bin/env python3
from pathlib import Path
import json
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
errors = []

def check(condition, message):
    if not condition:
        errors.append(message)

with (ROOT / "repository.yaml").open() as handle:
    repository = yaml.safe_load(handle)
with (ROOT / "config.yaml").open() as handle:
    config = yaml.safe_load(handle)
with (ROOT / "build.yaml").open() as handle:
    build = yaml.safe_load(handle)
with (ROOT / "runtime/package.json").open() as handle:
    package = json.load(handle)
with (ROOT / ".github/workflows/build.yml").open() as handle:
    workflow = yaml.safe_load(handle)

check(isinstance(workflow, dict) and "jobs" in workflow, "GitHub Actions workflow YAML is invalid")
check(set(repository) == {"name", "url", "maintainer"}, "repository.yaml must have the repository contract keys")
check(repository.get("url") == "https://github.com/WOOWTECH/Woow_ha_opendesign_add_on", "repository URL mismatch")
check(config.get("version") == "0.2.12", "release version must be 0.2.12")
check("browser-local API BYOK" in config.get("description", ""), "add-on description must describe browser-local BYOK")
check(config.get("arch") == ["amd64"], "the core image is amd64-only; only amd64 is allowed")
check(config.get("ingress") is True, "ingress must be enabled")
check(config.get("ingress_stream") is True, "ingress_stream must be enabled")
check(config.get("ingress_port") == 8099, "ingress port must be 8099")
check(config.get("ingress_entry") == "plugins", "ingress_entry must be the relative plugins path; a leading slash makes <token>// URLs that 404")
check(config.get("ports") == {"8081/tcp": None} and set(config.get("ports_description", {})) == {"8081/tcp"} and "webui" not in config, "only the unmapped built-in MCP port 8081 may be declared")
check(not config.get("homeassistant_api") and not config.get("hassio_api") and not config.get("full_access"), "built-in MCP administration relies on Ingress login; no HA/Supervisor API access")
check(config.get("backup") == "cold", "cold backup is required")
check(config.get("watchdog") == "http://[HOST]:[PORT:8099]/api/health", "watchdog must use ingress health route")
check(config.get("options") == {} and config.get("schema") == {}, "add-on options/schema must stay empty (no provider secrets)")
check("map" not in config, "host/add-on path maps are forbidden")
check(config.get("image") == "ghcr.io/woowtech/woow-ha-opendesign-{arch}", "architecture image pattern mismatch")
# The add-on derives from the shared WoowTech OpenDesign core image. Every build
# input names the same published core (digest for CI/Dockerfile, its immutable
# tag for Supervisor local builds), so no build can fall back to upstream OpenDesign.
core_image = "ghcr.io/woowtech/open-design-core:20261029.0033@sha256:c8cd57f07adaef23b8dddbb22a8b75f97bdf8ca42c8bfbec1b284dc60ee5a4cf"
local_core_image = "ghcr.io/woowtech/open-design-core:20261029.0033"
check(build.get("build_from") == {"amd64": local_core_image}, "Supervisor local builds must use the core image (tag syntax, amd64 only)")
check("nexu-io/od" not in (ROOT / "build.yaml").read_text(), "build.yaml must not fall back to the upstream OpenDesign image")
check(package.get("dependencies") == {"playwright-core": "1.55.0"}, "renderer dependency must remain exactly pinned")
dockerfile = (ROOT / "Dockerfile").read_text()
launcher = (ROOT / "rootfs/usr/local/bin/ha-opendesign").read_text()
entry = (ROOT / "rootfs/opt/ha-opendesign/headless-entry.mjs").read_text()
renderer = (ROOT / "rootfs/opt/ha-opendesign/headless-renderer.mjs").read_text()
export_bridge = (ROOT / "rootfs/opt/ha-opendesign/ha-export-bridge.js").read_text()
nginx = (ROOT / "rootfs/etc/nginx/nginx.conf").read_text()
workflow_text = (ROOT / ".github/workflows/build.yml").read_text()
runtime_sources = "\n".join([
    launcher,
    entry,
    renderer,
    export_bridge,
    nginx,
    (ROOT / "runtime/package.json").read_text(),
])

check(re.search(rf"^ARG BUILD_FROM={re.escape(core_image)}$", dockerfile, re.M), "Dockerfile base must match the immutable core pin")
check("nexu-io/od" not in dockerfile, "Dockerfile must not fall back to the upstream OpenDesign image")
check("EXPOSE" not in dockerfile, "Dockerfile must not expose a port")
check("OD_DATA_DIR=/data/opendesign" in dockerfile, "OD_DATA_DIR persistence is missing")
check("OD_BIND_HOST=127.0.0.1" in dockerfile, "Dockerfile must set loopback bind")
check(re.search(r"^USER root$", dockerfile, re.M), "PID 1 must start as root to prepare HA's root-owned /data mount")
check("su-exec open-design:open-design" in launcher, "launcher must drop OpenDesign and ttyd to UID/GID 1001")
check("su-exec ha-ingress:ha-ingress /usr/sbin/nginx" in launcher, "launcher must run nginx as its own ha-ingress UID")
check("no_supervisor_env=(/usr/bin/env -u SUPERVISOR_TOKEN -u HASSIO_TOKEN)" in launcher, "children must not inherit Supervisor credentials")
check(len(re.findall(r'^start_child \w+ \\\n  "\$\{no_supervisor_env\[@\]\}" ', launcher, re.M)) == len(re.findall(r"^start_child ", launcher, re.M)) == 5, "every supervised child must start without Supervisor credentials")
check('"${no_supervisor_env[@]}" /opt/woow/bin/ha-opendesign-mcp' in launcher, "launcher must start the built-in MCP server")
check("RUN python3 /tmp/ha-patches/sign-in-hint.py /app/apps/web/out" in dockerfile, "HA sign-in hint patch must run on the core web build")
check("sh /tmp/mcp-runtime/install.sh" in dockerfile and "FROM ${BUILD_FROM} AS woow-mcp-ui" in dockerfile, "built-in MCP install missing")
check("proxy_pass http://unix:/run/ha-opendesign-mcp/admin.sock:/;" in nginx and nginx.count("allow 172.30.32.2;") == 3 and nginx.count("deny all;") == 3, "MCP admin must be Ingress-peer only over the Unix socket")
# Server-level source restriction (0.2.12): the first directives of the 8099 server block admit only the Supervisor Ingress gateway and
# loopback. Without them every other container on the hassio network (and HA Core on the host network) reached the UI/API, the writable
# /console/ terminal and the Omnigent API with no credentials. Locations that declare their own allow/deny (/mcp-admin, Paseo) replace them.
server_block = nginx.partition("listen 8099 default_server;")[2]
check(server_block != "", "nginx.conf must define the 8099 server block")
server_head = [l.strip() for l in server_block.splitlines() if l.strip() and not l.strip().startswith("#")][:3]
check(server_head == ["allow 172.30.32.2;", "allow 127.0.0.1;", "deny all;"],
      "the 8099 server block must start with allow 172.30.32.2; allow 127.0.0.1; deny all;")
# Every allow/deny directive of the shipped nginx configuration, comments removed (a trailing `# ...` must not hide one). The server level admits the
# Supervisor and loopback; /mcp-admin (two locations) and the Paseo include admit only the Supervisor. A further allow anywhere (a subnet for "another
# add-on", `allow all`, a location that replaces the server-level rules without ending in `deny all`) reopens the exposure this release closes, so the
# whole multiset is pinned rather than a few spellings.
def nginx_code(text):
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())

def nginx_rules(text, directive):
    return sorted(re.findall(rf"\b{directive}\s+([^;\s]+)\s*;", nginx_code(text)))

nginx_dir = ROOT / "rootfs/etc/nginx"
paseo_proxy = (nginx_dir / "paseo-proxy.conf").read_text()
paseo_setup = (nginx_dir / "paseo-setup.conf").read_text()
check(nginx_rules(nginx, "allow") == sorted(["172.30.32.2", "127.0.0.1", "172.30.32.2", "172.30.32.2"]),
      "nginx.conf may allow only the Supervisor (server level and the two /mcp-admin locations) and loopback (server level)")
check(nginx_rules(nginx, "deny") == ["all"] * 3 and nginx_rules(paseo_proxy, "allow") == ["172.30.32.2"] and nginx_rules(paseo_proxy, "deny") == ["all"]
      and nginx_rules(paseo_setup, "allow") == [] and nginx_rules(paseo_setup, "deny") == [],
      "every allow must be paired with `deny all`; paseo-proxy.conf admits only the Supervisor; paseo-setup.conf has no rules of its own")
for directive in ("satisfy", "auth_request", "auth_basic", "error_page", "real_ip_header", "set_real_ip_from", "try_files"):
    check(not re.search(rf"^\s*{directive}\b", nginx_code(nginx) + nginx_code(paseo_proxy) + nginx_code(paseo_setup), re.M),
          f"nginx must not use `{directive}`: it can change which peers pass the source rules (review the access matrix before adding it)")
check(not re.search(r"\blisten\b[^;]*proxy_protocol", nginx_code(nginx)), "nginx must not trust PROXY protocol addresses")
check(config.get("panel_admin") is True, "panel_admin must stay true: it is what keeps non-administrators out of the Ingress panel")
# `return` runs in nginx's rewrite phase, before allow/deny: in this server block it may only issue redirects (301/302) or refusals (403), never content.
server_code = "\n".join(line.split("#", 1)[0] for line in server_block.splitlines())
returns = re.findall(r"\breturn\s+(\d+)", server_code)
check(returns and all(code in ("301", "302", "403") for code in returns),
      "a `return` in the 8099 server block bypasses the peer rules (rewrite phase): only 301/302/403 are allowed, never a content response")
# The Paseo routes include paseo-proxy.conf, whose own allow/deny replaces the server-level rules: it must keep admitting only the Supervisor peer
# (not loopback) and keep its X-Ingress-Path guard. Nothing else exercises this file's access rules without Ingress-shaped headers.
paseo_proxy_head = [l.strip() for l in (ROOT / "rootfs/etc/nginx/paseo-proxy.conf").read_text().splitlines() if l.strip() and not l.strip().startswith("#")][:3]
check(paseo_proxy_head == ["allow 172.30.32.2;", "deny all;", 'if ($safe_ingress_path = "") { return 403; }'],
      "paseo-proxy.conf must start with allow 172.30.32.2; deny all; and the X-Ingress-Path guard")
check(re.search(r"chown -R root:root /opt/ha-opendesign(\s|;|$)", dockerfile) and "chown -R open-design:open-design /opt/ha-opendesign" not in dockerfile,
      "/opt/ha-opendesign must be root-owned: UID 1001 (agents, Omnigent sessions) must not rewrite scripts served into the HA browser")

check("npm" not in launcher.lower(), "launcher must not download/install CLI packages at startup")
check("shared-agents.mjs" not in launcher, "OpenDesign-native plugin/skill registries must not be replaced by startup symlinks")
for setting in ["HA_OPENDESIGN_HOME=", "CLAUDE_CONFIG_DIR=", "CODEX_HOME=", "PI_CODING_AGENT_DIR=", "XDG_CONFIG_HOME="]:
    check(setting in launcher, f"launcher must pin the CLI config location: {setting}")
check((ROOT / "rootfs/usr/local/bin/ha-opendesign-agents").exists(), "shared agent status/sync CLI is missing")
check((ROOT / "tests/shared-agents.test.mjs").exists(), "shared agent integration tests are missing")
check("sh /tmp/paseo-runtime/install.sh" in dockerfile and "start_child paseo" in launcher, "shared Paseo runtime must be installed and supervised")
# The legacy external supervisor remains absent; the native daemon owns Omnigent.
check(not (ROOT / "rootfs/etc/omnigent-host").exists() and not (ROOT / "rootfs/etc/profile.d/omnigent-host.sh").exists(), "do not reintroduce a second host supervisor")
check('su-exec open-design:open-design /usr/local/bin/node /opt/ha-opendesign/headless-entry.mjs' in launcher, "OpenDesign must start directly")
check(not re.search(r"^(ENTRYPOINT|CMD) .*omnigent", dockerfile, re.M), "the HA launcher must own PID 1")
check(not re.search(r"OMNIGENT_(?:CONFIG_HOME|DATA_DIR)=", dockerfile), "native private host state must not be overridden globally")
check("prepare_owned_dir" in launcher and "chown -h" in launcher, "privileged /data preparation must reject/fail closed on symlinks")
check("/usr/sbin/nginx -e stderr" in launcher, "unprivileged nginx must use its inherited stderr descriptor under HA procfs")
apk_block = re.search(r"RUN apk add --no-cache(.*?)&& rm -rf", dockerfile, re.S)
check(apk_block is not None, "HA package install step missing")
if apk_block:
    check(apk_block.group(1).split() == ["\\", "nginx", "\\", "su-exec", "\\", "ttyd=1.7.7-r0", "\\"], "only HA-specific packages may be installed over the core")
for core_assertion in [
    "test -f /app/skills/woowtech-brand/SKILL.md",
    "test ! -e /app/skills/brainstorming",
    "fc-list | grep -qi 'Noto Sans CJK'",
    "chromium-browser python3 rg tmux flock setsid nginx ttyd su-exec",
]:
    check(core_assertion in dockerfile, f"core contract assertion missing: {core_assertion}")
check("/usr/local/bin/npm ci --omit=dev" in dockerfile, "locked production npm install must use the upstream absolute npm path for HA BuildKit")
check("test -x /usr/local/bin/npm" in dockerfile, "image build must verify the absolute npm executable")
check(not (ROOT / "runtime/opencode").exists() and "opencode" not in dockerfile.split("COPY runtime/")[1].split("\n")[0], "OpenCode comes from the core image; no add-on OpenCode runtime")
check("npm install --global" not in dockerfile and "npm install -g" not in dockerfile, "agent CLIs come from the core image, not add-on npm installs")
for arg, version in {
    "CORE_OPENDESIGN_VERSION": "0.24.1",
    "CORE_DAEMON_PACKAGE_VERSION": "0.23.1",
    "CORE_CLAUDE_CODE_VERSION": "2.1.296",
    "CORE_CODEX_VERSION": "0.162.1",
    "CORE_PI_VERSION": "1.1.0",
    "CORE_OPENCODE_VERSION": "1.18.33",
}.items():
    check(re.search(rf"^ARG {arg}={re.escape(version)}$", dockerfile, re.M), f"core contract must pin {arg}={version}")
    check(f"${{{arg}}}" in dockerfile, f"core contract must assert {arg}")
check('su-exec open-design:open-design sh -ceu' in dockerfile, "core CLI versions must be asserted as UID 1001")
for removed_path in [
    "runtime/pi",
    "rootfs/usr/local/bin/pi",
    "rootfs/opt/ha-opendesign/ha-pi-wrapper.mjs",
    "rootfs/opt/ha-opendesign/ha-byok-store.mjs",
    "rootfs/opt/ha-opendesign/ha-byok-profiles-bridge.js",
]:
    check(not (ROOT / removed_path).exists(), f"withdrawn persistent BYOK component remains: {removed_path}")
check("ha-byok" not in nginx and "127.0.0.1:7457" not in nginx, "nginx must not expose the withdrawn profile sidecar")
check('wait -n -p exited_pid "${child_pids[@]}"' in launcher and "byok_pid" not in launcher, "launcher must supervise every started child")
for child in ["start_child opendesign", "start_child nginx", "start_child ttyd", "start_child mcp"]:
    check(child in launcher, f"launcher must supervise {child.split()[-1]}")
check("remove_obsolete_credentials" in launcher and "rm -f -- \"$legacy_dir\"" in launcher, "launcher must safely remove obsolete credential symlinks")
check("startServer" in entry and "desktopSlideRenderer: renderSlides" in entry, "slide renderer injection missing")
check("desktopPdfExporter" not in entry and "exportPdf" not in entry, "misleading desktop vector PDF exporter must not be injected")
check("host = '127.0.0.1'" in entry, "OpenDesign entry must bind loopback")
check("wait -n" in launcher and "terminate_children" in launcher, "watchdog launcher missing")
check("SHUTDOWN_GRACE_SECONDS" in launcher and "kill -KILL" in launcher, "bounded TERM-to-KILL shutdown missing")
check("canonicalizeOutputDir" in renderer and "canonical outputDir escapes" in renderer, "canonical output confinement missing")
check("evaluateRequestPolicy" in renderer and "allowPublicHttpAssets: true" in renderer, "renderer network policy missing")
check("context.route" in renderer and "serviceWorkers: 'block'" in renderer, "renderer policy must cover popups/workers")
check("context.routeWebSocket" in renderer and "WebSockets disabled in renderer" in renderer, "renderer must block WebSockets at browser-context level")
check("new Semaphore(1)" in renderer and "MAX_REMOTE_FETCHES" in renderer, "renderer concurrency controls missing")
check("runWithAbsoluteDeadline" in renderer and "AbortController" in renderer, "renderer absolute abortable deadline missing")
check("mkdtemp('/tmp/ha-opendesign-chromium-')" in renderer and "XDG_CONFIG_HOME" in renderer and "XDG_CACHE_HOME" in renderer, "renderer Chromium must use an ephemeral writable HOME/XDG profile")
check("--disable-web-security" not in renderer, "renderer must not disable browser web security")
check("redirectPdfRequest" in export_bridge and "/export/image" in export_bridge, "browser PDF/image export bridge missing")
check("proxy_pass http://127.0.0.1:7456" in nginx, "nginx may only forward to loopback OpenDesign")
check("proxy_pass http://127.0.0.1:7681;" in nginx and "location ^~ /console/" in nginx, "interactive CLI TTY must be routed only through nginx (/console/)")
check("/tmp/ha-opendesign-nginx" in nginx, "unprivileged nginx temp paths missing")
check("error_log stderr" in nginx and "access_log off" in nginx, "unprivileged nginx must not reopen HA Supervisor log pipes through /dev")
check("container-smoke.sh" in workflow_text and "load: true" in workflow_text, "real amd64 container smoke lane missing")
check("linux/amd64" in workflow_text and "linux/arm64" not in workflow_text and "aarch64" not in workflow_text, "CI must build amd64 only")
check("ghcr.io/woowtech/woow-ha-opendesign-${{ matrix.arch }}" in workflow_text, "CI GHCR architecture image name mismatch")
check("latest" not in workflow_text.lower(), "CI must not publish a latest tag")
check(workflow.get("permissions") == {"contents": "read"}, "top-level workflow permissions must be contents:read only")
check(core_image in workflow_text and "nexu-io/od" not in workflow_text, "workflow build inputs must use the core image")
for action_ref in re.findall(r"uses:\s*[^\s]+@([^\s#]+)", workflow_text):
    check(bool(re.fullmatch(r"[0-9a-f]{40}", action_ref)), f"GitHub Action is not pinned to a full commit SHA: {action_ref}")

for pattern, label in [
    (r"(?:^|[\s=:/])docker\.sock(?:$|[\s])", "container socket"),
    (r"(?:^|\s)--privileged(?:\s|$)", "privileged mode"),
    (r"(?:^|\s)--network[= ]host(?:\s|$)", "host networking"),
    (r"(?:^|\s)(?:aider|gemini|cursor-agent|qwen|copilot|amp)(?:@|\s|$)", "unapproved local AI CLI package"),
    (r"/(?:mnt|media|share|config)(?:/|\s|$)", "host path coupling"),
]:
    check(not re.search(pattern, runtime_sources, re.I | re.M), f"forbidden runtime coupling detected: {label}")

for required in ["README.md", "README_zh-TW.md", "DOCS.md", "CHANGELOG.md", "LICENSE"]:
    check((ROOT / required).is_file(), f"missing required file: {required}")

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
print("metadata/runtime validation: OK")
