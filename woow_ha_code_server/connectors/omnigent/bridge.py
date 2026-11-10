#!/usr/bin/env python3
"""Deployment-private Omnigent lifecycle; credentials only enter on stdin.

The vendored controller handles the official 0.16 API, safe host ownership,
catalogue and assistant-only reply checks. This layer replaces Pi lifecycle.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.metadata
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("woow_omnigent_controller", ROOT / "vendor/controller.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
Error = core.PluginError
VERSION = "0.16.0"
PAUSE_MARKER = "WOOW_CONNECTOR_PAUSE_V1"
MUTATIONS = {"configure", "connect", "start", "restore", "stop", "disconnect", "verify", "chat", "continue", "switchModel", "archive", "refreshMcp"}
_strict_normalize_server = core.normalize_server


def normalize_server(value):
    """Explicit private-network HTTP is supported; public endpoints need TLS.

    No DNS lookup or TLS verification bypass. Accounts can choose the private
    service URL explicitly; we never downgrade or rewrite an HTTPS URL.
    """
    if isinstance(value, str):
        try:
            parsed = core.urlsplit(value.strip())
            host = (parsed.hostname or "").lower()
            private = host in {"localhost", "omnigent-server", "host.containers.internal"} or host.endswith(".svc.cluster.local")
            try:
                address = ipaddress.ip_address(host)
                private = private or address.is_loopback or any(address in network for network in (
                    ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
                    ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("100.64.0.0/10"),
                    ipaddress.ip_network("fc00::/7")))
            except ValueError:
                pass
            if parsed.scheme == "http" and private:
                checked = _strict_normalize_server(core.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment)))
                return "http" + checked[5:]
        except ValueError:
            pass
    return _strict_normalize_server(value)


# Apply the same normalization to inherited receipt/kit identity checks.
core.normalize_server = normalize_server


def private_json(path: Path) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    except OSError:
        raise Error("unsafe_state", "連線狀態檔案不安全，已停止操作。") from None
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 65536:
            raise Error("unsafe_state", "連線狀態檔案不安全，已停止操作。")
        # kubelet fsGroup can add group bits when a private PVC is remounted.
        # Tighten our own regular inode before reading; never follow symlinks
        # or chmod a file belonging to another UID.
        if info.st_mode & 0o077:
            os.fchmod(stream.fileno(), 0o600)
        value = json.load(stream)
        if not isinstance(value, dict):
            raise Error("invalid_state", "連線狀態格式不正確。")
        return value


class Connector(core.Plugin):
    def __init__(self, request, **dependencies):
        self.root = Path(os.environ["WOOW_OMNIGENT_CONNECTOR_STATE"])
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid():
            raise Error("unsafe_state", "連線目錄必須由目前使用者持有。")
        os.chmod(self.root, 0o700)
        self.state_path = self.root / "state.json"
        self.saved = private_json(self.state_path)
        self.deployment_managed = os.environ.get("WOOW_OMNIGENT_DEPLOYMENT_MANAGED") == "1"
        config_home = Path(os.environ["OMNIGENT_CONFIG_HOME"])
        data_dir = Path(os.environ["OMNIGENT_DATA_DIR"])
        kit_state = Path(os.environ.get("OG_STATE_DIR") or data_dir / "omnigent-host")
        self.pause_path = Path(os.environ.get("OG_PAUSE_FILE") or kit_state / "connector-paused")
        self.kit_path = Path(os.environ.get("OG_KIT_DIR", "/etc/omnigent-host")) / "supervisor.sh"
        self.kit_status_path = Path(os.environ.get("OG_STATUS_FILE") or kit_state / "status.json")
        os.environ["OG_STATUS_FILE"] = str(self.kit_status_path)
        args = {**request, "stateDir": str(self.root), "configHome": str(config_home), "dataDir": str(data_dir),
                "workspace": self.saved.get("workspace") or os.environ.get("OG_WORKSPACE") or os.environ.get("HOME", "/workspace"),
                "allowManagedHost": True, "omnigentBin": str(Path(sys.executable).parent / "omnigent")}
        if self.saved.get("server"):
            args["server"] = self.saved["server"]
        super().__init__(args, **dependencies)

    def write_state(self, **changes):
        self.saved = {**self.saved, **changes, "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        core.atomic_json(self.state_path, self.saved)

    def pause_supported(self):
        if not self.deployment_managed:
            return True
        try:
            return PAUSE_MARKER in self.kit_path.read_text()
        except OSError:
            return False

    def public_status(self):
        data = super().status()
        receipts = private_json(self.root / "verification.json")
        host = data.get("host", {})
        verified = all(receipts.get(engine, {}).get("ok") is True
                       and receipts[engine].get("cleanup") == "stopped"
                       and receipts[engine].get("server") == data.get("server")
                       and receipts[engine].get("hostId") == host.get("id")
                       and receipts[engine].get("cliVersion") == data.get("engines", {}).get(engine, {}).get("version")
                       and receipts[engine].get("toolsHash") == self.tools_hash()
                       for engine in core.ENGINES)
        phase = "stopped" if self.saved.get("enabled") is False or self.pause_path.exists() else (
            "connected" if host.get("connected") else "needs-login" if not self.saved.get("loginConfirmed") else "offline")
        return {**data, "ok": True, "phase": phase, "connected": host.get("connected", False),
                "mode": "deployment-managed" if self.deployment_managed else "connector-managed",
                "pauseSupported": self.pause_supported(), "loginConfirmed": self.saved.get("loginConfirmed", False),
                "enabled": self.saved.get("enabled", False), "verified": verified, "verification": receipts,
                "runtime": {"installed": True, "version": VERSION},
                "sharedTools": {"skills": str(Path(os.environ["PI_AGENT_DATA_DIR"]) / "skills"),
                                "mcp": str(Path(os.environ["PI_AGENT_DATA_DIR"]) / "shared/mcp.json"),
                                "sessionReloadRequiredAfterChanges": True}}

    def validate_config(self, request):
        settings = dict(self.saved)
        if "server" in request:
            settings["server"] = core.normalize_server(request["server"])
        if "workspace" in request:
            workspace = request["workspace"]
            if not isinstance(workspace, str) or not Path(workspace).is_absolute() or not Path(workspace).is_dir():
                raise Error("invalid_workspace", "工作目錄必須是既有絕對路徑。")
            settings["workspace"] = str(Path(workspace).resolve())
        else:
            settings.setdefault("workspace", str(self.workspace.resolve()))
        if "hostName" in request:
            name = request["hostName"]
            if not isinstance(name, str) or not name.strip() or len(name) > 128 or core.safe_text(name) != name:
                raise Error("invalid_host_name", "Host 名稱必須為 1 至 128 個可顯示字元。")
            settings["hostName"] = name.strip()
        if self.deployment_managed:
            if os.environ.get("OG_WORKSPACE") and settings["workspace"] != str(Path(os.environ["OG_WORKSPACE"]).resolve()):
                raise Error("workspace_managed_by_deployment", "此 host 工作目錄由部署設定管理，請使用原目錄。")
            if os.environ.get("OG_HOST_NAME") and settings.get("hostName") not in (None, os.environ["OG_HOST_NAME"]):
                raise Error("host_name_managed_by_deployment", "此 host 名稱由部署設定管理，請使用原名稱。")
        changed = any(settings.get(k) != self.saved.get(k) for k in ("server", "workspace", "hostName"))
        if changed and self.saved.get("enabled") and self.saved.get("loginConfirmed"):
            raise Error("disconnect_required", "變更連線身分前，請先取消連線。")
        if changed:
            settings.update(loginConfirmed=False, enabled=False)
            (self.root / "verification.json").unlink(missing_ok=True)
        self.write_state(**settings)
        self.workspace = Path(settings["workspace"])
        self.request.update({k: settings[k] for k in ("server", "workspace", "hostName") if k in settings})
        return {"ok": True, "configured": True, **{k: settings[k] for k in ("server", "workspace", "hostName") if k in settings}}

    def ensure_host(self, server):
        if self.deployment_managed:
            host = self.local_host()
            if not host["managerRunning"]:
                raise Error("kit_not_running", "部署的 Omnigent supervisor 未執行；不會另外建立第二份 host。")
            # Remove the persisted pause only after connect authenticated this
            # exact server or resume checked the stored host/account receipt.
            if self.pause_path.exists():
                if not self.pause_supported():
                    raise Error("pause_unsupported", "部署 supervisor 尚未支援安全暫停／恢復。")
                self.pause_path.unlink()
            return "kit"
        return super().ensure_host(server)

    def managed_host_pid(self, server, *, record=None):
        # Exited children awaiting PID1 have no argv/environ. Only a matching
        # recorded birth identity lets us treat such a zombie as already gone.
        recorded = self.host_process_record() if record is None else record
        pid = recorded.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 1:
            try:
                proc = Path(f"/proc/{pid}")
                fields = (proc / "stat").read_text().rsplit(") ", 1)[1].split()
                if fields[0] == "Z" and proc.stat().st_uid == os.getuid() \
                        and recorded.get("server") == server and self.complete_process_identity(recorded) \
                        and all(recorded[key] == self.process_identity(pid).get(key) for key in ("processStart", "bootId")):
                    return None
            except (OSError, IndexError):
                pass
        return super().managed_host_pid(server, record=recorded)

    def stop(self):
        if self.deployment_managed and not self.pause_supported():
            raise Error("pause_unsupported", "部署 supervisor 尚未支援持久暫停；需先套用 WOOW_CONNECTOR_PAUSE_V1 補丁。")
        self.write_state(enabled=False)
        if self.deployment_managed:
            self.pause_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            core.atomic_json(self.pause_path, {"paused": True, "source": "code-server-connector"})
            deadline = self.clock() + min(self.timeout(default=40), 60)
            while self.local_host()["managerRunning"]:
                if core.read_json(self.kit_status_path).get("state") == "paused":
                    return {"ok": True, "stopped": True, "phase": "stopped", "mode": "deployment-managed", "credentialsRetained": True}
                if self.clock() >= deadline:
                    raise Error("pause_timeout", "暫停已持久儲存，supervisor 尚未確認停止。")
                self.sleep(1)
            return {"ok": True, "stopped": True, "phase": "stopped", "mode": "deployment-managed", "credentialsRetained": True}
        try:
            server = self.server()
        except Error as error:
            if error.code != "NEEDS_SERVER":
                raise
            return {"ok": True, "stopped": True, "phase": "stopped", "credentialsRetained": True}
        pid = self.managed_host_pid(server)
        if pid is not None:
            birth = self.process_identity(pid)
            try:
                if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                    pidfd = os.pidfd_open(pid)
                    try:
                        if self.managed_host_pid(server) == pid:
                            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                    finally:
                        os.close(pidfd)
                else:
                    os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = self.clock() + min(self.timeout(default=20), 30)
            # During exit the kernel can clear argv/environ before reporting Z.
            # We already proved ownership before signalling. Poll the birth ID
            # and exit state, without reinterpreting cleared argv as PID reuse.
            while True:
                try:
                    proc = Path(f"/proc/{pid}")
                    state = (proc / "stat").read_text().rsplit(") ", 1)[1].split()[0]
                    if state == "Z" or self.process_identity(pid) != birth:
                        break
                except FileNotFoundError:
                    break
                if self.clock() >= deadline:
                    raise Error("host_stop_timeout", "已送出停止要求，但原 host 尚未結束；自動恢復已暫停。")
                self.sleep(.2)
        return {"ok": True, "stopped": True, "phase": "stopped", "credentialsRetained": True}

    def connected(self, request):
        self.validate_config(request)
        if not self.saved.get("server"):
            raise Error("needs_server", "請先設定 Omnigent server。")
        for name, maximum in (("username", 256), ("password", 4096)):
            if name in request and (not isinstance(request[name], str) or not request[name] or len(request[name]) > maximum):
                raise Error("invalid_login", "登入欄位格式不正確。")
        data = super().connect()
        self.write_state(enabled=True, loginConfirmed=True, hostId=data["host"]["id"],
                         configHome=str(self.config_home), dataDir=str(self.data_dir))
        return {"ok": True, **data, "phase": "connected", "verified": False}

    def restore(self, *, explicit=False):
        if not self.saved.get("loginConfirmed") or (not explicit and not self.saved.get("enabled")):
            if explicit:
                raise Error("needs_connection", "尚無成功連線紀錄，請先完成連線。")
            return {"ok": True, "resumed": False, "reason": "stopped" if self.saved.get("enabled") is False else "no-saved-authority"}
        if not all(self.saved.get(k) for k in ("server", "workspace", "hostId", "configHome", "dataDir")) \
                or self.saved["configHome"] != str(self.config_home) or self.saved["dataDir"] != str(self.data_dir):
            raise Error("connection_identity_mismatch", "既有連線紀錄不屬於這個部署，請重新登入。")
        self.request["resumeHostId"] = self.saved["hostId"]
        self.request["action"] = "resume"
        data = super().resume()
        self.write_state(enabled=True)
        return {"ok": True, "resumed": True, **data}

    def disconnect_connector(self):
        self.write_state(enabled=False, loginConfirmed=False)
        if self.deployment_managed and self.pause_supported():
            self.stop()
        # Official controller clears only this server's token and keeps host ID.
        data = super().disconnect()
        (self.root / "verification.json").unlink(missing_ok=True)
        return {"ok": True, **data, "phase": "needs-login", "verified": False}

    def tools_hash(self):
        data = Path(os.environ["PI_AGENT_DATA_DIR"])
        digest = hashlib.sha256()
        for file in [data / "shared/mcp.json", *sorted((data / "skills").rglob("SKILL.md"))]:
            try:
                digest.update(str(file.relative_to(data)).encode())
                digest.update(file.read_bytes())
            except OSError:
                pass
        return digest.hexdigest()

    def verify_connector(self):
        if not self.saved.get("enabled") or not self.saved.get("loginConfirmed"):
            raise Error("needs_connection", "請先從本擴充完成連線，再開始模型實測。")
        data = super().verify()
        engine = self.request["engine"]
        receipts = private_json(self.root / "verification.json")
        current = super().status()
        receipt = {**data, "server": self.saved["server"], "hostId": self.saved["hostId"],
                   "cliVersion": current["engines"][engine]["version"], "toolsHash": self.tools_hash(),
                   "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        receipts[engine] = receipt
        core.atomic_json(self.root / "verification.json", receipts)
        passed = data.get("ok") is True and data.get("cleanup") == "stopped"
        return {"ok": passed, "verification": receipt,
                **({} if passed else {"error": {"code": data.get("reason") or "VERIFY_CLEANUP_FAILED",
                                               "message": "真實模型回覆或測試對話清理尚未通過。"}})}

    def refresh_mcp(self):
        import asyncio
        from mcp_refresh import refresh_codex, synchronize, RefreshError
        from native_resume import refresh_pi, NativeRefreshError
        from claude_mcp_plugin import refresh_claude, ClaudeRefreshError
        sid = self.request.get("sessionId")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", sid):
            raise Error("INVALID_SESSION_ID", "Enter the existing conversation ID.")
        if not self.saved.get("enabled") or not self.saved.get("loginConfirmed"):
            raise Error("NEEDS_CONNECTION", "Connect this deployment first.")
        client = self.client_factory(self.server(), True)
        try:
            info = client.request("GET", "/v1/sessions/" + core.quote(sid, safe=""))
        finally:
            client.close()
        if type(info.get("permission_level")) is not int or info["permission_level"] < 2:
            raise Error("MCP_PERMISSION_DENIED", "Editing this conversation requires its existing edit permission.")
        if info.get("host_id") != self.saved.get("hostId"):
            raise Error("MCP_SESSION_NOT_LOCAL", "Select a conversation on this host.")
        if info.get("archived"):
            raise Error("SESSION_ARCHIVED", "This conversation is archived.")
        if info.get("status") != "idle":
            raise Error("SESSION_BUSY", "Wait for this conversation to become idle.")
        harness = info.get("harness") or info.get("harness_override")
        if harness not in ("codex-native", "pi-native", "claude-native"):
            raise Error("MCP_REFRESH_UNSUPPORTED", "This native harness has no verified safe MCP reload yet; the conversation was not changed.")
        try:
            if harness == "codex-native":
                operation = refresh_codex(sid, info)
            elif harness == "pi-native":
                operation = refresh_pi(sid, info, sync=synchronize)
            else:
                operation = refresh_claude(sid, info, sync=synchronize)
            result = asyncio.run(asyncio.wait_for(operation, timeout=90))
        except (RefreshError, NativeRefreshError, ClaudeRefreshError) as error:
            raise Error(error.code, error.code) from None
        except TimeoutError:
            raise Error("MCP_REFRESH_TIMEOUT", "Refresh timed out; check status before retrying.") from None
        if result.get("refresh", {}).get("state") == "submission-unknown":
            return {"ok": False, **result, "error": {"code": "MCP_RELOAD_SUBMISSION_UNKNOWN",
                "message": "Native reload submission is uncertain; inspect the original conversation before retrying."}}
        return {"ok": True, **result}

    def session_action(self, action):
        """Operate only sessions created here, never arbitrary server sessions.

        These actions expose transport results, not acceptance-test claims.
        `session` returns assistant text for the caller's role/turn assertions.
        """
        if not self.saved.get("enabled") or not self.saved.get("loginConfirmed"):
            raise Error("needs_connection", "請先完成連線。")
        server = self.server()
        sessions_file = self.root / "sessions.json"
        sessions = private_json(sessions_file)
        client = self.client_factory(server, action == "session")
        sid = self.request.get("sessionId")
        prompt = self.request.get("prompt")
        if action in ("chat", "continue"):
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16384:
                raise Error("invalid_prompt", "對話內容必須為 1 至 16384 個字元。")
        if action == "chat":
            engine = self.request.get("engine")
            if engine not in core.ENGINES:
                raise Error("invalid_engine", "代理必須是 claude、codex 或 pi。")
            catalog = self.catalog(client=client, read_only=False, engine_key=engine)
            entry = catalog["engines"][engine]
            if not catalog["host"]["connected"] or not entry["ready"]:
                raise Error("engine_not_ready", "此 host 或代理尚未準備完成。")
            model = self.request.get("model")
            if model is not None and model not in {row["id"] for row in entry["models"]}:
                raise Error("invalid_model", "模型不在此 host 的實際模型清單。")
            body = {"agent_id": entry["agentId"], "host_id": catalog["host"]["id"],
                    "workspace": str(self.workspace), "title": "code-server connector · " + engine,
                    "harness_override": core.ENGINES[engine]["harness"]}
            if model:
                body["model_override"] = model
            if engine == "claude":
                body["terminal_launch_args"] = ["--permission-mode", "default"]
            created = client.request("POST", "/v1/sessions", body)
            sid = created.get("id") or created.get("session_id")
            if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid):
                raise Error("invalid_session_response", "Server 未回傳有效對話 ID。")
            sessions[sid] = {"server": server, "hostId": self.saved["hostId"], "engine": engine,
                             "workspace": str(self.workspace), "archived": False}
            core.atomic_json(sessions_file, sessions)
            if engine == "claude":
                self.sleep(3)
        record = sessions.get(sid) if isinstance(sid, str) else None
        if not isinstance(record, dict) or record.get("server") != server or record.get("hostId") != self.saved.get("hostId") \
                or record.get("workspace") != str(self.workspace):
            raise Error("session_not_owned", "只能操作由此擴充在目前 host 建立的對話。")
        prefix = "/v1/sessions/" + core.quote(sid, safe="")
        result = {"ok": True, "sessionId": sid, "engine": record["engine"], "url": server + "/c/" + core.quote(sid, safe="")}
        if action in ("chat", "continue"):
            if record.get("archived"):
                raise Error("session_archived", "此測試對話已封存。")
            client.request("POST", prefix + "/events", {"type": "message", "data": {
                "role": "user", "content": [{"type": "input_text", "text": prompt}]}})
            return {**result, "messageSent": True, "replyVerified": False}
        if action == "switchModel":
            catalog = self.catalog(client=client, read_only=False, engine_key=record["engine"])
            model = self.request.get("model")
            if model not in {row["id"] for row in catalog["engines"][record["engine"]]["models"]}:
                raise Error("invalid_model", "模型不在此 host 的實際模型清單。")
            client.request("PATCH", prefix, {"model_override": model})
            info = client.request("GET", prefix)
            return {**result, "requestedModel": model, "effectiveModel": core.safe_text(info.get("llm_model")),
                    "switchVerified": info.get("llm_model") == model, "replyVerified": False}
        if action == "archive":
            client.request("POST", prefix + "/events", {"type": "stop_session", "data": {}})
            client.request("PATCH", prefix, {"archived": True})
            record["archived"] = True
            core.atomic_json(sessions_file, sessions)
            return {**result, "stopped": True, "archived": True}
        info = client.request("GET", prefix)
        page = client.request("GET", prefix + "/items?limit=100&order=desc")
        messages = []
        for item in page.get("data", []):
            if isinstance(item, dict) and item.get("type") == "message" and item.get("role") == "assistant":
                text = "".join(part.get("text", "") for part in item.get("content", [])
                               if isinstance(part, dict) and part.get("type") in ("output_text", "text")
                               and isinstance(part.get("text"), str))
                if text:
                    messages.append({"id": core.safe_text(item.get("id")), "role": "assistant", "text": text[:32768]})
        return {**result, "effectiveModel": core.safe_text(info.get("llm_model")),
                "assistantMessages": messages, "replyVerified": False}


def dispatch(request, **dependencies):
    if not isinstance(request, dict) or request.get("action") not in MUTATIONS | {"status", "models", "session"}:
        raise Error("invalid_action", "不支援此 Omnigent 操作。")
    if importlib.metadata.version("omnigent") != VERSION:
        raise Error("runtime_version_mismatch", "此 adapter 只支援固定版本 Omnigent 0.16.0。")
    plugin = Connector(request, **dependencies)
    lock = None
    try:
        action = request["action"]
        if action in MUTATIONS:
            fd = os.open(plugin.root / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            lock = os.fdopen(fd, "r+")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Error("operation_busy", "另一個 Omnigent 操作仍在執行。") from None
            # The prior process may have written between construction and lock.
            plugin.saved = private_json(plugin.state_path)
        if action == "status":
            return plugin.public_status()
        if action == "configure":
            return plugin.validate_config(request)
        if action == "connect":
            return plugin.connected(request)
        if action in ("start", "restore"):
            return plugin.restore(explicit=action == "start")
        if action == "stop":
            return plugin.stop()
        if action == "disconnect":
            return plugin.disconnect_connector()
        if action == "refreshMcp":
            return plugin.refresh_mcp()
        if action == "models":
            return {"ok": True, **plugin.catalog()}
        if action in ("chat", "continue", "switchModel", "session", "archive"):
            return plugin.session_action(action)
        return plugin.verify_connector()
    finally:
        if lock:
            lock.close()
        plugin.close()


def main():
    os.umask(0o077)
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise Error("request_too_large", "請求過大。")
        request = json.loads(raw)
        # Do not propagate SDK logging or provider response bodies onto stdout.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = dispatch(request)
    except Error as error:
        result = {"ok": False, "error": {"code": error.code, "message": error.message}}
    except (ImportError, importlib.metadata.PackageNotFoundError):
        result = {"ok": False, "error": {"code": "RUNTIME_MISSING", "message": "Omnigent runtime 尚未安裝完整。"}}
    except (ValueError, UnicodeError):
        result = {"ok": False, "error": {"code": "INVALID_REQUEST", "message": "請求或狀態資料格式不正確。"}}
    except Exception:
        result = {"ok": False, "error": {"code": "ADAPTER_FAILED", "message": "Omnigent 操作失敗，請檢查 runtime 及部署狀態。"}}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
