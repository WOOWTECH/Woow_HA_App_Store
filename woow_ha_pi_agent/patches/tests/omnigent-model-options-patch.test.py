"""Unit tests for omnigent-model-options-patch (run in the image build after the patch).

    /opt/omnigent/venv/bin/python /opt/patches/tests/omnigent-model-options-patch.test.py

Omnigent's "Configure Pi" picker asks the host for the models a Pi session may
start with. Upstream 0.16.0 answers an own-login Pi from auth.json INTERSECT
models-store.json; Pi writes that store only for providers whose catalog it
refreshes over the network, so a gateway declared in models.json -- which is
what the pi-web Models page writes -- is in neither file and the picker comes
up empty. The patch routes that case to `pi --list-models`.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from omnigent.harnesses.pi_native import credentials as c

LISTING = (
    "provider  model              context  output  tools  vision\n"
    "--------  -----------------  -------  ------  -----  ------\n"
    "litellm   apporo/gpt-6-sol      128K   16.4K     no      no\n"
    "litellm   qwen3-4b-cluster1     128K   16.4K     no      no\n"
)


NOTICE = (
    "No models available. Use /login to log into a provider via OAuth or API key. See:\n"
    "  /usr/local/lib/node_modules/@earendil-works/pi-coding-agent/docs/providers.md\n"
    "  /usr/local/lib/node_modules/@earendil-works/pi-coding-agent/docs/models.md\n"
)


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


class ModelOptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.real_run = c.subprocess.run
        self.addCleanup(setattr, c.subprocess, "run", self.real_run)

    def write(self, auth, store):
        (self.tmp / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
        (self.tmp / "models-store.json").write_text(json.dumps(store), encoding="utf-8")

    def test_patch_is_applied(self):
        self.assertTrue(
            hasattr(c, "_ambient_pi_model_options"),
            "omnigent-model-options-patch did not apply to this build",
        )

    def test_empty_pair_falls_back_to_the_pi_cli(self):
        self.write({}, {})
        c.subprocess.run = lambda *a, **k: Completed(LISTING)
        options = c.pi_own_login_model_options(self.tmp)
        self.assertEqual(
            [o["id"] for o in options],
            ["litellm/apporo/gpt-6-sol", "litellm/qwen3-4b-cluster1"],
        )

    def test_populated_pair_still_wins(self):
        """The fallback must not shadow a real Pi login."""
        self.write(
            {"anthropic": {"type": "api_key"}},
            {"anthropic": {"models": [{"id": "claude-opus-5.5", "name": "Opus"}]}},
        )
        c.subprocess.run = lambda *a, **k: self.fail("must not shell out when the pair answers")
        options = c.pi_own_login_model_options(self.tmp)
        self.assertEqual([o["id"] for o in options], ["anthropic/claude-opus-5.5"])
        self.assertEqual(options[0]["displayName"], "Opus")

    def test_a_failing_cli_is_not_an_error(self):
        self.write({}, {})
        c.subprocess.run = lambda *a, **k: Completed("", returncode=1)
        self.assertEqual(c.pi_own_login_model_options(self.tmp), [])

    def test_a_missing_cli_is_not_an_error(self):
        self.write({}, {})

        def boom(*a, **k):
            raise OSError("no pi on PATH")

        c.subprocess.run = boom
        self.assertEqual(c.pi_own_login_model_options(self.tmp), [])

    def test_the_listing_header_is_ignored(self):
        self.write({}, {})
        c.subprocess.run = lambda *a, **k: Completed(LISTING)
        ids = [o["id"] for o in c.pi_own_login_model_options(self.tmp)]
        self.assertNotIn("provider/model", ids)
        self.assertTrue(all("-" != i[0] for i in ids))

    def test_pis_no_models_notice_is_not_a_model(self):
        """With nothing configured Pi prints this on STDOUT with exit code 0. Reading every two-word line as a model turned it into `No/models`."""
        self.write({}, {})
        c.subprocess.run = lambda *a, **k: Completed(NOTICE)
        self.assertEqual(c.pi_own_login_model_options(self.tmp), [])

    def test_only_rows_under_the_table_header_are_models(self):
        self.write({}, {})
        c.subprocess.run = lambda *a, **k: Completed("Warning: an update is available\nplease upgrade now\n" + LISTING + "\n(2 models)\n")
        ids = [o["id"] for o in c.pi_own_login_model_options(self.tmp)]
        self.assertEqual(ids, ["litellm/apporo/gpt-6-sol", "litellm/qwen3-4b-cluster1"])

    def test_the_listing_of_newer_pi_versions_is_read_too(self):
        """Pi 1.x prints `max-out thinking images` and no separator row."""
        self.write({}, {})
        c.subprocess.run = lambda *a, **k: Completed(
            "provider    model                context  max-out  thinking  images\n"
            "openrouter  vendor/model-a:free  128K     16.4K    no        no\n"
            "anthropic   claude-haiku-4-5     200K     64K      yes       yes\n"
        )
        self.assertEqual([o["id"] for o in c.pi_own_login_model_options(self.tmp)], ["anthropic/claude-haiku-4-5", "openrouter/vendor/model-a:free"])

    def test_the_cli_gets_less_time_than_the_host_rpc_allows(self):
        """The server stops waiting for the host after 15 seconds (_MODEL_OPTIONS_TIMEOUT_S); a slower CLI must mean an empty picker, not an HTTP 504."""
        self.write({}, {})
        seen = {}
        c.subprocess.run = lambda *a, **k: (seen.update(k), Completed(LISTING))[1]
        c.pi_own_login_model_options(self.tmp)
        self.assertLess(seen["timeout"], 15)

    def test_the_cli_is_pointed_at_the_directory_that_was_read(self):
        self.write({}, {})
        seen = {}
        c.subprocess.run = lambda *a, **k: (seen.update(k), Completed(LISTING))[1]
        c.pi_own_login_model_options(self.tmp)
        self.assertEqual(seen["env"]["PI_CODING_AGENT_DIR"], str(self.tmp))

    def test_undecodable_output_cannot_raise(self):
        self.write({}, {})
        seen = {}
        c.subprocess.run = lambda *a, **k: (seen.update(k), Completed(LISTING))[1]
        c.pi_own_login_model_options(self.tmp)
        self.assertEqual(seen["errors"], "replace")

    def real_pi_options(self):
        """What the picker returns when it talks to the REAL Pi CLI in a bare environment.

        Nothing inherited from the build or a developer machine (API keys, cloud credentials) can configure a provider, and the agent directory is a scratch
        one. The test is skipped, with the reason, when this environment cannot run the CLI at all or runs it slower than the picker would wait: those say
        nothing about how the picker reads the listing, and must not turn into a red build.
        """
        if not shutil.which("pi"):
            self.skipTest("the real Pi CLI is not installed in this build")
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp), "PI_CODING_AGENT_DIR": str(self.tmp)}
        started = time.monotonic()
        try:
            probe = subprocess.run(["pi", "--list-models"], capture_output=True, text=True, errors="replace", timeout=60, check=False, stdin=subprocess.DEVNULL, env=env)
        except (OSError, subprocess.SubprocessError) as error:
            self.skipTest("the Pi CLI does not run in this environment: %r" % (error,))
        if probe.returncode != 0:
            self.skipTest("`pi --list-models` exits %d in this environment: %s" % (probe.returncode, probe.stderr.strip()[:200]))
        if time.monotonic() - started > 8:
            self.skipTest("`pi --list-models` needs more than 8 s in this environment; the picker gives up after 12 s")
        with mock.patch.dict(os.environ, env, clear=True):
            return [o["id"] for o in c.pi_own_login_model_options(self.tmp)]

    def test_real_pi_with_nothing_configured_offers_nothing(self):
        """Against the real CLI: its own notice must not become a model."""
        self.write({}, {})
        self.assertEqual(self.real_pi_options(), [])

    def test_real_pi_lists_a_gateway_declared_in_models_json(self):
        """The case this patch exists for, against the real CLI: a gateway that is only in models.json (auth.json and models-store.json are empty)."""
        self.write({}, {})
        (self.tmp / "models.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "litellm": {
                            "baseUrl": "http://127.0.0.1:4000/v1",
                            "api": "openai-completions",
                            "apiKey": "not-a-secret",
                            "models": [{"id": "apporo/gpt-6-sol"}, {"id": "qwen3-4b-cluster1"}],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.real_pi_options(), ["litellm/apporo/gpt-6-sol", "litellm/qwen3-4b-cluster1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
