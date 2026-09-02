#!/usr/bin/env python3
"""Regress n8n preload de-duplication through Supervisor and real nginx."""

from __future__ import annotations

import http.client
import json
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from playwright.sync_api import Page, sync_playwright


ADDON_DIR = Path(__file__).resolve().parents[1]
NGINX_CONFIG = ADDON_DIR / "rootfs/etc/nginx/nginx.conf"
FRAME_HEIGHT_SCRIPT = ADDON_DIR / "rootfs/etc/nginx/ingress-frame-height.js"
INGRESS_PATH = "/api/hassio_ingress/abcdefghijklmnop"
SUPPORTED_N8N_VERSION = "2.12.3"
ROOT_BUILDER = "hee=function(e){return`/`+e}"
PREFIX_BUILDER = "hee=function(e){return(window.BASE_PATH||`/`)+e}"

HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="/assets/BaseLayout.css">
<link rel="stylesheet" href="/assets/index.css">
<script>window.BASE_PATH = '/';</script>
<script type="module" src="/assets/preload.js"></script>
</head><body><div id="app"><div id="n8n-app" class="appGrid app"><div class="natural-content"></div></div></div></body></html>
"""

BASE_LAYOUT_CSS = ".appGrid { height: 100%; }\n"
INDEX_CSS = """html, body { height: 100%; margin: 0; }
.app { height: 100vh; }
.natural-content { height: 489px; }
"""

# This keeps the pinned n8n/Vite root builder and its native duplicate-link
# selector together. The production fix must alter the response, not this fixture.
PRELOAD_JS = r"""const hee=function(e){return`/`+e};
(async function(){
  const e=hee("assets/BaseLayout.css");
  const t=e.endsWith(".css");
  const s=t?'[rel="stylesheet"]':"";
  const existing=document.querySelector(`link[href="${e}"]${s}`);
  if(!existing){
    const l=document.createElement("link");
    l.rel=t?"stylesheet":"modulepreload";
    l.href=e;
    document.head.appendChild(l);
    if(t) await new Promise((resolve,reject)=>{l.addEventListener("load",resolve);l.addEventListener("error",reject)});
  }
  window.preloadFinished=true;
})().catch((error)=>{window.preloadError=String(error);throw error});
"""


def assert_supported_pin_gate() -> None:
    """Reject the version-specific fixture until every upstream pin is reviewed."""
    dockerfile = (ADDON_DIR / "Dockerfile").read_text()
    build_from = re.findall(
        r"^ARG BUILD_FROM=(\S+)$", dockerfile, flags=re.MULTILINE
    )
    runner_from = re.findall(
        r"^FROM (\S+) AS runner$", dockerfile, flags=re.MULTILINE
    )
    assert len(build_from) == 1, f"expected one Dockerfile BUILD_FROM, got {build_from}"
    assert len(runner_from) == 1, f"expected one Dockerfile runner FROM, got {runner_from}"

    addon_info = yaml.safe_load((ADDON_DIR / "addon_info.yaml").read_text())
    expected_n8n_image = f"docker.io/n8nio/n8n:{SUPPORTED_N8N_VERSION}"
    expected_runner_image = f"docker.io/n8nio/runners:{SUPPORTED_N8N_VERSION}"
    assert not (ADDON_DIR / "build.yaml").exists(), (
        "prebuilt GHCR add-on images must not retain Supervisor's client-side build.yaml"
    )
    pins = {
        "Dockerfile BUILD_FROM": (build_from[0], expected_n8n_image),
        "Dockerfile runner FROM": (runner_from[0], expected_runner_image),
        "addon_info current_version": (
            addon_info["source"]["current_version"],
            f"n8n@{SUPPORTED_N8N_VERSION}",
        ),
    }
    mismatches = [
        f"{name}: found {actual!r}, expected {expected!r}"
        for name, (actual, expected) in pins.items()
        if actual != expected
    ]
    assert not mismatches, (
        "the exact preload fixture/rewrite is supported only for n8n "
        f"{SUPPORTED_N8N_VERSION}; review the minified seam before changing pins:\n"
        + "\n".join(mismatches)
    )
    assert PRELOAD_JS.count(ROOT_BUILDER) == 1, (
        "the pinned preload fixture must contain exactly one supported root builder"
    )
    assert PREFIX_BUILDER not in PRELOAD_JS, (
        "the backend fixture must remain unpatched so nginx performs the rewrite"
    )


class BackendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.partition("?")[0]
        resources = {
            "/signin": ("text/html; charset=utf-8", HTML.encode()),
            "/assets/BaseLayout.css": ("text/css", BASE_LAYOUT_CSS.encode()),
            "/assets/index.css": ("text/css", INDEX_CSS.encode()),
            "/assets/preload.js": ("application/javascript", PRELOAD_JS.encode()),
        }
        resource = resources.get(path)
        if resource is None:
            self.send_error(404)
            return
        content_type, body = resource
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


class SupervisorProxyHandler(BaseHTTPRequestHandler):
    nginx_port = 0

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path
        if path == INGRESS_PATH:
            upstream_path = "/"
        elif path.startswith(f"{INGRESS_PATH}/"):
            upstream_path = path[len(INGRESS_PATH) :]
        else:
            self.send_error(404, "request did not use the Supervisor ingress prefix")
            return

        connection = http.client.HTTPConnection(
            "127.0.0.1", type(self).nginx_port, timeout=5
        )
        try:
            connection.request(
                "GET",
                upstream_path,
                headers={
                    "Host": self.headers.get("Host", "127.0.0.1"),
                    "X-Ingress-Path": INGRESS_PATH,
                },
            )
            response = connection.getresponse()
            body = response.read()
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in {
                    "connection",
                    "content-length",
                    "keep-alive",
                    "transfer-encoding",
                }:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            connection.close()

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def replace_once(config: str, old: str, new: str) -> str:
    assert config.count(old) == 1, f"expected one nginx config seam: {old}"
    return config.replace(old, new)


def http_get(port: int, path: str) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def browser_result(page: Page, url: str) -> dict[str, object]:
    failed_resources: list[str] = []
    page_errors: list[str] = []
    page.on(
        "requestfailed",
        lambda request: failed_resources.append(
            f"{request.method} {request.url}: {request.failure}"
        ),
    )
    page.on(
        "response",
        lambda response: failed_resources.append(
            f"{response.status} {response.request.resource_type} {response.url}"
        )
        if response.status >= 400
        and response.request.resource_type in {"stylesheet", "script"}
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.goto(url, wait_until="load")
    page.wait_for_function("window.preloadFinished === true", timeout=5_000)
    result = page.evaluate(
        """() => {
          const baseLinks = [...document.querySelectorAll('link[rel="stylesheet"]')]
            .filter((link) => new URL(link.href).pathname.endsWith('/assets/BaseLayout.css'));
          const stylesheetHrefs = [...document.querySelectorAll('link[rel="stylesheet"]')]
            .map((link) => link.href);
          const counts = stylesheetHrefs.reduce((all, href) => {
            all[href] = (all[href] || 0) + 1;
            return all;
          }, {});
          return {
            baseLayoutStylesheets: baseLinks.length,
            duplicateStylesheetHrefs: Object.entries(counts)
              .filter(([, count]) => count > 1)
              .map(([href]) => href),
            n8nAppHeight: document.querySelector('#n8n-app').getBoundingClientRect().height,
            viewportHeight: innerHeight,
          };
        }"""
    )
    result["failedResources"] = failed_resources
    result["pageErrors"] = page_errors
    return result


def main() -> None:
    assert_supported_pin_gate()

    nginx = shutil.which("nginx")
    if not nginx:
        raise RuntimeError("preload de-duplication test requires nginx in PATH")

    backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    supervisor: ThreadingHTTPServer | None = None
    supervisor_thread: threading.Thread | None = None
    process: subprocess.Popen[bytes] | None = None

    try:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            tmp.chmod(0o755)
            nginx_port = unused_port()
            config = NGINX_CONFIG.read_text()
            config = replace_once(config, "pid /var/run/nginx.pid;", f"pid {tmp / 'nginx.pid'};")
            config = replace_once(
                config, "error_log /dev/stderr info;", f"error_log {tmp / 'error.log'} info;"
            )
            config = replace_once(
                config, "access_log /dev/stdout;", f"access_log {tmp / 'access.log'};"
            )
            config = replace_once(
                config,
                "listen 5690 default_server;",
                f"listen 127.0.0.1:{nginx_port} default_server;",
            )
            config = replace_once(config, "allow 172.30.32.2;", "allow 127.0.0.1;")
            config = replace_once(
                config,
                "proxy_pass http://127.0.0.1:5678;",
                f"proxy_pass http://127.0.0.1:{backend.server_port};",
            )
            if "alias /etc/nginx/ingress-frame-height.js;" in config:
                served_script = tmp / "ingress-frame-height.js"
                shutil.copyfile(FRAME_HEIGHT_SCRIPT, served_script)
                config = replace_once(
                    config,
                    "alias /etc/nginx/ingress-frame-height.js;",
                    f"alias {served_script};",
                )
            test_config = tmp / "nginx.conf"
            test_config.write_text(config)

            syntax = subprocess.run(
                [nginx, "-t", "-c", str(test_config), "-p", str(tmp)],
                check=False,
                capture_output=True,
                text=True,
            )
            assert syntax.returncode == 0, syntax.stdout + syntax.stderr

            process = subprocess.Popen(
                [nginx, "-c", str(test_config), "-p", str(tmp)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 5
            while True:
                if process.poll() is not None:
                    raise AssertionError((tmp / "error.log").read_text())
                try:
                    status, _body = http_get(nginx_port, "/signin")
                    assert status == 200, status
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)

            SupervisorProxyHandler.nginx_port = nginx_port
            supervisor = ThreadingHTTPServer(
                ("127.0.0.1", 0), SupervisorProxyHandler
            )
            supervisor_thread = threading.Thread(
                target=supervisor.serve_forever, daemon=True
            )
            supervisor_thread.start()

            ingress_origin = f"http://127.0.0.1:{supervisor.server_port}"
            direct_origin = f"http://127.0.0.1:{backend.server_port}"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900}, device_scale_factor=1
                )
                ingress = browser_result(
                    context.new_page(), f"{ingress_origin}{INGRESS_PATH}/signin"
                )
                direct = browser_result(context.new_page(), f"{direct_origin}/signin")
                context.close()
                browser.close()

            status, helper_body = http_get(
                supervisor.server_port, f"{INGRESS_PATH}/assets/preload.js"
            )
            assert status == 200, status
            helper = helper_body.decode()
            ingress["helperPrefixAware"] = PREFIX_BUILDER in helper
            ingress["helperRetainsRootBuilder"] = ROOT_BUILDER in helper
            direct["helperPrefixAware"] = PREFIX_BUILDER in PRELOAD_JS
            direct["helperRetainsRootBuilder"] = ROOT_BUILDER in PRELOAD_JS

            evidence = {"direct": direct, "ingress": ingress}
            print(json.dumps(evidence, indent=2, sort_keys=True), flush=True)

            problems: list[str] = []
            if ingress["baseLayoutStylesheets"] != 1:
                problems.append(
                    f"ingress BaseLayout stylesheet count: {ingress['baseLayoutStylesheets']} (expected 1)"
                )
            if ingress["duplicateStylesheetHrefs"]:
                problems.append(
                    f"ingress duplicate stylesheet hrefs: {ingress['duplicateStylesheetHrefs']}"
                )
            if abs(float(ingress["n8nAppHeight"]) - 900) > 1:
                problems.append(
                    f"ingress #n8n-app height: {ingress['n8nAppHeight']}px (expected 900px)"
                )
            if not ingress["helperPrefixAware"]:
                problems.append("ingress helper response lacks the prefix-aware pinned builder")
            if ingress["failedResources"] or ingress["pageErrors"]:
                problems.append(
                    f"ingress browser errors: resources={ingress['failedResources']}, page={ingress['pageErrors']}"
                )
            if direct["baseLayoutStylesheets"] != 1:
                problems.append(
                    f"direct BaseLayout stylesheet count: {direct['baseLayoutStylesheets']} (expected 1)"
                )
            if direct["duplicateStylesheetHrefs"]:
                problems.append(
                    f"direct duplicate stylesheet hrefs: {direct['duplicateStylesheetHrefs']}"
                )
            if abs(float(direct["n8nAppHeight"]) - 900) > 1:
                problems.append(
                    f"direct #n8n-app height: {direct['n8nAppHeight']}px (expected 900px)"
                )
            if direct["failedResources"] or direct["pageErrors"]:
                problems.append(
                    f"direct browser errors: resources={direct['failedResources']}, page={direct['pageErrors']}"
                )
            if direct["helperPrefixAware"] or not direct["helperRetainsRootBuilder"]:
                problems.append("direct backend helper was unexpectedly changed")
            assert not problems, "\n".join(problems)

    finally:
        if supervisor is not None:
            supervisor.shutdown()
            supervisor.server_close()
        if supervisor_thread is not None:
            supervisor_thread.join(timeout=5)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=5)

    print("ingress preload de-duplication browser test passed")


if __name__ == "__main__":
    main()
