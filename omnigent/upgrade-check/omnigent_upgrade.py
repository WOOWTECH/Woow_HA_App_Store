"""Woow Omnigent 升級測試的資料檢查（Store pipeline #138）。

Store 的升級測試（Woow_HA_App_Store .addon-sync/upgrade_runtime.py）在比對對象
（最新 Release）上跑 `seed`，再用同一份 `/data` 啟動新版本、跑 `verify`。兩支 hook
都在 mock Supervisor 的容器裡執行，只透過 omnigent 自己的 HTTP API（ADDON_URL，
也就是 8000 port 的 web UI）讀寫，不碰資料庫：

seed     admin 登入；建立一個暫停中的 scheduled task（不需要 runner），以及一個
         經由 invite → register 建立的記號成員。
verify   server 起得來（migration 跑完）；admin 用同一組密碼登入；scheduled task
         的內容不變、仍是暫停、沒有被觸發，新版有 `session_mode` 時必須是 "new"
         （0.21.0 的 migration d0a1f879a01d 對既有 task 的預設值）；task 指向的 agent
         還在；記號成員還在、還能用原密碼登入。

verify 需要的 id 與記號成員的密碼存在 HOOK_STATE_DIR（只在 CI 的暫存目錄）。
每項檢查寫進 $REPORT_DIR/<hook>.json；有任何一項 fail，hook 就 exit 1。
只用標準函式庫（hook 跑在 python:3.12-alpine）。
"""
from __future__ import annotations

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
                timeout: float = 60) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status, raw, set_cookies = response.status, response.read(), response.headers.get_all("Set-Cookie")
        except urllib.error.HTTPError as error:
            status, raw, set_cookies = error.code, error.read(), error.headers.get_all("Set-Cookie")
        except (urllib.error.URLError, OSError) as error:
            return 0, str(error)
        for header in set_cookies or ():
            parsed = SimpleCookie()
            parsed.load(header)
            for name, morsel in parsed.items():
                self.cookies[name] = morsel.value
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, raw.decode(errors="replace")[:300]

    def ok(self, method: str, path: str, body: object | None = None) -> object:
        status, payload = self.request(method, path, body)
        if not 200 <= status < 300:
            raise AssertionError(f"{method} {path} -> {status}: {str(payload)[:300]}")
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

    with open(state_path(), "w", encoding="utf-8") as f:
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
        return f"{agent.get('name')} ({seeded_task['agent_id']})"
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
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
