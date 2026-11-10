"""code_server 升級測試的資料檢查（pipeline unattended-pipeline/182、/186）。

Store 的升級測試（Woow_HA_App_Store .addon-sync/upgrade_runtime.py）在比對對象
（最新 Release）上跑 `seed`，再用同一份 `/data` 啟動新版本、跑 `verify`。兩支 hook
都在 mock Supervisor 的容器裡執行，透過 $DATA_DIR_DATA 讀寫 addon 的 /data。

code_server 沒有資料庫，也沒有寫入使用者資料的 API；它的使用者資料就是 /data
裡的檔案，所以 hook 直接讀寫資料目錄（#182 的決定，#90 的 API 標準不適用）。

seed     1. 在 /data/pi-agent 寫一個帶隨機值的使用者檔案（放在自己的子目錄，
            pi-seed、migrate-claude-state、woow-agent-sync 都不碰它）。
         2. 等比對對象的 init-woow 把 ACP agent 合併進
            /data/vscode/User/settings.json（至少 pi 與 claude，0.1.6 起就有），
            再加一個使用者設定值與一個自訂 ACP agent（都帶隨機值）。
         隨機值與寫入後 settings.json 的 mtime 存在 HOOK_STATE_DIR。
verify   1. 使用者檔案還在、內容不變。
         2. 等新版本的 init-woow 重寫 settings.json（mtime 或 inode 變了，表示
            這次啟動的 jq 合併真的跑過），然後確認新版本 rootfs/opt/acp-settings.json
            保證的每個 agent（NEW_AGENTS：pi、claude、codex）都在且 command 正確、
            使用者設定值不變、自訂 agent 沒有被蓋掉或改動。
            NEW_AGENTS 要和 rootfs/opt/acp-settings.json 的 acp.agents 一致
            （hook 只看得到 upgrade-check/，讀不到那個檔案）。

每項檢查寫進 $REPORT_DIR/<hook>.json；有任何一項不是 pass，hook 就 exit 1。
只用標準函式庫（hook 跑在 python:3.12-alpine）。
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time

USER_FILE = ("pi-agent", "woow-upgrade-check", "user-note.txt")
SETTINGS = ("vscode", "User", "settings.json")
USER_SETTING = "window.title"
CUSTOM_AGENT = "woow-upgrade-check"
# Agents every version since 0.1.6 merges: what seed waits for on the comparison target.
OLD_AGENTS = {"pi": "pi-code", "claude": "claude-agent-acp"}
# Agents this version's init-woow guarantees (rootfs/opt/acp-settings.json `acp.agents`).
NEW_AGENTS = {"pi": "pi-code", "claude": "claude-agent-acp", "codex": "codex-code"}
WAIT_SECONDS = 180


def data_path(parts: tuple[str, ...]) -> str:
    return os.path.join(os.environ["DATA_DIR_DATA"], *parts)


def state_path() -> str:
    return os.path.join(os.environ["HOOK_STATE_DIR"], "code-server-seed.json")


def read_settings() -> dict:
    with open(data_path(SETTINGS), encoding="utf-8") as f:
        loaded = json.load(f)
    assert isinstance(loaded, dict), f"settings.json is a {type(loaded).__name__}, not an object"
    return loaded


def agents_problem(settings: dict, required: dict[str, str]) -> str:
    """'' when acp.agents has every `required` agent with its command, else what is wrong."""
    agents = settings.get("acp.agents")
    if not isinstance(agents, dict):
        return f"acp.agents is {agents!r}"
    wrong = {name: (agents.get(name) or {}).get("command") if isinstance(agents.get(name), dict) else agents.get(name)
             for name, command in required.items()
             if not isinstance(agents.get(name), dict) or agents[name].get("command") != command}
    return f"agents with a missing or wrong command (name: command): {wrong}; present: {sorted(agents)}" if wrong else ""


def wait_for(condition, what: str, timeout: float = WAIT_SECONDS):
    """Poll condition() (returns a value, or raises / returns None to keep waiting) until it gives a value."""
    deadline, last = time.monotonic() + timeout, "no attempt"
    while True:
        try:
            value = condition()
            if value is not None:
                return value
            last = "not yet"
        except Exception as error:  # noqa: BLE001 - keep polling, report the last reason
            last = f"{type(error).__name__}: {error}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"{what} after {int(timeout)} s: {last}")
        time.sleep(2)


class Checks:
    """每項檢查都會跑；依賴的前一項失敗時記為 skip，報告裡仍看得到失敗的那一項。"""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def run(self, name: str, check, needs: bool = True):
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
        self.items.append({"name": name, "result": "pass", "detail": detail[:500]})
        print(f"pass {name}: {detail}", flush=True)
        return value if value is not None else True

    def finish(self, hook: str) -> int:
        with open(os.path.join(os.environ["REPORT_DIR"], f"{hook}.json"), "w", encoding="utf-8") as f:
            json.dump({"checks": self.items}, f, indent=1)
        return 1 if any(c["result"] != "pass" for c in self.items) else 0


def seed() -> int:
    checks = Checks()
    token = secrets.token_hex(16)
    state = {
        "user_file": os.path.join(*USER_FILE),
        "user_file_content": f"WOOW upgrade check, written on {os.environ.get('ADDON_VERSION', '?')}: {token}\n",
        "user_setting": {USER_SETTING: f"WOOW upgrade check {token}"},
        "custom_agent": {CUSTOM_AGENT: {"command": "woow-upgrade-check-agent", "args": ["--token", token],
                                        "env": {"WOOW_UPGRADE_CHECK": token}}},
    }

    def write_user_file() -> str:
        path = data_path(USER_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(state["user_file_content"])
        return f"wrote {len(state['user_file_content'])} bytes to {path}"
    checks.run("user file written under /data/pi-agent", write_user_file)

    def merged() -> str:
        return wait_for(lambda: None if agents_problem(read_settings(), OLD_AGENTS) else
                        "present: " + ", ".join(sorted(read_settings()["acp.agents"])),
                        "init-woow had not merged the pi and claude agents into settings.json")
    ready = checks.run("settings.json has the pi and claude agents (init-woow ran on the old version)", merged)

    def add_settings() -> str:
        path = data_path(SETTINGS)
        settings = read_settings()
        settings.update(state["user_setting"])
        settings["acp.agents"][CUSTOM_AGENT] = state["custom_agent"][CUSTOM_AGENT]
        tmp = path + ".woow-upgrade-check.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
            f.write("\n")
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
        st = os.stat(path)
        state["settings_mtime_ns"], state["settings_inode"] = st.st_mtime_ns, st.st_ino
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        return f"added {USER_SETTING} and acp.agents.{CUSTOM_AGENT} to {path}"
    added = checks.run("user setting and custom ACP agent added to settings.json", add_settings, bool(ready))

    def read_back() -> str:
        settings = read_settings()
        assert settings.get(USER_SETTING) == state["user_setting"][USER_SETTING], f"{USER_SETTING} is {settings.get(USER_SETTING)!r}"
        assert settings["acp.agents"].get(CUSTOM_AGENT) == state["custom_agent"][CUSTOM_AGENT], "custom agent not read back"
        return "read back unchanged"
    checks.run("settings.json reads back the seeded values", read_back, bool(added))
    return checks.finish("seed")


def verify() -> int:
    checks = Checks()

    def read_state() -> dict:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict) and "settings_mtime_ns" in loaded, f"seed state is incomplete: {sorted(loaded)}"
        return loaded
    want = checks.run("seed state readable", read_state)
    if want is None:
        want = {}

    def user_file() -> str:
        path = data_path(USER_FILE)
        with open(path, encoding="utf-8") as f:
            got = f.read()
        assert got == want["user_file_content"], f"{path} changed: {got[:200]!r}"
        return f"{path} unchanged"
    checks.run("user file under /data/pi-agent still there, unchanged", user_file, bool(want))

    def rewritten() -> str:
        def changed():
            st = os.stat(data_path(SETTINGS))
            if st.st_mtime_ns != want["settings_mtime_ns"] or st.st_ino != want["settings_inode"]:
                read_settings()  # parses: init-woow finished its write-temp-then-rename
                return f"mtime {want['settings_mtime_ns']} -> {st.st_mtime_ns}, inode {want['settings_inode']} -> {st.st_ino}"
            return None
        return wait_for(changed, "settings.json was not rewritten by the new version's init-woow")
    merged = checks.run("settings.json rewritten by init-woow on the new version", rewritten, bool(want))

    def both_agents() -> str:
        problem = agents_problem(read_settings(), NEW_AGENTS)
        assert not problem, problem
        return ", ".join(f"{name} -> {command}" for name, command in NEW_AGENTS.items())
    checks.run("pi, claude and codex ACP agents all present after the merge", both_agents, bool(merged))

    def user_setting() -> str:
        got = read_settings().get(USER_SETTING)
        assert got == want["user_setting"][USER_SETTING], f"{USER_SETTING} is {got!r}"
        return f"{USER_SETTING} unchanged"
    checks.run("user setting kept, unchanged", user_setting, bool(merged))

    def custom_agent() -> str:
        agents = read_settings().get("acp.agents") or {}
        got = agents.get(CUSTOM_AGENT)
        assert got == want["custom_agent"][CUSTOM_AGENT], f"acp.agents.{CUSTOM_AGENT} is {got!r}; agents: {sorted(agents)}"
        return f"acp.agents.{CUSTOM_AGENT} unchanged; agents: {', '.join(sorted(agents))}"
    checks.run("custom ACP agent kept, not overwritten", custom_agent, bool(merged))
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
