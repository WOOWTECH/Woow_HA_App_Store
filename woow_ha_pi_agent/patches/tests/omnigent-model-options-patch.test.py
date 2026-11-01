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
import subprocess
import tempfile
import unittest
from pathlib import Path

from omnigent.harnesses.pi_native import credentials as c

LISTING = (
    "provider  model              context  output  tools  vision\n"
    "--------  -----------------  -------  ------  -----  ------\n"
    "litellm   apporo/gpt-6-sol      128K   16.4K     no      no\n"
    "litellm   qwen3-4b-cluster1     128K   16.4K     no      no\n"
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
