import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = load("native_resume", "native_resume.py")
patcher = load("patch_native_resume", "patch-native-resume.py")
SID = "01234567-89ab-4cde-8f01-23456789abcd"


class NativeProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = Path(self.tmp.name)
        self.socket = self.bridge / "woow-mcp.sock"
        self.requests = []
        self.reply = None
        self.release = None
        self.entered = asyncio.Event()
        self.server = await asyncio.start_unix_server(self.handle, str(self.socket))
        self.socket.chmod(0o600)
        self.addAsyncCleanup(self.close)
        binding = patch.object(native, "_bridge_for_session", return_value=self.bridge)
        binding.start()
        self.addCleanup(binding.stop)
        self.sync_calls = 0

    async def close(self):
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, reader, writer):
        try:
            request = json.loads(await reader.readline())
            self.requests.append(request)
            self.entered.set()
            if self.release:
                await self.release.wait()
            if self.reply is not None:
                result = self.reply
            elif request["action"] == "probe":
                result = {"state": "ready", "nativeSessionId": SID}
            else:
                result = {"state": "applied", "nativeSessionId": SID,
                          "configurationHash": "a" * 64, "method": "native-mcp-reload",
                          "historyPreserved": True, "inventoryVerified": True,
                          "toolsVerified": False, "toolCount": 1,
                          "raw_diagnostic": "must-not-leak"}
            writer.write((json.dumps(result) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def sync(self):
        self.sync_calls += 1
        return "a" * 64

    async def refresh(self, info=None):
        return await native.refresh_pi("conv_original", info if info is not None else {"external_session_id": SID}, sync=self.sync)

    async def test_same_identity_probe_before_sync_and_whitelisted_receipt(self):
        result = await self.refresh()
        self.assertEqual(result["sessionId"], "conv_original")
        self.assertEqual(result["refresh"]["nativeSessionId"], SID)
        self.assertTrue(result["refresh"]["inventoryVerified"])
        self.assertFalse(result["refresh"]["toolsVerified"])
        self.assertEqual([r["action"] for r in self.requests], ["probe", "refresh"])
        self.assertEqual(self.sync_calls, 1)
        self.assertNotIn("must-not-leak", json.dumps(result))

    async def test_busy_never_synchronizes_or_falls_back(self):
        self.reply = {"state": "refused", "code": "SESSION_BUSY"}
        with self.assertRaisesRegex(native.NativeRefreshError, "^SESSION_BUSY$"):
            await self.refresh()
        self.assertEqual(self.sync_calls, 0)
        self.assertEqual(len(self.requests), 1)

    async def test_missing_persistence_never_contacts_native_or_sync(self):
        with self.assertRaisesRegex(native.NativeRefreshError, "^MCP_PERSISTENCE_MISSING$"):
            await self.refresh({})
        self.assertEqual(self.requests, [])
        self.assertEqual(self.sync_calls, 0)

    async def test_unknown_native_error_is_sanitized(self):
        self.reply = {"state": "refused", "code": "private-secret-diagnostics"}
        with self.assertRaisesRegex(native.NativeRefreshError, "^MCP_REFRESH_FAILED$"):
            await self.refresh()

    async def test_bad_probe_identity_prevents_sync(self):
        self.reply = {"state": "ready", "nativeSessionId": "different"}
        with self.assertRaisesRegex(native.NativeRefreshError, "^MCP_NATIVE_ID_CHANGED$"):
            await self.refresh()
        self.assertEqual(self.sync_calls, 0)

    async def test_process_file_lock_refuses_concurrent_requests(self):
        self.release = asyncio.Event()
        first = asyncio.create_task(self.refresh())
        await self.entered.wait()
        try:
            with self.assertRaisesRegex(native.NativeRefreshError, "^SESSION_BUSY$"):
                await self.refresh()
        finally:
            self.release.set()
        self.assertEqual((await first)["refresh"]["state"], "applied")
        self.assertEqual(self.sync_calls, 1)

    async def test_sync_failure_does_not_request_reload(self):
        def broken():
            raise RuntimeError("secret output")
        with self.assertRaisesRegex(native.NativeRefreshError, "^MCP_SYNC_FAILED$"):
            await native.refresh_pi("conv_original", {"external_session_id": SID}, sync=broken)
        self.assertEqual(len(self.requests), 1)

    async def test_unsafe_socket_permissions_refused(self):
        self.socket.chmod(0o666)
        with self.assertRaisesRegex(native.NativeRefreshError, "^MCP_UNSAFE_BRIDGE$"):
            await self.refresh()
        self.assertEqual(self.requests, [])


class PinnedPatch(unittest.TestCase):
    def setUp(self):
        # Explicit fixture path; never patch the fixture or import live app code.
        fixture = os.environ.get("OMNIGENT_TEST_SITE_PACKAGES")
        if not fixture:
            self.skipTest("Set OMNIGENT_TEST_SITE_PACKAGES to a pristine 0.16.0 fixture")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        for name in patcher.HASHES:
            target = self.site / "omnigent" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(fixture) / "omnigent" / name, target)
        metadata = self.site / "omnigent-0.16.0.dist-info" / "METADATA"
        metadata.parent.mkdir()
        metadata.write_text("Name: omnigent\nVersion: 0.16.0\n")

    def snapshot(self):
        return {str(p.relative_to(self.site)): p.read_bytes() for p in self.site.rglob("*") if p.is_file()}

    def test_preflight_no_writes_then_idempotent_and_exact_scope(self):
        before = self.snapshot()
        self.assertEqual(patcher.patch(self.site, check=True)["state"], "verified")
        self.assertEqual(before, self.snapshot())
        result = patcher.patch(self.site)
        self.assertEqual(result["state"], "applied")
        after = self.snapshot()
        self.assertEqual(patcher.patch(self.site)["state"], "already-applied")
        self.assertEqual(after, self.snapshot())
        self.assertEqual(set(after) - set(before), {"omnigent/" + patcher.HELPER, "omnigent/" + patcher.RECEIPT})
        self.assertFalse((self.site / "omnigent/runner/app.py").exists())

    def test_modified_vendor_file_blocks_all_writes(self):
        name = list(patcher.HASHES)[-1]
        target = self.site / "omnigent" / name
        target.write_bytes(target.read_bytes() + b"\n// vendor drift\n")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "MCP_NATIVE_PATCH_SOURCE_MISMATCH"):
            patcher.patch(self.site)
        self.assertEqual(before, self.snapshot())

    def test_forged_receipt_cannot_bless_patched_source_drift(self):
        patcher.patch(self.site)
        name = list(patcher.HASHES)[-1]
        target = self.site / "omnigent" / name
        target.write_bytes(target.read_bytes() + b"\n// changed\n")
        receipt = self.site / "omnigent" / patcher.RECEIPT
        payload = json.loads(receipt.read_text())
        payload["targets"][name]["patched"] = patcher.digest(target.read_bytes())
        receipt.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "MCP_NATIVE_PATCH_SOURCE_MISMATCH"):
            patcher.patch(self.site)

    def test_helper_tampering_detected(self):
        patcher.patch(self.site)
        (self.site / "omnigent" / patcher.HELPER).write_text("modified")
        with self.assertRaisesRegex(ValueError, "MCP_NATIVE_PATCH_RECEIPT_MISMATCH"):
            patcher.patch(self.site)


if __name__ == "__main__":
    unittest.main()
