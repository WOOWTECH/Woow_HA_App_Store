"""Woow Omnigent 升級測試的資料檢查（Store pipeline #138）。

Store 的升級測試（Woow_HA_App_Store .addon-sync/upgrade_runtime.py）在比對對象
（最新 Release）上跑 `seed`，再用同一份 `/data` 啟動新版本、跑 `verify`。兩支 hook
都在 mock Supervisor 的容器裡執行，只透過 omnigent 自己的 HTTP API（ADDON_URL，
也就是 8000 port 的 web UI）讀寫，不碰資料庫：

seed     admin 登入；建立 paused task、記號成員、private/shared session、read grant
         與檔案。舊版已有 MCP 時，另建 active/revoked profile 並保存原 URL。
verify   migration 後使用原帳密登入，驗 task/agent/session/ACL/檔案 SHA-256；
         新版建立、使用、撤銷 profile；MCP A→B 升級沿用原 token 與 revoked_at。

verify 需要的 id 與記號成員的密碼存在 HOOK_STATE_DIR（只在 CI 的暫存目錄）。
每項檢查寫進 $REPORT_DIR/<hook>.json；有任何一項 fail，hook 就 exit 1。
只用標準函式庫（hook 跑在 python:3.12-alpine）。
"""
from __future__ import annotations

import io
import hashlib
import tarfile
import urllib.parse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie

# 0.20、0.21 都有的內建 agent；找不到時退回清單的第一個（detail 會寫明）。
AGENT_NAME = "claude-native-ui"
TASK = {
    "name": "Woow upgrade check",
    "prompt": "Upgrade check marker. This task stays paused and never runs.",
    # 每年一次；建立後立刻暫停，所以測試期間不會觸發。
    "rrule": "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1",
    "timezone": "Asia/Taipei",
}
# 升級前後都必須相同的 task 欄位（API 回應的 key）。
KEPT_FIELDS = (
    "id", "name", "prompt", "rrule", "owner_user_id", "agent_id", "timezone", "created_at",
    "model_override", "reasoning_effort", "permission_mode", "max_cost_usd",
    "workspace", "host_id", "execution_target", "state",
)
MARKER_USER = "upgrade-marker"
READY_TIMEOUT = 300


class Client:
    """omnigent 的 HTTP API；session cookie 自己保存，不受 cookie 的 Secure／domain 規則影響。"""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str, body: object | None = None,
                timeout: float = 60, *, content_type: str = "application/json",
                raw_response: bool = False) -> tuple[int, object]:
        data = body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
        headers = {"Content-Type": content_type, "Accept": "application/json, text/event-stream"}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status, raw, set_cookies = response.status, response.read(), response.headers.get_all("Set-Cookie")
        except urllib.error.HTTPError as error:
            status, raw, set_cookies = error.code, error.read(), error.headers.get_all("Set-Cookie")
        except (urllib.error.URLError, OSError) as error:
            return 0, type(error).__name__
        for header in set_cookies or ():
            parsed = SimpleCookie()
            parsed.load(header)
            for name, morsel in parsed.items():
                self.cookies[name] = morsel.value
        if raw_response:
            return status, raw
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, raw.decode(errors="replace")[:300]

    def ok(self, method: str, path: str, body: object | None = None) -> object:
        status, payload = self.request(method, path, body)
        if not 200 <= status < 300:
            raise AssertionError(f"HTTP {method} failed with status {status}")
        return payload

    def wait_ready(self) -> str:
        """等 /health 與 /v1/info 都回應，且 admin 已經建立（needs_setup 為 false）。"""
        deadline, last = time.monotonic() + READY_TIMEOUT, ""
        while time.monotonic() < deadline:
            status, health = self.request("GET", "/health", timeout=10)
            if status == 200:
                status, info = self.request("GET", "/v1/info", timeout=10)
                if status == 200 and isinstance(info, dict) and info.get("needs_setup") is False:
                    return f"omnigent {info.get('server_version')}"
                last = f"/v1/info -> {status} {str(info)[:200]}"
            else:
                last = f"/health -> {status} {str(health)[:200]}"
            time.sleep(2)
        raise AssertionError(f"server not ready after {READY_TIMEOUT}s: {last}")

    def login(self, username: str, password: str) -> str:
        self.ok("POST", "/auth/login", {"username": username, "password": password})
        me = self.ok("GET", "/auth/me")
        assert isinstance(me, dict) and me.get("id") == username.strip().lower(), f"/auth/me answered {me}"
        return f"{me['id']} (is_admin={me.get('is_admin')})"


class Checks:
    """每項檢查都會跑；依賴的前一項失敗時記為 skip，報告裡仍看得到失敗的那一項。"""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def run(self, name: str, check, needs: bool = True) -> object:
        if not needs:
            self.items.append({"name": name, "result": "skip", "detail": "an earlier check it needs failed"})
            print(f"skip {name}", flush=True)
            return None
        try:
            value = check()
        except Exception as error:  # noqa: BLE001 - 每個例外都記成一項失敗與原因
            self.items.append({"name": name, "result": "fail", "detail": f"{type(error).__name__}: {error}"[:500]})
            print(f"FAIL {name}: {error}", flush=True)
            return None
        detail = value if isinstance(value, str) else "ok"
        self.items.append({"name": name, "result": "pass", "detail": detail})
        print(f"pass {name}: {detail}", flush=True)
        return value if value is not None else True

    def finish(self, hook: str) -> int:
        with open(os.path.join(os.environ["REPORT_DIR"], f"{hook}.json"), "w", encoding="utf-8") as f:
            json.dump({"checks": self.items}, f, indent=1)
        return 1 if any(c["result"] != "pass" for c in self.items) else 0


def admin_credentials() -> tuple[str, str]:
    """add-on 的 admin 帳密：框架寫進 /data/options.json（admin_password 由框架產生）。"""
    with open(os.path.join(os.environ["DATA_DIR_DATA"], "options.json"), encoding="utf-8") as f:
        options = json.load(f)
    username, password = options.get("admin_username"), options.get("admin_password")
    assert username and password, "options.json has no admin_username/admin_password"
    return username, password


def state_path() -> str:
    return os.path.join(os.environ["HOOK_STATE_DIR"], "omnigent-seed.json")


PROFILE_API = "/v1/admin/mcp-server/profiles"
ARTIFACT = b"Omnigent upgrade fixture: preserve every byte.\n"


def multipart(api: Client, path: str, parts: list[tuple[str, str | None, str, bytes]]) -> dict:
    boundary = "upgrade-" + secrets.token_hex(16)
    data = bytearray()
    for name, filename, mime, content in parts:
        data.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"".encode())
        if filename:
            data.extend(f"; filename=\"{filename}\"".encode())
        data.extend(f"\r\nContent-Type: {mime}\r\n\r\n".encode() + content + b"\r\n")
    data.extend(f"--{boundary}--\r\n".encode())
    status, result = api.request("POST", path, bytes(data), content_type=f"multipart/form-data; boundary={boundary}")
    assert 200 <= status < 300 and isinstance(result, dict), f"fixture upload failed: HTTP {status}"
    return result


def agent_bundle() -> bytes:
    data = (b"name: upgrade-fixture\nprompt: Upgrade fixture; never execute.\nexecutor:\n"
            b"  model: gpt-4o-mini\n  harness: openai-agents\n")
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        entry = tarfile.TarInfo("agent.yaml")
        entry.size = len(data)
        archive.addfile(entry, io.BytesIO(data))
    return out.getvalue()


def member_client(state: dict) -> Client:
    member = state["member"]
    client = Client(os.environ["ADDON_URL"])
    client.login(member["username"], member["password"])
    return client


def seed_sessions(api: Client, state: dict) -> str:
    sessions = {}
    for visibility in ("private", "shared"):
        created = multipart(api, "/v1/sessions", [
            ("metadata", None, "application/json", json.dumps({"title": f"Upgrade {visibility} fixture"}).encode()),
            ("bundle", "agent.tar.gz", "application/gzip", agent_bundle()),
        ])
        sid = created["session_id"]
        snapshot = api.ok("GET", f"/v1/sessions/{sid}")
        sessions[visibility] = {"id": sid, "snapshot": {
            k: snapshot[k] for k in ("session_id", "id", "title", "agent_id", "created_at", "metadata") if k in snapshot
        }}
    state["sessions"] = sessions
    shared = sessions["shared"]["id"]
    api.ok("PUT", f"/v1/sessions/{shared}/permissions", {"user_id": state["member"]["username"], "level": 1})
    uploaded = multipart(api, f"/v1/sessions/{shared}/resources/files",
                         [("file", "upgrade-marker.txt", "text/plain", ARTIFACT)])
    state["artifact"] = {"id": uploaded["id"], "sha256": hashlib.sha256(ARTIFACT).hexdigest()}
    verify_sessions(api, state)
    return "private/shared sessions, read grant and file bytes recorded"


def verify_sessions(api: Client, state: dict) -> str:
    member = member_client(state)
    for visibility, saved in state["sessions"].items():
        current = api.ok("GET", f"/v1/sessions/{saved['id']}")
        assert all(current.get(k) == v for k, v in saved["snapshot"].items()), "session fields changed"
        status, _ = member.request("GET", f"/v1/sessions/{saved['id']}")
        assert status == 200 if visibility == "shared" else status in (403, 404), "session ACL changed"
    shared = state["sessions"]["shared"]["id"]
    permissions = api.ok("GET", f"/v1/sessions/{shared}/permissions")["permissions"]
    assert any(p["user_id"] == state["member"]["username"] and p["level"] == 1 for p in permissions), "read grant changed"
    artifact = state["artifact"]
    status, content = member.request("GET", f"/v1/sessions/{shared}/resources/files/{artifact['id']}/content", raw_response=True)
    assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"], "artifact content changed"
    return "session fields, privacy, read grant and artifact SHA-256 unchanged"


def create_profile(api: Client, state: dict, name: str) -> dict:
    member = state["member"]
    created = api.ok("POST", PROFILE_API, {"name": name, "username": member["username"], "password": member["password"]})
    # The API is authoritative. A profile URL must never use the HA UI origin.
    url = urllib.parse.urlsplit(created["connection_url"])
    assert url.scheme in ("https", "http") and url.hostname, "missing canonical connection URL"
    assert not url.query and not url.fragment and not url.username, "unsafe connection URL"
    assert "/api/hassio_ingress/" not in url.path, "connection URL uses HA Ingress"
    assert url.path.endswith("/mcp/private_" + created["token"]), "connection URL token mismatch"
    with open(os.path.join(os.environ["DATA_DIR_DATA"], "options.json"), encoding="utf-8") as f:
        public_base = json.load(f).get("mcp_public_base_url", "").rstrip("/")
    if public_base:
        assert created["connection_url"] == public_base + "/mcp/private_" + created["token"], "public base changed or duplicated"
    return created


def rpc(profile: dict, method: str, params: dict | None = None) -> tuple[int, object]:
    # No browser or HA cookies. Direct ADDON_URL reaches the same server even
    # when the advertised public hostname is unavailable inside the mock.
    return Client(os.environ["ADDON_URL"]).request("POST", "/mcp/private_" + profile["token"],
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def check_profile(profile: dict, *, active: bool, require_history: bool = True) -> str:
    if not active:
        status, _ = rpc(profile, "tools/list")
        assert status == 401, f"revoked token accepted: HTTP {status}"
        return "revoked token still denied"
    initialized_status, initialized = rpc(profile, "initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "ha-upgrade-check", "version": "1"}})
    assert initialized_status == 200 and "result" in initialized, "MCP initialization failed"
    status, result = rpc(profile, "tools/list")
    assert status == 200 and "result" in result, f"active token failed: HTTP {status}"
    names = {t["name"] for t in result["result"]["tools"]}
    required = {"omnigent_session_get", "omnigent_automation_list"}
    if require_history:
        required.add("omnigent_session_history")
    assert required <= names, "MCP tools missing"
    return "active token works without browser cookies; required live tools available"


def seed_profiles(api: Client, state: dict) -> str:
    status, _ = api.request("GET", PROFILE_API)
    if status == 404:
        state["profiles"] = None
        return "baseline has no MCP API; create/revoke will be checked after upgrade"
    assert status == 200, f"MCP capability probe failed: HTTP {status}"
    active = create_profile(api, state, "Upgrade active fixture")
    revoked = create_profile(api, state, "Upgrade revoked fixture")
    api.ok("DELETE", PROFILE_API + "/" + revoked["profile"]["id"])
    listed = {p["id"]: p for p in api.ok("GET", PROFILE_API)["profiles"]}
    for profile in (active, revoked):
        profile["profile"] = listed[profile["profile"]["id"]]
    state["profiles"] = {"active": active, "revoked": revoked}
    check_profile(active, active=True, require_history=False)
    check_profile(revoked, active=False)
    return "active URL and revoked URL recorded privately for the next version"


def verify_profiles(api: Client, state: dict) -> str:
    profiles = state["profiles"]
    if profiles is None:
        return "baseline predates MCP; new profile lifecycle checked separately"
    listed = {p["id"]: p for p in api.ok("GET", PROFILE_API)["profiles"]}
    for name, saved in profiles.items():
        current = listed[saved["profile"]["id"]]
        assert all(current[k] == saved["profile"][k] for k in
                   ("id", "name", "user_id", "created_by", "created_at", "revoked_at", "active")), "profile identity or revocation changed"
        check_profile(saved, active=name == "active")
    return "original tokens, account bindings and revocation timestamps preserved"


def new_profile_lifecycle(api: Client, state: dict) -> str:
    created = create_profile(api, state, "Upgrade lifecycle fixture")
    try:
        check_profile(created, active=True)
        for visibility, saved in state["sessions"].items():
            for tool in ("omnigent_session_get", "omnigent_session_history"):
                status, result = rpc(created, "tools/call", {"name": tool, "arguments": {"session_id": saved["id"]}})
                assert status == 200 and "result" in result, "MCP session call failed"
                denied = result["result"].get("isError", False)
                assert denied == (visibility == "private"), "MCP did not preserve session ACL"
        status, _ = member_client(state).request("GET", PROFILE_API)
        assert status == 403, "member can administer MCP profiles"
    finally:
        api.ok("DELETE", PROFILE_API + "/" + created["profile"]["id"])
    check_profile(created, active=False)
    return "create, canonical URL, tools, session ACL and revocation passed"


def seed() -> int:
    api, checks, state = Client(os.environ["ADDON_URL"]), Checks(), {}
    ready = checks.run("server ready", api.wait_ready)
    creds = checks.run("admin credentials in options.json", admin_credentials)
    admin = checks.run("admin logs in", lambda: api.login(*creds), bool(ready) and bool(creds))

    def scheduled_task() -> str:
        agents = api.ok("GET", "/v1/agents").get("data") or []
        assert agents, "no agents listed"
        agent = next((a for a in agents if a.get("name") == AGENT_NAME), agents[0])
        created = api.ok("POST", "/v1/scheduled-tasks", {**TASK, "agent_id": agent["id"]})
        api.ok("PATCH", f"/v1/scheduled-tasks/{created['id']}", {"state": "paused"})
        task = api.ok("GET", f"/v1/scheduled-tasks/{created['id']}")
        assert task.get("state") == "paused", f"state is {task.get('state')!r} after pausing"
        state["task"] = {k: task.get(k) for k in KEPT_FIELDS}
        state["agent"] = {k: agent.get(k) for k in ("id", "name", "description", "version")}
        return f"{task['id']} (agent {agent.get('name')}, paused)"
    checks.run("scheduled task created", scheduled_task, bool(admin))

    def member() -> str:
        invite = api.ok("POST", "/auth/invite", {"is_admin": False})
        password = secrets.token_urlsafe(18)
        # register 會替新成員簽 cookie，用另一個 Client，admin 的 session 不受影響。
        Client(os.environ["ADDON_URL"]).ok(
            "POST", "/auth/register", {"invite": invite["token"], "username": MARKER_USER, "password": password})
        users = {u.get("id"): u for u in api.ok("GET", "/auth/users").get("users", [])}
        assert MARKER_USER in users, f"/auth/users lists {sorted(users)}"
        state["member"] = {"username": MARKER_USER, "password": password}
        return f"{MARKER_USER} registered through an invite"
    checks.run("member created", member, bool(admin))

    checks.run("private/shared sessions and artifact created", lambda: seed_sessions(api, state),
               bool(admin) and "member" in state)
    checks.run("MCP profiles seeded when supported", lambda: seed_profiles(api, state),
               bool(admin) and "member" in state)
    # State includes synthetic account passwords and bearer URLs. Never publish
    # this directory as an artifact; only the redacted JSON report is public.
    fd = os.open(state_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    return checks.finish("seed")


def verify() -> int:
    api, checks = Client(os.environ["ADDON_URL"]), Checks()

    def read_state() -> dict[str, object]:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict), f"seed state is not an object: {type(loaded).__name__}"
        return loaded
    state = checks.run("seed state readable", read_state) or {}
    ready = checks.run("server ready (migrations finished)", api.wait_ready)
    creds = checks.run("admin credentials in options.json", admin_credentials)
    admin = checks.run("admin logs in with the same password", lambda: api.login(*creds), bool(ready) and bool(creds))
    seeded_task = state.get("task") if isinstance(state.get("task"), dict) else None

    def task_kept() -> str:
        task = api.ok("GET", f"/v1/scheduled-tasks/{seeded_task['id']}")
        changed = {k: (seeded_task[k], task.get(k)) for k in KEPT_FIELDS if task.get(k) != seeded_task[k]}
        assert not changed, f"changed by the upgrade (before, after): {changed}"
        assert task.get("last_run_at") is None, f"the paused task ran at {task.get('last_run_at')}"
        detail = "same fields, still paused, never ran"
        if "session_mode" in task:
            assert task["session_mode"] == "new", f"session_mode is {task['session_mode']!r}, expected 'new'"
            assert task.get("session_id") is None, f"session_id is {task.get('session_id')!r}, expected none"
            detail += ", session_mode new"
        return detail
    checks.run("scheduled task kept", task_kept, bool(admin) and seeded_task is not None)

    def agent_kept() -> str:
        agent = api.ok("GET", f"/v1/agents/{seeded_task['agent_id']}")
        assert all(agent.get(k) == v for k, v in state["agent"].items()), "agent fields changed"
        return "same agent identity and configuration summary"
    checks.run("scheduled task's agent still exists", agent_kept, bool(admin) and seeded_task is not None)

    member = state.get("member") if isinstance(state.get("member"), dict) else None

    def member_kept() -> str:
        users = {u.get("id"): u for u in api.ok("GET", "/auth/users").get("users", [])}
        assert member["username"] in users, f"/auth/users lists {sorted(users)}"
        assert users[member["username"]].get("is_admin") is False, "the member became an admin"
        return f"{member['username']} listed, not an admin"
    checks.run("member kept", member_kept, bool(admin) and member is not None)
    checks.run("member logs in with the same password",
               lambda: Client(os.environ["ADDON_URL"]).login(member["username"], member["password"]),
               bool(ready) and member is not None)
    checks.run("private/shared sessions and artifact kept", lambda: verify_sessions(api, state),
               bool(admin) and member is not None)
    checks.run("existing MCP URLs and revoked state kept", lambda: verify_profiles(api, state), bool(admin))
    checks.run("new MCP profile create/use/revoke", lambda: new_profile_lifecycle(api, state),
               bool(admin) and member is not None)
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
