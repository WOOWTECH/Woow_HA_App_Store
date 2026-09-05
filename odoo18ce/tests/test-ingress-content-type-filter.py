#!/usr/bin/env python3
"""Live nginx contract for HTML-only ingress runtime shim injection."""
import json
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


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/html":
            body = b"<html><head><title>Odoo</title></head><body>ok</body></html>"
            content_type = "text/html; charset=utf-8"
        elif self.path == "/json":
            # This mirrors the Document Layout RPC: preview HTML is a JSON
            # string, so raw shim bytes after its <head> would corrupt JSON.
            body = json.dumps(
                {
                    "preview": "<html><head><title>Preview</title></head></html>",
                    "src": "/web/assets/preview.js",
                }
            ).encode()
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
    ingress = template[template.index("# HA Supervisor Ingress adapter."):]
    generic = ingress[ingress.index("\n        location / {"):]
    assert "map $upstream_http_content_type $ingress_runtime_shim {" in template
    assert '"~*^text/html(?:;|$)"' in template
    assert "sub_filter '<head>' '<head>$ingress_runtime_shim';" in generic
    # The JSON rewrite remains in the same generic ingress response filter.
    assert "sub_filter '\"src\": \"/' '\"src\": \"$safe_ingress_path/';" in generic


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
            socket = root / "filter.sock"
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
    listen unix:{socket};
    set $safe_ingress_path {PREFIX};
    sub_filter_once off;
    sub_filter_types text/html application/json;
    sub_filter '<head>' '<head>$ingress_runtime_shim';
    sub_filter '"src": "/' '"src": "$safe_ingress_path/';
    location / {{ proxy_pass http://127.0.0.1:{upstream.server_port}; }}
  }}
}}
''',
                encoding="utf-8",
            )
            subprocess.run([nginx, "-t", "-p", str(root), "-c", str(config)], check=True, capture_output=True, text=True)
            process = subprocess.Popen([nginx, "-p", str(root), "-c", str(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(100):
                    if socket.exists():
                        break
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        raise AssertionError(f"nginx response harness exited: {stdout}{stderr}")
                    time.sleep(0.02)
                else:
                    raise AssertionError("nginx response harness socket did not become ready")

                html = request(socket, "html")
                assert f'<head><script>window.__INGRESS_PATH__="{PREFIX}";</script>' in html

                payload = request(socket, "json")
                decoded = json.loads(payload)
                assert "window.__INGRESS_PATH__" not in payload
                assert decoded["preview"] == "<html><head><title>Preview</title></head></html>"
                assert decoded["src"] == f"{PREFIX}/web/assets/preview.js"
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
