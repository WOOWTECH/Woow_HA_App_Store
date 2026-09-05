#!/usr/bin/env python3
"""Live nginx contracts for ingress HTML and JSON response filtering."""
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
PREFIX = "/api/hassio_ingress/testtoken"
PREVIEW_HTML = (
    '<html><head><link href="/web/assets/preview.css">'
    '<script src="/web/assets/preview.js"></script></head></html>'
)


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/html":
            body = b"<html><head><title>Odoo</title></head><body>ok</body></html>"
            content_type = "text/html; charset=utf-8"
        elif self.path == "/json":
            # Document Layout serializes preview markup. These are literal JSON
            # bytes (href=\"...\"), not HTML attributes in an HTML response.
            payload = json.dumps({"preview": PREVIEW_HTML, "src": "/web/assets/top.js"})
            assert r'href=\"/web/assets/preview.css\"' in payload
            assert r'src=\"/web/assets/preview.js\"' in payload
            body = payload.encode()
            content_type = "application/json; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def request(socket: Path, route: str) -> str:
    return subprocess.run(
        ["curl", "--fail", "--silent", "--unix-socket", str(socket), f"http://localhost/{route}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def assert_template_contract(template: str) -> None:
    public_start = template.index("# Internal public origin.")
    ingress_start = template.index("# HA Supervisor Ingress adapter.")
    public = template[public_start:ingress_start]
    ingress = template[ingress_start:]
    generic = ingress[ingress.index("\n        location / {"):]
    assert "map $upstream_http_content_type $ingress_runtime_shim {" in template
    assert '"~*^text/html(?:;|$)"' in template
    assert "sub_filter '<head>' '<head>$ingress_runtime_shim';" in generic
    # Top-level bundle JSON rewriting remains intentionally separate.
    assert "sub_filter '\"src\": \"/' '\"src\": \"$safe_ingress_path/';" in generic
    href_rule = "sub_filter 'href=\\\\\"/web/assets/' 'href=\\\\\"$safe_ingress_path/web/assets/';"
    src_rule = "sub_filter 'src=\\\\\"/web/assets/' 'src=\\\\\"$safe_ingress_path/web/assets/';"
    assert href_rule in generic
    assert src_rule in generic
    assert href_rule not in public, "preview rewrite must not affect public origin"
    assert src_rule not in public, "preview rewrite must not affect public origin"


def preview_assets(payload: dict) -> tuple[str, str]:
    preview = payload["preview"]
    href = re.search(r'<link href="([^"]+)"', preview)
    src = re.search(r'<script src="([^"]+)"', preview)
    assert href and src, preview
    return href.group(1), src.group(1)


def main() -> None:
    nginx = shutil.which("nginx")
    assert nginx, "nginx is required for ingress content-type response tests"
    assert_template_contract(TEMPLATE.read_text(encoding="utf-8"))

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="odoo-content-type-nginx-") as directory:
            root = Path(directory)
            ingress_socket = root / "ingress.sock"
            public_socket = root / "public.sock"
            config = root / "nginx.conf"
            config.write_text(
                f'''daemon off;
master_process off;
pid {root / "nginx.pid"};
error_log {root / "error.log"} notice;
events {{}}
http {{
  access_log off;
  map $upstream_http_content_type $ingress_runtime_shim {{
    default "";
    "~*^text/html(?:;|$)" '<script>window.__INGRESS_PATH__="$safe_ingress_path";</script>';
  }}
  server {{
    listen unix:{ingress_socket};
    set $safe_ingress_path {PREFIX};
    sub_filter_once off;
    sub_filter_types text/html application/json;
    sub_filter '<head>' '<head>$ingress_runtime_shim';
    sub_filter '"src": "/' '"src": "$safe_ingress_path/';
    sub_filter 'href=\\\\"/web/assets/' 'href=\\\\"$safe_ingress_path/web/assets/';
    sub_filter 'src=\\\\"/web/assets/' 'src=\\\\"$safe_ingress_path/web/assets/';
    location / {{ proxy_pass http://127.0.0.1:{upstream.server_port}; }}
  }}
  server {{
    listen unix:{public_socket};
    location / {{ proxy_pass http://127.0.0.1:{upstream.server_port}; }}
  }}
}}
''',
                encoding="utf-8",
            )
            subprocess.run(
                [nginx, "-t", "-p", str(root), "-c", str(config)],
                check=True,
                capture_output=True,
                text=True,
            )
            process = subprocess.Popen(
                [nginx, "-p", str(root), "-c", str(config)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                for _ in range(100):
                    if ingress_socket.exists() and public_socket.exists():
                        break
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        raise AssertionError(f"nginx response harness exited: {stdout}{stderr}")
                    time.sleep(0.02)
                else:
                    raise AssertionError("nginx response harness sockets did not become ready")

                html = request(ingress_socket, "html")
                assert f'<head><script>window.__INGRESS_PATH__="{PREFIX}";</script>' in html

                ingress_payload = request(ingress_socket, "json")
                decoded_ingress = json.loads(ingress_payload)
                assert "window.__INGRESS_PATH__" not in ingress_payload
                assert preview_assets(decoded_ingress) == (
                    f"{PREFIX}/web/assets/preview.css",
                    f"{PREFIX}/web/assets/preview.js",
                )
                assert decoded_ingress["src"] == f"{PREFIX}/web/assets/top.js"

                decoded_public = json.loads(request(public_socket, "json"))
                assert preview_assets(decoded_public) == (
                    "/web/assets/preview.css",
                    "/web/assets/preview.js",
                )
                assert decoded_public["src"] == "/web/assets/top.js"
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
