"""Exercise the shipped nginx config against a local HTTP backend, no HA needed."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

ADDON = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Backend(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.endswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            time.sleep(0.8)
            self.wfile.write(b"data: last\n\n")
            return
        self.echo()

    def echo(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        response = json.dumps({"method": self.command, "path": self.path, "body": body.decode(),
                               "accept": self.headers.get("Accept"), "content_type": self.headers.get("Content-Type"),
                               "session": self.headers.get("Mcp-Session-Id"), "protocol": self.headers.get("MCP-Protocol-Version")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    do_POST = echo
    do_DELETE = echo


class NginxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nginx = os.environ.get("NGINX_BINARY") or shutil.which("nginx")
        if not cls.nginx:
            raise unittest.SkipTest("nginx binary required; set NGINX_BINARY")
        cls.addClassCleanup(cls.cleanup)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        cls.thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = free_port()
        config = (ADDON / "rootfs/etc/nginx/nginx.conf").read_text()
        config = config.replace("include       /etc/nginx/mime.types;", "")
        config = config.replace("pid /var/run/nginx.pid;", f"pid {cls.root}/nginx.pid;")
        config = config.replace("listen 8080", f"listen 127.0.0.1:{cls.port}")
        config = config.replace("allow 172.30.32.2;", "allow 127.0.0.1;")
        config = config.replace("127.0.0.1:8000", f"127.0.0.1:{cls.backend.server_port}")
        config = config.replace("    sendfile on;", f"    sendfile on;\n    client_body_temp_path {cls.root}/body;\n    proxy_temp_path {cls.root}/proxy;\n    fastcgi_temp_path {cls.root}/fastcgi;\n    uwsgi_temp_path {cls.root}/uwsgi;\n    scgi_temp_path {cls.root}/scgi;")
        (cls.root / "nginx.conf").write_text(config)
        cls.log = (cls.root / "nginx.log").open("w+")
        cls.process = subprocess.Popen([cls.nginx, "-p", str(cls.root), "-c", str(cls.root / "nginx.conf"), "-g", "daemon off;"], stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    return
            except OSError:
                if cls.process.poll() is not None:
                    cls.log.seek(0)
                    raise AssertionError(cls.log.read())
                time.sleep(0.02)
        raise AssertionError("nginx did not start")

    @classmethod
    def cleanup(cls):
        if hasattr(cls, "process") and cls.process.poll() is None:
            cls.process.terminate()
            cls.process.wait(timeout=5)
        if hasattr(cls, "backend"):
            cls.backend.shutdown()
            cls.backend.server_close()
            cls.thread.join(timeout=5)
        if hasattr(cls, "log"):
            cls.log.close()
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    def test_methods_paths_headers_and_logs(self):
        token = "private_omcp_SYNTHETIC_DO_NOT_PUBLISH_123"
        for method in ("POST", "GET", "DELETE"):
            path = "/mcp/" + token
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            connection.request(method, path, body='{"marker":"/assets/ untouched"}', headers={
                "Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                "Mcp-Session-Id": "fixture-session", "MCP-Protocol-Version": "2025-03-26",
                "Referer": "https://example.test/" + token, "User-Agent": token})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            data = json.loads(response.read())
            self.assertEqual(data["method"], method)
            self.assertEqual(data["path"], path)
            self.assertEqual(data["accept"], "application/json, text/event-stream")
            self.assertEqual(data["content_type"], "application/json")
            self.assertEqual(data["session"], "fixture-session")
            self.assertEqual(data["protocol"], "2025-03-26")
            self.assertEqual(data["body"], '{"marker":"/assets/ untouched"}')
            connection.close()
        time.sleep(0.05)
        self.log.seek(0)
        logged = self.log.read()
        self.assertNotIn(token, logged)
        self.assertIn("/mcp/[redacted]", logged)

    def test_sse_arrives_before_response_finishes(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        started = time.monotonic()
        connection.request("GET", "/mcp/private_omcp_fixture/stream", headers={"Accept": "text/event-stream"})
        response = connection.getresponse()
        self.assertEqual(response.readline(), b"data: first\n")
        self.assertLess(time.monotonic() - started, 0.6)
        self.assertIn(b"data: last", response.read())
        connection.close()

    def test_encoded_and_query_credentials_are_not_logged(self):
        token = "private_omcp_SYNTHETIC_ENCODED_123"
        for path in ("/m%63p/" + token, "/mcp/" + token + "?secret=" + token, "/health?token=" + token,
                     "/mcp/" + token + "/%GG"):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            connection.request("GET", path)
            response = connection.getresponse()
            response.read()
            connection.close()
        time.sleep(0.05)
        self.log.seek(0)
        self.assertNotIn(token, self.log.read())

    def test_encoded_prefix_credentials_are_redacted(self):
        token = "private_omcp_SYNTHETIC_REVIEW_123"
        encoded = token.replace("omcp", "o%6dcp")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", "/assistant/m%63p/" + encoded)
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        connection.close()
        time.sleep(0.05)
        self.log.seek(0)
        logged = self.log.read()
        self.assertNotIn(token, logged)
        self.assertNotIn(encoded, logged)
        self.assertIn("/mcp/[redacted]", logged)

    def test_z_upstream_failure_does_not_log_token(self):
        self.backend.shutdown()
        self.backend.server_close()
        token = "private_omcp_SYNTHETIC_UPSTREAM_FAILURE"
        encoded = token.replace("omcp", "o%6dcp")
        for path in ("/mcp/" + token, "/health?token=" + token, "/mcp/../missing?token=" + token,
                     "/assistant/m%63p/" + encoded):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            connection.request("POST", path, body="{}", headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 502)
            response.read()
            connection.close()
        time.sleep(0.05)
        self.log.seek(0)
        logged = self.log.read()
        self.assertNotIn(token, logged)
        self.assertNotIn(encoded, logged)


if __name__ == "__main__":
    unittest.main()
