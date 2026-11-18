#!/usr/bin/env python3
"""The few Supervisor answers an add-on start needs, for postgres_after_restore.sh.

The image does not start without a Supervisor: bashio::config is
GET /addons/self/options/config, and cont-init asks it for the options
before anything else. This answers that from /data/options.json, read on
every request so the file a restore puts back is the one served, and the
two reads the Canonical URL waits for -- the host's LAN address and the
published 8069 port -- so a start does not spend the Supervisor budget
(supervisor-read.sh) on them. Any other path answers 404, as an unknown path
does on the real Supervisor; the add-on logs that and carries on, except
the self-check, which stops the container in the end (no add-on address).

It listens on loopback, and the add-on joins its network namespace with
SUPERVISOR_API pointing here, which bashio honours. Standard library only:
it runs in the image under test, started with `python3 -c`.

Usage: python3 supervisor_stub.py PORT
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPTIONS = "/data/options.json"
ANSWERS = {
    "/addons/self/info": {
        "slug": "odoo18ce",
        "network": {"8069/tcp": 8069, "8072/tcp": 8072},
    },
    # 192.0.2.0/24 is reserved for documentation: no real host has it.
    "/network/interface/default/info": {"ipv4": {"address": ["192.0.2.10/24"]}},
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/addons/self/options/config":
            with open(OPTIONS, encoding="utf-8") as handle:
                data = json.load(handle)
        elif path in ANSWERS:
            data = ANSWERS[path]
        else:
            self.answer(404, {"result": "error", "message": f"{path} is not in the stub"})
            return
        self.answer(200, {"result": "ok", "data": data})

    do_POST = do_GET

    def answer(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
