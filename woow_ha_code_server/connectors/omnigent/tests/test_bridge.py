import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("connector_bridge", ROOT / "bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
core = bridge.core


class Client:
    def __init__(self):
        self.calls = []
        self.model = "model-a"

    def request(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path, payload))
        if path == "/v1/sessions" and method == "POST":
            return {"id": "owned-session"}
        if method == "PATCH" and payload.get("model_override"):
            self.model = payload["model_override"]
        if "/items?" in path:
            return {"data": [
                {"id": "echo", "type": "message", "role": "user", "content": [{"type": "input_text", "text": "SECRET_USER_ECHO"}]},
                {"id": "a1", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "REAL_ASSISTANT_REPLY"}]}]}
        return {"llm_model": self.model}

    def close(self):
        pass


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.env = {
            "WOOW_OMNIGENT_CONNECTOR_STATE": str(self.root / "state"),
            "OMNIGENT_CONFIG_HOME": str(self.root / "sdk"),
            "OMNIGENT_DATA_DIR": str(self.root / "sdk"),
            "PI_AGENT_DATA_DIR": str(self.root / "pi"),
            "HOME": str(self.workspace), "WOOW_OMNIGENT_DEPLOYMENT_MANAGED": "0",
        }
        self.env_patch = patch.dict(os.environ, self.env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = Client()

    def plugin(self, action="restore", **request):
        return bridge.Connector({"action": action, **request}, client_factory=lambda *_: self.client)

    def authorize(self, plugin):
        plugin.write_state(enabled=True, loginConfirmed=True, server="https://example.test", hostId="my-host",
                           workspace=str(self.workspace), configHome=str(plugin.config_home), dataDir=str(plugin.data_dir))
        plugin.request["server"] = "https://example.test"

    def test_fresh_restore_does_not_start_from_sdk_credentials(self):
        plugin = self.plugin()
        with patch.object(core.Plugin, "resume", side_effect=AssertionError("must not resume")):
            self.assertEqual(plugin.restore(), {"ok": True, "resumed": False, "reason": "no-saved-authority"})

    def test_refresh_requires_edit_permission_local_host_idle_and_supported_harness(self):
        import mcp_refresh
        info = {"permission_level": 2, "host_id": "my-host", "harness": "codex-native", "status": "idle"}
        for changes, code in [({"permission_level": 1}, "MCP_PERMISSION_DENIED"),
                              ({"permission_level": True}, "MCP_PERMISSION_DENIED"),
                              ({"host_id": "another-host"}, "MCP_SESSION_NOT_LOCAL"),
                              ({"archived": True}, "SESSION_ARCHIVED"),
                              ({"status": "running"}, "SESSION_BUSY"),
                              ({"harness": "unsupported-native"}, "MCP_REFRESH_UNSUPPORTED")]:
            plugin = self.plugin("refreshMcp", sessionId="existing-session")
            self.authorize(plugin)
            with patch.object(self.client, "request", return_value={**info, **changes}), \
                    patch.object(mcp_refresh, "refresh_codex", new_callable=AsyncMock) as refresh:
                with self.assertRaises(bridge.Error) as ctx:
                    plugin.refresh_mcp()
                self.assertEqual(ctx.exception.code, code)
                refresh.assert_not_called()

    def test_refresh_targets_existing_conversation_without_creation_or_turn(self):
        import mcp_refresh
        info = {"permission_level": 2, "host_id": "my-host", "harness": "codex-native", "status": "idle"}
        plugin = self.plugin("refreshMcp", sessionId="existing-session")
        self.authorize(plugin)
        with patch.object(self.client, "request", return_value=info) as request, \
                patch.object(mcp_refresh, "refresh_codex", new_callable=AsyncMock, return_value={"sessionId":"existing-session", "refresh":{"state":"queued"}}) as refresh:
            self.assertEqual(plugin.refresh_mcp()["sessionId"], "existing-session")
            request.assert_called_once_with("GET", "/v1/sessions/existing-session")
            refresh.assert_awaited_once_with("existing-session", info)

    def test_pi_refresh_uses_existing_native_control_and_keeps_sync_callback_private(self):
        import native_resume, mcp_refresh
        plugin = self.plugin("refreshMcp", sessionId="existing-pi-session")
        self.authorize(plugin)
        info = {"permission_level": 2, "host_id": "my-host", "harness": "pi-native", "status": "idle", "external_session_id": "same-native"}
        with patch.object(self.client, "request", return_value=info) as request, \
                patch.object(native_resume, "refresh_pi", new_callable=AsyncMock, return_value={"sessionId":"existing-pi-session", "refresh":{"state":"applied"}}) as refresh:
            self.assertEqual(plugin.refresh_mcp()["sessionId"], "existing-pi-session")
            request.assert_called_once_with("GET", "/v1/sessions/existing-pi-session")
            refresh.assert_awaited_once_with("existing-pi-session", info, sync=mcp_refresh.synchronize)

    def test_explicit_private_http_allowed_public_http_and_credentials_rejected(self):
        for url in ("http://192.168.2.121:8001", "http://omnigent-server:8000", "http://host.containers.internal:8000",
                    "http://svc-65b75f59-omnigent.paas-ws-ab6564da.svc.cluster.local:8000"):
            self.assertEqual(bridge.normalize_server(url), url)
        for url in ("http://example.org", "http://8.8.8.8", "http://user:secret@192.168.2.121:8001", "http://10.0.0.1?token=bad"):
            with self.assertRaises(bridge.Error):
                bridge.normalize_server(url)

    def test_claude_refresh_keeps_original_session_and_honest_native_receipt(self):
        import claude_mcp_plugin, mcp_refresh
        plugin = self.plugin("refreshMcp", sessionId="existing-claude-session")
        self.authorize(plugin)
        info = {"permission_level": 2, "host_id": "my-host", "harness": "claude-native", "status": "idle", "external_session_id": "same-native"}
        for state in ("queued", "reloaded", "submission-unknown"):
            result = {"sessionId": "existing-claude-session", "engine": "claude", "refresh": {
                "state": state, "nativeSessionId": "same-native", "inventoryVerified": False, "toolsVerified": False}}
            with patch.object(self.client, "request", return_value=info) as request, \
                patch.object(claude_mcp_plugin, "refresh_claude", new_callable=AsyncMock, return_value=result) as refresh:
                received = plugin.refresh_mcp()
                self.assertEqual(received["ok"], state != "submission-unknown")
                self.assertEqual(received["refresh"], result["refresh"])
                request.assert_called_once_with("GET", "/v1/sessions/existing-claude-session")
                refresh.assert_awaited_once_with("existing-claude-session", info, sync=mcp_refresh.synchronize)
                if state == "submission-unknown":
                    self.assertEqual(received["error"]["code"], "MCP_RELOAD_SUBMISSION_UNKNOWN")

    def test_stop_persists_across_new_adapter_and_periodic_restore(self):
        plugin = self.plugin()
        self.authorize(plugin)
        with patch.object(plugin, "managed_host_pid", return_value=None):
            self.assertTrue(plugin.stop()["stopped"])
        with patch.object(core.Plugin, "resume", side_effect=AssertionError("must not resume")):
            self.assertEqual(self.plugin().restore()["reason"], "stopped")
        with patch.object(core.Plugin, "resume", return_value={"host": {"id": "my-host", "connected": True}}):
            self.assertTrue(self.plugin().restore(explicit=True)["resumed"])

    def test_stop_signals_only_matching_owned_process_and_handles_reaping(self):
        plugin = self.plugin()
        self.authorize(plugin)
        executable = self.root / "omnigent"
        executable.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(30)\n")
        executable.chmod(0o700)
        child = subprocess.Popen([str(executable), "host", "--server", "https://example.test", "--non-interactive"],
                                 env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup():
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        self.addCleanup(cleanup)
        record = {"pid": child.pid, "server": "https://example.test", **plugin.process_identity(child.pid)}
        core.atomic_json(plugin.root / "host-process.json", record)
        time.sleep(.05)
        self.assertEqual(plugin.managed_host_pid("https://example.test"), child.pid)
        self.assertTrue(plugin.stop()["stopped"])
        self.assertIsNotNone(child.poll())

    def test_unrelated_process_is_not_signalled(self):
        plugin = self.plugin()
        self.authorize(plugin)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], env=dict(os.environ))
        def cleanup():
            child.terminate()
            child.wait(timeout=5)
        self.addCleanup(cleanup)
        core.atomic_json(plugin.root / "host-process.json", {"pid": child.pid, "server": "https://example.test",
                                                             **plugin.process_identity(child.pid)})
        with self.assertRaises(bridge.Error) as ctx:
            plugin.stop()
        self.assertEqual(ctx.exception.code, "HOST_PROCESS_MISMATCH")
        self.assertIsNone(child.poll())

    def test_restore_rejects_foreign_data_root(self):
        plugin = self.plugin()
        self.authorize(plugin)
        plugin.write_state(dataDir="/other/deployment")
        with self.assertRaisesRegex(bridge.Error, "部署"):
            self.plugin().restore()

    def test_config_does_not_persist_credentials_or_remote_state_paths(self):
        plugin = self.plugin("configure")
        plugin.validate_config({"server": "https://EXAMPLE.test/", "workspace": str(self.workspace),
                                "password": "SECRET_NEVER_SAVE", "username": "do-not-save", "stateDir": "/tmp/foreign"})
        raw = plugin.state_path.read_text()
        self.assertNotIn("SECRET", raw)
        self.assertNotIn("username", raw)
        self.assertNotIn("foreign", raw)
        self.assertEqual(plugin.state_path.stat().st_mode & 0o777, 0o600)

    def test_active_identity_change_requires_disconnect(self):
        plugin = self.plugin()
        self.authorize(plugin)
        with self.assertRaises(bridge.Error) as ctx:
            plugin.validate_config({"server": "https://another.test"})
        self.assertEqual(ctx.exception.code, "DISCONNECT_REQUIRED")
        self.assertEqual(plugin.saved["server"], "https://example.test")

    def test_state_symlink_is_refused(self):
        plugin = self.plugin()
        foreign = self.root / "foreign.json"
        foreign.write_text("{}")
        plugin.state_path.symlink_to(foreign)
        with self.assertRaises(bridge.Error):
            self.plugin()

    def test_pvc_fsgroup_permissions_are_retightened_before_state_read(self):
        plugin = self.plugin()
        self.authorize(plugin)
        plugin.state_path.chmod(0o660)
        self.assertTrue(self.plugin().saved["loginConfirmed"])
        self.assertEqual(plugin.state_path.stat().st_mode & 0o777, 0o600)

    def test_unpatched_kit_pause_explicitly_unsupported(self):
        os.environ["WOOW_OMNIGENT_DEPLOYMENT_MANAGED"] = "1"
        plugin = self.plugin()
        self.authorize(plugin)
        with self.assertRaises(bridge.Error) as ctx:
            plugin.stop()
        self.assertEqual(ctx.exception.code, "PAUSE_UNSUPPORTED")
        self.assertTrue(plugin.saved["enabled"])

    def test_configured_kit_never_spawns_private_host(self):
        os.environ["WOOW_OMNIGENT_DEPLOYMENT_MANAGED"] = "1"
        plugin = self.plugin()
        with patch.object(plugin, "local_host", return_value={"managerRunning": False}), \
                patch.object(core.Plugin, "ensure_host", side_effect=AssertionError("second host forbidden")):
            with self.assertRaises(bridge.Error) as ctx:
                plugin.ensure_host("https://example.test")
        self.assertEqual(ctx.exception.code, "KIT_NOT_RUNNING")

    def test_patched_kit_stop_and_resume_reuse_same_manager(self):
        kit = self.root / "kit"
        kit.mkdir()
        (kit / "supervisor.sh").write_text("# WOOW_CONNECTOR_PAUSE_V1\n")
        os.environ.update(WOOW_OMNIGENT_DEPLOYMENT_MANAGED="1", OG_KIT_DIR=str(kit))
        plugin = self.plugin()
        self.authorize(plugin)
        core.atomic_json(plugin.kit_status_path, {"state": "paused"})
        with patch.object(plugin, "local_host", return_value={"managerRunning": True}):
            self.assertTrue(plugin.stop()["stopped"])
            self.assertTrue(plugin.pause_path.exists())
            self.assertEqual(plugin.ensure_host("https://example.test"), "kit")
            self.assertFalse(plugin.pause_path.exists())

    def test_session_operations_are_owned_and_use_assistant_records_only(self):
        plugin = self.plugin("chat", engine="pi", prompt="SECRET_USER_ECHO", model="model-a")
        self.authorize(plugin)
        entry = {"ready": True, "agentId": "pi-agent", "models": [{"id": "model-a"}, {"id": "model-b"}]}
        catalog = {"host": {"connected": True, "id": "my-host"}, "engines": {"pi": entry}}
        with patch.object(plugin, "catalog", return_value=catalog):
            result = plugin.session_action("chat")
            self.assertTrue(result["messageSent"])
            self.assertFalse(result["replyVerified"])
            plugin.request["sessionId"] = result["sessionId"]
            page = plugin.session_action("session")
            self.assertEqual(page["assistantMessages"], [{"id": "a1", "role": "assistant", "text": "REAL_ASSISTANT_REPLY"}])
            self.assertNotIn("SECRET_USER_ECHO", json.dumps(page))
            plugin.request["model"] = "model-b"
            self.assertTrue(plugin.session_action("switchModel")["switchVerified"])
            self.assertTrue(plugin.session_action("archive")["archived"])
            plugin.request["sessionId"] = "somebody-elses-session"
            with self.assertRaises(bridge.Error) as ctx:
                plugin.session_action("continue")
            self.assertEqual(ctx.exception.code, "SESSION_NOT_OWNED")
        self.assertFalse(any("somebody-elses" in path for _, path, _ in self.client.calls))

    def test_online_status_is_not_model_verification(self):
        plugin = self.plugin("status")
        self.authorize(plugin)
        online = {"server": "https://example.test", "host": {"id": "my-host", "connected": True}, "engines": {}}
        with patch.object(core.Plugin, "status", return_value=online):
            result = plugin.public_status()
            self.assertTrue(result["connected"])
            self.assertFalse(result["verified"])

    def test_engine_failure_or_cleanup_failure_never_verifies(self):
        plugin = self.plugin("verify", engine="pi")
        self.authorize(plugin)
        current = {"engines": {"pi": {"version": "0.99.1"}}}
        with patch.object(core.Plugin, "status", return_value=current), \
                patch.object(core.Plugin, "verify", return_value={"ok": True, "reply": core.SENTINEL, "cleanup": "stop_failed"}):
            self.assertFalse(plugin.verify_connector()["ok"])

    def test_sentinel_user_echo_never_counts_as_reply(self):
        self.assertFalse(core.Plugin.assistant_sentinel([{"role": "user", "type": "message",
                         "content": [{"type": "output_text", "text": core.SENTINEL}]}]))


if __name__ == "__main__":
    unittest.main()
