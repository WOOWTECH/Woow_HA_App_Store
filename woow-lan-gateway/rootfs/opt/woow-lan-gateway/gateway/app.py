import json
import logging
import os
import signal
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping

from .firewall import NftablesFirewall
from .service import GatewayConfig, GatewayService, GatewayStatus


_LOG = logging.getLogger("woow-lan-gateway")


class NotificationOutbox:
    def __init__(self, delivery):
        self.delivery = delivery
        self._pending: tuple[str, str] | None = None

    @property
    def pending(self) -> bool:
        return self._pending is not None

    def publish(self, state: str, message: str) -> None:
        self._pending = (state, message)
        self.retry()

    def retry(self) -> None:
        if self._pending is None:
            return
        if self.delivery(*self._pending):
            self._pending = None


def status_document(
    status: GatewayStatus, packet_counters: Mapping[str, int] | None = None
) -> dict:
    return {
        "state": status.state,
        "enabled": status.state == "enabled",
        "expires_at": status.expires_at,
        "lan_interface": status.lan_interface,
        "wan_interface": status.wan_interface,
        "source_cidr": status.source_cidr,
        "rules_checksum": status.rules_checksum,
        "packet_counters": dict(packet_counters or {}),
    }


class GatewayApplication:
    def __init__(self, options_path: str = "/data/options.json") -> None:
        options = json.loads(Path(options_path).read_text())
        self.config = GatewayConfig(
            lan_interface=options["lan_interface"],
            wan_interface=options["wan_interface"],
            source_cidr=options["source_cidr"],
            heartbeat_interval=int(options["heartbeat_interval"]),
            lease_timeout=int(options["lease_timeout"]),
        )
        self.firewall = NftablesFirewall(clock=time.time)
        self.service = GatewayService(self.config, self.firewall, time.time)
        self.stop_event = threading.Event()
        self.last_status = self.service.status()
        self.last_error = ""
        self.httpd: ThreadingHTTPServer | None = None
        self.notifications = NotificationOutbox(self._deliver_notification)

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)
        self._start_http()
        try:
            self.last_status = self.service.start()
            self.notifications.publish(
                "已啟用", "192.168.50.0/24 對外網路已由 fail-closed Gateway App 啟用。"
            )
            _LOG.info("gateway enabled; lease expires at %.3f", self.last_status.expires_at)
            while not self.stop_event.wait(self.config.heartbeat_interval):
                self.notifications.retry()
                previous_error = self.last_error
                try:
                    self.last_status = self.service.heartbeat()
                    self.last_error = ""
                    if previous_error:
                        self.notifications.publish(
                            "已恢復", "Gateway 規則已重新驗證並恢復對外 forwarding。"
                        )
                except Exception as error:
                    self.last_error = str(error)
                    self.last_status = self.service.status()
                    _LOG.exception("heartbeat failed; egress is fail-closed")
                    self.notifications.publish(
                        "故障並已關閉",
                        f"Gateway heartbeat 失敗：`{error}`\n\n對外 forwarding 已關閉。",
                    )
        except Exception as error:
            self.last_error = str(error)
            self.last_status = self.service.status()
            _LOG.exception("gateway startup failed")
            self.notifications.publish(
                "啟動失敗", f"Gateway 啟動失敗：`{error}`\n\n對外 forwarding 保持關閉。"
            )
            return 1
        finally:
            self.last_status = self.service.stop()
            if self.httpd:
                self.httpd.shutdown()
                self.httpd.server_close()
        self.notifications.publish(
            "已停用", "Woow LAN Gateway App 已停止，192.168.50.0/24 現在沒有對外 forwarding。"
        )
        return 0

    def _request_stop(self, _signum, _frame) -> None:
        self.stop_event.set()

    def _start_http(self) -> None:
        application = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in ("/", "/health", "/status"):
                    self.send_error(404)
                    return
                application.last_status = application.service.status()
                document = status_document(
                    application.last_status, packet_counters=application.firewall.counters()
                )
                if application.last_error:
                    document["last_error"] = application.last_error
                body = json.dumps(document, sort_keys=True).encode()
                code = 200 if application.last_status.state == "enabled" else 503
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                _LOG.debug(format, *args)

        self.httpd = ThreadingHTTPServer(("0.0.0.0", 45987), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @staticmethod
    def _deliver_notification(state: str, message: str) -> bool:
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            _LOG.warning("SUPERVISOR_TOKEN unavailable; notification deferred")
            return False
        payload = json.dumps(
            {
                "notification_id": "woow_lan_gateway_status",
                "title": f"Woow LAN Gateway — {state}",
                "message": message,
            }
        ).encode()
        request = urllib.request.Request(
            "http://supervisor/core/api/services/persistent_notification/create",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            urllib.request.urlopen(request, timeout=5).close()
            return True
        except Exception as error:
            _LOG.warning("persistent notification failed: %s", error)
            return False


def cleanup() -> int:
    NftablesFirewall(clock=time.time).disable(config=GatewayConfig.fixed_topology())
    return 0
