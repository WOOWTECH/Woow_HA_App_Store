"""Helpers for driving a real Woow n8n add-on container in smoke tests.

The container runs the way Home Assistant Supervisor runs it: on a bridge
network in the hassio address range, with /data/options.json and /config
mounted, a Supervisor token in the environment, and the Supervisor's own
address (172.30.32.2) as the only client the ingress nginx accepts.
Standard library only, so it runs on a bare CI runner or build host.
"""

from __future__ import annotations

import http.cookiejar
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

SUPERVISOR_IP = "172.30.32.2"
ADDON_IP = "172.30.33.10"
SUBNET = "172.30.32.0/23"
FAKE_SUPERVISOR_TOKEN = "smoke-supervisor-token-must-stay-hidden"
SECRET_OPTION_VALUE = "smoke-option-secret-must-not-be-logged"
OWNER = {
    "email": "smoke@example.com",
    "firstName": "Smoke",
    "lastName": "Test",
    "password": "SmokeTest123!",
}


def docker(*args: str, check: bool = True, capture: bool = True) -> str:
    result = subprocess.run(
        ["docker", *args], check=False, capture_output=capture, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker {' '.join(args)} failed ({result.returncode}): "
            f"{result.stdout}{result.stderr}"
        )
    return (result.stdout or "") if capture else ""


@dataclass
class Addon:
    image: str
    workdir: Path
    name: str = field(default_factory=lambda: f"woow-n8n-smoke-{uuid.uuid4().hex[:8]}")
    network: str = ""
    port: int = 0
    env_vars: list[dict[str, str]] = field(default_factory=list)

    @property
    def data(self) -> Path:
        return self.workdir / "data"

    @property
    def config(self) -> Path:
        return self.workdir / "config"

    def write_options(self) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        self.config.mkdir(parents=True, exist_ok=True)
        options = {
            "N8N_LOG_LEVEL": "info",
            "N8N_SECURE_COOKIE": False,
            "env_vars": [
                {"key": "WOOW_SMOKE_VISIBLE", "value": "visible"},
                {"key": "WOOW_SMOKE_API_TOKEN", "value": SECRET_OPTION_VALUE},
                *self.env_vars,
            ],
        }
        (self.data / "options.json").write_text(json.dumps(options))

    def start(self) -> None:
        if not self.network:
            self.network = f"{self.name}-net"
            docker("network", "create", "--subnet", SUBNET, self.network)
        if not (self.data / "options.json").exists():
            self.write_options()
        docker(
            "run", "-d", "--name", self.name,
            "--network", self.network, "--ip", ADDON_IP,
            "-e", f"SUPERVISOR_TOKEN={FAKE_SUPERVISOR_TOKEN}",
            "-e", f"HASSIO_TOKEN={FAKE_SUPERVISOR_TOKEN}",
            "-v", f"{self.data}:/data",
            "-v", f"{self.config}:/config",
            "-p", "127.0.0.1::5678",
            self.image,
        )
        self._read_port()

    def _read_port(self) -> None:
        mapping = docker("port", self.name, "5678/tcp").strip().splitlines()[0]
        self.port = int(mapping.rsplit(":", 1)[1])

    def restart(self) -> None:
        """Restart the container (the published host port changes)."""
        docker("restart", "-t", "60", self.name)
        self._read_port()

    def stop(self, remove: bool = True) -> None:
        docker("stop", "-t", "60", self.name, check=False)
        if remove:
            docker("rm", "-f", self.name, check=False)

    def destroy(self) -> None:
        docker("rm", "-f", self.name, check=False)
        if self.network:
            docker("network", "rm", self.network, check=False)

    def logs(self) -> str:
        result = subprocess.run(
            ["docker", "logs", self.name], capture_output=True, text=True, check=False
        )
        return result.stdout + result.stderr

    def exec(self, script: str, check: bool = True) -> str:
        return docker("exec", self.name, "sh", "-c", script, check=check)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def wait_ready(self, timeout: float = 900) -> dict[str, float]:
        """Wait for /healthz then /healthz/readiness; return the seconds each took."""
        started = time.monotonic()
        marks: dict[str, float] = {}
        while time.monotonic() - started < timeout:
            for key, path in (("healthz", "/healthz"), ("readiness", "/healthz/readiness")):
                if key in marks:
                    continue
                if http_status(self.url(path)) == 200:
                    marks[key] = round(time.monotonic() - started, 1)
            if "readiness" in marks:
                marks.setdefault("healthz", marks["readiness"])
                return marks
            if docker("inspect", "-f", "{{.State.Running}}", self.name).strip() != "true":
                raise AssertionError("add-on container exited:\n" + self.logs())
            time.sleep(0.5)
        raise AssertionError(f"n8n not ready after {timeout}s:\n" + self.logs()[-6000:])

    def supervisor_get(self, path: str) -> tuple[int, str]:
        """GET the ingress port from the Supervisor's address, as the watchdog does."""
        out = docker(
            "run", "--rm", "--network", self.network, "--ip", SUPERVISOR_IP,
            "--entrypoint", "curl", self.image,
            "-s", "-o", "/dev/stdout", "-w", "\n%{http_code}", "--max-time", "10",
            f"http://{ADDON_IP}:5690{path}",
        )
        body, _, code = out.rpartition("\n")
        return int(code), body


def http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0


class N8nClient:
    """Cookie-authenticated client for n8n's internal REST API."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, method: str, path: str, body: object | None = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=60) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = error.code
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, raw.decode(errors="replace")

    def ok(self, method: str, path: str, body: object | None = None) -> object:
        status, payload = self.request(method, path, body)
        assert 200 <= status < 300, f"{method} {path} -> {status}: {payload}"
        return payload["data"] if isinstance(payload, dict) and "data" in payload else payload

    def wait_rest(self, timeout: float = 120) -> None:
        """Readiness can precede the REST routes (n8n 2.12); wait for them."""
        deadline = time.monotonic() + timeout
        while True:
            status, _payload = self.request("GET", "/rest/settings")
            if status == 200:
                return
            assert time.monotonic() < deadline, f"/rest/settings still {status}"
            time.sleep(1)

    def setup_owner(self) -> None:
        self.wait_rest()
        self.ok("POST", "/rest/owner/setup", OWNER)

    def login(self) -> None:
        self.wait_rest()
        self.ok(
            "POST",
            "/rest/login",
            {"emailOrLdapLoginId": OWNER["email"], "password": OWNER["password"]},
        )


JS_CODE = """return [{json: {
  js: [1, 2, 3].reduce((a, b) => a + b, 0),
  visible: $env.WOOW_SMOKE_VISIBLE ?? null,
  supervisor: $env.SUPERVISOR_TOKEN ?? null,
  hassio: $env.HASSIO_TOKEN ?? null,
  broker: $env.N8N_RUNNERS_AUTH_TOKEN ?? null,
  credentialOk: $input.first().json.credentialOk ?? null,
}}];"""

PY_CODE = """import os
previous = _items[0]["json"]
return [{"json": {**previous, "py": sum(range(10)), "pyEnvSupervisor": os.environ.get("SUPERVISOR_TOKEN")}}]"""


def smoke_workflow(path: str, name: str = "Woow smoke") -> dict[str, object]:
    """Webhook -> JavaScript Code node -> native Python Code node."""
    return {
        "name": name,
        "active": False,
        "settings": {"executionOrder": "v1"},
        "nodes": [
            {
                "parameters": {"path": path, "responseMode": "lastNode", "options": {}},
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "webhookId": str(uuid.uuid4()),
            },
            {
                "parameters": {"jsCode": JS_CODE},
                "name": "JS",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [220, 0],
            },
            {
                "parameters": {"language": "pythonNative", "pythonCode": PY_CODE},
                "name": "PY",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [440, 0],
            },
        ],
        "connections": {
            "Webhook": {"main": [[{"node": "JS", "type": "main", "index": 0}]]},
            "JS": {"main": [[{"node": "PY", "type": "main", "index": 0}]]},
        },
    }


def activate(client: N8nClient, workflow: dict[str, object]) -> None:
    status, payload = client.request(
        "POST",
        f"/rest/workflows/{workflow['id']}/activate",
        {"versionId": workflow["versionId"]},
    )
    if 200 <= status < 300:
        return
    # n8n releases before the publish flow activated through PATCH.
    client.ok(
        "PATCH",
        f"/rest/workflows/{workflow['id']}",
        {"active": True, "versionId": workflow["versionId"]},
    )


def call_webhook(addon: Addon, path: str, timeout: float = 120) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(addon.url(f"/webhook/{path}"), timeout=60) as response:
                payload = json.loads(response.read())
                return payload[0] if isinstance(payload, list) else payload
        except urllib.error.HTTPError as error:
            last = f"{error.code} {error.read()[:300]!r}"
        except (urllib.error.URLError, OSError) as error:
            last = str(error)
        time.sleep(2)
    raise AssertionError(f"webhook {path} did not answer: {last}\n{addon.logs()[-4000:]}")


def assert_code_nodes(result: dict[str, object]) -> None:
    assert result.get("js") == 6, f"JavaScript Code node result: {result}"
    assert result.get("py") == 45, f"Python Code node result: {result}"
    assert result.get("visible") == "visible", f"$env lost a user variable: {result}"
    for key in ("supervisor", "hassio", "broker", "pyEnvSupervisor"):
        assert result.get(key) is None, f"workflow can read {key}: {result}"
