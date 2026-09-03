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
check(config.get("arch") == ["amd64", "aarch64"], "only amd64 and aarch64 are allowed")
check(config.get("ingress") is True, "ingress must be enabled")
check(config.get("ingress_stream") is True, "ingress_stream must be enabled")
check(config.get("ingress_port") == 8099, "ingress port must be 8099")
check("ports" not in config and "ports_description" not in config and "webui" not in config, "LAN port publication is forbidden")
check(config.get("backup") == "cold", "cold backup is required")
check(config.get("watchdog") == "http://[HOST]:[PORT:8099]/api/health", "watchdog must use ingress health route")
check(config.get("options") == {} and config.get("schema") == {}, "add-on options/schema must stay empty (no provider secrets)")
check("map" not in config, "host/add-on path maps are forbidden")
check(config.get("image") == "ghcr.io/woowtech/woow-ha-opendesign-{arch}", "architecture image pattern mismatch")
upstream_image = "ghcr.io/nexu-io/od:0.21.1@sha256:441daca881e699657bacf28e0c27b16cd6be551dfff4bd63368dd74bec581f39"
local_build_image = "ghcr.io/nexu-io/od:0.21.1"
check(build.get("build_from") == {"amd64": local_build_image, "aarch64": local_build_image}, "Supervisor local builds must use the supported OpenDesign 0.21.1 tag syntax")
check(package.get("dependencies") == {"playwright-core": "1.55.0"}, "renderer dependency must remain exactly pinned")

dockerfile = (ROOT / "Dockerfile").read_text()
launcher = (ROOT / "rootfs/usr/local/bin/ha-opendesign").read_text()
entry = (ROOT / "rootfs/opt/ha-opendesign/headless-entry.mjs").read_text()
renderer = (ROOT / "rootfs/opt/ha-opendesign/headless-renderer.mjs").read_text()
export_bridge = (ROOT / "rootfs/opt/ha-opendesign/ha-export-bridge.js").read_text()
nginx = (ROOT / "rootfs/etc/nginx/nginx.conf").read_text()
workflow_text = (ROOT / ".github/workflows/build.yml").read_text()
runtime_sources = "\n".join([
    dockerfile,
    launcher,
    entry,
    renderer,
    export_bridge,
    nginx,
    (ROOT / "runtime/package.json").read_text(),
])

check(re.search(rf"^ARG BUILD_FROM={re.escape(upstream_image)}$", dockerfile, re.M), "Dockerfile base must pin the approved upstream digest")
check("EXPOSE" not in dockerfile, "Dockerfile must not expose a port")
check("OD_DATA_DIR=/data/opendesign" in dockerfile, "OD_DATA_DIR persistence is missing")
check("OD_BIND_HOST=127.0.0.1" in dockerfile, "Dockerfile must set loopback bind")
check(re.search(r"^USER root$", dockerfile, re.M), "PID 1 must start as root to prepare HA's root-owned /data mount")
check("su-exec open-design:open-design" in launcher, "launcher must drop OpenDesign and nginx to UID/GID 1001")
check("prepare_owned_dir" in launcher and "chown -h" in launcher, "privileged /data preparation must reject/fail closed on symlinks")
check("/usr/sbin/nginx -e stderr" in launcher, "unprivileged nginx must use its inherited stderr descriptor under HA procfs")
for expected in ["bash", "chromium", "font-noto-cjk", "font-noto-emoji", "fontconfig", "nginx", "su-exec"]:
    check(expected in dockerfile, f"expected image package missing: {expected}")
check("/usr/local/bin/npm ci --omit=dev" in dockerfile, "locked production npm install must use the upstream absolute npm path for HA BuildKit")
check("test -x /usr/local/bin/npm" in dockerfile, "image build must verify the absolute npm executable")
check("startServer" in entry and "desktopSlideRenderer: renderSlides" in entry, "slide renderer injection missing")
check("desktopPdfExporter" not in entry and "exportPdf" not in entry, "misleading desktop vector PDF exporter must not be injected")
check("host = '127.0.0.1'" in entry, "OpenDesign entry must bind loopback")
check("wait -n" in launcher and "terminate_children" in launcher, "two-process watchdog launcher missing")
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
check("/tmp/ha-opendesign-nginx" in nginx, "unprivileged nginx temp paths missing")
check("error_log stderr" in nginx and "access_log off" in nginx, "unprivileged nginx must not reopen HA Supervisor log pipes through /dev")
check("container-smoke.sh" in workflow_text and "load: true" in workflow_text, "real amd64 container smoke lane missing")
check("linux/amd64" in workflow_text and "linux/arm64" in workflow_text, "CI architecture matrix is incomplete")
check("ghcr.io/woowtech/woow-ha-opendesign-${{ matrix.arch }}" in workflow_text, "CI GHCR architecture image name mismatch")
check("latest" not in workflow_text.lower(), "CI must not publish a latest tag")
check(workflow.get("permissions") == {"contents": "read"}, "top-level workflow permissions must be contents:read only")
check(upstream_image in workflow_text, "workflow build inputs must pin the approved upstream digest")
for action_ref in re.findall(r"uses:\s*[^\s]+@([^\s#]+)", workflow_text):
    check(bool(re.fullmatch(r"[0-9a-f]{40}", action_ref)), f"GitHub Action is not pinned to a full commit SHA: {action_ref}")

for pattern, label in [
    (r"(?:^|[\s=:/])docker\.sock(?:$|[\s])", "container socket"),
    (r"(?:^|\s)--privileged(?:\s|$)", "privileged mode"),
    (r"(?:^|\s)--network[= ]host(?:\s|$)", "host networking"),
    (r"(?:^|\s)(?:claude|codex|opencode)(?:@|\s|$)", "local AI CLI package"),
    (r"@(?:mariozechner|earendil-works)/pi-coding-agent", "Pi AI CLI package"),
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
