"""Harness regression tests. These are not HAOS/Supervisor acceptance evidence."""
import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import hashlib
import json
import os
from pathlib import Path
import socket
import tarfile
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, mock_open, patch
import zipfile

import httpx
import yaml

from haos import acceptance, browser, host, provenance


HEAD = "a" * 40
TREE = "b" * 40


def migration_fixture(files, heads):
    return {"files": {name: hashlib.sha256(body.encode()).hexdigest() for name, body in files.items()},
            "heads": heads}


def registry_fixture(version=host.CANDIDATE_VERSION, *, revision="pushed"):
    config = json.dumps({"architecture": "amd64", "os": "linux", "config": {"Labels": {
        "io.hass.version": version}}}).encode()
    config_id = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"digest": config_id, "size": len(config), "mediaType": "application/vnd.oci.image.config.v1+json"},
        "layers": [], "annotations": {"fixture": revision}}).encode()
    return config, config_id, manifest, "sha256:" + hashlib.sha256(manifest).hexdigest()


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.run = {"head_sha": HEAD, "event": "pull_request", "run_attempt": 2}
        self.jobs = [{"name": "build (amd64)", "conclusion": "success", "run_attempt": 1}]
        self.artifacts = [
            {"name": "upgrade-comparison-image-woow-omnigent-attempt-1", "expired": False},
            {"name": "haos-image-source-attempt-1", "expired": False},
        ]

    def select(self):
        return host.select_artifact(self.run, self.jobs, self.artifacts, HEAD)

    def test_uses_build_attempt_when_other_job_reruns(self):
        self.assertEqual(self.select(), self.artifacts)

    def test_rebuilt_job_cannot_reuse_old_artifact(self):
        self.jobs[0]["run_attempt"] = 2
        self.assertIsNone(self.select())

    def test_wrong_head_rejected(self):
        self.run["head_sha"] = "c" * 40
        with self.assertRaises(RuntimeError):
            self.select()

    def test_non_pr_rejected(self):
        self.run["event"] = "push"
        with self.assertRaises(RuntimeError):
            self.select()

    def test_failed_build_not_accepted(self):
        self.jobs[0]["conclusion"] = "failure"
        self.assertIsNone(self.select())

    def test_expired_image_not_accepted(self):
        self.artifacts[0]["expired"] = True
        self.assertIsNone(self.select())

    def test_missing_source_receipt_not_accepted(self):
        self.artifacts.pop()
        self.assertIsNone(self.select())

    def test_ambiguous_image_rejected(self):
        self.artifacts.append(copy.deepcopy(self.artifacts[0]))
        with self.assertRaises(RuntimeError):
            self.select()

    def test_unknown_attempt_rejected(self):
        del self.jobs[0]["run_attempt"]
        with self.assertRaises(RuntimeError):
            self.select()

    def make_archive(self, directory, *, member="woow-omnigent.tar", tag=host.IMAGE_TAG,
                     extra=None):
        blob = io.BytesIO()
        with tarfile.open(fileobj=blob, mode="w") as t:
            content = json.dumps([{"RepoTags": [tag]}]).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(content)
            t.addfile(info, io.BytesIO(content))
            if extra:
                t.addfile(tarfile.TarInfo(extra))
        archive = Path(directory) / "image.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(member, blob.getvalue())
        return archive

    def test_valid_archive(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "image.tar"
            digest = host.extract_image(self.make_archive(d), target)
            self.assertEqual(digest, host.sha256(target))

    def test_wrong_archive_member(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(RuntimeError):
            host.extract_image(self.make_archive(d, member="../image.tar"), Path(d) / "image.tar")

    def test_wrong_image_tag(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(RuntimeError):
            host.extract_image(self.make_archive(d, tag="other:latest"), Path(d) / "image.tar")

    def test_tar_path_traversal(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(RuntimeError):
            host.extract_image(self.make_archive(d, extra="../../outside"), Path(d) / "image.tar")


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.receipt = {"schema": 1, "pr_head": HEAD, "checkout_commit": "c" * 40,
                        "addon_tree": TREE, "image_id": "sha256:" + "d" * 64,
                        "files": provenance.hashes(acceptance.ROOT)}

    def validate(self):
        with patch.dict(os.environ, {"HAOS_HEAD_SHA": HEAD}):
            provenance.validate_source(self.receipt, HEAD, TREE, acceptance.ROOT)

    def test_merge_checkout_with_identical_addon_tree(self):
        self.validate()

    def test_merge_checkout_with_changed_addon_tree_rejected(self):
        self.receipt["addon_tree"] = "e" * 40
        with self.assertRaises(RuntimeError):
            self.validate()

    def test_changed_pin_rejected(self):
        self.receipt["files"]["build/artifact-pin.json"] = "0" * 64
        with self.assertRaises(RuntimeError):
            self.validate()

    def test_wrong_acceptance_checkout_rejected(self):
        with patch.dict(os.environ, {"HAOS_HEAD_SHA": HEAD}), self.assertRaises(RuntimeError):
            provenance.validate_source(self.receipt, "f" * 40, TREE, acceptance.ROOT)

    def test_unvalidated_image_identity_rejected(self):
        self.receipt["image_id"] = "not-a-digest"
        with self.assertRaises(RuntimeError):
            self.validate()


class ArchiveIdentityTests(unittest.TestCase):
    def archive(self, directory, *, config_data=None, config_reference=None, tag=host.IMAGE_TAG,
                duplicate=False, bad_manifest_hash=False, bad_descriptor_size=False):
        config = config_data or b'{"architecture":"amd64","os":"linux","rootfs":{"type":"layers","diff_ids":[]}}'
        config_id = "sha256:" + hashlib.sha256(config).hexdigest()
        config_name = "blobs/sha256/" + config_id[7:]
        manifest = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                       "digest": config_reference or config_id, "size": len(config)}, "layers": []}).encode()
        manifest_id = "sha256:" + hashlib.sha256(manifest).hexdigest()
        files = {"manifest.json": json.dumps([{"Config": config_name, "RepoTags": [tag], "Layers": []}]).encode(),
                 config_name: config,
                 "blobs/sha256/" + manifest_id[7:]: manifest + (b" " if bad_manifest_hash else b""),
                 "index.json": json.dumps({"schemaVersion": 2, "manifests": [{"digest": manifest_id,
                     "size": len(manifest) + int(bad_descriptor_size),
                     "mediaType": "application/vnd.oci.image.manifest.v1+json"}]}).encode()}
        target = Path(directory) / "candidate.tar"
        with tarfile.open(target, "w") as t:
            for name, data in list(files.items()) + ([('manifest.json', files['manifest.json'])] if duplicate else []):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        return target, config_id, manifest_id

    def test_manifest_producer_and_config_consumer_are_cryptographically_linked(self):
        with tempfile.TemporaryDirectory() as d:
            path, config_id, manifest_id = self.archive(d)
            self.assertNotEqual(config_id, manifest_id)
            identity = provenance.archive_identity(path, manifest_id)
            self.assertEqual(identity, {"config_digest": config_id, "producer_image_id": manifest_id,
                                        "producer_id_kind": "manifest"})

    def test_legacy_config_producer_identity(self):
        with tempfile.TemporaryDirectory() as d:
            path, config_id, _ = self.archive(d)
            self.assertEqual(provenance.archive_identity(path, config_id)["producer_id_kind"], "config")

    def test_unknown_producer_id_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path, _, _ = self.archive(d)
            with self.assertRaises(RuntimeError):
                provenance.archive_identity(path, "sha256:" + "0" * 64)

    def test_changed_config_reference_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path, _, manifest_id = self.archive(d, config_reference="sha256:" + "0" * 64)
            with self.assertRaises(RuntimeError):
                provenance.archive_identity(path, manifest_id)

    def test_corrupt_manifest_duplicate_member_and_wrong_tag_rejected(self):
        for change in ({"bad_manifest_hash": True}, {"duplicate": True}, {"tag": "other:new"},
                       {"bad_descriptor_size": True}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                path, _, manifest_id = self.archive(d, **change)
                with self.assertRaises(RuntimeError):
                    provenance.archive_identity(path, manifest_id)


class HostTests(unittest.TestCase):
    def test_baseline_anchor_exports_only_pulled_immutable_image_and_deletes_tar(self):
        for mismatch in (False, True):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                tag = "haos-acceptance-baseline:" + host.BASELINE_VERSION
                fixture, config_id, _ = ArchiveIdentityTests().archive(d, tag=tag)
                def command(argv, **kwargs):
                    if argv[:3] == ["docker", "image", "inspect"]:
                        self.assertEqual(argv[-1], host.BASELINE_IMAGE)
                        value = "sha256:" + "0"*64 if mismatch else config_id
                        return SimpleNamespace(returncode=0, stdout=value.encode(), stderr=b"")
                    if argv[1] == "tag":
                        self.assertEqual(argv, ["docker", "tag", host.BASELINE_IMAGE, tag])
                    if argv[1] == "save":
                        self.assertEqual(argv[-1], tag)
                        Path(argv[3]).write_bytes(fixture.read_bytes())
                    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
                h.run = Mock(side_effect=command)
                if mismatch:
                    with self.assertRaises(RuntimeError):
                        h.baseline_identity()
                else:
                    self.assertEqual(h.baseline_identity()["config_digest"], config_id)
                self.assertFalse((Path(d) / "baseline-image.tar").exists())

    def test_registry_metadata_is_bounded_loopback_only_and_does_not_redirect(self):
        for status, body in ((200, b"{}"), (302, b""), (200, b"x"*(1024*1024+1))):
            with self.subTest(status=status, size=len(body)), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                def respond(request):
                    self.assertEqual(str(request.url), "http://127.0.0.1:15000/v2/omnigent-acceptance/manifests/" + host.CANDIDATE_VERSION)
                    return httpx.Response(status, content=body, headers={
                        "Docker-Content-Digest": "sha256:" + "d"*64, "Location": "https://invalid.example"})
                with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
                    def stream(method, url, **kwargs):
                        self.assertFalse(kwargs.pop("trust_env"))
                        self.assertFalse(kwargs["follow_redirects"])
                        return client.stream(method, url, **kwargs)
                    with patch("haos.host.httpx.stream", side_effect=stream):
                        if status == 200 and len(body) <= 1024*1024:
                            self.assertEqual(h._registry_metadata("manifests/" + host.CANDIDATE_VERSION)[0], body)
                        else:
                            with self.assertRaises(RuntimeError):
                                h._registry_metadata("manifests/" + host.CANDIDATE_VERSION)
                self.assertNotIn("invalid.example", json.dumps(h.registry_progress))
                with self.assertRaises(RuntimeError):
                    h._registry_metadata("https://invalid.example/private")

    def test_pushed_manifest_binding_handles_host_config_guest_manifest_for_both_versions(self):
        for version in (host.BASELINE_VERSION, host.CANDIDATE_VERSION):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                config, config_id, manifest, pushed_id = registry_fixture(version)
                _, _, _, producer_id = registry_fixture(version, revision="producer")
                self.assertNotEqual(producer_id, pushed_id)
                anchor = {"config_digest": config_id, "producer_image_id": producer_id}
                image = {"Id": config_id, "Architecture": "amd64", "Config": {
                    "Labels": {"io.hass.version": version}}}
                h.run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=b"", stderr=b"")]*2 + [
                    SimpleNamespace(returncode=0, stdout=json.dumps([image]).encode(), stderr=b"")])
                h._registry_metadata = Mock(side_effect=[(manifest, pushed_id), (config, config_id)])
                source = host.BASELINE_IMAGE if version == host.BASELINE_VERSION else host.IMAGE_TAG
                h.publish_local(source, version, identity=anchor)
                for guest_id in (pushed_id, config_id):
                    h.ssh = Mock(return_value=SimpleNamespace(stdout=json.dumps([
                        {"Image": guest_id, "Name": "/app_local_woow-omnigent"}]).encode()))
                    self.assertEqual(h.verify_guest_image(config_id), "app_local_woow-omnigent")
                for wrong in (producer_id, "sha256:" + "f" * 64):
                    h.ssh.return_value.stdout = json.dumps([
                        {"Image": wrong, "Name": "/app_local_woow-omnigent"}]).encode()
                    with self.assertRaises(RuntimeError):
                        h.verify_guest_image(config_id)

    def test_guest_identity_without_registry_proof_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.ssh = Mock(return_value=SimpleNamespace(stdout=b'[{"Image":"same","Name":"/app_local_woow-omnigent"}]'))
            with self.assertRaises(RuntimeError):
                h.verify_guest_image("same")

    def test_registry_manifest_wrong_hash_config_and_anchor_rejected(self):
        config, config_id, manifest, pushed_id = registry_fixture()
        for raw, digest, blob, expected in ((manifest+b" ", pushed_id, config, config_id),
                (manifest, "sha256:"+"0"*64, config, config_id),
                (manifest, pushed_id, config+b" ", config_id),
                (manifest, pushed_id, config, "sha256:"+"0"*64)):
            with self.subTest(digest=digest, expected=expected), self.assertRaises(RuntimeError):
                provenance.registry_identity(raw, digest, blob, expected)

    def test_registry_failure_retains_command_exit_without_raw_output(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            with patch("haos.host.subprocess.run", side_effect=[
                    SimpleNamespace(returncode=0, stdout=b"", stderr=b""), SimpleNamespace(
                    returncode=125, stdout=b"", stderr=b"denied synthetic-secret /mcp/private_token")]):
                with self.assertRaises(RuntimeError):
                    h.registry()
            self.assertEqual(h.registry_progress["stage"], "registry_launch")
            self.assertEqual(h.registry_progress["commands"][-1], {
                "stage": "registry_launch", "exit": 125, "timeout": False,
                "error_codes": ["access_denied"]})
            self.assertIsNone(h.registry_created)
            self.assertEqual(h.registry_progress["exception"], "RuntimeError")
            self.assertEqual(h.registry_progress["states"], {"registry_pull": True, "registry_launch": False})
            self.assertNotIn("synthetic-secret", json.dumps(h.registry_progress))
            self.assertNotIn("private_token", json.dumps(h.registry_progress))

    def test_registry_push_timeout_retains_exact_image_stage(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
                host.subprocess.TimeoutExpired(["docker", "synthetic-secret"], 240)])
            with self.assertRaises(host.subprocess.TimeoutExpired):
                h.publish_local(host.IMAGE_TAG, host.CANDIDATE_VERSION, identity={"config_digest": "sha256:" + "c"*64, "producer_image_id": "sha256:" + "c"*64})
            self.assertEqual(h.registry_progress["stage"], "candidate_push")
            self.assertEqual(h.registry_progress["commands"][-1], {
                "stage": "candidate_push", "exit": None, "timeout": True, "error_codes": []})
            self.assertNotIn("synthetic-secret", json.dumps(h.registry_progress))

    def test_registry_forwarding_failure_retains_probe_and_tunnel_exit(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.start = Mock(return_value=Mock(poll=Mock(return_value=255)))
            h.ssh = Mock(return_value=SimpleNamespace(returncode=7))
            def once(check, *args):
                self.assertFalse(check())
                raise RuntimeError("timeout")
            with patch("haos.host.wait_for", side_effect=once), self.assertRaises(RuntimeError):
                h.registry_tunnel()
            self.assertEqual(h.registry_progress["stage"], "guest_registry_forwarding")
            self.assertEqual(h.registry_progress["forwarding"], {
                "probe_exit": 7, "probe_timeout": False, "tunnel_exit": 255})

    def test_registry_image_version_guard_remains_enforced_and_identified(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            image = {"Architecture": "amd64", "Config": {"Labels": {"io.hass.version": "wrong"}}}
            h.run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=b"", stderr=b"")]*2 + [
                SimpleNamespace(returncode=0, stdout=json.dumps([image]).encode(), stderr=b"")])
            with self.assertRaisesRegex(RuntimeError, "wrong add-on version"):
                h.publish_local(host.BASELINE_IMAGE, host.BASELINE_VERSION, identity={"config_digest": "sha256:" + "c"*64, "producer_image_id": "sha256:" + "c"*64})
            self.assertEqual(h.registry_progress["stage"], "baseline_version")
            self.assertTrue(all(c["exit"] == 0 for c in h.registry_progress["commands"]))

    def test_registry_all_command_boundaries_preserve_failures_and_markers(self):
        stages = ["registry_pull", "registry_launch", "registry_inspect"] + [
            role + "_" + step for role in ("baseline", "candidate") for step in ("tag", "push", "inspect")]
        for stage in stages:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.run = Mock(return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=
                    b"x509: https://synthetic-secret no such file or directory"))
                with self.assertRaises(RuntimeError):
                    h._registry_run(stage, ["docker", "synthetic-secret"])
                self.assertEqual(h.registry_progress["stage"], stage)
                self.assertFalse(h.registry_progress["states"][stage])
                self.assertEqual(h.registry_progress["commands"][0]["error_codes"],
                                 ["certificate_error", "missing_path"])
                self.assertNotIn("synthetic-secret", json.dumps(h.registry_progress))

    def test_registry_exception_class_is_allowlisted_without_details(self):
        class SecretException(Exception):
            pass
        for error, kind in ((OSError("private-path"), "OSError"),
                            (ValueError("private-value"), "ValueError"),
                            (SecretException("private-value"), "other")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.run = Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    h._registry_run("registry_pull", ["docker", "private-command"])
                self.assertEqual(h.registry_progress["exception"], kind)
                self.assertNotIn("private-", json.dumps(h.registry_progress))
                self.assertNotIn("SecretException", json.dumps(h.registry_progress))

    def test_registry_container_and_host_http_boundaries(self):
        for running, status in ((False, None), (True, 503), (True, 200)):
            with self.subTest(running=running, status=status), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=b"", stderr=b"")]*2 + [
                    SimpleNamespace(returncode=0, stdout=json.dumps(
                        {"Running": running, "ExitCode": 0 if running else 2}).encode(), stderr=b"")])
                h.registry_tunnel = Mock()
                def once(check, *args):
                    host.require(check(), "timeout")
                with patch("haos.host.wait_for", side_effect=once), \
                        patch("haos.host.httpx.get", return_value=SimpleNamespace(status_code=status)):
                    if running and status == 200:
                        h.registry()
                        h.registry_tunnel.assert_called_once()
                        self.assertTrue(h.registry_progress["states"]["host_registry_http"])
                    else:
                        with self.assertRaises(RuntimeError):
                            h.registry()
                        h.registry_tunnel.assert_not_called()
                        stage = "host_registry_http" if running else "registry_container_state"
                        self.assertEqual(h.registry_progress["stage"], stage)
                        self.assertFalse(h.registry_progress["states"][stage])
                self.assertTrue(h.registry_created)
                self.assertIs(h.registry_progress["container_running"], running)
                commands = [call.args[0] for call in h.run.call_args_list]
                self.assertEqual(commands[0], ["docker", "pull", "--platform", "linux/amd64", host.REGISTRY_IMAGE])
                self.assertIn("--pull=never", commands[1])
                self.assertIn("127.0.0.1:15000:5000", commands[1])

    def test_registry_image_metadata_and_architecture_guards(self):
        for payload, stage in ((b"invalid", "candidate_metadata"),
                               (json.dumps([{"Architecture": "arm64"}]).encode(), "candidate_architecture")):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=b"", stderr=b"")]*2 + [
                    SimpleNamespace(returncode=0, stdout=payload, stderr=b"")])
                with self.assertRaises((ValueError, RuntimeError)):
                    h.publish_local(host.IMAGE_TAG, host.CANDIDATE_VERSION, identity={"config_digest": "sha256:" + "c"*64, "producer_image_id": "sha256:" + "c"*64})
                self.assertEqual(h.registry_progress["stage"], stage)
                self.assertFalse(h.registry_progress["states"][stage])

    def test_registry_host_http_exception_remains_safe_and_retryable(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=b"", stderr=b"")]*2 + [
                SimpleNamespace(returncode=0, stdout=b'{"Running":true,"ExitCode":0}', stderr=b"")])
            def once(check, *args):
                self.assertFalse(check())
                raise RuntimeError("timeout")
            with patch("haos.host.wait_for", side_effect=once), \
                    patch("haos.host.httpx.get", side_effect=httpx.ConnectError("private-url")), \
                    self.assertRaises(RuntimeError):
                h.registry()
            self.assertEqual(h.registry_progress["stage"], "host_registry_http")
            self.assertEqual(h.registry_progress["host_http"], {"http_status": None, "exception": "HTTPError"})
            self.assertNotIn("private-url", json.dumps(h.registry_progress))

    def test_registry_forward_timeout_and_start_failure_remain_distinct(self):
        for start_fails in (True, False):
            with self.subTest(start_fails=start_fails), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.start = Mock(side_effect=OSError("private-path")) if start_fails else Mock(
                    return_value=Mock(poll=Mock(return_value=None)))
                h.ssh = Mock(side_effect=host.subprocess.TimeoutExpired(["private-command"], 10))
                with patch("haos.host.wait_for", side_effect=lambda check, *args: check()), \
                        self.assertRaises((OSError, host.subprocess.TimeoutExpired)):
                    h.registry_tunnel()
                self.assertEqual(h.registry_progress["stage"], "guest_registry_forwarding")
                self.assertEqual(h.registry_progress["exception"], "OSError" if start_fails else "TimeoutExpired")
                self.assertEqual(h.registry_progress["forwarding"]["probe_timeout"], not start_fails)
                self.assertNotIn("private-", json.dumps(h.registry_progress))

    def test_kvm_refresh_settles_before_each_grant_and_keeps_original_acl(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            identity = (1, 2, 3, 0, 100)
            snapshots = [(identity, b"original", False), (identity, b"grant-one", True),
                         (identity, b"original", False), (identity, b"grant-two", True)]
            h._kvm_access_snapshot = Mock(side_effect=snapshots)
            h.run = Mock()
            with patch("haos.host.os.getuid", return_value=1001):
                h.refresh_kvm_access("preflight")
                h.refresh_kvm_access("boot")
            self.assertEqual(h.original_kvm_acl, b"original")
            self.assertEqual(h.kvm_access_baseline, snapshots[-1])
            self.assertEqual([c.args[0] for c in h.run.call_args_list], [
                ["udevadm", "settle", "--timeout=5"],
                ["sudo", "-n", "setfacl", "-m", "u:1001:rw", "/dev/kvm"],
                ["udevadm", "settle", "--timeout=5"],
                ["sudo", "-n", "setfacl", "-m", "u:1001:rw", "/dev/kvm"]])
            self.assertTrue(h.kvm_access_progress["refreshes"][1]["acl_changed_since_grant"])
            self.assertFalse(h.kvm_access_progress["refreshes"][1]["effective_access_before"])
            self.assertTrue(h.kvm_access_progress["refreshes"][1]["effective_access_after"])
            self.assertNotIn("original", json.dumps(h.kvm_access_progress))
            self.assertNotIn("1001", json.dumps(h.kvm_access_progress))

    def test_kvm_refresh_settle_failure_prevents_grant(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.run = Mock(side_effect=RuntimeError("settle failed"))
            h._kvm_access_snapshot = Mock()
            with self.assertRaises(RuntimeError):
                h.refresh_kvm_access("boot")
            h.run.assert_called_once_with(["udevadm", "settle", "--timeout=5"], timeout=6)
            h._kvm_access_snapshot.assert_not_called()

    def test_kvm_ineffective_grant_fails_and_preserves_pre_grant_identity(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            identity = (1, 2, 3, 0, 100)
            h._kvm_access_snapshot = Mock(side_effect=[
                (identity, b"original", False), (identity, b"changed-acl", False)])
            def run(argv, **kwargs):
                if argv[0] == "sudo":
                    self.assertEqual(h.original_kvm_acl, b"original")
                    self.assertEqual(h.kvm_identity, identity)
            h.run = Mock(side_effect=run)
            with self.assertRaisesRegex(RuntimeError, "grant ineffective"):
                h.refresh_kvm_access("preflight")
            self.assertIsNone(h.kvm_access_baseline)
            self.assertFalse(h.kvm_access_progress["refreshes"][0]["effective_access_after"])

    def test_kvm_refresh_refuses_replaced_device(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.original_kvm_acl = b"original"
            h.kvm_identity = (1, 2, 3, 0, 100)
            h.kvm_access_baseline = (h.kvm_identity, b"grant", True)
            h._kvm_access_snapshot = Mock(return_value=((1, 9, 3, 0, 100), b"other", False))
            h.run = Mock()
            with self.assertRaisesRegex(RuntimeError, "KVM device identity"):
                h.refresh_kvm_access("boot")
            h.run.assert_called_once_with(["udevadm", "settle", "--timeout=5"], timeout=6)

    def test_kvm_cleanup_reaps_then_settles_then_restores_original_acl(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.original_kvm_acl = b"original-private-acl"
            h.kvm_identity = (1, 2, 3, 0, 100)
            h._kvm_access_snapshot = Mock(return_value=(h.kvm_identity, b"grant", True))
            events = []
            qemu = Mock()
            qemu.poll.return_value = None
            qemu.terminate.side_effect = lambda: events.append("terminate")
            def reaped(**kwargs):
                events.append("reap")
                qemu.poll.return_value = 0
            qemu.wait.side_effect = reaped
            h.qemu, h.processes = qemu, [qemu]
            def run(argv, **kwargs):
                events.append("settle" if argv[0] == "udevadm" else "restore")
                if argv[0] == "sudo":
                    self.assertEqual(kwargs["data"], b"original-private-acl")
            h.run = Mock(side_effect=run)
            h.cleanup()
            self.assertEqual(events, ["terminate", "reap", "settle", "restore"])
            self.assertTrue(h.kvm_access_progress["restored"])

    def test_kvm_cleanup_restores_even_when_settle_fails(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.original_kvm_acl = b"original"
            h.kvm_identity = (1, 2, 3, 0, 100)
            h._kvm_access_snapshot = Mock(return_value=(h.kvm_identity, b"grant", True))
            h.run = Mock(side_effect=[RuntimeError("settle failed"), SimpleNamespace(returncode=0)])
            with self.assertRaisesRegex(RuntimeError, "settle failed"):
                h.cleanup()
            self.assertEqual(h.run.call_args.args[0], ["sudo", "-n", "setfacl", "--restore=-"])
            self.assertEqual(h.run.call_args.kwargs["data"], b"original")
            self.assertTrue(h.kvm_access_progress["restored"])
            self.assertEqual(h.kvm_access_progress["cleanup_failure"], "udev_settle")

    def test_kvm_cleanup_refuses_replaced_device_or_owner(self):
        original = (1, 2, 3, 0, 100)
        for index in range(len(original)):
            changed = list(original)
            changed[index] += 1
            with self.subTest(index=index), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.original_kvm_acl = b"original"
                h.kvm_identity = original
                h._kvm_access_snapshot = Mock(return_value=(tuple(changed), b"other", False))
                h.run = Mock()
                with self.assertRaisesRegex(RuntimeError, "KVM device identity"):
                    h.cleanup()
                h.run.assert_called_once_with(["udevadm", "settle", "--timeout=5"], timeout=6)
                self.assertFalse(h.kvm_access_progress["restored"])
                self.assertEqual(h.kvm_access_progress["cleanup_failure"], "device_identity")

    def test_kvm_snapshot_ignores_acl_mode_bits_but_requires_character_device(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.run = Mock(return_value=SimpleNamespace(stdout=b"private-acl"))
            info = SimpleNamespace(st_dev=1, st_ino=2, st_rdev=3, st_uid=0, st_gid=100,
                                   st_mode=host.stat.S_IFCHR | 0o660)
            with patch("haos.host.Path.stat", return_value=info), patch("haos.host.os.access", return_value=True):
                first = h._kvm_access_snapshot()
                info.st_mode = host.stat.S_IFCHR | 0o600
                self.assertEqual(h._kvm_access_snapshot()[0], first[0])
                info.st_mode = host.stat.S_IFREG | 0o660
                h.original_kvm_acl, h.kvm_identity = first[1], first[0]
                h.run.reset_mock()
                with self.assertRaisesRegex(RuntimeError, "character device"):
                    h.cleanup()
                h.run.assert_called_once_with(["udevadm", "settle", "--timeout=5"], timeout=6)
                self.assertEqual(h.kvm_access_progress["cleanup_failure"], "device_identity")

    def test_kvm_refresh_immediately_precedes_initial_and_cold_boot(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            events = []
            h.disk_guard = Mock()
            h.refresh_kvm_access = Mock(side_effect=lambda phase: events.append("refresh"))
            qemu = Mock(poll=Mock(return_value=0))
            def start(argv, **kwargs):
                self.assertEqual(argv[0], "qemu-system-x86_64")
                self.assertIn("q35,accel=kvm", argv)
                self.assertNotIn("sudo", argv)
                network = argv[argv.index("-nic") + 1]
                self.assertIn(f"hostfwd=tcp:127.0.0.1:{host.HA_PORTS[0]}-:80,", network)
                self.assertIn(f"hostfwd=tcp:127.0.0.1:{host.HA_PORTS[1]}-:8123,", network)
                self.assertTrue(set(host.HA_PORTS).issubset(host.PORTS))
                events.append("start")
                return qemu
            h.start = Mock(side_effect=start)
            h._wait_boot = Mock(return_value={})
            h._capture_boot_signals = Mock()
            with contextlib.redirect_stdout(io.StringIO()):
                h.boot()
                h.boot()
            self.assertEqual(events, ["refresh", "start", "refresh", "start"])

    def test_exited_qemu_fails_immediately_instead_of_waiting_for_ssh(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.disk_guard = Mock()
            h.refresh_kvm_access = Mock()
            h.start = Mock(return_value=Mock(poll=Mock(return_value=1)))
            h.ssh = Mock()
            # One predicate call is enough to detect a dead QEMU process.
            def check_once(check, *args):
                result = check()
                self.assertTrue(result, "dead QEMU was treated as retryable SSH readiness")
                return result
            with patch("haos.host.wait_for", side_effect=check_once), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(host.BootFailure, "QEMU exited before guest readiness"):
                    h.boot()
            h.ssh.assert_not_called()
            self.assertEqual(h.boot_progress["qemu_exit"], 1)

    def test_terminal_boot_failure_is_not_swallowed_by_wait_for(self):
        check = Mock(side_effect=host.BootFailure("QEMU exited before guest readiness"))
        with patch("haos.host.time.sleep") as sleep, self.assertRaises(host.BootFailure):
            host.wait_for(check, 600, "fresh HAOS developer SSH")
        sleep.assert_not_called()
        check.assert_called_once()

    def test_boot_diagnostics_export_labels_not_raw_log_content(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.qemu = Mock(poll=Mock(return_value=1))
            secret = "private_omcp_SYNTHETIC_SECRET https://example.invalid/?token=secret"
            (Path(d) / "qemu.log").write_text("Block node is read-only\n" + secret)
            (Path(d) / "console.log").write_text("Linux version fixture\nUpdate SSH authorized_keys!\n" + secret)
            h._capture_boot_signals()
            self.assertEqual(h.boot_progress, {
                "qemu_exit": 1, "qemu_error_codes": ["readonly_block"],
                "console_markers": ["linux_started", "ssh_key_imported"]})
            self.assertNotIn(secret, json.dumps(h.boot_progress))

    def test_boot_ssh_diagnostics_export_error_class_only(self):
        for error, expected in (
            (b"Permission denied (publickey). private_omcp_SYNTHETIC", "authentication_denied"),
            (b"Connection refused private_omcp_SYNTHETIC", "connection_refused"),
            (b"unknown private_omcp_SYNTHETIC", "unclassified"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.qemu = Mock(poll=Mock(return_value=None))
                h.boot_progress["ssh_attempts"] = 0
                h.ssh = Mock(return_value=SimpleNamespace(returncode=255, stderr=error))
                self.assertFalse(h._ssh_ready())
                self.assertEqual(h.boot_progress["last_ssh_error"], expected)
                self.assertEqual(h.boot_progress["ssh_attempts"], 1)
                self.assertNotIn("SYNTHETIC", json.dumps(h.boot_progress))

    def test_boot_ssh_timeout_is_bounded_and_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.qemu = Mock(poll=Mock(return_value=None))
            h.boot_progress["ssh_attempts"] = 0
            h.boot_progress["last_ssh_exit"] = 255
            h.ssh = Mock(side_effect=host.subprocess.TimeoutExpired("private command", 10))
            self.assertFalse(h._ssh_ready())
            self.assertEqual(h.boot_progress["last_ssh_error"], "command_timeout")
            self.assertIsNone(h.boot_progress["last_ssh_exit"])

    def boot_fixture(self, supervisor_info, root_info):
        """Use the real response envelopes, parser and readiness predicate."""
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.disk_guard = Mock()
            h.refresh_kvm_access = Mock()
            h.start = Mock(return_value=Mock(poll=Mock(return_value=None)))
            visited = []
            def ssh(command, **kwargs):
                if command == "true":
                    return SimpleNamespace(returncode=0)
                for path, data in (("/supervisor/info", supervisor_info), ("/info", root_info)):
                    if '"http://$address' + path + '"' in command:
                        visited.append(path)
                        return SimpleNamespace(returncode=0, stderr=b"HAOS_BOOT curl_exit 0\n",
                                               stdout=json.dumps({"result": "ok", "data": data}).encode() + b"\n200\n")
                self.fail("unexpected guest command")
            h.ssh = Mock(side_effect=ssh)
            def check_once(check, seconds, description, interval=3):
                result = check()
                if not result:
                    raise RuntimeError("not ready")
                return result
            with patch("haos.host.wait_for", side_effect=check_once), contextlib.redirect_stdout(io.StringIO()):
                receipt = h.boot()
            self.assertEqual(visited, ["/supervisor/info", "/info"])
            return receipt

    def test_boot_accepts_actual_supervisor_and_root_info_shapes(self):
        # API supervisor.py has healthy/version and nested app states, but no
        # top-level state. API root.py exposes the system state at GET /info.
        supervisor_info = {"version": "2026.11.0", "arch": "amd64", "healthy": True,
                           "supported": True, "addons": [{"slug": "fixture", "state": "stopped"}]}
        root_info = {"supervisor": "2026.11.0", "hassos": "18.1", "arch": "amd64",
                     "state": "running", "supported": True}
        self.assertEqual(self.boot_fixture(supervisor_info, root_info),
                         {"version": "2026.11.0", "arch": "amd64", "healthy": True, "state": "running"})

    def test_boot_requires_healthy_supervisor_info(self):
        for supervisor_info in ({"healthy": False}, {}):
            with self.subTest(supervisor_info=supervisor_info), self.assertRaisesRegex(RuntimeError, "not ready"):
                self.boot_fixture(supervisor_info, {"state": "running"})

    def test_boot_requires_running_root_info(self):
        for root_info in ({"state": "startup"}, {"state": None}, {}):
            with self.subTest(root_info=root_info), self.assertRaisesRegex(RuntimeError, "not ready"):
                self.boot_fixture({"healthy": True, "addons": [{"state": "started"}]}, root_info)

    def supervisor_probe_fixture(self, *, missing=None, token=True, address=True,
                                 inspect_exit=0, status=200, curl_exit=0, timeout=False,
                                 token_exec_exit=0, cli_env_null=False, operation=False,
                                 jq_program_invalid=False):
        """Execute the actual POSIX probe with real jq and controlled commands."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tools = root / "bin"
            tools.mkdir()
            jq = host.shutil.which("jq")
            self.assertIsNotNone(jq, "jq is required for the real shell regression")
            if missing != "jq":
                if jq_program_invalid:
                    (tools / "jq").write_text("#!/bin/sh\nexec " + jq + " '['\n")
                    (tools / "jq").chmod(0o700)
                else:
                    (tools / "jq").symlink_to(jq)
            cli = [{"Config": {"Env": ["SUPERVISOR_TOKEN=SYNTHETIC_PRIVATE"] if token else []}}]
            if cli_env_null:
                cli[0]["Config"]["Env"] = None
            supervisor = [{"NetworkSettings": {"Networks": {
                "fixture_network": {"IPAddress": "192.0.2.123" if address else ""}}}}]
            docker = tools / "docker"
            docker.write_text("#!/bin/sh\ncase \"$*\" in\n"
                "'exec hassio_cli printenv SUPERVISOR_TOKEN') printf '%s' '"
                + ("SYNTHETIC_PRIVATE" if token else "") + f"'; exit {token_exec_exit};;\n"
                "'inspect hassio_cli') printf '%s' '" + json.dumps(cli) + "';;\n"
                "'inspect hassio_supervisor') printf '%s' '" + json.dumps(supervisor)
                + f"'; exit {inspect_exit};;\n*) exit 99;;\nesac\n")
            docker.chmod(0o700)
            if missing != "curl":
                curl = tools / "curl"
                curl.write_text("#!/bin/sh\nprintf '%s\\n' "
                                "'{\"result\":\"ok\",\"data\":{\"healthy\":true,\"private\":\"SYNTHETIC_PRIVATE\"}}'\n"
                                f"case \"$*\" in *--write-out*) printf '%s\\n' '{status}';; esac\n"
                                f"printf '%s\\n' 'SYNTHETIC_PRIVATE 192.0.2.123' >&2\nexit {curl_exit}\n")
                curl.chmod(0o700)
            h = host.Host(root)
            def ssh(command, **kwargs):
                if not operation:
                    self.assertFalse(kwargs["check"])
                self.assertEqual(kwargs["timeout"], 30)
                result = host.subprocess.run(["/bin/sh", "-c", command], capture_output=True,
                                             env={"PATH": str(tools)}, input=kwargs.get("data"), timeout=5)
                if timeout:
                    raise host.subprocess.TimeoutExpired("private command", 30,
                                                         output=result.stdout, stderr=result.stderr)
                if kwargs.get("check", True):
                    host.require(result.returncode == 0, "fixture guest command failed")
                return result
            h.ssh = ssh
            result = (h.supervisor("POST", "/backups/new/partial", {"name": "fixture"}, timeout=30)
                      if operation else h._supervisor_boot_info("supervisor_info"))
            self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(h.boot_progress))
            self.assertNotIn("192.0.2.123", json.dumps(h.boot_progress))
            return result, h.boot_progress.get("supervisor_info", {})

    def test_supervisor_readiness_uses_runtime_token_without_cli_inspect_env(self):
        result, progress = self.supervisor_probe_fixture(cli_env_null=True)
        self.assertTrue(result.get("healthy"))
        self.assertEqual(progress["http_status"], 200)

    def test_old_inspect_token_filter_reproduces_jq_exit_five_on_null_env(self):
        # A synthetic malformed inspect shape reproduces the observed exit code;
        # the failed CI guest's raw inspect payload was intentionally not retained.
        result = host.subprocess.run(["jq", "-er", '.[0].Config.Env[] | '
            'select(startswith("SUPERVISOR_TOKEN=")) | sub("^SUPERVISOR_TOKEN=";"")'],
            input=b'[{"Config":{"Env":null}}]', capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 5)

    def test_supervisor_operations_use_runtime_token_without_cli_inspect_env(self):
        result, _ = self.supervisor_probe_fixture(cli_env_null=True, operation=True)
        self.assertTrue(result.get("healthy"))

    def test_supervisor_probe_records_successful_command_families(self):
        result, progress = self.supervisor_probe_fixture()
        self.assertTrue(result["healthy"])
        for name in ("docker_available_exit", "curl_available_exit", "jq_available_exit",
                     "cli_token_exec_exit", "token_lookup_exit", "supervisor_inspect_exit",
                     "network_lookup_exit", "address_lookup_exit", "curl_exit", "ssh_exit"):
            self.assertEqual(progress[name], 0, name)
        self.assertEqual(progress["network_count"], 1)
        self.assertEqual(progress["http_status"], 200)
        self.assertTrue(progress["api_ok"])

    def test_supervisor_probe_fails_immediately_for_missing_guest_tools(self):
        for tool in ("curl", "jq"):
            with self.subTest(tool=tool), self.assertRaisesRegex(host.BootFailure, "executable missing"):
                self.supervisor_probe_fixture(missing=tool)

    def test_supervisor_probe_rejects_impossible_command_and_jq_errors(self):
        with self.assertRaisesRegex(host.BootFailure, "token command unavailable"):
            self.supervisor_probe_fixture(token_exec_exit=127)
        with self.assertRaisesRegex(host.BootFailure, "jq program invalid"):
            self.supervisor_probe_fixture(jq_program_invalid=True)

    def test_supervisor_probe_records_inspect_and_lookup_failures(self):
        for options, field in (({"inspect_exit": 1}, "supervisor_inspect_exit"),
                               ({"token_exec_exit": 1}, "cli_token_exec_exit"),
                               ({"token": False}, "token_lookup_exit"),
                               ({"address": False}, "address_lookup_exit")):
            with self.subTest(field=field):
                result, progress = self.supervisor_probe_fixture(**options)
                self.assertEqual(result, {})
                self.assertNotEqual(progress[field], 0)
                self.assertNotIn("curl_exit", progress)

    def test_supervisor_probe_records_http_failure_and_timeout(self):
        for status, code in ((401, 22), (503, 22), (0, 7)):
            with self.subTest(status=status):
                result, progress = self.supervisor_probe_fixture(status=f"{status:03}", curl_exit=code)
                self.assertEqual(result, {})
                self.assertEqual(progress["http_status"], status)
                self.assertEqual(progress["curl_exit"], code)
        result, progress = self.supervisor_probe_fixture(timeout=True)
        self.assertEqual(result, {})
        self.assertTrue(progress["command_timeout"])
        self.assertEqual(progress["token_lookup_exit"], 0)
        self.assertIsNone(progress["ssh_exit"])

    def test_supervisor_readiness_keeps_both_endpoint_failures(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.qemu = Mock(poll=Mock(return_value=None))
            h._ssh_ready = Mock(return_value=True)
            h.ssh = Mock(side_effect=[
                SimpleNamespace(returncode=22, stdout=b"\n401\n", stderr=b"HAOS_BOOT curl_exit 22\n"),
                SimpleNamespace(returncode=22, stdout=b"\n503\n", stderr=b"HAOS_BOOT curl_exit 22\n")])
            def once(check, *args):
                value = check()
                if not value:
                    raise RuntimeError("not ready")
                return value
            with patch("haos.host.wait_for", side_effect=once), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "not ready"):
                    h._wait_boot()
            self.assertEqual(h.boot_progress["stage"], "waiting_for_supervisor")
            self.assertEqual(h.boot_progress["supervisor_info"]["http_status"], 401)
            self.assertEqual(h.boot_progress["root_info"]["http_status"], 503)
            self.assertIsNone(h.boot_progress["supervisor_healthy"])
            self.assertEqual(h.boot_progress["supervisor_state"], "missing")

    def test_supervisor_state_and_health_diagnostics_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.qemu = Mock(poll=Mock(return_value=None))
            h._ssh_ready = Mock(return_value=True)
            h._supervisor_boot_info = Mock(side_effect=[
                {"healthy": "SYNTHETIC_PRIVATE"}, {"state": "SYNTHETIC_PRIVATE"}])
            def once(check, *args):
                value = check()
                if not value:
                    raise RuntimeError("not ready")
                return value
            with patch("haos.host.wait_for", side_effect=once), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "not ready"):
                    h._wait_boot()
            self.assertIsNone(h.boot_progress["supervisor_healthy"])
            self.assertEqual(h.boot_progress["supervisor_state"], "other")
            self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(h.boot_progress))

    def test_non_ci_refused_before_kvm(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with patch("builtins.open") as opened, self.assertRaises(RuntimeError):
                host.Host(d).preflight()
            opened.assert_not_called()

    def test_root_runner_is_refused_before_acl_or_qemu(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
                patch("haos.host.platform.machine", return_value="x86_64"), \
                patch("haos.host.os.getuid", return_value=0):
            h = host.Host(d)
            h.refresh_kvm_access = Mock()
            with self.assertRaisesRegex(RuntimeError, "unprivileged runner"):
                h.preflight()
            h.refresh_kvm_access.assert_not_called()

    def test_missing_kvm_is_failure(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with patch("haos.host.platform.machine", return_value="x86_64"), \
                    patch.object(host.Host, "refresh_kvm_access"), \
                    patch("haos.host.os.getuid", return_value=1001), \
                    patch("builtins.open", side_effect=PermissionError), \
                    self.assertRaises(PermissionError):
                host.Host(d).preflight()

    def test_kvm_create_vm_required_before_physical_disk_check(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with patch("haos.host.platform.machine", return_value="x86_64"), \
                    patch.object(host.Host, "refresh_kvm_access") as refresh, \
                    patch("haos.host.os.getuid", return_value=1001), \
                    patch("builtins.open", mock_open()), \
                    patch("haos.host.fcntl.ioctl", side_effect=[12, 999]) as ioctl, \
                    patch("haos.host.os.close") as close, \
                    patch("haos.host.shutil.disk_usage", return_value=SimpleNamespace(free=11 * host.GIB)), \
                    self.assertRaisesRegex(RuntimeError, "12 GiB"):
                host.Host(d).preflight()
            self.assertEqual([call.args[1] for call in ioctl.call_args_list], [0xAE00, 0xAE01])
            close.assert_called_once_with(999)
            refresh.assert_called_once_with("preflight")

    def test_create_vm_ioctl_failure_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with patch("haos.host.platform.machine", return_value="x86_64"), \
                    patch.object(host.Host, "refresh_kvm_access"), \
                    patch("haos.host.os.getuid", return_value=1001), \
                    patch("builtins.open", mock_open()), \
                    patch("haos.host.fcntl.ioctl", side_effect=[12, OSError("KVM unavailable")]), \
                    self.assertRaises(OSError):
                host.Host(d).preflight()

    def test_cleanup_refuses_unowned_registry(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.registry_launch_attempted = True
            h.run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"another-owner\n"))
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                h.cleanup()
            self.assertEqual(h.run.call_count, 1)
            self.assertFalse(h.registry_progress["cleanup"]["ownership_match"])
            self.assertEqual(h.registry_progress["cleanup"]["result"], "failure")

    def test_cleanup_finds_owned_container_after_launch_timeout_or_error(self):
        for timed_out in (True, False):
            with self.subTest(timed_out=timed_out), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                ok = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
                failure = host.subprocess.TimeoutExpired(["private-command"], 180) if timed_out else (
                    SimpleNamespace(returncode=125, stdout=b"", stderr=b"private-error"))
                h.run = Mock(side_effect=[ok, failure])
                with self.assertRaises((host.subprocess.TimeoutExpired, RuntimeError)):
                    h.registry()
                self.assertTrue(h.registry_launch_attempted)
                self.assertIsNone(h.registry_created)
                self.assertIsNone(h.registry_progress["container_created"])
                h.run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=h.owner.encode()), ok])
                h.cleanup()
                commands = [call.args[0] for call in h.run.call_args_list]
                self.assertEqual(commands[0][:3], ["docker", "container", "inspect"])
                self.assertEqual(commands[0][-1], h.owner)
                self.assertEqual(commands[1], ["docker", "rm", "-f", "-v", h.owner])
                self.assertTrue(h.registry_progress["container_created"])
                self.assertEqual(h.registry_progress["cleanup"]["result"], "removed")
                self.assertNotIn("private-", json.dumps(h.registry_progress))

    def test_cleanup_requires_confirmed_registry_absence(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.registry_launch_attempted = True
            h.registry_created = None
            h.run = Mock(side_effect=[SimpleNamespace(returncode=1, stdout=b"", stderr=b"not found"),
                                     SimpleNamespace(returncode=0, stdout=b"", stderr=b"")])
            h.cleanup()
            self.assertEqual(h.run.call_count, 2)
            self.assertEqual(h.run.call_args.args[0], ["docker", "container", "ls", "--all", "--filter",
                             "name=^/" + h.owner + "$", "--format", "{{.Names}}"])
            self.assertEqual(h.registry_progress["cleanup"]["result"], "absent")
            self.assertFalse(h.registry_progress["container_created"])

    def test_cleanup_inspect_failure_is_not_absence(self):
        for listing_exit, listing_output in ((1, b""), (0, b"present-container")):
            with self.subTest(listing_exit=listing_exit), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.registry_launch_attempted = True
                h.run = Mock(side_effect=[SimpleNamespace(returncode=1, stdout=b"", stderr=b"private-error"),
                    SimpleNamespace(returncode=listing_exit, stdout=listing_output, stderr=b"private-error")])
                with self.assertRaises(RuntimeError):
                    h.cleanup()
                self.assertEqual(h.run.call_count, 2)
                self.assertEqual(h.registry_progress["cleanup"]["result"], "failure")
                self.assertNotIn("private-error", json.dumps(h.registry_progress))

    def test_cleanup_registry_inspect_timeout_is_failure(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.registry_launch_attempted = True
            h.run = Mock(side_effect=host.subprocess.TimeoutExpired(["private-command"], 5))
            with self.assertRaises(host.subprocess.TimeoutExpired):
                h.cleanup()
            self.assertEqual(h.run.call_count, 1)
            self.assertEqual(h.registry_progress["cleanup"]["exception"], "TimeoutExpired")
            self.assertEqual(h.registry_progress["cleanup"]["result"], "failure")

    def test_supervisor_secret_body_is_stdin_only(self):
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            h.ssh = Mock(return_value=SimpleNamespace(returncode=0, stdout=b'{"result":"ok","data":{}}\n200'))
            h.supervisor("POST", "/addons/local_woow-omnigent/options", {"password": "synthetic-secret"})
            call = h.ssh.call_args
            self.assertNotIn("synthetic-secret", call.args[0])
            self.assertIn(b"synthetic-secret", call.kwargs["data"])

    def test_install_config_is_discovered_in_current_supervisor_local_apps(self):
        # Supervisor 2026.11.0 config.APPS_LOCAL and StoreData.update use apps/local.
        for version in (host.BASELINE_VERSION, host.CANDIDATE_VERSION):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                local = root / "apps/local"
                local.mkdir(parents=True)
                h = host.Host(root)
                config = {"slug": "woow-omnigent", "version": version,
                          "image": "original-image", "options": {"fixture": "unchanged"}}
                original = copy.deepcopy(config)
                def ssh(command, **kwargs):
                    command = command.replace("/mnt/data/supervisor", str(root))
                    result = host.subprocess.run(["/bin/sh", "-c", command],
                        input=kwargs.get("data"), capture_output=True, timeout=5)
                    host.require(result.returncode == 0, "fixture write failed")
                    return result
                def supervisor(method, path, body=None):
                    if path == "/store/reload":
                        self.assertTrue((local / "woow-omnigent/config.yaml").is_file())
                        return {}
                    self.assertEqual((method, path), ("GET", "/store/addons/local_woow-omnigent"))
                    return {"slug": "local_woow-omnigent", "repository": "local", "version_latest": version}
                h.ssh, h.supervisor = Mock(side_effect=ssh), Mock(side_effect=supervisor)
                h.install_config(config)
                written = yaml.safe_load((local / "woow-omnigent/config.yaml").read_text())
                self.assertEqual(written, dict(original, image="127.0.0.1:15000/omnigent-acceptance"))
                self.assertEqual(config, original)
                self.assertEqual(h.supervisor.call_count, 2)
                self.assertEqual(h.install_progress["stage"], "catalog_verified")
                self.assertFalse((root / "addons").exists())

    def test_install_config_requires_existing_root_and_exact_catalog_entry(self):
        config = {"slug": "woow-omnigent", "version": host.BASELINE_VERSION}
        with tempfile.TemporaryDirectory() as d:
            h = host.Host(d)
            def ssh(command, **kwargs):
                result = host.subprocess.run(["/bin/sh", "-c", command.replace(
                    "/mnt/data/supervisor", d)], input=kwargs.get("data"), capture_output=True, timeout=5)
                host.require(result.returncode == 0, "missing local root")
            h.ssh, h.supervisor = ssh, Mock()
            with self.assertRaises(RuntimeError):
                h.install_config(config)
            h.supervisor.assert_not_called()
            self.assertFalse((Path(d) / "apps").exists())
        entry = {"slug": "local_woow-omnigent", "repository": "local", "version_latest": host.BASELINE_VERSION}
        for field in entry:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.ssh = Mock()
                h.supervisor = Mock(side_effect=[{}, dict(entry, **{field: "wrong"})])
                with self.assertRaisesRegex(RuntimeError, "catalog"):
                    h.install_config(config)
                self.assertEqual(h.install_progress["stage"], "catalog_lookup")

    def test_supervisor_operations_record_only_fixed_status_and_error_codes(self):
        cases = [
            (200, {"result": "ok", "data": {}}, 0, "none"),
            (404, {"result": "error", "error_key": "store_app_not_found_error"}, 0, "store_app_not_found_error"),
            (503, {"result": "error", "error_key": "system_not_ready_error"}, 0, "system_not_ready_error"),
            (403, {"result": "error", "error_key": "PRIVATE_ERROR"}, 0, "forbidden"),
            (400, {"result": "error", "message": "PRIVATE_ERROR"}, 0, "api_error"),
            (200, {"result": "PRIVATE_ERROR"}, 0, "invalid_result"),
            (0, {}, 7, "transport_error"),
        ]
        for status, response, code, expected in cases:
            with self.subTest(status=status, expected=expected), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                response["private"] = "PRIVATE_SECRET"
                raw = json.dumps(response).encode() + f"\n{status:03}".encode()
                h.ssh = Mock(return_value=SimpleNamespace(returncode=code, stdout=raw))
                if expected == "none":
                    h.supervisor("POST", "/store/addons/local_woow-omnigent/install", {})
                else:
                    with self.assertRaises(RuntimeError):
                        h.supervisor("POST", "/store/addons/local_woow-omnigent/install", {})
                progress = h.supervisor_progress
                self.assertEqual(progress["operation"], "store_install")
                self.assertEqual(progress["http_status"], status or None)
                self.assertEqual(progress["ssh_exit"], code)
                self.assertEqual(progress["error_code"], expected)
                self.assertNotIn("PRIVATE", json.dumps(progress))
                self.assertFalse(h.ssh.call_args.kwargs["check"])

    def test_supervisor_operation_timeout_and_non_json_do_not_leak_response(self):
        for timeout in (True, False):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                if timeout:
                    h.ssh = Mock(side_effect=host.subprocess.TimeoutExpired("PRIVATE_COMMAND", 30,
                        output=b"PRIVATE_OUTPUT", stderr=b"PRIVATE_ERROR"))
                else:
                    h.ssh = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"PRIVATE_BODY\n500"))
                with self.assertRaises((RuntimeError, host.subprocess.TimeoutExpired)):
                    h.supervisor("GET", "/backups/private_slug/info", timeout=30)
                self.assertEqual(h.supervisor_progress["operation"], "backup_info")
                self.assertEqual(h.supervisor_progress["error_code"], "timeout" if timeout else "invalid_json")
                self.assertNotIn("private", json.dumps(h.supervisor_progress).lower())

    def test_supervisor_operation_bounds_metadata_and_unknown_operation_labels(self):
        for raw, code in ((b'{"result":"ok"}', "invalid_http_status"),
                          (b"x" * (1024 * 1024 + 1) + b"\n200", "response_too_large"),
                          (b"[]\n200", "invalid_json")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as d:
                h = host.Host(d)
                h.ssh = Mock(return_value=SimpleNamespace(returncode=0, stdout=raw))
                with self.assertRaises(RuntimeError):
                    h.supervisor("GET", "/private_path")
                self.assertEqual(h.supervisor_progress["operation"], "other")
                self.assertEqual(h.supervisor_progress["error_code"], code)
                self.assertNotIn("private", json.dumps(h.supervisor_progress).lower())

    def test_supervisor_path_injection_refused(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(RuntimeError):
            host.Host(d).supervisor("GET", "/info; echo unexpected")


class AcceptanceTests(unittest.TestCase):
    def test_tls_method_probe_streams_and_closes_without_reading_sse_body(self):
        class OpenStream(httpx.SyncByteStream):
            closed = False
            def __iter__(self):
                raise AssertionError("must not wait for the end of an SSE stream")
            def close(self):
                self.closed = True
        stream, seen = OpenStream(), []
        def handle(request):
            seen.append((request.method, request.headers.get("cookie")))
            if request.method == "GET":
                return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"}, stream=stream)
            self.assertTrue(stream.closed)
            return httpx.Response(405)
        suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
        suite.evidence, suite.ssl_context = {}, True
        profile = {"token": "SYNTHETIC_METHOD_TEST",
                   "connection_url": acceptance.PUBLIC_BASE + "/mcp/private_SYNTHETIC_METHOD_TEST"}
        client = httpx.Client(transport=httpx.MockTransport(handle))
        with patch("haos.acceptance.httpx.Client", return_value=client):
            suite.tls_methods(profile)
        self.assertEqual(seen, [("GET", None), ("DELETE", None)])
        self.assertTrue(stream.closed)
        self.assertEqual(suite.evidence["tls_methods"], {
            "GET": {"status": 200, "sse": True, "closed": True},
            "DELETE": {"status": 405, "sse": False, "closed": True}})
        self.assertNotIn("SYNTHETIC", json.dumps(suite.evidence))

    def test_tls_method_probe_rejects_wrong_status_or_media_type(self):
        for get_status, content_type, delete_status in ((200, "text/html", 405),
                (405, "application/json", 405), (401, "application/json", 405),
                (200, "text/event-stream", 200)):
            with self.subTest(get_status=get_status, content_type=content_type, delete_status=delete_status):
                suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                suite.evidence, suite.ssl_context = {}, True
                def handle(request):
                    return httpx.Response(get_status if request.method == "GET" else delete_status,
                        headers={"content-type": content_type})
                client = httpx.Client(transport=httpx.MockTransport(handle))
                with patch("haos.acceptance.httpx.Client", return_value=client), self.assertRaises(RuntimeError):
                    suite.tls_methods({"token": "SYNTHETIC_METHOD_TEST",
                        "connection_url": acceptance.PUBLIC_BASE + "/mcp/private_SYNTHETIC_METHOD_TEST"})
                last = "GET" if get_status != 200 or content_type != "text/event-stream" else "DELETE"
                self.assertTrue(suite.evidence["tls_methods"][last]["closed"])

    def test_tls_diagnostics_never_include_private_rpc_or_request_values(self):
        for rpc in (True, False):
            for error in (httpx.ReadTimeout("PRIVATE_ERROR"), httpx.ConnectError("PRIVATE_ERROR")):
                with self.subTest(rpc=rpc, error=type(error).__name__):
                    suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                    suite.evidence, suite.ssl_context = {}, True
                    profile = {"token": "PRIVATE_TOKEN",
                               "connection_url": acceptance.PUBLIC_BASE + "/mcp/private_PRIVATE_TOKEN"}
                    def handle(request):
                        raise error
                    client = httpx.Client(transport=httpx.MockTransport(handle))
                    with patch("haos.acceptance.httpx.Client", return_value=client), self.assertRaises(httpx.HTTPError):
                        if rpc:
                            suite.tls_rpc(profile, "PRIVATE_METHOD", {"PRIVATE_PARAM": "PRIVATE_VALUE"})
                        else:
                            suite.tls_methods(profile)
                    self.assertNotIn("PRIVATE", json.dumps(suite.evidence))
                    progress = suite.evidence["tls_rpc"] if rpc else suite.evidence["tls_methods"]["GET"]
                    self.assertEqual(progress["error"], "timeout" if isinstance(error, httpx.TimeoutException) else "transport_error")
                    self.assertIsNone(progress["status"])
                    if rpc:
                        self.assertEqual(progress["method"], "other")
                    else:
                        self.assertFalse(progress["closed"])

    def test_migration_rule_follows_candidate_and_baseline_contents(self):
        base = migration_fixture({"a_base.py": "1", "b_head.py": "2"}, ["b_head"])
        same = migration_fixture({"a_base.py": "1", "b_head.py": "2"}, ["b_head"])
        new = migration_fixture({"a_base.py": "1", "b_head.py": "2", "c_new.py": "3"}, ["c_new"])
        # merge-only revision 也是新 migration：檔案集合變大就要前進。
        merge = migration_fixture({"a_base.py": "1", "b_head.py": "2", "m_merge.py": "4"}, ["m_merge"])
        missing = migration_fixture({"b_head.py": "2", "c_new.py": "3"}, ["c_new"])
        changed = migration_fixture({"a_base.py": "X", "b_head.py": "2", "c_new.py": "3"}, ["c_new"])
        cases = (
            ("new migration, head advanced", new, "c_new", "new"),
            ("merge-only migration, head advanced", merge, "m_merge", "new"),
            ("no new migration, head unchanged", same, "b_head", "none"),
            ("new migration, head kept", new, "b_head", "did not advance"),
            ("new migration, head elsewhere", new, "a_base", "did not advance"),
            ("merge-only migration, head kept", merge, "b_head", "did not advance"),
            ("no new migration, head changed", same, "c_new", "changed without a new migration"),
            ("no new migration, head went back", same, "a_base", "changed without a new migration"),
            ("baseline migration missing", missing, "c_new", "baseline migration"),
            ("baseline migration changed", changed, "c_new", "baseline migration"),
        )
        for name, candidate, db_head, expected in cases:
            with self.subTest(name):
                if expected in ("new", "none"):
                    self.assertEqual(acceptance.migration_rule(base, candidate, db_head, "b_head"), expected)
                else:
                    with self.assertRaisesRegex(RuntimeError, expected):
                        acceptance.migration_rule(base, candidate, db_head, "b_head")

    def test_migration_rule_rejects_ambiguous_script_heads(self):
        base = migration_fixture({"a.py": "1"}, ["a"])
        two = migration_fixture({"a.py": "1", "b.py": "2", "c.py": "3"}, ["b", "c"])
        with self.assertRaisesRegex(RuntimeError, "single migration head"):
            acceptance.migration_rule(base, two, "b", "a")

    def test_migration_listing_parses_and_validates_container_output(self):
        good = migration_fixture({"a_base.py": "1"}, ["a_base"])
        suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
        suite.container, suite.host = "app_local_woow-omnigent", Mock()
        suite.host.ssh.return_value.stdout = json.dumps(good).encode()
        self.assertEqual(suite.migrations(), good)
        command = suite.host.ssh.call_args.args[0]
        self.assertTrue(command.startswith("docker exec app_local_woow-omnigent python3 -c "))
        self.assertIn("get_heads", command)
        self.assertIn("versions", command)
        for bad in ({"files": {}, "heads": ["a"]}, {"files": {"../x.py": "0" * 64}, "heads": ["x"]},
                    {"files": {"a.py": "short"}, "heads": ["a"]}, {"files": {"a.py": "0" * 64}, "heads": []},
                    {"files": {"a.py": "0" * 64}, "heads": ["bad head"]}, ["not", "an", "object"]):
            with self.subTest(bad=bad):
                suite.host.ssh.return_value.stdout = json.dumps(bad).encode()
                with self.assertRaisesRegex(RuntimeError, "migration listing"):
                    suite.migrations()

    def install_fixture(self, d, *, baseline, head, listing, baseline_listing=None):
        version = host.BASELINE_VERSION if baseline else host.CANDIDATE_VERSION
        config, config_id, manifest, pushed_id = registry_fixture(version)
        suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
        h = suite.host = host.Host(d)
        h.image_identities[config_id] = provenance.registry_identity(manifest, pushed_id, config, config_id)
        suite.old_image = suite.new_image = {"Id": config_id}
        suite.old_config = {"version": host.BASELINE_VERSION, "options": {}}
        suite.config = {"version": host.CANDIDATE_VERSION, "options": {}}
        suite.username, suite.password = "fixture-user", "fixture-password"
        suite.pin, suite.evidence = {"fixture": "pin"}, {}
        if baseline_listing is not None:
            suite.baseline_migrations = baseline_listing
        suite.wait_addon = Mock()
        h.install_config, h.supervisor = Mock(), Mock()
        def ssh(command, **kwargs):
            if command.startswith("docker inspect app_"):
                value = json.dumps([{"Image": pushed_id, "Name": "/app_local_woow-omnigent"}])
            elif " cat /usr/share/omnigent/artifact-pin.json" in command:
                value = json.dumps(suite.pin)
            elif "SHOW server_version" in command:
                value = "16.10"
            elif "SELECT version_num" in command:
                value = head
            elif "get_heads" in command:
                value = json.dumps(listing)
            else:
                value = ""
            return SimpleNamespace(stdout=value.encode())
        h.ssh = Mock(side_effect=ssh)
        h.verify_guest_image = Mock(wraps=h.verify_guest_image)
        return suite, h, config_id

    def test_install_uses_bound_guest_manifest_for_baseline_and_candidate(self):
        base = migration_fixture({"a.py": "1", host.BASELINE_MIGRATION + "_x.py": "2"}, [host.BASELINE_MIGRATION])
        new = migration_fixture({"a.py": "1", host.BASELINE_MIGRATION + "_x.py": "2", "n_new.py": "3"}, ["n_new"])
        for baseline, head, listing in ((True, host.BASELINE_MIGRATION, base), (False, "n_new", new),
                                        (False, host.BASELINE_MIGRATION, base)):
            with self.subTest(baseline=baseline, head=head), tempfile.TemporaryDirectory() as d:
                suite, h, config_id = self.install_fixture(d, baseline=baseline, head=head, listing=listing,
                                                           baseline_listing=None if baseline else base)
                suite.install(baseline=baseline)
                h.verify_guest_image.assert_called_once_with(config_id)
                self.assertEqual(suite.container, "app_local_woow-omnigent")
                # baseline 也有 MCP，seed hook 檢查的公開網址兩版都要設。
                options = next(c.args[2] for c in h.supervisor.call_args_list
                               if c.args[1].endswith("/options"))["options"]
                self.assertEqual(options["mcp_public_base_url"], acceptance.PUBLIC_BASE)
                if baseline:
                    self.assertEqual(suite.baseline_migrations, base)
                    self.assertEqual(suite.evidence["baseline_database"],
                                     {"migration_head": head, "migration_files": 2})
                else:
                    self.assertEqual(suite.evidence["guest_database"], {
                        "postgres": "16.10", "migration_head": head,
                        "new_migrations": "new" if listing is new else "none",
                        "migration_files": len(listing["files"])})

    def test_install_applies_migration_rule_to_collected_contents(self):
        base = migration_fixture({"a.py": "1", host.BASELINE_MIGRATION + "_x.py": "2"}, [host.BASELINE_MIGRATION])
        new = migration_fixture({"a.py": "1", host.BASELINE_MIGRATION + "_x.py": "2", "n_new.py": "3"}, ["n_new"])
        for head, listing, message in ((host.BASELINE_MIGRATION, new, "did not advance"),
                                       ("n_new", base, "changed without a new migration")):
            with self.subTest(head=head), tempfile.TemporaryDirectory() as d:
                suite, h, _ = self.install_fixture(d, baseline=False, head=head, listing=listing,
                                                   baseline_listing=base)
                with self.assertRaisesRegex(RuntimeError, message):
                    suite.install(baseline=False)
                self.assertNotIn("guest_database", suite.evidence)

    def test_baseline_install_cross_checks_pinned_baseline_head(self):
        base = migration_fixture({"a.py": "1", host.BASELINE_MIGRATION + "_x.py": "2"}, [host.BASELINE_MIGRATION])
        other = migration_fixture({"a.py": "1"}, ["other_head"])
        for head, listing in (("other_head", base), (host.BASELINE_MIGRATION, other)):
            with self.subTest(head=head), tempfile.TemporaryDirectory() as d:
                suite, h, _ = self.install_fixture(d, baseline=True, head=head, listing=listing)
                with self.assertRaisesRegex(RuntimeError, "pinned baseline migration head"):
                    suite.install(baseline=True)

    def test_baseline_rollback_requires_baseline_migration_head(self):
        for head, restored in ((host.BASELINE_MIGRATION, True), ("candidate_head", False)):
            with self.subTest(head=head):
                suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                suite.host = Mock()
                suite.host.verify_guest_image.return_value = "app_local_woow-omnigent"
                suite.host.ssh.return_value.stdout = head.encode()
                suite.old_image, suite.new_image = {"Id": "old"}, {"Id": "new"}
                suite.baseline_backup, suite.evidence = "abcd", {}
                suite.restore = Mock()
                if restored:
                    suite.baseline_rollback()
                    self.assertEqual(suite.evidence["rollback_database"],
                                     {"migration_head": head, "image_id": "old"})
                else:
                    with self.assertRaisesRegex(RuntimeError, "candidate database"):
                        suite.baseline_rollback()
                suite.restore.assert_called_once_with("abcd", host.BASELINE_VERSION, "old")
                suite.host.verify_guest_image.assert_called_once_with("old")
                self.assertIn("SELECT version_num FROM alembic_version", suite.host.ssh.call_args.args[0])

    def test_baseline_rollback_requires_baseline_image(self):
        # 沒有新 migration 時 head 分不出兩版，要靠執行中的 image 分辨。
        for name in ("running image is not the baseline", "baseline and candidate images are the same"):
            with self.subTest(name):
                suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                suite.host = Mock()
                suite.host.ssh.return_value.stdout = host.BASELINE_MIGRATION.encode()
                suite.old_image, suite.baseline_backup, suite.evidence = {"Id": "old"}, "abcd", {}
                suite.restore = Mock()
                if name.startswith("running"):
                    suite.new_image = {"Id": "new"}
                    suite.host.verify_guest_image.side_effect = RuntimeError(
                        "Supervisor is not running the verified image")
                    message = "not running the verified image"
                else:
                    suite.new_image = {"Id": "old"}
                    suite.host.verify_guest_image.return_value = "app_local_woow-omnigent"
                    message = "cannot tell the baseline image from the candidate"
                with self.assertRaisesRegex(RuntimeError, message):
                    suite.baseline_rollback()
                self.assertNotIn("rollback_database", suite.evidence)

    def test_backup_restore_and_coldboot_use_bound_guest_manifest_for_both_versions(self):
        for version in (host.BASELINE_VERSION, host.CANDIDATE_VERSION):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as d:
                config, config_id, manifest, pushed_id = registry_fixture(version)
                suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                h = suite.host = host.Host(d)
                h.image_identities[config_id] = provenance.registry_identity(manifest, pushed_id, config, config_id)
                suite.old_image = suite.new_image = {"Id": config_id}
                suite.config = {"version": version}
                suite.wait_addon = Mock()
                suite.data_preserved = Mock()
                suite.api = Mock()
                suite.hooks = Mock()
                suite.state = {}
                h.supervisor = Mock(side_effect=[{"slug": "abcd"}, {"addons": [{"slug": acceptance.ADDON}]}, {}])
                starts, boots = iter((b"before", b"after")), iter((b"kernel-before", b"kernel-after"))
                def ssh(command, **kwargs):
                    if "StartedAt" in command:
                        data = next(starts)
                    elif "boot_id" in command:
                        data = next(boots)
                    else:
                        data = json.dumps([{"Image": pushed_id, "Name": "/app_local_woow-omnigent"}]).encode()
                    return SimpleNamespace(stdout=data)
                h.ssh = Mock(side_effect=ssh)
                h.verify_guest_image = Mock(wraps=h.verify_guest_image)
                self.assertEqual(suite.backup("baseline" if version == host.BASELINE_VERSION else "candidate"), "abcd")
                self.assertEqual(h.verify_guest_image.call_count, 2)
                suite.restore("abcd", version, config_id)
                h.cold_shutdown, h.boot, h.registry_tunnel = Mock(), Mock(), Mock()
                suite.cold_boot()
                self.assertEqual(h.verify_guest_image.call_count, 4)
                self.assertTrue(all(c.args == (config_id,) for c in h.verify_guest_image.call_args_list))

    def test_registry_final_identity_guards_remain_enforced_and_identified(self):
        for guard, new_id, revision in (("candidate_producer_image_id", "wrong", "source"),
                                         ("candidate_core_source", "expected", "wrong"),
                                         ("verified", "expected", "source"),
                                         ("verified", "linked-config", "source")):
            with self.subTest(guard=guard):
                suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                suite.host = host.Host("/unused-fixture-path")
                suite.host.registry = Mock()
                suite.host.publish_local = Mock(side_effect=[{}, {
                    "Id": new_id, "Config": {"Labels": {"org.opencontainers.image.revision": revision}}}])
                suite.config = {"version": host.CANDIDATE_VERSION}
                suite.producer = {"image_id": "expected", "checkout_commit": HEAD, "addon_tree": TREE}
                suite.baseline_identity = {"config_digest": "baseline-config", "producer_image_id": "baseline-id"}
                suite.candidate_identity = {"config_digest": "linked-config", "producer_image_id": "expected",
                                            "producer_id_kind": "manifest"}
                suite.pin = {"sourceCommit": "source", "wheelSha256": "wheel"}
                suite.evidence = {"candidate": {}}
                if guard == "verified":
                    suite.registry()
                else:
                    with self.assertRaises(RuntimeError):
                        suite.registry()
                    self.assertEqual(suite.evidence["candidate"], {})
                self.assertEqual(suite.host.registry_progress["stage"], guard)

    def test_registry_failure_reaches_receipt_without_raw_command_data(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {
                "RUNNER_TEMP": d, "HAOS_REPORT_DIR": d}):
            suite = acceptance.Acceptance(Path(d))
            suite.phase = "private image registry and image identities"
            suite.run = suite.host.registry
            suite.host.cleanup = Mock()
            suite.host.run = Mock(return_value=SimpleNamespace(
                returncode=125, stdout=b"synthetic-secret", stderr=b"denied /mcp/private_token"))
            with patch("haos.acceptance.Acceptance", return_value=suite), \
                    patch("haos.acceptance.signal.signal"), patch("haos.acceptance.os.umask"), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(acceptance.main(), 1)
            text = (Path(d) / "haos-acceptance.json").read_text()
            report = json.loads(text)
            self.assertFalse(report["passed"])
            self.assertEqual(report["evidence"]["registry_progress"]["stage"], "registry_pull")
            for secret in ("synthetic-secret", "private_token"):
                self.assertNotIn(secret, text)

    def test_cold_backup_requires_observed_container_restart(self):
        suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
        suite.host = Mock()
        suite.old_image = {"Id": "old"}
        suite.new_image = {"Id": "new"}
        suite.config = {"version": host.CANDIDATE_VERSION}
        suite.wait_addon = Mock()
        suite.host.verify_guest_image.return_value = "app_local_woow-omnigent"
        suite.host.supervisor.side_effect = [
            {"slug": "abcd"}, {"addons": [{"slug": acceptance.ADDON}]}]
        suite.host.ssh.return_value.stdout = b"same-start-time"
        with self.assertRaisesRegex(RuntimeError, "did not restart"):
            suite.backup("candidate")

    def test_failure_report_does_not_emit_exception_body(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Mock()
            fake.phase = "trusted localhost HTTPS MCP proxy"
            fake.checks, fake.evidence = [], {}
            fake.run.side_effect = RuntimeError("password=secret /mcp/private_omcp_SYNTHETIC")
            output = io.StringIO()
            with patch.dict(os.environ, {"RUNNER_TEMP": d, "HAOS_REPORT_DIR": d}), \
                    patch("haos.acceptance.Acceptance", return_value=fake), \
                    patch("haos.acceptance.signal.signal"), patch("haos.acceptance.os.umask"), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(acceptance.main(), 1)
            text = (Path(d) / "haos-acceptance.json").read_text()
            self.assertFalse(json.loads(text)["passed"])
            for secret in ("password=", "secret", "private_omcp_"):
                self.assertNotIn(secret, text + output.getvalue())
            fake.host.cleanup.assert_called_once()

    def test_workflow_permissions_head_checkout_and_only_safe_upload(self):
        path = Path(__file__).resolve().parents[2] / ".github/workflows/test-haos-addon.yml"
        workflow = yaml.safe_load(path.read_text())
        self.assertEqual(workflow.get("on", workflow.get(True)), {"pull_request": None})
        self.assertEqual(workflow["permissions"], {"contents": "read", "actions": "read"})
        job = workflow["jobs"]["haos"]
        self.assertEqual(job["runs-on"], "ubuntu-22.04")
        self.assertEqual(job["timeout-minutes"], 60)
        steps = job["steps"]
        self.assertEqual(steps[0]["with"]["ref"], "$" + "{{ github.event.pull_request.head.sha }}")
        upload = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(upload), 1)
        self.assertEqual(upload[0]["with"]["path"], "$" + "{{ runner.temp }}/haos-report/haos-acceptance.json")
        # The harness owns the original ACL snapshot and lifecycle; setup must
        # not grant access before it can save the runner's unmodified ACL.
        self.assertNotIn("setfacl", path.read_text())

    def test_workflow_report_directory_uses_runner_only_in_step_context(self):
        path = Path(__file__).resolve().parents[2] / ".github/workflows/test-haos-addon.yml"
        job = yaml.safe_load(path.read_text())["jobs"]["haos"]
        # GitHub evaluates job env before a runner exists. runner is available
        # in step env, as documented in the Actions context-availability table.
        self.assertNotIn("HAOS_REPORT_DIR", job["env"])
        self.assertTrue(all("runner." not in str(value) for value in job["env"].values()))
        boot = next(step for step in job["steps"] if "python -m haos.acceptance" in step.get("run", ""))
        self.assertEqual(boot["env"]["HAOS_REPORT_DIR"], "$" + "{{ runner.temp }}/haos-report")


class BrowserTests(unittest.TestCase):
    def invoke(self, progress):
        return browser.ingress("http://127.0.0.1:18123", "owner-fixture", "HA_PASSWORD_PRIVATE",
                               "admin-fixture", "ADDON_PASSWORD_PRIVATE",
                               {"username": "member-fixture", "password": "MEMBER_PASSWORD_PRIVATE"},
                               "https://localhost:18443/omnigent", progress=progress)

    def test_browser_boundaries_and_owned_cleanup(self):
        from playwright.sync_api import Error
        for target, stage, cleanup in [
            ("launch", "browser_launch", {"context": None, "browser": None, "driver": True}),
            ("context", "browser_context", {"context": None, "browser": True, "driver": True}),
            ("page", "new_page", {"context": True, "browser": True, "driver": True}),
            ("navigation", "ha_navigation", {"context": True, "browser": True, "driver": True}),
            ("username", "ha_username", {"context": True, "browser": True, "driver": True}),
        ]:
            with self.subTest(stage=stage), patch("playwright.sync_api.sync_playwright") as factory:
                driver = factory.return_value.start.return_value
                chromium = driver.chromium.launch.return_value
                context = chromium.new_context.return_value
                page = context.new_page.return_value
                method = {"launch": driver.chromium.launch, "context": chromium.new_context,
                          "page": context.new_page, "navigation": page.goto,
                          "username": page.locator.return_value.fill}[target]
                failure = Error("private_oTOKEN HA_PASSWORD_PRIVATE https://private.invalid/secret")
                method.side_effect = failure
                progress = {}
                with self.assertRaises(Error) as caught:
                    self.invoke(progress)
                self.assertIs(caught.exception, failure)
                self.assertEqual(progress["stage"], stage)
                self.assertEqual(progress["error"], "playwright_error")
                self.assertEqual(progress["cleanup"], cleanup)
                self.assertNotIn("PRIVATE", json.dumps(progress))
                self.assertNotIn("private.invalid", json.dumps(progress))
                driver.stop.assert_called_once()

    def test_browser_success_and_cleanup_failure_are_distinct(self):
        from playwright.sync_api import Error
        for cleanup_fails in (False, True):
            with self.subTest(cleanup_fails=cleanup_fails), patch("playwright.sync_api.sync_playwright") as factory, \
                    patch("playwright.sync_api.expect"):
                driver = factory.return_value.start.return_value
                chromium = driver.chromium.launch.return_value
                context = chromium.new_context.return_value
                page = context.new_page.return_value
                frame = Mock(url="http://127.0.0.1:18123/api/hassio_ingress/PRIVATE/")
                page.expect_event = MagicMock()
                page.expect_event.return_value.__enter__.return_value.value = frame
                created = {"token": "PRIVATE", "connection_url": "https://localhost:18443/omnigent/mcp/private_PRIVATE"}
                page.expect_response = MagicMock()
                page.expect_response.return_value.__enter__.return_value.value.json.return_value = created
                frame.evaluate.return_value = {"secure_context": True, "write_policy": True}
                page.evaluate.return_value = "matched"
                frame.locator.return_value.inner_text.return_value = "fixture"
                context.cookies.return_value = []
                if cleanup_fails:
                    context.close.side_effect = Error("PRIVATE cleanup error")
                progress = {}
                if cleanup_fails:
                    with self.assertRaisesRegex(RuntimeError, "owned browser cleanup failed"):
                        self.invoke(progress)
                    self.assertEqual(progress["stage"], "browser_cleanup")
                    self.assertEqual(progress["error"], "cleanup_failed")
                else:
                    self.assertEqual(self.invoke(progress), created)
                    self.assertEqual(progress["stage"], "complete")
                    self.assertIsNone(progress["error"])
                self.assertEqual(progress["cleanup"], {"context": not cleanup_fails,
                                                       "browser": True, "driver": True})
                chromium.close.assert_called_once()
                driver.stop.assert_called_once()
                self.assertNotIn("PRIVATE", json.dumps(progress))

    def test_browser_error_codes_are_fixed_and_bounded(self):
        from playwright.sync_api import Error, TimeoutError
        for error, code in [
            (Error("Locator.fill: strict mode violation: private_oSECRET"), "ambiguous_locator"),
            (Error("Page.goto: net::ERR_CONNECTION_REFUSED at private_oSECRET"), "connection_refused"),
            (Error("Page.goto: net::ERR_NAME_NOT_RESOLVED at private_oSECRET"), "name_not_resolved"),
            (Error("Page.goto: net::ERR_ABORTED at private_oSECRET"), "navigation_aborted"),
            (Error("Navigation interrupted by another navigation private_oSECRET"), "navigation_interrupted"),
            (Error("Executable doesn't exist at /private_oSECRET"), "browser_executable_missing"),
            (Error("Host system is missing dependencies private_oSECRET"), "browser_dependencies_missing"),
            (Error("Target page, context or browser has been closed private_oSECRET"), "browser_closed"),
            (TimeoutError("private_oSECRET"), "timeout"),
            (AssertionError("private_oSECRET"), "assertion_failed"),
            (ValueError("private_oSECRET"), "response_shape"),
            (RuntimeError("private_oSECRET"), "requirement_failed"),
            (OSError("private_oSECRET"), "other"),
            (Error("x" * 4096 + "strict mode violation"), "playwright_error"),
        ]:
            with self.subTest(code=code):
                self.assertEqual(browser.error_code(error), code)

    def test_browser_cleanup_preserves_original_failure(self):
        from playwright.sync_api import Error
        with patch("playwright.sync_api.sync_playwright") as factory:
            driver = factory.return_value.start.return_value
            chromium = driver.chromium.launch.return_value
            context = chromium.new_context.return_value
            failure = Error("net::ERR_CONNECTION_REFUSED private_oSECRET")
            context.new_page.return_value.goto.side_effect = failure
            context.close.side_effect = Error("cleanup private_oSECRET")
            progress = {}
            with self.assertRaises(Error) as caught:
                self.invoke(progress)
            self.assertIs(caught.exception, failure)
            self.assertEqual(progress["stage"], "ha_navigation")
            self.assertEqual(progress["error"], "connection_refused")
            self.assertEqual(progress["cleanup"], {"context": False, "browser": True, "driver": True})
            chromium.close.assert_called_once()
            driver.stop.assert_called_once()

    def test_browser_receipt_excludes_event_urls_and_error_text(self):
        from playwright.sync_api import Error
        with patch("playwright.sync_api.sync_playwright") as factory:
            page = factory.return_value.start.return_value.chromium.launch.return_value.new_context.return_value.new_page.return_value
            callbacks = {}
            page.on.side_effect = lambda name, callback: callbacks.update({name: callback})
            def navigate(*args, **kwargs):
                callbacks["pageerror"](Error("PASSWORD_PRIVATE"))
                callbacks["response"](SimpleNamespace(status=503,
                    url="http://127.0.0.1:18123/api/hassio_ingress/PRIVATE/assets/PRIVATE.js?token=PRIVATE",
                    request=SimpleNamespace(resource_type="script")))
                callbacks["response"](SimpleNamespace(status=401,
                    url="http://127.0.0.1:18123/api/hassio_ingress/PRIVATE/",
                    request=SimpleNamespace(resource_type="document")))
                raise Error("unknown PRIVATE browser failure")
            page.goto.side_effect = navigate
            progress = {}
            with self.assertRaises(Error):
                self.invoke(progress)
            self.assertEqual(progress["javascript_errors"], 1)
            self.assertEqual(progress["asset_errors"], 1)
            self.assertEqual(progress["document"], {"scope": "ingress", "http_status": 401,
                                                   "same_origin": True})
            self.assertNotIn("PRIVATE", json.dumps(progress))
            self.assertNotIn("127.0.0.1", json.dumps(progress))

    def test_real_logout_uses_account_page_and_retains_ingress(self):
        from playwright.sync_api import sync_playwright
        prefix = "/api/hassio_ingress/SYNTHETIC"
        state = {"posts": 0, "escape": False}
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def reply(self, status, body):
                self.send_response(status)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                if self.path == "/":
                    body = ('<iframe src="' + prefix + '/settings/mcp-server"></iframe>').encode()
                elif self.path == prefix + "/settings/mcp-server":
                    body = b"<h1>Create profile</h1>"
                elif self.path == prefix + "/settings/account":
                    login = "/login" if state["escape"] else prefix + "/login"
                    # Candidate AccountSection awaits its real logout request,
                    # then hard-navigates to the prefixed login route.
                    body = ('<h1>Account</h1><button onclick="void signOut()">Sign out</button>'
                            '<script>async function signOut(){await fetch('
                            + json.dumps(prefix + "/auth/logout") + ',{method:"POST"});location.href='
                            + json.dumps(login) + ';}</script>').encode()
                elif self.path in (prefix + "/login", "/login"):
                    body = b'<label>Password<input type="password"></label>'
                else:
                    return self.reply(404, b"")
                self.reply(200, body)
            def do_POST(self):
                if self.path != prefix + "/auth/logout":
                    return self.reply(404, b"")
                state["posts"] += 1
                self.reply(204, b"")
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as driver:
                chromium = driver.chromium.launch(headless=True, args=["--no-sandbox"])
                context = chromium.new_context()
                try:
                    for escape in (False, True):
                        with self.subTest(escape=escape):
                            state.update(posts=0, escape=escape)
                            page = context.new_page()
                            try:
                                base = "http://127.0.0.1:" + str(server.server_port)
                                page.goto(base + "/")
                                frame = page.frames[1]
                                frame.get_by_role("heading", name="Create profile", exact=True).wait_for()
                                self.assertEqual(frame.get_by_role("button", name="Sign out", exact=True).count(), 0)
                                progress = {}
                                if escape:
                                    with self.assertRaisesRegex(RuntimeError, "logout escaped Ingress"):
                                        browser.logout_ingress(frame, base + prefix, progress, timeout=2000)
                                else:
                                    browser.logout_ingress(frame, base + prefix, progress, timeout=2000)
                                    self.assertEqual(frame.url, base + prefix + "/login")
                                self.assertEqual(state["posts"], 1)
                                self.assertEqual(progress["stage"], "logout_login")
                                self.assertNotIn("SYNTHETIC", json.dumps(progress))
                            finally:
                                page.close()
                finally:
                    context.close()
                    chromium.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_real_clipboard_completion_and_permission_failure(self):
        from playwright.sync_api import sync_playwright
        canonical = "https://localhost/fixture/mcp/private_SYNTHETIC_CLIPBOARD"
        error_text = "Could not copy the URL. Select and copy it manually."
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def do_GET(self):
                mode = self.path.rsplit("/", 1)[-1]
                if self.path.startswith("/frame/"):
                    # Same async copy/caught error as the immutable candidate UI:
                    # no success toast/state. Only the fixture delays the write.
                    script = ""
                    if mode == "delayed":
                        script = ("const original=navigator.clipboard.writeText.bind(navigator.clipboard);"
                                  "navigator.clipboard.writeText=async value=>{"
                                  "await new Promise(r=>setTimeout(r,250));return original(value);};")
                    value = "WRONG_SYNTHETIC_CLIPBOARD" if mode == "wrong" else canonical
                    body = ('<div role="dialog"><button onclick="void copyLink()">Copy URL</button>'
                            '<p id="error"></p></div><script>' + script
                            + 'async function copyLink(){try{await navigator.clipboard.writeText('
                            + json.dumps(value) + ');}catch{document.querySelector("#error").textContent='
                            + json.dumps(error_text) + ';}}</script>').encode()
                else:
                    # Match HA's same-origin Ingress iframe: no allow or sandbox.
                    body = ('<iframe title="Omnigent" src="/frame/' + mode + '"></iframe>').encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                if mode == "denied":
                    self.send_header("Permissions-Policy", "clipboard-write=()")
                if mode == "read_denied":
                    self.send_header("Permissions-Policy", "clipboard-read=()")
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as driver:
                chromium = driver.chromium.launch(headless=True, args=["--no-sandbox"])
                context = chromium.new_context(permissions=["clipboard-read", "clipboard-write"])
                try:
                    for mode in ("delayed", "immediate", "wrong", "denied", "read_denied", "pending_read"):
                        with self.subTest(mode=mode):
                            page = context.new_page()
                            try:
                                base = "http://127.0.0.1:" + str(server.server_port)
                                page.goto(base + "/initial")
                                # Do not let an earlier successful copy satisfy a later case.
                                page.evaluate('navigator.clipboard.writeText("")')
                                page.goto(base + "/" + mode)
                                frame = page.frames[1]
                                frame.get_by_role("button", name="Copy URL").wait_for()
                                if mode == "pending_read":
                                    # Prove the deadline also covers an unresolved native-API boundary.
                                    page.evaluate("() => { navigator.clipboard.readText = () => new Promise(() => {}); }")
                                progress = {}
                                if mode in ("wrong", "pending_read"):
                                    with self.assertRaisesRegex(RuntimeError, "clipboard copy failed"):
                                        browser.copy_profile_url(page, frame, canonical, progress, timeout=500)
                                    self.assertEqual(progress["clipboard"]["result"], "timeout")
                                elif mode == "denied":
                                    with self.assertRaisesRegex(RuntimeError, "clipboard copy failed"):
                                        browser.copy_profile_url(page, frame, canonical, progress, timeout=2000)
                                    self.assertEqual(progress["clipboard"]["result"], "ui_error")
                                    self.assertFalse(progress["clipboard"]["write_policy"])
                                elif mode == "read_denied":
                                    with self.assertRaisesRegex(RuntimeError, "clipboard copy failed"):
                                        browser.copy_profile_url(page, frame, canonical, progress, timeout=2000)
                                    self.assertEqual(progress["clipboard"]["result"], "read_denied")
                                else:
                                    browser.copy_profile_url(page, frame, canonical, progress, timeout=2000)
                                    self.assertEqual(page.evaluate("navigator.clipboard.readText()"), canonical)
                                    self.assertEqual(progress["clipboard"]["result"], "matched")
                                    self.assertTrue(progress["clipboard"]["write_policy"])
                                self.assertNotIn("SYNTHETIC", json.dumps(progress))
                                self.assertEqual(progress["stage"], "profile_clipboard")
                            finally:
                                page.close()
                finally:
                    context.close()
                    chromium.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_real_browser_waits_for_ingress_navigation(self):
        from playwright.sync_api import sync_playwright, TimeoutError
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def do_GET(self):
                if self.path.startswith("/api/hassio_ingress/") or self.path == "/unrelated":
                    body = b"<h1>frame fixture</h1>"
                else:
                    delay = 250 if self.path == "/delayed" else 0
                    include_ingress = self.path != "/missing"
                    script = ("event.preventDefault();let other=document.createElement('iframe');"
                              "other.src='/unrelated';document.body.append(other);")
                    if include_ingress:
                        script += ("setTimeout(() => {let f=document.createElement('iframe');"
                                   "f.src='/api/hassio_ingress/SYNTHETIC/';document.body.append(f);},"
                                   + str(delay) + ");")
                    body = ('<ha-sidebar style="display:block"><a href="#" onclick="' + script
                            + '">Omnigent</a></ha-sidebar>').encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as driver:
                chromium = driver.chromium.launch(headless=True, args=["--no-sandbox"])
                context = chromium.new_context()
                try:
                    for path in ("/delayed", "/immediate", "/missing"):
                        with self.subTest(path=path):
                            page = context.new_page()
                            try:
                                page.goto("http://127.0.0.1:" + str(server.server_port) + path)
                                progress = {}
                                if path == "/missing":
                                    with self.assertRaises(TimeoutError):
                                        browser.open_ingress(page, page.locator("ha-sidebar"), progress, timeout=500)
                                else:
                                    frame = browser.open_ingress(page, page.locator("ha-sidebar"), progress, timeout=2000)
                                    self.assertIn("/api/hassio_ingress/", frame.url)
                                    self.assertEqual(frame.get_by_role("heading").inner_text(), "frame fixture")
                                self.assertEqual(progress["stage"], "ingress_frame")
                                self.assertNotIn("SYNTHETIC", json.dumps(progress))
                            finally:
                                page.close()
                finally:
                    context.close()
                    chromium.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_configured_ha_ports_support_discovery_and_real_browser(self):
        from playwright.sync_api import sync_playwright
        class Handler(BaseHTTPRequestHandler):
            # Keep responses alive until HTTPX/Chromium close their connections.
            # HTTP/1.0 server-first close leaves TIME_WAIT on the HA forward and
            # prevents the immediately following acceptance preflight from binding.
            protocol_version = "HTTP/1.1"
            def do_GET(self):
                body = b"[]" if self.path == "/api/onboarding" else b"<!doctype html><title>fixture</title>"
                self.send_response(200)
                self.send_header("Content-Type", "application/json" if self.path == "/api/onboarding" else "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        # Use the actual configured forwards, not an arbitrary free port: HTTPX
        # can reach ports Chromium rejects before any request leaves the browser.
        for port in host.HA_PORTS:
            with self.subTest(port=port):
                server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                    suite.evidence = {}
                    base = suite.find_ha()
                    self.assertEqual(base, "http://127.0.0.1:" + str(port))
                    self.assertEqual(suite.evidence["ha_core"], {"forwarded_port": port})
                    with sync_playwright() as driver:
                        chromium = driver.chromium.launch(headless=True, args=["--no-sandbox"])
                        context = chromium.new_context()
                        try:
                            response = context.new_page().goto(base + "/", wait_until="domcontentloaded", timeout=10000)
                            self.assertEqual(response.status, 200)
                        finally:
                            context.close()
                            chromium.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
                # The next CI step performs this exclusive bind. Fixture teardown
                # must leave the actual forwarded ports reusable immediately.
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", port))

    def test_real_browser_records_ambiguous_input_and_closes(self):
        from playwright.sync_api import Error
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'<input name="username"><input name="username" value="PRIVATE">'
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            progress = {}
            with self.assertRaises(Error):
                browser.ingress("http://127.0.0.1:" + str(server.server_port),
                                "fixture", "PRIVATE", "fixture", "PRIVATE", {}, "PRIVATE", progress=progress)
            self.assertEqual(progress["stage"], "ha_username")
            self.assertEqual(progress["error"], "ambiguous_locator")
            self.assertEqual(progress["document"], {"scope": "ha", "http_status": 200, "same_origin": True})
            self.assertEqual(progress["cleanup"], {"context": True, "browser": True, "driver": True})
            self.assertNotIn("PRIVATE", json.dumps(progress))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_real_browser_records_navigation_refusal_and_closes(self):
        from playwright.sync_api import Error
        # Bound, non-listening socket keeps the port owned throughout the probe.
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            progress = {}
            with self.assertRaises(Error):
                browser.ingress("http://127.0.0.1:" + str(reserved.getsockname()[1]),
                                "fixture", "PRIVATE", "fixture", "PRIVATE", {}, "PRIVATE", progress=progress)
            self.assertEqual(progress["stage"], "ha_navigation")
            self.assertEqual(progress["error"], "connection_refused")
            self.assertIsNone(progress["document"])
            self.assertEqual(progress["cleanup"], {"context": True, "browser": True, "driver": True})
            self.assertNotIn("PRIVATE", json.dumps(progress))


class RealTLSFixtureTests(unittest.TestCase):
    def test_actual_trusted_tls_prefix_cookie_isolation_and_log_hygiene(self):
        observed = []
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                observed.append((self.path, self.headers.get("Cookie"), payload))
                body = b'{"jsonrpc":"2.0","id":1,"result":{}}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                observed.append((self.path, self.headers.get("Cookie"), {"method": "GET"}))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.flush()
                # No Content-Length or EOF: the client must close the stream.

            def do_DELETE(self):
                observed.append((self.path, self.headers.get("Cookie"), {"method": "DELETE"}))
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        origin = "https://localhost:" + str(port)
        token = "omcp_SYNTHETIC_TLS_TEST"
        try:
            with tempfile.TemporaryDirectory() as d:
                suite = acceptance.Acceptance.__new__(acceptance.Acceptance)
                suite.private = Path(d)
                suite.host = host.Host(d)
                suite.evidence = {}
                try:
                    with patch("haos.acceptance.DIRECT", "http://127.0.0.1:" + str(server.server_port)), \
                            patch("haos.acceptance.PUBLIC_BASE", origin + "/omnigent"):
                        suite.tls()
                        profile = {"token": token, "connection_url": origin + "/omnigent/mcp/private_" + token}
                        status, result = suite.tls_rpc(profile, "initialize")
                        self.assertEqual(status, 200)
                        self.assertEqual(result["result"], {})
                        self.assertEqual(observed[0][:2], ("/mcp/private_" + token, None))
                        self.assertEqual(observed[0][2]["method"], "initialize")
                        suite.tls_methods(profile)
                        self.assertEqual([row[2]["method"] for row in observed], ["initialize", "GET", "DELETE"])
                        self.assertTrue(all(row[1] is None for row in observed))
                        with self.assertRaises(httpx.ConnectError):
                            httpx.get(origin, trust_env=False)
                        for log in Path(d).glob("*.log"):
                            self.assertNotIn(token, log.read_text())
                finally:
                    suite.host.cleanup()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
