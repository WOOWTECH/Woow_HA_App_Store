#!/usr/bin/env python3
"""A capture SMTP server for the outbound-artefact parity run (#145).

It accepts every message and writes it to a directory as a `.eml` file,
with the envelope recipients in `X-Capture-Rcpt` headers. It never relays
anything, so no real recipient can get a message sent to it.

    python3 smtp_capture_sink.py --host 127.0.0.1 --port 2525 --dir /tmp/woow-parity-mail

The standard library only (Python 3.11 has no `smtpd` replacement), so it
runs as-is inside the add-on container. Odoo reaches it through an
`ir.mail_server` pointing at the same host and port, without TLS or login.
"""
from __future__ import annotations

import argparse
import itertools
import os
import socketserver
import time

_counter = itertools.count(1)


class _Handler(socketserver.StreamRequestHandler):
    def reply(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("ascii"))
        self.wfile.flush()

    def handle(self) -> None:
        self.reply("220 woow-parity capture sink")
        sender, recipients = None, []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            verb = line[:4].upper()
            if verb == "EHLO":
                self.wfile.write(b"250-woow-parity\r\n250-8BITMIME\r\n250 SMTPUTF8\r\n")
                self.wfile.flush()
            elif verb == "HELO":
                self.reply("250 woow-parity")
            elif verb == "MAIL":
                sender, recipients = line.split(":", 1)[1].strip(), []
                self.reply("250 OK")
            elif verb == "RCPT":
                recipients.append(line.split(":", 1)[1].strip().strip("<>"))
                self.reply("250 OK")
            elif verb == "DATA":
                self.reply("354 End data with <CR><LF>.<CR><LF>")
                self.store(sender, recipients, self.read_data())
                sender, recipients = None, []
                self.reply("250 OK: captured, not relayed")
            elif verb == "RSET":
                sender, recipients = None, []
                self.reply("250 OK")
            elif verb == "NOOP":
                self.reply("250 OK")
            elif verb == "QUIT":
                self.reply("221 Bye")
                return
            else:
                self.reply("502 Command not implemented")

    def read_data(self) -> bytes:
        lines = []
        while True:
            raw = self.rfile.readline()
            if not raw or raw in (b".\r\n", b".\n"):
                break
            lines.append(raw[1:] if raw.startswith(b".") else raw)  # RFC 5321 dot-unstuffing
        return b"".join(lines)

    def store(self, sender: str | None, recipients: list[str], data: bytes) -> None:
        header = "".join("X-Capture-Rcpt: %s\r\n" % rcpt for rcpt in recipients)
        header += "X-Capture-From: %s\r\n" % (sender or "")
        name = "%s-%05d.eml" % (time.strftime("%Y%m%dT%H%M%S"), next(_counter))
        path = os.path.join(self.server.directory, name)
        with open(path + ".part", "wb") as handle:
            handle.write(header.encode("utf-8") + data)
        os.replace(path + ".part", path)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    directory = ""


def make_server(host: str, port: int, directory: str) -> _Server:
    os.makedirs(directory, exist_ok=True)
    server = _Server((host, port), _Handler)
    server.directory = directory
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2525)
    parser.add_argument("--dir", required=True)
    args = parser.parse_args()
    server = make_server(args.host, args.port, args.dir)
    print("capturing on %s:%d into %s" % (args.host, args.port, args.dir), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
