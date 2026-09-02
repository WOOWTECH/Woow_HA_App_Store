#!/usr/bin/env python3
"""Exercise ingress transforms and cache policy in real nginx."""

from __future__ import annotations

import http.client
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ADDON_DIR = Path(__file__).resolve().parents[1]
NGINX_CONFIG = ADDON_DIR / "rootfs/etc/nginx/nginx.conf"
INGRESS_PATH = "/api/hassio_ingress/abcdefghijklmnop"
ROOT_BUILDER = "hee=function(e){return`/`+e}"
PREFIX_BUILDER = "hee=function(e){return(window.BASE_PATH||`/`)+e}"
UPSTREAM_CACHE_CONTROL = "public, max-age=86400"
FIXTURE_ETAG = '"ingress-cache-fixture-v1"'
FIXTURE_LAST_MODIFIED = "Wed, 01 Jan 2025 00:00:00 GMT"
MIXED_CASE_MIME_TYPES = {
    "/mime/html": "Text/HTML ; charset=utf-8",
    "/mime/application-javascript": "Application/JavaScript ; charset=utf-8",
    "/mime/application-x-javascript": "Application/X-JavaScript ; charset=utf-8",
    "/mime/text-javascript": "Text/JavaScript ; charset=utf-8",
    "/mime/text-x-javascript": "Text/X-JavaScript ; charset=utf-8",
    "/mime/css": "Text/CSS ; charset=utf-8",
}


class BackendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.partition("?")[0]
        if path == "/signin":
            body = (
                "<!doctype html><html><head><title>n8n</title>"
                "<script>window.BASE_PATH = '/';</script>"
                "</head><body>ok</body></html>"
            ).encode()
            content_type = "text/html; charset=utf-8"
        elif path == "/assets/preload.js":
            body = f"const {ROOT_BUILDER};export default hee;".encode()
            content_type = "application/javascript"
        elif path == "/assets/app.css":
            body = b".hero{background:url(/assets/pixel.png)}"
            content_type = "text/css"
        elif path == "/assets/pixel.png":
            body = b"\x89PNG\r\n\x1a\nfixture"
            content_type = "image/png"
        elif path in MIXED_CASE_MIME_TYPES:
            body = b"MIME fixture"
            content_type = MIXED_CASE_MIME_TYPES[path]
        else:
            self.send_error(404)
            return

        if self.headers.get("If-None-Match") == FIXTURE_ETAG or (
            "If-None-Match" not in self.headers
            and self.headers.get("If-Modified-Since") == FIXTURE_LAST_MODIFIED
        ):
            self.send_response(304)
            self.send_header("ETag", FIXTURE_ETAG)
            self.send_header("Last-Modified", FIXTURE_LAST_MODIFIED)
            self.send_header("Cache-Control", UPSTREAM_CACHE_CONTROL)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("ETag", FIXTURE_ETAG)
        self.send_header("Last-Modified", FIXTURE_LAST_MODIFIED)
        self.send_header("Cache-Control", UPSTREAM_CACHE_CONTROL)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def replace_once(config: str, old: str, new: str) -> str:
    assert config.count(old) == 1, f"expected one config seam: {old}"
    return config.replace(old, new)


def request(port: int, path: str, headers: dict[str, str] | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        connection.close()


def header_values(headers: list[tuple[str, str]], name: str) -> list[str]:
    return [value for key, value in headers if key.lower() == name.lower()]


def assert_cache_control(headers: list[tuple[str, str]], expected: str) -> None:
    values = header_values(headers, "Cache-Control")
    assert values == [expected], headers


def assert_fixture_validators(headers: list[tuple[str, str]]) -> None:
    assert header_values(headers, "ETag") == [FIXTURE_ETAG], headers
    assert header_values(headers, "Last-Modified") == [
        FIXTURE_LAST_MODIFIED
    ], headers


def main() -> None:
    nginx = shutil.which("nginx")
    if not nginx:
        raise RuntimeError("nginx ingress test requires an nginx binary in PATH")

    backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    ingress_port = unused_port()

    try:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            tmp.chmod(0o755)
            config = NGINX_CONFIG.read_text()
            config = replace_once(config, "pid /var/run/nginx.pid;", f"pid {tmp / 'nginx.pid'};")
            config = replace_once(
                config,
                "error_log /dev/stderr info;",
                f"error_log {tmp / 'error.log'} info;",
            )
            config = replace_once(
                config, "access_log /dev/stdout;", f"access_log {tmp / 'access.log'};"
            )
            config = replace_once(
                config,
                "listen 5690 default_server;",
                f"listen 127.0.0.1:{ingress_port} default_server;",
            )
            config = replace_once(config, "allow 172.30.32.2;", "allow 127.0.0.1;")
            config = replace_once(
                config,
                "proxy_pass http://127.0.0.1:5678;",
                f"proxy_pass http://127.0.0.1:{backend.server_port};",
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
            try:
                deadline = time.monotonic() + 5
                while True:
                    if process.poll() is not None:
                        raise AssertionError((tmp / "error.log").read_text())
                    try:
                        status, _headers, _body = request(
                            ingress_port,
                            "/signin",
                            headers={"X-Ingress-Path": INGRESS_PATH},
                        )
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.05)
                assert status == 200, status

                status, headers, html = request(
                    ingress_port,
                    "/signin",
                    headers={"X-Ingress-Path": INGRESS_PATH},
                )
                decoded_html = html.decode()
                assert status == 200, status
                assert_cache_control(headers, "no-store")
                assert f'<base href="{INGRESS_PATH}/">' in decoded_html
                assert f'window.__INGRESS_PATH__="{INGRESS_PATH}"' in decoded_html
                assert f"window.BASE_PATH = '{INGRESS_PATH}/';" in decoded_html
                assert "ingress-frame-height.js" not in decoded_html

                status, headers, javascript = request(
                    ingress_port,
                    "/assets/preload.js",
                    headers={"X-Ingress-Path": INGRESS_PATH},
                )
                decoded_javascript = javascript.decode()
                assert status == 200, status
                assert header_values(headers, "Content-Type") == [
                    "application/javascript"
                ], headers
                assert_cache_control(headers, "no-store")
                assert PREFIX_BUILDER in decoded_javascript, decoded_javascript
                assert ROOT_BUILDER not in decoded_javascript, decoded_javascript

                status, headers, css = request(
                    ingress_port,
                    "/assets/app.css",
                    headers={"X-Ingress-Path": INGRESS_PATH},
                )
                assert status == 200, status
                assert_cache_control(headers, "no-store")
                assert f"url({INGRESS_PATH}/assets/pixel.png)" in css.decode(), css

                status, headers, binary = request(
                    ingress_port,
                    "/assets/pixel.png",
                    headers={"X-Ingress-Path": INGRESS_PATH},
                )
                assert status == 200, status
                assert_cache_control(headers, UPSTREAM_CACHE_CONTROL)
                assert binary == b"\x89PNG\r\n\x1a\nfixture", binary

                for path, content_type in MIXED_CASE_MIME_TYPES.items():
                    status, headers, _body = request(
                        ingress_port,
                        path,
                        headers={"X-Ingress-Path": INGRESS_PATH},
                    )
                    assert status == 200, (path, status)
                    assert header_values(headers, "Content-Type") == [
                        content_type
                    ], headers
                    assert_cache_control(headers, "no-store")

                conditional_headers = (
                    {"If-None-Match": FIXTURE_ETAG},
                    {"If-Modified-Since": FIXTURE_LAST_MODIFIED},
                )
                transformed_resources = (
                    ("/signin", f'<base href="{INGRESS_PATH}/">'.encode()),
                    ("/assets/preload.js", PREFIX_BUILDER.encode()),
                    (
                        "/assets/app.css",
                        f"url({INGRESS_PATH}/assets/pixel.png)".encode(),
                    ),
                )
                for conditional_header in conditional_headers:
                    for path, transformed_fragment in transformed_resources:
                        status, headers, body = request(
                            ingress_port,
                            path,
                            headers={
                                "X-Ingress-Path": INGRESS_PATH,
                                **conditional_header,
                            },
                        )
                        assert status == 200, (path, conditional_header, status)
                        assert_cache_control(headers, "no-store")
                        assert transformed_fragment in body, (
                            path,
                            conditional_header,
                            body,
                        )

                for conditional_header in conditional_headers:
                    status, headers, body = request(
                        ingress_port,
                        "/assets/pixel.png",
                        headers={
                            "X-Ingress-Path": INGRESS_PATH,
                            **conditional_header,
                        },
                    )
                    assert status == 200, (conditional_header, status)
                    assert_cache_control(headers, UPSTREAM_CACHE_CONTROL)
                    assert body == b"\x89PNG\r\n\x1a\nfixture", body

                direct_paths = (
                    "/signin",
                    "/assets/preload.js",
                    "/assets/app.css",
                    "/assets/pixel.png",
                    *MIXED_CASE_MIME_TYPES,
                )
                for path in direct_paths:
                    status, headers, _body = request(backend.server_port, path)
                    assert status == 200, (path, status)
                    assert_cache_control(headers, UPSTREAM_CACHE_CONTROL)
                    assert_fixture_validators(headers)

                for conditional_header in conditional_headers:
                    status, headers, body = request(
                        backend.server_port,
                        "/signin",
                        headers=conditional_header,
                    )
                    assert status == 304, (conditional_header, status)
                    assert body == b"", (conditional_header, body)
                    assert header_values(headers, "Content-Type") == [], headers
                    assert_cache_control(headers, UPSTREAM_CACHE_CONTROL)
                    assert_fixture_validators(headers)

                status, _headers, _body = request(
                    ingress_port,
                    "/_woow/ingress-frame-height.js",
                    headers={"X-Ingress-Path": INGRESS_PATH},
                )
                assert status == 404, status
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=5)

    print(
        "nginx ingress test passed: HTML base/runtime injection retained, "
        "pinned helper rewritten, validators suppressed upstream, transformed "
        "types no-store, binary/direct cache policy preserved, old frame-height "
        "resource absent"
    )


if __name__ == "__main__":
    main()
