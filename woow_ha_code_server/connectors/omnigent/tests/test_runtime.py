"""Run with the installed private runtime's Python for real SDK contracts."""
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    AVAILABLE = importlib.metadata.version("omnigent") == "0.16.0"
except importlib.metadata.PackageNotFoundError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "run with installed Omnigent 0.16.0 runtime")
class RuntimeContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.target = self.root / "session"
        self.source.mkdir()
        self.target.mkdir()
        (self.source / "skills" / "shared-proof").mkdir(parents=True)
        (self.source / "skills" / "shared-proof" / "SKILL.md").write_text("# Shared fixture\n")
        self.env = patch.dict(os.environ, {"WOOW_OMNIGENT_SHARED_TOOLS": "1", "PI_CODING_AGENT_DIR": str(self.source)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_actual_sdk_runner_preserves_pinned_claude_guard_without_forwarding_unrelated_secrets(self):
        from omnigent.host.connect import _build_runner_env
        adapter = Path(__file__).resolve().parents[1] / "index.mjs"
        source = ("import {environment} from " + json.dumps(adapter.as_uri()) + ";"
                  "console.log(JSON.stringify(environment({HOME:" + json.dumps(str(self.root)) + ","
                  "OMNIGENT_CONFIG_HOME:" + json.dumps(str(self.root / "config")) + ","
                  "UNRELATED_PRIVATE_SECRET:'synthetic-secret',DISABLE_AUTOUPDATER:'0'})));" )
        base = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", source], text=True))
        with patch.dict(os.environ, {"HOME": str(self.root), "OMNIGENT_CONFIG_HOME": str(self.root / "config")}, clear=True):
            runner = _build_runner_env(base, server_url="http://127.0.0.1:8000", runner_id="test-runner",
                                       binding_token="synthetic-binding", workspace=str(self.root), parent_pid=1,
                                       harness="claude-native")
        self.assertEqual(runner["DISABLE_AUTOUPDATER"], "1")
        self.assertNotIn("UNRELATED_PRIVATE_SECRET", runner)

    def test_codex_private_home_gets_shared_skills_and_mcp_but_model_edits_stay_private(self):
        from omnigent.inner.codex_executor import _populate_codex_home_config
        config = 'model = "first-model"\n[mcp_servers.shared_fixture]\ncommand = "echo"\nargs = ["fixture"]\n'
        (self.source / "config.toml").write_text(config)
        _populate_codex_home_config(self.target, self.source, minimal_config=False, include_credentials=False)
        # Credentials=False intentionally suppresses config copy. Run the ordinary
        # subscribed native path with an entirely credential-free fixture home.
        _populate_codex_home_config(self.target, self.source, minimal_config=False)
        self.assertEqual((self.target / "skills").resolve(), (self.source / "skills").resolve())
        self.assertIn("mcp_servers.shared_fixture", (self.target / "config.toml").read_text())
        self.assertFalse((self.target / "config.toml").is_symlink())
        (self.target / "config.toml").write_text(config.replace("first-model", "second-model"))
        self.assertEqual((self.source / "config.toml").read_text(), config)

    def test_pi_managed_provider_home_inherits_effective_directory_and_mcp(self):
        from omnigent.inner.pi_settings import prepare_managed_pi_agent_dir
        (self.source / "settings.json").write_text(json.dumps({"theme": "test-theme", "defaultThinkingLevel": "high"}))
        (self.source / "mcp.json").write_text(json.dumps({"mcpServers": {"fixture": {"command": "echo"}}}))
        (self.source / "extensions").mkdir()
        (self.target / "models.json").write_text('{"managed":true}')
        prepare_managed_pi_agent_dir(self.target, overlay={"defaultThinkingLevel": None})
        self.assertEqual(json.loads((self.target / "settings.json").read_text()), {"theme": "test-theme", "defaultThinkingLevel": None})
        self.assertEqual((self.target / "skills").resolve(), (self.source / "skills").resolve())
        self.assertEqual((self.target / "mcp.json").resolve(), (self.source / "mcp.json").resolve())
        self.assertEqual(json.loads((self.target / "models.json").read_text()), {"managed": True})
        prepare_managed_pi_agent_dir(self.target)  # repeated launch is idempotent

    def test_pi_conflicting_private_tool_path_fails_before_launch(self):
        from omnigent.inner.pi_settings import prepare_managed_pi_agent_dir
        (self.target / "skills").mkdir()
        with self.assertRaisesRegex(ValueError, "conflicts"):
            prepare_managed_pi_agent_dir(self.target)

    def test_pi_resource_helper_existing_same_symlink_is_reused(self):
        from omnigent.inner import pi_settings
        (self.source / "extensions").mkdir()
        # Exercise the real native helper creating those links before the WOOW
        # hook, exactly the ordering an expanded SDK resource list would use.
        with patch.object(pi_settings, "_PI_AGENT_RESOURCE_DIRS", ("npm", "git", "skills", "extensions")):
            pi_settings.prepare_managed_pi_agent_dir(self.target)
            pi_settings.prepare_managed_pi_agent_dir(self.target)
        self.assertEqual((self.target / "skills").resolve(), (self.source / "skills").resolve())

    def pi_catalog(self, custom, stored=None, authenticated=None):
        from omnigent.harnesses.pi_native.credentials import pi_own_login_model_options
        (self.source / "auth.json").write_text(json.dumps(authenticated or {
            "gateway": {"type": "api_key", "key": "synthetic-private-key"}}))
        (self.source / "models-store.json").write_text(json.dumps(stored or {}))
        (self.source / "models.json").write_text(json.dumps({"providers": custom}))
        return pi_own_login_model_options(self.source)

    def test_pi_authenticated_custom_provider_exposes_nested_model_ids_without_credentials(self):
        result = self.pi_catalog({"gateway": {"baseUrl": "https://private.invalid/v1",
            "apiKey": "another-private-key", "models": [
                {"id": "apporo/first", "name": "First"}, {"id": "apporo/second"}]},
            "not-authenticated": {"models": [{"id": "hidden"}]}})
        self.assertEqual(result, [
            {"id": "gateway/apporo/first", "model": "gateway/apporo/first", "displayName": "First"},
            {"id": "gateway/apporo/second", "model": "gateway/apporo/second", "displayName": "apporo/second"}])
        self.assertNotIn("private", json.dumps(result))

    def test_pi_custom_models_extend_and_override_builtins_once(self):
        result = self.pi_catalog({"gateway": {"models": [{"id": "same", "name": "Custom"},
            {"id": "new"}]}}, {"gateway": {"models": [{"id": "same", "name": "Original"}, {"id": "old"}]}})
        self.assertEqual([m["id"] for m in result], ["gateway/new", "gateway/old", "gateway/same"])
        self.assertEqual(result[-1]["displayName"], "Custom")

    def test_pi_malformed_custom_catalog_preserves_builtins(self):
        stored = {"gateway": {"models": [{"id": "old"}]}}
        expected = [{"id": "gateway/old", "model": "gateway/old", "displayName": "old"}]
        for custom in (None, [], "invalid", {"gateway": None}, {"gateway": {"models": {}}},
                       {"gateway": {"models": [None, {}, {"id": 7}]}}):
            with self.subTest(custom=custom):
                self.assertEqual(self.pi_catalog(custom, stored), expected)

    def test_pi_custom_catalog_flag_off_keeps_upstream_behavior(self):
        with patch.dict(os.environ, {"WOOW_OMNIGENT_SHARED_TOOLS": "0"}):
            self.assertEqual(self.pi_catalog({"gateway": {"models": [{"id": "custom"}]}}), [])

    def test_pi_custom_catalog_requires_native_auth(self):
        from omnigent.harnesses.pi_native.credentials import pi_own_login_model_options
        self.pi_catalog({"gateway": {"models": [{"id": "custom"}]}})
        (self.source / "auth.json").write_text("{}")
        self.assertEqual(pi_own_login_model_options(self.source), [])


if __name__ == "__main__":
    unittest.main()
