"""Owned host resources and verified input downloads for one disposable CI guest."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat
import subprocess
import tarfile
import threading
import time
import zipfile

import httpx

from .provenance import MANIFEST_TYPES, archive_identity, registry_identity

HAOS_URL = "https://github.com/home-assistant/operating-system/releases/download/18.1/haos_ova-18.1.qcow2.xz"
HAOS_SHA256 = "60df08773901e1eac9b9cfe03d53e1d939e67b669c172c3a41037fb3cd295b9d"
# 升級起點是最新的正式 Release。換 baseline 時，下面五個值要一起換：
# Release 的 commit、該 commit 的 config.yaml SHA-256、amd64 image 的 index
# digest，以及該版 omnigent 的 alembic head（回滾後資料庫要回到這裡）。
BASELINE_VERSION = "0.1.25"
BASELINE_COMMIT = "e7b0bc0ec835e7f5abf9476321a5f50fc06631d9"
BASELINE_CONFIG_SHA256 = "f9a4197e0bf41d74a93cdf25ce7ed59756c32dc83ab8964498615d38735ef6bf"
BASELINE_IMAGE = "ghcr.io/woowtech/woow-ha-omnigent-amd64@sha256:7bba628e5b2583ea0548b87201aab09476578344ccbbe2f629c0319d68172313"
BASELINE_MIGRATION = "zb4c5d6e7f80"
# 這張 PR 的 add-on 版本，必須等於 config.yaml 的 version。
CANDIDATE_VERSION = "0.1.26"
REGISTRY_IMAGE = "registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
IMAGE_TAG = "upgrade-comparison/woow-omnigent:new"
HA_PORTS = (18080, 18123)
PORTS = (*HA_PORTS, 18000, 12222, 15000, 18443)
GIB = 1024**3


class BootFailure(Exception):
    """Terminal boot failure; wait_for must not swallow it as a retry."""


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def wait_for(check, seconds, description, interval=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (httpx.HTTPError, OSError, ValueError, RuntimeError):
            pass
        time.sleep(interval)
    # Do not include HTTP bodies, process output, request URLs or credentials.
    raise RuntimeError("timeout: " + description)


def download(url, target, expected=None, *, limit=2 * GIB):
    """Never forward GitHub authentication to signed artifact download hosts."""
    digest, count = hashlib.sha256(), 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        require(response.status_code == 200, "download HTTP failure")
        with Path(target).open("wb") as output:
            for chunk in response.iter_bytes():
                count += len(chunk)
                require(count <= limit, "download exceeded size bound")
                digest.update(chunk)
                output.write(chunk)
    require(not expected or digest.hexdigest() == expected, "download checksum mismatch")
    return digest.hexdigest()


def extract_image(archive, target):
    with zipfile.ZipFile(archive) as z:
        require(z.namelist() == ["woow-omnigent.tar"], "unexpected artifact members")
        info = z.getinfo("woow-omnigent.tar")
        require(0 < info.file_size <= 2 * GIB, "image archive exceeded size bound")
        with z.open(info) as source, Path(target).open("wb") as output:
            shutil.copyfileobj(source, output)
    # Docker consumes the archive; reject unsafe paths and unexpected tags first.
    with tarfile.open(target) as t:
        members = t.getmembers()
        require(all(not m.name.startswith("/") and ".." not in Path(m.name).parts
                    and (m.isfile() or m.isdir()) for m in members), "unsafe image tar")
        manifest = json.load(t.extractfile("manifest.json"))
        require(len(manifest) == 1 and manifest[0]["RepoTags"] == [IMAGE_TAG],
                "unexpected image tag")
    return sha256(target)


def select_artifact(run, jobs, artifacts, head):
    """Only the successful amd64 build in this run; never guess across heads."""
    require(run["head_sha"] == head and run["event"] == "pull_request", "run identity mismatch")
    build = [j for j in jobs if j["name"] == "build (amd64)"]
    if len(build) != 1 or build[0]["conclusion"] != "success":
        return None
    # On a failed-jobs rerun GitHub retains the original job's run_attempt.
    attempt = build[0].get("run_attempt")
    require(isinstance(attempt, int) and attempt > 0, "build attempt missing")
    pair = []
    for wanted in (f"upgrade-comparison-image-woow-omnigent-attempt-{attempt}",
                   f"haos-image-source-attempt-{attempt}"):
        matches = [a for a in artifacts if a["name"] == wanted and not a["expired"]]
        require(len(matches) <= 1, "ambiguous candidate artifacts")
        if not matches:
            return None
        pair.append(matches[0])
    return pair


def candidate_artifact(private):
    repo, head = os.environ["GITHUB_REPOSITORY"], os.environ["HAOS_HEAD_SHA"]
    require(repo == "WOOWTECH/Woow_ha_omnigent_addon", "unexpected repository")
    require(re.fullmatch("[0-9a-f]{40}", head), "invalid source commit")
    # Read-only, short-lived job token is only used for these GitHub API calls.
    token = os.environ.pop("GH_TOKEN")
    with httpx.Client(base_url="https://api.github.com", timeout=30,
                      headers={"Authorization": "Bearer " + token,
                               "Accept": "application/vnd.github+json"}) as api:
        def get(path, **params):
            r = api.get(f"/repos/{repo}" + path, params=params)
            require(r.status_code == 200, "GitHub read-only API failed")
            return r.json()

        def available():
            runs = get("/actions/workflows/publish-omnigent-addon-images.yml/runs",
                       head_sha=head, event="pull_request", per_page=20)["workflow_runs"]
            if not runs:
                return None
            run = max(runs, key=lambda r: r["id"])
            jobs = get(f"/actions/runs/{run['id']}/jobs", per_page=100)["jobs"]
            artifacts = get(f"/actions/runs/{run['id']}/artifacts", per_page=100)["artifacts"]
            artifact = select_artifact(run, jobs, artifacts, head)
            return (run, artifact, jobs) if artifact else None

        run, pair, jobs = wait_for(available, 900, "matching PR amd64 build artifact", 10)
        for artifact, filename in zip(pair, ("candidate.zip", "source.zip")):
            digest = artifact.get("digest", "")
            require(re.fullmatch("sha256:[0-9a-f]{64}", digest), "artifact checksum missing")
            r = api.get(f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip")
            require(r.status_code in (302, 307), "artifact redirect missing")
            signed_url = r.headers["Location"]
            require(signed_url.startswith("https://"), "insecure artifact redirect")
            download(signed_url, private / filename, digest.removeprefix("sha256:"),
                     limit=2 * GIB if filename == "candidate.zip" else 64 * 1024)
    del token
    with zipfile.ZipFile(private / "source.zip") as z:
        require(z.namelist() == ["producer-source.json"], "unexpected source receipt members")
        require(z.getinfo("producer-source.json").file_size <= 16384, "source receipt too large")
        source = z.read("producer-source.json")
    receipt = json.loads(source)
    attempt = next(j["run_attempt"] for j in jobs if j["name"] == "build (amd64)")
    require(receipt["run_id"] == run["id"] and receipt["run_attempt"] == attempt,
            "source receipt run mismatch")
    (private / "producer-source.json").write_bytes(source)
    (private / "source.zip").unlink()
    archive = private / "candidate.zip"
    target = private / "candidate.tar"
    tar_digest = extract_image(archive, target)
    archive.unlink()
    return {"run_id": run["id"], "run_attempt": attempt, "artifact_id": pair[0]["id"],
            "head_sha": head, "artifact_digest": pair[0]["digest"], "tar_sha256": tar_digest,
            "source_artifact_id": pair[1]["id"], "source_artifact_digest": pair[1]["digest"]}


class Host:
    def __init__(self, private):
        self.private = Path(private)
        self.owner = "haos-ci-" + self.private.name
        self.processes = []
        self.registry_launch_attempted = False
        self.registry_created = False
        self.registry_progress = {"launch_attempted": False, "container_created": False,
                                  "container_running": None}
        self.install_progress = {}
        self.supervisor_progress = {}
        self.image_identities = {}
        self.guard_stop = threading.Event()
        self.disk_exhausted = False
        self.ssh_base = ["ssh", "-i", str(self.private / "key"), "-p", "12222",
                         "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                         "-o", "StrictHostKeyChecking=accept-new",
                         "-o", "UserKnownHostsFile=" + str(self.private / "known_hosts"),
                         "root@127.0.0.1"]
        self.qemu = None
        self.boot_progress = {}
        self.original_kvm_acl = None
        self.kvm_identity = None
        self.kvm_access_baseline = None
        self.kvm_access_progress = {"refreshes": [], "restored": None, "cleanup_failure": None}

    def run(self, argv, *, data=None, timeout=120, check=True):
        r = subprocess.run(argv, input=data, capture_output=True, timeout=timeout)
        # Private diagnostics are deliberately not an upload artifact.
        with (self.private / "commands.log").open("ab") as log:
            log.write(r.stdout + r.stderr + b"\n")
        require(not check or r.returncode == 0, "host/guest command failed")
        return r

    def start(self, argv, *, log_name="processes.log"):
        with (self.private / log_name).open("ab") as log:
            p = subprocess.Popen(argv, stdout=log, stderr=log)
        self.processes.append(p)
        return p

    def ssh(self, command, *, data=None, timeout=120, check=True):
        return self.run([*self.ssh_base, command], data=data, timeout=timeout, check=check)

    def supervisor(self, method, path, body=None, timeout=300):
        require(method in ("GET", "POST", "DELETE") and re.fullmatch(r"/[a-zA-Z0-9_./-]+", path),
                "invalid Supervisor request")
        # Fixed labels only: backup IDs, request bodies and error text stay private.
        operations = {
            "/store/reload": "store_reload",
            "/store/addons/local_woow-omnigent": "store_catalog",
            "/backups/new/partial": "backup_create",
        }
        for action in ("install", "update"):
            operations["/store/addons/local_woow-omnigent/" + action] = "store_" + action
        for action in ("options", "start", "restart", "info"):
            operations["/addons/local_woow-omnigent/" + action] = "addon_" + action
        operation = operations.get(path, "other")
        if re.fullmatch(r"/backups/[a-zA-Z0-9_-]+/info", path):
            operation = "backup_info"
        elif re.fullmatch(r"/backups/[a-zA-Z0-9_-]+/restore/partial", path):
            operation = "backup_restore"
        progress = self.supervisor_progress
        progress.clear()
        progress.update(operation=operation, method=method, ssh_exit=None, timeout=False,
                        http_status=None, result="unknown", error_code="pending")
        # Root developer access belongs solely to this newly created guest.
        # Supervisor injects SUPERVISOR_TOKEN into the CLI container environment.
        # Read only that runtime value; it never leaves the guest shell.
        command = r"""
set -eu
token=$(docker exec hassio_cli printenv SUPERVISOR_TOKEN)
test -n "$token"
address=$(docker inspect hassio_supervisor | jq -r '.[0].NetworkSettings.Networks | to_entries[0].value.IPAddress')
test -n "$address"
curl --silent --show-error --write-out '\n%{http_code}' --max-time """ + str(timeout - 10) + r""" \
 -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
 -X """ + method + (" --data-binary @- " if body is not None else " ") + \
            '"http://$address' + path + '"'
        try:
            r = self.ssh(command, data=json.dumps(body).encode() if body is not None else None,
                         timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            progress.update(timeout=True, error_code="timeout")
            raise
        progress["ssh_exit"] = r.returncode
        raw, _, status = r.stdout.rstrip(b"\r\n").rpartition(b"\n")
        if re.fullmatch(rb"[1-5][0-9]{2}", status):
            progress["http_status"] = int(status)
        if r.returncode:
            progress["error_code"] = "transport_error"
            raise RuntimeError("Supervisor transport failed")
        if progress["http_status"] is None:
            progress["error_code"] = "invalid_http_status"
            raise RuntimeError("Supervisor HTTP status missing")
        if len(raw) > 1024 * 1024:
            progress["error_code"] = "response_too_large"
            raise RuntimeError("Supervisor response exceeds metadata limit")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            progress["error_code"] = "invalid_json"
            raise RuntimeError("Supervisor response is not JSON") from None
        if not isinstance(result, dict):
            progress["error_code"] = "invalid_json"
            raise RuntimeError("Supervisor response is not an object")
        outcome = result.get("result")
        progress["result"] = outcome if outcome in ("ok", "error") else "unknown"
        if progress["http_status"] == 200 and outcome == "ok":
            progress["error_code"] = "none"
        else:
            key = result.get("error_key")
            progress["error_code"] = (key if key in ("store_app_not_found_error", "system_not_ready_error")
                else {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(
                    progress["http_status"], "api_error" if outcome == "error" else "invalid_result"))
            raise RuntimeError("Supervisor rejected operation")
        return result.get("data", {})

    def preflight(self):
        require(os.environ.get("GITHUB_ACTIONS") == "true", "real VM runner is CI-only")
        require(platform.machine() == "x86_64", "native amd64 required")
        require(os.getuid() != 0, "QEMU must run as the unprivileged runner")
        self.refresh_kvm_access("preflight")
        # Test the KVM ioctl, not just the existence of a device node.
        with open("/dev/kvm", "r+b", buffering=0) as kvm:
            require(fcntl.ioctl(kvm, 0xAE00, 0) == 12, "unsupported KVM API")
            vm = fcntl.ioctl(kvm, 0xAE01, 0)
            os.close(vm)
        free = shutil.disk_usage(self.private).free
        require(free >= 12 * GIB, "at least 12 GiB physical free space required")
        for port in PORTS:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
        return {"architecture": "amd64", "kvm_api": 12, "free_bytes": free,
                "guest_vcpus": 2, "guest_memory_mib": 6144, "virtual_disk_gib": 32}

    def _kvm_access_snapshot(self):
        info = Path("/dev/kvm").stat()
        require(stat.S_ISCHR(info.st_mode), "KVM device is not a character device")
        # ACL masks can change mode bits; they are deliberately not identity.
        identity = (info.st_dev, info.st_ino, info.st_rdev, info.st_uid, info.st_gid)
        acl = self.run(["getfacl", "-p", "-n", "/dev/kvm"], timeout=5).stdout
        return identity, acl, os.access("/dev/kvm", os.R_OK | os.W_OK, effective_ids=True)

    def refresh_kvm_access(self, phase):
        require(phase in ("preflight", "boot"), "invalid KVM access phase")
        # VM create/close events may replace named ACLs asynchronously. Drain
        # pending events BEFORE the grant immediately preceding each launch.
        self.run(["udevadm", "settle", "--timeout=5"], timeout=6)
        before = self._kvm_access_snapshot()
        if self.original_kvm_acl is None:
            self.original_kvm_acl = before[1]
            self.kvm_identity = before[0]
        require(before[0] == self.kvm_identity, "KVM device identity changed")
        record = {"phase": phase, "effective_access_before": before[2],
                  "effective_access_after": None, "acl_changed_since_grant":
                  before[1] != self.kvm_access_baseline[1] if self.kvm_access_baseline else None}
        self.kvm_access_progress["refreshes"].append(record)
        self.run(["sudo", "-n", "setfacl", "-m", f"u:{os.getuid()}:rw", "/dev/kvm"], timeout=5)
        after = self._kvm_access_snapshot()
        record["effective_access_after"] = after[2]
        require(after[0] == self.kvm_identity, "KVM device identity changed")
        require(after[2], "KVM access grant ineffective")
        self.kvm_access_baseline = after

    def restore_kvm_access(self):
        if self.original_kvm_acl is None:
            return
        progress = self.kvm_access_progress
        progress["restored"] = False
        progress["cleanup_failure"] = "qemu_not_reaped"
        require(self.qemu is None or self.qemu.poll() is not None, "QEMU must be reaped before ACL restore")
        # Restore even when settle fails, but never write an ACL to a replaced
        # device. The identity saved before the FIRST grant stays authoritative.
        settle_error = None
        try:
            self.run(["udevadm", "settle", "--timeout=5"], timeout=6)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            settle_error = error
        progress["cleanup_failure"] = "device_identity"
        require(self._kvm_access_snapshot()[0] == self.kvm_identity, "KVM device identity changed")
        progress["cleanup_failure"] = "acl_restore"
        self.run(["sudo", "-n", "setfacl", "--restore=-"], data=self.original_kvm_acl, timeout=5)
        progress["restored"] = True
        progress["cleanup_failure"] = "udev_settle" if settle_error else None
        if settle_error:
            raise settle_error

    def watch_disk(self):
        def guard():
            while not self.guard_stop.wait(5):
                if shutil.disk_usage(self.private).free < 2 * GIB:
                    self.disk_exhausted = True
                    os.kill(os.getpid(), 15)
                    return
        threading.Thread(target=guard, daemon=True).start()

    def disk_guard(self):
        require(shutil.disk_usage(self.private).free >= 2 * GIB, "host disk reserve below 2 GiB")

    def prepare_vm(self):
        archive = self.private / "haos.qcow2.xz"
        download(HAOS_URL, archive, HAOS_SHA256)
        self.run(["xz", "-d", str(archive)], timeout=180)
        self.run(["qemu-img", "resize", str(self.private / "haos.qcow2"), "32G"])
        self.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.private / "key")])
        self.run(["truncate", "-s", "4M", str(self.private / "config.img")])
        self.run(["mkfs.vfat", "-n", "CONFIG", str(self.private / "config.img")])
        self.run(["mcopy", "-i", str(self.private / "config.img"),
                  str(self.private / "key.pub"), "::/authorized_keys"])
        shutil.copyfile("/usr/share/OVMF/OVMF_VARS.fd", self.private / "OVMF_VARS.fd")

    def boot(self):
        self.disk_guard()
        require(self.qemu is None or self.qemu.poll() is not None, "guest already running")
        self.boot_progress.clear()
        self.boot_progress.update({"stage": "refreshing_kvm_access", "ssh_attempts": 0,
                                   "last_ssh_exit": None, "last_ssh_error": "not_checked"})
        (self.private / "qemu.log").write_bytes(b"")
        self.refresh_kvm_access("boot")
        self.boot_progress["stage"] = "starting_qemu"
        self.qemu = self.start([
            "qemu-system-x86_64", "-machine", "q35,accel=kvm", "-cpu", "host",
            "-smp", "2", "-m", "6144", "-display", "none", "-monitor", "none",
            "-serial", "file:" + str(self.private / "console.log"),
            "-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd",
            "-drive", "if=pflash,format=raw,file=" + str(self.private / "OVMF_VARS.fd"),
            "-drive", "if=virtio,format=qcow2,discard=unmap,file=" + str(self.private / "haos.qcow2"),
            "-device", "qemu-xhci,id=xhci", "-drive",
            "if=none,id=config,format=raw,readonly=on,file=" + str(self.private / "config.img"),
            "-device", "usb-storage,drive=config",
            "-nic", f"user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:{HA_PORTS[0]}-:80,"
            f"hostfwd=tcp:127.0.0.1:{HA_PORTS[1]}-:8123,hostfwd=tcp:127.0.0.1:18000-:8000,"
            "hostfwd=tcp:127.0.0.1:12222-:22222",
        ], log_name="qemu.log")
        try:
            return self._wait_boot()
        finally:
            self._capture_boot_signals()

    def _boot_stage(self, stage):
        self.boot_progress["stage"] = stage
        print("BOOT " + stage, flush=True)

    def _require_qemu_alive(self):
        code = self.qemu.poll()
        if code is not None:
            self.boot_progress["qemu_exit"] = code
            self._boot_stage("qemu_exited")
            raise BootFailure("QEMU exited before guest readiness")

    def _ssh_ready(self):
        self._require_qemu_alive()
        self.boot_progress["ssh_attempts"] += 1
        try:
            result = self.ssh("true", check=False, timeout=10)
        except subprocess.TimeoutExpired:
            self.boot_progress["last_ssh_exit"] = None
            self.boot_progress["last_ssh_error"] = "command_timeout"
            return False
        self.boot_progress["last_ssh_exit"] = result.returncode
        code = "none" if result.returncode == 0 else "unclassified"
        if result.returncode:
            for marker, label in (
                (b"Connection refused", "connection_refused"),
                (b"Connection timed out", "connection_timeout"),
                (b"Permission denied", "authentication_denied"),
                (b"UNPROTECTED PRIVATE KEY FILE", "key_permissions"),
                (b"Connection reset", "connection_reset"),
                (b"REMOTE HOST IDENTIFICATION HAS CHANGED", "host_key_changed"),
            ):
                if marker in result.stderr:
                    code = label
                    break
        self.boot_progress["last_ssh_error"] = code
        return result.returncode == 0

    def _wait_boot(self):
        self._boot_stage("waiting_for_guest_ssh")
        wait_for(self._ssh_ready, 600, "fresh HAOS developer SSH")
        self._boot_stage("waiting_for_supervisor")
        def ready():
            self._require_qemu_alive()
            self.boot_progress["supervisor_attempts"] = self.boot_progress.get("supervisor_attempts", 0) + 1
            info = self._supervisor_boot_info("supervisor_info")
            # Health belongs to supervisor/info; system state belongs to /info.
            # Probe both even when one fails, preserving independent HTTP evidence.
            root = self._supervisor_boot_info("root_info")
            healthy = info.get("healthy")
            self.boot_progress["supervisor_healthy"] = healthy if type(healthy) is bool else None
            state = root.get("state")
            self.boot_progress["supervisor_state"] = (
                state if state in ("initialize", "setup", "startup", "running", "freeze", "shutdown", "close")
                else "missing" if state is None else "other")
            if info.get("healthy") is True and root.get("state") == "running":
                return dict(info, state=root["state"])
            return None
        info = wait_for(ready, 600, "actual healthy Supervisor API")
        self._boot_stage("supervisor_ready")
        self.disk_guard()
        return {k: info.get(k) for k in ("version", "arch", "healthy", "state")}

    def _supervisor_boot_info(self, family):
        """Readiness-only probe; export numeric diagnostics, never command output."""
        path = {"supervisor_info": "/supervisor/info", "root_info": "/info"}[family]
        progress = {"ssh_exit": None, "command_timeout": False, "http_status": None,
                    "api_ok": False}
        self.boot_progress[family] = progress
        # No set -e or pipelines around docker inspect: retain each command's
        # real exit code. Values, HTTP bodies and stderr remain private.
        command = r'''
set -u
probe() { printf 'HAOS_BOOT %s %s\n' "$1" "$2" >&2; }
missing=0
for tool in docker curl jq; do
    command -v "$tool" >/dev/null 2>&1
    rc=$?; probe "${tool}_available_exit" "$rc"
    if [ "$rc" -ne 0 ]; then missing=1; fi
done
[ "$missing" -eq 0 ] || exit 127
token=$(docker exec hassio_cli printenv SUPERVISOR_TOKEN)
rc=$?; probe cli_token_exec_exit "$rc"; [ "$rc" -eq 0 ] || exit "$rc"
test -n "$token"
rc=$?; probe token_lookup_exit "$rc"; [ "$rc" -eq 0 ] || exit "$rc"
supervisor=$(docker inspect hassio_supervisor)
rc=$?; probe supervisor_inspect_exit "$rc"; [ "$rc" -eq 0 ] || exit "$rc"
count=$(printf '%s' "$supervisor" | jq -er '.[0].NetworkSettings.Networks | length')
rc=$?; probe network_lookup_exit "$rc"; [ "$rc" -eq 0 ] || exit "$rc"
probe network_count "$count"
address=$(printf '%s' "$supervisor" | jq -er '.[0].NetworkSettings.Networks | to_entries[0].value.IPAddress | select(type == "string" and length > 0)')
rc=$?; probe address_lookup_exit "$rc"; [ "$rc" -eq 0 ] || exit "$rc"
curl --silent --show-error --fail --max-time 20 --write-out '\n%{http_code}\n' \
 -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
 -X GET "http://$address''' + path + '''"
rc=$?; probe curl_exit "$rc"; exit "$rc"
'''
        try:
            result = self.ssh(command, check=False, timeout=30)
            progress["ssh_exit"] = result.returncode
        except subprocess.TimeoutExpired as error:
            progress["command_timeout"] = True
            result = error
        allowed = {"docker_available_exit", "curl_available_exit", "jq_available_exit",
                   "cli_token_exec_exit", "token_lookup_exit", "supervisor_inspect_exit",
                   "network_lookup_exit", "network_count", "address_lookup_exit", "curl_exit"}
        for line in (result.stderr or b"").splitlines():
            match = re.fullmatch(rb"HAOS_BOOT ([a-z_]+) ([0-9]{1,3})", line)
            if match and match[1].decode() in allowed and int(match[2]) <= 255:
                progress[match[1].decode()] = int(match[2])
        # Missing/stopped CLI or absent runtime token can be normal startup.
        # Missing executables and jq usage/compile errors cannot become ready.
        if any(progress.get(tool + "_available_exit", 0) != 0 for tool in ("docker", "curl", "jq")):
            raise BootFailure("required guest probe executable missing")
        if progress.get("cli_token_exec_exit") in (126, 127):
            raise BootFailure("CLI runtime token command unavailable")
        if any(progress.get(key) in (2, 3) for key in ("network_lookup_exit", "address_lookup_exit")):
            raise BootFailure("Supervisor probe jq program invalid")
        body, _, status = (result.stdout or b"").rstrip(b"\n").rpartition(b"\n")
        if re.fullmatch(rb"[0-9]{3}", status) and (int(status) == 0 or 100 <= int(status) <= 599):
            progress["http_status"] = int(status)
        if progress["ssh_exit"] != 0 or progress["http_status"] != 200:
            return {}
        try:
            response = json.loads(body)
        except ValueError:
            progress["response_json"] = False
            return {}
        progress["response_json"] = True
        if isinstance(response, dict) and response.get("result") == "ok" and isinstance(response.get("data"), dict):
            progress["api_ok"] = True
            return response["data"]
        return {}

    def _capture_boot_signals(self):
        """Export only allowlisted labels and integers, never raw log text."""
        self.boot_progress["qemu_exit"] = self.qemu.poll()
        def tail(name):
            path = self.private / name
            if not path.exists():
                return b""
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 65536))
                return stream.read(65536)
        qemu, console = tail("qemu.log"), tail("console.log")
        markers = {
            "kvm_initialization": b"failed to initialize kvm",
            "kvm_access": b"Could not access KVM",
            "readonly_block": b"Block node is read-only",
            "missing_file": b"No such file or directory",
            "permission_denied": b"Permission denied",
            "port_forward": b"Could not set up host forwarding rule",
            "kvm_internal_error": b"KVM internal error",
            "invalid_property": b"Property ",
        }
        self.boot_progress["qemu_error_codes"] = [k for k, v in markers.items() if v in qemu]
        markers = {
            "linux_started": b"Linux version ",
            "ha_console": b"Welcome to Home Assistant",
            "login_prompt": b"homeassistant login:",
            "config_imported": b"Imported CONFIG succesfully",
            "ssh_key_imported": b"Update SSH authorized_keys",
            "kernel_panic": b"Kernel panic",
            "no_boot_device": b"No bootable device",
        }
        self.boot_progress["console_markers"] = [k for k, v in markers.items() if v in console]

    @contextlib.contextmanager
    def registry_stage(self, stage):
        allowed = {"registry_pull", "registry_launch", "registry_inspect", "registry_container_state",
                   "host_registry_http", "guest_registry_forwarding", "candidate_producer_image_id",
                   "candidate_core_source", "baseline_archive", "baseline_anchor_inspect",
                   "baseline_anchor_tag", "baseline_anchor_save"} | {
                       role + "_" + step for role in ("baseline", "candidate")
                       for step in ("tag", "push", "inspect", "metadata", "architecture", "version",
                                    "source_identity", "registry_binding")}
        require(stage in allowed, "invalid registry stage")
        self.registry_progress["stage"] = stage
        self.registry_progress["exception"] = None
        self.registry_progress.setdefault("states", {})[stage] = False
        try:
            yield
        except Exception as error:
            self.registry_progress["exception"] = self.registry_exception(error)
            raise
        self.registry_progress["states"][stage] = True

    @staticmethod
    def registry_exception(error):
        # Do not emit exception messages, URLs, filenames or arbitrary subclass names.
        for kind in (subprocess.TimeoutExpired, httpx.TimeoutException, httpx.HTTPError,
                     OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError):
            if isinstance(error, kind):
                return kind.__name__
        return "other"

    def _registry_run(self, stage, argv, *, timeout=120):
        with self.registry_stage(stage):
            return self._registry_command(stage, argv, timeout=timeout)

    def _registry_command(self, stage, argv, *, timeout):
        diagnostic = {"stage": stage, "exit": None, "timeout": False, "error_codes": []}
        self.registry_progress.setdefault("commands", []).append(diagnostic)
        try:
            result = self.run(argv, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            diagnostic["timeout"] = True
            raise
        diagnostic["exit"] = result.returncode
        if result.returncode:
            output = (result.stdout + result.stderr)[-65536:].lower()
            markers = {
                "access_denied": b"denied", "rate_limited": b"toomanyrequests",
                "connection_refused": b"connection refused", "no_space": b"no space left",
                "manifest_unknown": b"manifest unknown", "missing_image": b"no such image",
                "http_to_https": b"http response to https client",
                "container_name_conflict": b"already in use",
                "certificate_error": b"x509:", "tls_handshake": b"tls handshake",
                "missing_path": b"no such file or directory", "dns_failure": b"no such host",
                "connection_reset": b"connection reset", "daemon_unavailable": b"cannot connect to the docker daemon",
            }
            diagnostic["error_codes"] = [name for name, marker in markers.items() if marker in output]
        require(result.returncode == 0, "registry command failed")
        return result

    def registry(self):
        # Split Docker's implicit pull from container launch to identify either failure.
        self._registry_run("registry_pull", ["docker", "pull", "--platform", "linux/amd64",
                                             REGISTRY_IMAGE], timeout=180)
        # A failed/timed-out Docker CLI can still have created the container.
        self.registry_launch_attempted = True
        self.registry_created = None
        self.registry_progress.update(launch_attempted=True, container_created=None)
        self._registry_run("registry_launch", ["docker", "run", "--pull=never", "-d", "--name", self.owner,
                  "--label", "io.woow.haos-ci=" + self.owner,
                  "-p", "127.0.0.1:15000:5000", REGISTRY_IMAGE], timeout=180)
        self.registry_created = True
        self.registry_progress["container_created"] = True
        result = self._registry_run("registry_inspect", ["docker", "inspect", "--format",
                                   "{{json .State}}", self.owner])
        with self.registry_stage("registry_container_state"):
            state = json.loads(result.stdout)
            running = state.get("Running") is True
            self.registry_progress["container_running"] = running
            code = state.get("ExitCode")
            self.registry_progress["container_exit"] = code if type(code) is int else None
            require(running, "registry container is not running")
        diagnostic = {"http_status": None, "exception": None}
        self.registry_progress["host_http"] = diagnostic
        def ready():
            diagnostic.update(http_status=None, exception=None)
            try:
                response = httpx.get("http://127.0.0.1:15000/v2/", timeout=3, trust_env=False)
            except httpx.HTTPError as error:
                diagnostic["exception"] = self.registry_exception(error)
                return False
            diagnostic["http_status"] = response.status_code
            return response.status_code == 200
        with self.registry_stage("host_registry_http"):
            wait_for(ready, 30, "host registry readiness")
        self.registry_tunnel()

    def registry_tunnel(self):
        # Guest Docker recognizes loopback as a local registry. No insecure
        # registry configuration or extra container is added to HAOS.
        with self.registry_stage("guest_registry_forwarding"):
            self._registry_forward()

    def _registry_forward(self):
        diagnostic = {"probe_exit": None, "probe_timeout": False, "tunnel_exit": None}
        self.registry_progress["forwarding"] = diagnostic
        tunnel = self.start([*self.ssh_base[:-1], "-N", "-o", "ExitOnForwardFailure=yes",
                    "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
                    "-R", "127.0.0.1:15000:127.0.0.1:15000", self.ssh_base[-1]])
        def ready():
            diagnostic.update(probe_exit=None, probe_timeout=False)
            try:
                result = self.ssh("curl -fsS http://127.0.0.1:15000/v2/", check=False, timeout=10)
            except subprocess.TimeoutExpired:
                diagnostic["probe_timeout"] = True
                raise
            diagnostic["probe_exit"] = result.returncode
            return result.returncode == 0
        try:
            wait_for(ready, 30, "guest registry forwarding")
        finally:
            diagnostic["tunnel_exit"] = tunnel.poll()

    def baseline_identity(self):
        # Export only the image pulled by immutable digest, then discard the tar.
        tag, archive = "haos-acceptance-baseline:" + BASELINE_VERSION, self.private / "baseline-image.tar"
        result = self._registry_run("baseline_anchor_inspect", ["docker", "image", "inspect",
                                    "--format", "{{.Id}}", BASELINE_IMAGE])
        image_id = result.stdout.decode().strip()
        self._registry_run("baseline_anchor_tag", ["docker", "tag", BASELINE_IMAGE, tag])
        try:
            self._registry_run("baseline_anchor_save", ["docker", "save", "-o", str(archive), tag], timeout=180)
            with self.registry_stage("baseline_archive"):
                return archive_identity(archive, image_id, expected_tag=tag)
        finally:
            archive.unlink(missing_ok=True)

    def _registry_metadata(self, suffix):
        versions = "|".join(re.escape(v) for v in (BASELINE_VERSION, CANDIDATE_VERSION))
        require(re.fullmatch(r"(?:manifests/(?:" + versions + r")|blobs/sha256:[0-9a-f]{64})", suffix),
                "unexpected registry metadata path")
        diagnostic = {"object": "manifest" if suffix.startswith("manifests/") else "config",
                      "http_status": None, "bytes": 0}
        self.registry_progress.setdefault("metadata_reads", []).append(diagnostic)
        with httpx.stream("GET", "http://127.0.0.1:15000/v2/omnigent-acceptance/" + suffix,
                          headers={"Accept": ", ".join(MANIFEST_TYPES)}, timeout=10,
                          trust_env=False, follow_redirects=False) as response:
            diagnostic["http_status"] = response.status_code
            require(response.status_code == 200, "registry metadata HTTP failure")
            data = bytearray()
            for chunk in response.iter_bytes():
                diagnostic["bytes"] += len(chunk)
                require(diagnostic["bytes"] <= 1024 * 1024, "registry metadata size bound exceeded")
                data.extend(chunk)
            return bytes(data), response.headers.get("Docker-Content-Digest")

    def publish_local(self, source, version, *, identity):
        require(version in (BASELINE_VERSION, CANDIDATE_VERSION), "unexpected acceptance image version")
        require(all(re.fullmatch(r"sha256:[0-9a-f]{64}", identity.get(key, ""))
                    for key in ("config_digest", "producer_image_id")), "invalid anchored identity")
        role = "baseline" if version == BASELINE_VERSION else "candidate"
        target = "127.0.0.1:15000/omnigent-acceptance:" + version
        self._registry_run(role + "_tag", ["docker", "tag", source, target])
        self._registry_run(role + "_push", ["docker", "push", target], timeout=240)
        result = self._registry_run(role + "_inspect", ["docker", "image", "inspect", source])
        with self.registry_stage(role + "_metadata"):
            image = json.loads(result.stdout)[0]
            require(isinstance(image, dict), "invalid image metadata")
        with self.registry_stage(role + "_architecture"):
            require(image["Architecture"] == "amd64", "wrong add-on architecture")
        with self.registry_stage(role + "_version"):
            require(image["Config"]["Labels"].get("io.hass.version") == version, "wrong add-on version")
        with self.registry_stage(role + "_source_identity"):
            require(image["Id"] in (identity["producer_image_id"], identity["config_digest"]),
                    "loaded image differs from anchored source")
        with self.registry_stage(role + "_registry_binding"):
            raw, digest = self._registry_metadata("manifests/" + version)
            config, _ = self._registry_metadata("blobs/" + identity["config_digest"])
            proof = registry_identity(raw, digest, config, identity["config_digest"])
            self.image_identities[image["Id"]] = proof
            self.registry_progress.setdefault("images", {})[role] = proof
        return image

    def install_config(self, config):
        import yaml
        require(config["slug"] == "woow-omnigent", "unexpected add-on slug")
        config = dict(config, image="127.0.0.1:15000/omnigent-acceptance")
        self.install_progress.update(stage="write_local_config")
        # Local and store installs have different slugs. Both sides use local.
        # Supervisor 2026.11.0 config.APPS_LOCAL is apps/local. Require its
        # existing root so a renamed or unexpected layout cannot be invented.
        self.ssh("test -d /mnt/data/supervisor/apps/local && "
                 "mkdir -p /mnt/data/supervisor/apps/local/woow-omnigent && "
                 "cat > /mnt/data/supervisor/apps/local/woow-omnigent/config.yaml",
                 data=yaml.safe_dump(config).encode())
        self.install_progress["stage"] = "store_reload"
        self.supervisor("POST", "/store/reload", {})
        self.install_progress["stage"] = "catalog_lookup"
        entry = self.supervisor("GET", "/store/addons/local_woow-omnigent")
        require(entry.get("slug") == "local_woow-omnigent" and entry.get("repository") == "local"
                and entry.get("version_latest") == config["version"], "local app catalog mismatch")
        self.install_progress["stage"] = "catalog_verified"

    def verify_guest_image(self, expected_id):
        proof = self.image_identities.get(expected_id)
        require(proof is not None, "guest image has no verified registry identity")
        # Names changed from addon_ to app_ in recent Supervisor releases.
        command = "docker inspect app_local_woow-omnigent 2>/dev/null || docker inspect addon_local_woow-omnigent"
        image = json.loads(self.ssh(command).stdout)[0]
        require(image["Image"] in (proof["config_digest"], proof["manifest_digest"]),
                "Supervisor is not running the verified image")
        return image["Name"].lstrip("/")

    def cold_shutdown(self):
        # Clean HAOS shutdown; preserve the disk but not the running VM process.
        self.ssh("systemctl poweroff", check=False, timeout=20)
        self.qemu.wait(timeout=90)
        require(self.qemu.returncode == 0, "HAOS did not shut down cleanly")

    def cleanup(self):
        self.guard_stop.set()
        try:
            self._cleanup_resources()
        finally:
            self.restore_kvm_access()

    def _cleanup_resources(self):
        for p in reversed(self.processes):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=2)
        if self.registry_launch_attempted:
            self._cleanup_registry()

    def _cleanup_registry(self):
        # Preserve the failed acceptance stage while recording cleanup separately.
        diagnostic = {"result": "pending", "inspect_exit": None, "absence_check_exit": None,
                      "ownership_match": None, "remove_exit": None, "exception": None}
        self.registry_progress["cleanup"] = diagnostic
        try:
            r = self.run(["docker", "container", "inspect", "--format",
                          '{{index .Config.Labels "io.woow.haos-ci"}}', self.owner],
                         check=False, timeout=5)
            diagnostic["inspect_exit"] = r.returncode
            if r.returncode:
                # An inspect failure alone does not prove absence (daemon errors
                # also fail). Require a successful, empty exact-name lookup.
                listing = self.run(["docker", "container", "ls", "--all", "--filter",
                                    "name=^/" + self.owner + "$", "--format", "{{.Names}}"],
                                   check=False, timeout=5)
                diagnostic["absence_check_exit"] = listing.returncode
                require(listing.returncode == 0 and not listing.stdout.strip(),
                        "registry cleanup could not confirm absence")
                if self.registry_created is None:
                    self.registry_created = False
                    self.registry_progress["container_created"] = False
                diagnostic["result"] = "absent"
                return
            diagnostic["ownership_match"] = r.stdout.decode().strip() == self.owner
            require(diagnostic["ownership_match"], "registry ownership mismatch")
            self.registry_created = True
            self.registry_progress["container_created"] = True
            result = self.run(["docker", "rm", "-f", "-v", self.owner], check=False, timeout=10)
            diagnostic["remove_exit"] = result.returncode
            require(result.returncode == 0, "registry cleanup removal failed")
            diagnostic["result"] = "removed"
        except Exception as error:
            diagnostic["result"] = "failure"
            diagnostic["exception"] = self.registry_exception(error)
            raise
