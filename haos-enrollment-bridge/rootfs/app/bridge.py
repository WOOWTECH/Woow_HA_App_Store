#!/usr/bin/env python3
"""Dnsmasq lease snapshots -> durable Home Assistant candidate events."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LOG = logging.getLogger("haos-enrollment-bridge")
EVENT_TYPE_RE = re.compile(r"^[a-z0-9_]+$")
MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")


class ProtocolError(RuntimeError):
    pass


def normalize_client(raw: dict[str, Any], network: ipaddress.IPv4Network) -> dict[str, Any] | None:
    lease = raw.get("lease") if isinstance(raw, dict) else None
    if not isinstance(lease, dict):
        return None
    mac = str(lease.get("mac_addr", "")).strip().lower()
    ip_text = str(lease.get("ip_addr", "")).strip()
    if not MAC_RE.fullmatch(mac):
        return None
    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError:
        return None
    if address.version != 4 or address not in network:
        return None
    return {
        "mac": mac,
        "ip": ip_text,
        "hostname": str(lease.get("hostname") or ""),
        "lease_expires": lease.get("expires"),
        "friendly_name": str(raw.get("friendly_name") or ""),
    }


class CandidateTracker:
    """Persist first-seen identity and retry event delivery until HA accepts it."""

    def __init__(
        self,
        state_path: Path,
        target_cidr: str,
        bootstrap_targets: list[str] | None = None,
    ) -> None:
        self.state_path = state_path
        self.network = ipaddress.ip_network(target_cidr, strict=False)
        if self.network.version != 4:
            raise ValueError("target_cidr must be IPv4")
        self.bootstrap_targets = set(bootstrap_targets or [])
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        default = {
            "version": 1,
            "initialized": False,
            "known": {},
            "pending": {},
            "bootstrap_delivered": [],
        }
        try:
            loaded = json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return default
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read durable state: {exc}") from exc
        if not isinstance(loaded, dict) or loaded.get("version") != 1:
            raise RuntimeError("unsupported durable state format")
        loaded.setdefault("initialized", False)
        loaded.setdefault("known", {})
        loaded.setdefault("pending", {})
        loaded.setdefault("bootstrap_delivered", [])
        return loaded

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="state-", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.state, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def _candidate_id(mac: str) -> str:
        digest = hashlib.sha256(f"dnsmasq-dhcp:{mac}".encode()).hexdigest()[:20]
        return f"dhcp-{digest}"

    def process_snapshot(self, raw_clients: list[dict[str, Any]], now: int | None = None) -> list[dict[str, Any]]:
        observed_at = int(time.time() if now is None else now)
        clients = [client for raw in raw_clients if (client := normalize_client(raw, self.network))]
        first_snapshot = not self.state["initialized"]

        for client in clients:
            mac = client["mac"]
            existing = self.state["known"].get(mac)
            is_new = existing is None
            if is_new:
                self.state["known"][mac] = {
                    "first_seen": observed_at,
                    "last_seen": observed_at,
                    "ip": client["ip"],
                    "hostname": client["hostname"],
                }
            else:
                existing.update({
                    "last_seen": observed_at,
                    "ip": client["ip"],
                    "hostname": client["hostname"],
                })

            bootstrap_requested = (
                client["ip"] in self.bootstrap_targets
                and client["ip"] not in self.state["bootstrap_delivered"]
            )
            should_emit = (not first_snapshot and is_new) or bootstrap_requested
            candidate_id = self._candidate_id(mac)
            if should_emit and candidate_id not in self.state["pending"]:
                self.state["pending"][candidate_id] = {
                    **client,
                    "candidate_id": candidate_id,
                    "observed_at": observed_at,
                    "source": "dnsmasq_dhcp_bridge",
                    "bootstrap_requested": bootstrap_requested,
                }

            pending = self.state["pending"].get(candidate_id)
            if pending:
                pending.update({
                    "ip": client["ip"],
                    "hostname": client["hostname"],
                    "lease_expires": client["lease_expires"],
                    "friendly_name": client["friendly_name"],
                })

        self.state["initialized"] = True
        self._save()
        return list(self.state["pending"].values())

    def mark_delivered(self, candidate_id: str, delivered_at: int | None = None) -> None:
        pending = self.state["pending"].pop(candidate_id, None)
        if pending is None:
            return
        known = self.state["known"].get(pending["mac"], {})
        known["event_delivered_at"] = int(time.time() if delivered_at is None else delivered_at)
        if pending.get("bootstrap_requested") and pending["ip"] not in self.state["bootstrap_delivered"]:
            self.state["bootstrap_delivered"].append(pending["ip"])
        self._save()


class WebSocketConnection:
    def __init__(self, url: str, ingress_path: str = "/", timeout: float = 45.0) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise ValueError("dnsmasq_ws_url must use ws://")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.path = parsed.path or "/"
        if parsed.query:
            self.path += "?" + parsed.query
        self.ingress_path = ingress_path
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.buffer = bytearray()

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=10)
        sock.settimeout(self.timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"X-Ingress-Path: {self.ingress_path}\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        headers = bytearray()
        while b"\r\n\r\n" not in headers:
            chunk = sock.recv(4096)
            if not chunk:
                raise ProtocolError("websocket closed during handshake")
            headers.extend(chunk)
            if len(headers) > 65536:
                raise ProtocolError("oversized websocket handshake")
        header_block, remainder = bytes(headers).split(b"\r\n\r\n", 1)
        status = header_block.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ProtocolError(f"websocket handshake failed: {status.decode(errors='replace')}")
        self.sock = sock
        self.buffer.extend(remainder)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None
        self.buffer.clear()

    def _read_exact(self, length: int) -> bytes:
        assert self.sock is not None
        while len(self.buffer) < length:
            chunk = self.sock.recv(max(4096, length - len(self.buffer)))
            if not chunk:
                raise EOFError("websocket closed")
            self.buffer.extend(chunk)
        value = bytes(self.buffer[:length])
        del self.buffer[:length]
        return value

    def _send_control(self, opcode: int, payload: bytes) -> None:
        assert self.sock is not None
        mask = secrets.token_bytes(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if len(payload) > 125:
            raise ProtocolError("control frame too large")
        self.sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)

    def receive_text(self) -> str:
        fragments = bytearray()
        started = False
        while True:
            first, second = self._read_exact(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > 16 * 1024 * 1024:
                raise ProtocolError("websocket message exceeds 16 MiB")
            mask = self._read_exact(4) if masked else None
            payload = self._read_exact(length)
            if mask:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))

            if opcode == 0x8:
                raise EOFError("websocket close frame")
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                fragments = bytearray(payload)
                started = True
            elif opcode == 0x0 and started:
                fragments.extend(payload)
            else:
                continue
            if final:
                return fragments.decode("utf-8")


def post_ha_event(event_type: str, event: dict[str, Any], token: str) -> None:
    if not EVENT_TYPE_RE.fullmatch(event_type):
        raise ValueError("invalid event_type")
    url = f"http://supervisor/core/api/events/{event_type}"
    request = urllib.request.Request(
        url,
        data=json.dumps(event).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"Home Assistant event returned HTTP {response.status}")


def load_options(path: Path = Path("/data/options.json")) -> dict[str, Any]:
    options = json.loads(path.read_text())
    required = {"dnsmasq_ws_url", "target_cidr", "event_type"}
    missing = sorted(required - options.keys())
    if missing:
        raise ValueError(f"missing options: {', '.join(missing)}")
    return options


def run() -> None:
    options = load_options()
    logging.basicConfig(
        level=getattr(logging, str(options.get("log_level", "info")).upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN is unavailable")
    tracker = CandidateTracker(
        Path("/data/state.json"),
        options["target_cidr"],
        options.get("bootstrap_targets", []),
    )
    delay = 1
    while True:
        connection = WebSocketConnection(
            options["dnsmasq_ws_url"],
            options.get("ingress_path", "/"),
        )
        try:
            connection.connect()
            LOG.info("connected to Dnsmasq lease stream")
            delay = 1
            while True:
                snapshot = json.loads(connection.receive_text())
                if not isinstance(snapshot, dict):
                    continue
                clients = snapshot.get("current_clients")
                if not isinstance(clients, list):
                    continue
                pending = tracker.process_snapshot(clients)
                for candidate in pending:
                    try:
                        post_ha_event(options["event_type"], candidate, token)
                    except (OSError, urllib.error.URLError, RuntimeError) as exc:
                        LOG.warning("candidate %s delivery failed: %s", candidate["candidate_id"], exc)
                    else:
                        tracker.mark_delivered(candidate["candidate_id"])
                        LOG.info(
                            "delivered candidate %s mac=%s ip=%s",
                            candidate["candidate_id"],
                            candidate["mac"],
                            candidate["ip"],
                        )
        except (OSError, EOFError, ProtocolError, ValueError, json.JSONDecodeError) as exc:
            LOG.warning("lease stream unavailable: %s; retrying in %ss", exc, delay)
        finally:
            connection.close()
        time.sleep(delay)
        delay = min(delay * 2, 60)


if __name__ == "__main__":
    run()
