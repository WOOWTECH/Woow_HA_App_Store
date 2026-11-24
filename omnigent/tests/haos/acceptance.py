"""Real HAOS acceptance, bounded to a newly created GitHub-hosted amd64 guest."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import re
import shlex
import signal
import ssl
import sys
import tempfile
import traceback
from urllib.parse import urlsplit

import httpx
import yaml

from . import browser
from .host import (BASELINE_COMMIT, BASELINE_CONFIG_SHA256, BASELINE_IMAGE,
                   BASELINE_MIGRATION, BASELINE_VERSION, CANDIDATE_VERSION, HAOS_SHA256, HAOS_URL, HA_PORTS, IMAGE_TAG, Host, candidate_artifact,
                   download, require, wait_for)
from .provenance import archive_identity, validate_source

ADDON = "local_woow-omnigent"
DIRECT = "http://127.0.0.1:18000"
PUBLIC_BASE = "https://localhost:18443/omnigent"
ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = [
    "Internet-public HTTPS/Pi client acceptance",
    "Native arm64 HAOS runtime",
    "External runner sessions and terminal WebSocket",
    "Long-duration MCP SSE delivery and reconnect (GET establishment only)",
]


MIGRATION_HEAD = r"[a-zA-Z0-9_]{1,64}"
# Runs inside the add-on container: list versions/*.py (name, SHA-256) and the alembic script heads.
MIGRATION_LISTING = """
import hashlib, json, pathlib, omnigent
from alembic.config import Config
from alembic.script import ScriptDirectory
root = pathlib.Path(omnigent.__file__).parent / "db" / "migrations"
files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root / "versions").glob("*.py"))}
config = Config()
config.set_main_option("script_location", str(root))
print(json.dumps({"files": files, "heads": sorted(ScriptDirectory.from_config(config).get_heads())}))
"""


def migration_rule(baseline, candidate, head, baseline_head):
    """Return "new" or "none"; the candidate database head must match what its migrations allow."""
    base, cand = baseline["files"], candidate["files"]
    require(all(cand.get(name) == digest for name, digest in base.items()),
            "candidate is missing or changed a baseline migration")
    if cand == base:
        require(head == baseline_head, "migration head changed without a new migration")
        return "none"
    # 檔案集合變大（含只有 merge revision 的情況）就是有新 migration，head 要前進到 candidate 的 head。
    require(len(candidate["heads"]) == 1, "candidate migrations do not have a single migration head")
    require(head == candidate["heads"][0] and head != baseline_head,
            "candidate has new migrations but the head did not advance to its migration head")
    return "new"


def load_hooks():
    spec = importlib.util.spec_from_file_location("haos_upgrade", ROOT / "upgrade-check/omnigent_upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_report(checks, evidence, failure=None):
    """Only controlled labels, counts and independently validated receipts."""
    return {"schema": 1, "passed": failure is None, "checks": checks,
            "evidence": evidence, "failure": failure, "not_covered": EXCLUDED}


class Acceptance:
    def __init__(self, private):
        self.private = private
        self.host = Host(private)
        self.hooks = load_hooks()
        self.checks = []
        self.evidence = {}
        self.evidence["boot_progress"] = self.host.boot_progress
        self.evidence["kvm_access"] = self.host.kvm_access_progress
        self.evidence["registry_progress"] = self.host.registry_progress
        self.evidence["install_progress"] = self.host.install_progress
        self.evidence["supervisor_operation"] = self.host.supervisor_progress
        self.phase = "initialization"
        self.username = "haos-ci-admin"
        self.password = secrets.token_urlsafe(24)
        self.ha_password = secrets.token_urlsafe(24)
        self.pin = json.loads((ROOT / "build/artifact-pin.json").read_text())
        self.config = yaml.safe_load((ROOT / "config.yaml").read_text())
        require(self.config["version"] == CANDIDATE_VERSION and self.config["backup"] == "cold",
                "candidate acceptance configuration mismatch")
        self.state = {}
        self.ssl_context = None
        for name in ("hook-state", "hook-reports", "options"):
            (private / name).mkdir()
        self.options = {"admin_username": self.username, "admin_password": self.password,
                        "mcp_public_base_url": PUBLIC_BASE}
        (private / "options/options.json").write_text(json.dumps(self.options))
        os.environ.update({"ADDON_URL": DIRECT, "DATA_DIR_DATA": str(private / "options"),
                           "HOOK_STATE_DIR": str(private / "hook-state"),
                           "REPORT_DIR": str(private / "hook-reports")})

    def step(self, name, action):
        self.phase = name
        print("START " + name, flush=True)
        self.host.disk_guard()
        value = action()
        self.checks.append({"name": name, "result": "pass"})
        print("PASS " + name, flush=True)
        return value

    def hook(self, name):
        # Existing hook diagnostics may include synthetic account state.
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = getattr(self.hooks, name)()
        (self.private / ("hook-" + name + ".log")).write_text(output.getvalue())
        require(code == 0, "upgrade data hook failed")
        report = json.loads((self.private / "hook-reports" / (name + ".json")).read_text())
        require(all(c["result"] == "pass" for c in report["checks"]), "upgrade hook incomplete")
        self.state = json.loads(Path(self.hooks.state_path()).read_text())

    def api(self):
        client = self.hooks.Client(DIRECT)
        client.wait_ready()
        client.login(self.username, self.password)
        return client

    def data_preserved(self):
        api = self.api()
        task = api.ok("GET", "/v1/scheduled-tasks/" + self.state["task"]["id"])
        require(all(task.get(k) == v for k, v in self.state["task"].items()), "task data changed")
        agent = api.ok("GET", "/v1/agents/" + self.state["task"]["agent_id"])
        require(all(agent.get(k) == v for k, v in self.state["agent"].items()), "agent data changed")
        self.hooks.verify_sessions(api, self.state)
        self.hooks.member_client(self.state)
        return api

    def wait_addon(self, version):
        def ready():
            data = self.host.supervisor("GET", f"/addons/{ADDON}/info", timeout=30)
            return data.get("state") == "started" and data.get("version") == version
        wait_for(ready, 300, "Supervisor add-on started")
        self.api()

    def find_ha(self):
        def ready():
            for port in HA_PORTS:
                base = "http://127.0.0.1:" + str(port)
                try:
                    r = httpx.get(base + "/api/onboarding", timeout=5)
                    if r.status_code == 200 and isinstance(r.json(), list):
                        self.evidence["ha_core"] = {"forwarded_port": port}
                        return base
                except (httpx.HTTPError, ValueError):
                    pass
            return None
        return wait_for(ready, 600, "HA Core onboarding")

    def inputs(self):
        self.evidence["candidate"] = candidate_artifact(self.private)
        self.producer = json.loads((self.private / "producer-source.json").read_text())
        head = self.host.run(["git", "rev-parse", "HEAD"]).stdout.decode().strip()
        tree = self.host.run(["git", "rev-parse", "HEAD:omnigent"]).stdout.decode().strip()
        validate_source(self.producer, head, tree, ROOT)
        self.candidate_identity = archive_identity(self.private / "candidate.tar", self.producer["image_id"])
        self.evidence["candidate"]["archive_identity"] = self.candidate_identity
        baseline = self.private / "baseline.yaml"
        download("https://raw.githubusercontent.com/WOOWTECH/Woow_ha_omnigent_addon/"
                 + BASELINE_COMMIT + "/omnigent/config.yaml", baseline,
                 BASELINE_CONFIG_SHA256, limit=256 * 1024)
        self.old_config = yaml.safe_load(baseline.read_text())
        require(self.old_config["version"] == BASELINE_VERSION and self.old_config["backup"] == "cold",
                "baseline configuration mismatch")
        self.host.run(["docker", "pull", "--platform", "linux/amd64", BASELINE_IMAGE], timeout=300)
        self.baseline_identity = self.host.baseline_identity()
        self.host.run(["docker", "load", "-i", str(self.private / "candidate.tar")], timeout=180)
        (self.private / "candidate.tar").unlink()
        self.evidence["baseline"] = {"version": BASELINE_VERSION, "source_commit": BASELINE_COMMIT,
                                     "image": BASELINE_IMAGE, "archive_identity": self.baseline_identity}

    def registry(self):
        self.host.registry()
        self.old_image = self.host.publish_local(BASELINE_IMAGE, BASELINE_VERSION, identity=self.baseline_identity)
        self.new_image = self.host.publish_local(IMAGE_TAG, self.config["version"], identity=self.candidate_identity)
        with self.host.registry_stage("candidate_producer_image_id"):
            require(self.new_image["Id"] in (self.candidate_identity["producer_image_id"],
                                            self.candidate_identity["config_digest"]),
                    "producer image ID mismatch")
        with self.host.registry_stage("candidate_core_source"):
            labels = self.new_image["Config"]["Labels"]
            require(labels.get("org.opencontainers.image.revision") == self.pin["sourceCommit"],
                    "candidate core source mismatch")
        self.host.registry_progress["stage"] = "verified"
        self.evidence["candidate"].update({
            "image_id": self.new_image["Id"], "core_source": self.pin["sourceCommit"],
            "producer_checkout": self.producer["checkout_commit"],
            "addon_tree": self.producer["addon_tree"],
            "wheel_sha256": self.pin["wheelSha256"], "version": self.config["version"]})

    def install(self, *, baseline):
        config = self.old_config if baseline else self.config
        version = str(config["version"])
        self.host.install_config(config)
        if baseline:
            self.host.supervisor("POST", f"/store/addons/{ADDON}/install", {})
        else:
            self.host.supervisor("POST", f"/store/addons/{ADDON}/update", {})
        # baseline 也有 MCP：seed hook 會在 baseline 建 profile，兩邊用同一個公開網址。
        options = dict(config["options"], admin_username=self.username, admin_password=self.password,
                       mcp_public_base_url=PUBLIC_BASE)
        self.host.supervisor("POST", f"/addons/{ADDON}/options",
                             {"options": options, "boot": "auto", "ingress_panel": True})
        # update may restart the add-on before new options are applied.
        self.host.supervisor("POST", f"/addons/{ADDON}/restart" if not baseline else
                             f"/addons/{ADDON}/start", {})
        self.wait_addon(version)
        self.container = self.host.verify_guest_image(
            self.old_image["Id"] if baseline else self.new_image["Id"])
        if not baseline:
            command = "docker exec " + shlex.quote(self.container)
            self.host.ssh(command + " python3 /usr/local/lib/omnigent-build/mcp_artifact.py "
                          "verify-installed --receipt /usr/share/omnigent/artifact-pin.json")
            installed = json.loads(self.host.ssh(
                command + " cat /usr/share/omnigent/artifact-pin.json").stdout)
            require(installed == self.pin, "guest wheel receipt mismatch")
            postgres = self.sql("SHOW server_version")
            migration = self.sql("SELECT version_num FROM alembic_version")
            require(re.fullmatch(r"16\.[0-9]+", postgres), "unexpected guest database version")
            require(re.fullmatch(MIGRATION_HEAD, migration), "invalid migration head")
            listing = self.migrations()
            # 有沒有新 migration 看兩版實際的 migration 檔案，不看版本號。
            new = migration_rule(self.baseline_migrations, listing, migration, BASELINE_MIGRATION)
            self.evidence["guest_database"] = {"postgres": postgres, "migration_head": migration,
                                               "new_migrations": new, "migration_files": len(listing["files"])}
        else:
            migration = self.sql("SELECT version_num FROM alembic_version")
            listing = self.migrations()
            # BASELINE_MIGRATION 是手寫的常數，用 baseline 實際的資料庫與 script head 對照。
            require(migration == BASELINE_MIGRATION and listing["heads"] == [BASELINE_MIGRATION],
                    "baseline does not match the pinned baseline migration head")
            self.baseline_migrations = listing
            self.evidence["baseline_database"] = {"migration_head": migration,
                                                  "migration_files": len(listing["files"])}

    def migrations(self):
        """Migration file names with SHA-256, and the alembic script heads, in the running container."""
        output = self.host.ssh(shlex.join(["docker", "exec", self.container, "python3", "-c",
                                           MIGRATION_LISTING])).stdout
        try:
            listing = json.loads(output)
        except ValueError:
            listing = None
        require(isinstance(listing, dict) and set(listing) == {"files", "heads"}
                and isinstance(listing["files"], dict) and listing["files"]
                and all(isinstance(n, str) and re.fullmatch(r"[A-Za-z0-9_]{1,128}\.py", n)
                        and isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h)
                        for n, h in listing["files"].items())
                and isinstance(listing["heads"], list) and listing["heads"]
                and all(isinstance(h, str) and re.fullmatch(MIGRATION_HEAD, h) for h in listing["heads"]),
                "invalid migration listing")
        return listing

    def sql(self, query):
        return self.host.ssh(shlex.join([
            "docker", "exec", "-u", "postgres", self.container, "psql", "-d",
            "omnigent", "-Atc", query])).stdout.decode().strip()

    def backup(self, name):
        expected = self.old_image["Id"] if name == "baseline" else self.new_image["Id"]
        container = self.host.verify_guest_image(expected)
        command = shlex.join(["docker", "inspect", "--format", "{{.State.StartedAt}}", container])
        before = self.host.ssh(command).stdout.strip()
        result = self.host.supervisor("POST", "/backups/new/partial", {
            "name": name, "addons": [ADDON], "homeassistant": False, "folders": [],
            "compressed": True}, timeout=300)
        slug = result.get("slug")
        require(isinstance(slug, str) and slug.isalnum(), "backup slug missing")
        info = self.host.supervisor("GET", "/backups/" + slug + "/info")
        require(any(a.get("slug") == ADDON for a in info.get("addons", [])),
                "backup does not contain the add-on")
        self.wait_addon(BASELINE_VERSION if name == "baseline" else self.config["version"])
        self.host.verify_guest_image(expected)
        after = self.host.ssh(command).stdout.strip()
        require(before and after and before != after, "cold backup did not restart the add-on")
        return slug

    def restore(self, slug, version, image_id):
        self.host.supervisor("POST", "/backups/" + slug + "/restore/partial",
                             {"addons": [ADDON], "homeassistant": False, "folders": []},
                             timeout=300)
        self.wait_addon(version)
        self.host.verify_guest_image(image_id)
        self.data_preserved()

    def baseline_rollback(self):
        self.restore(self.baseline_backup, BASELINE_VERSION, self.old_image["Id"])
        # baseline 也有 MCP API，改看資料庫 head：image 與資料庫都要退回 baseline。
        self.container = self.host.verify_guest_image(self.old_image["Id"])
        migration = self.sql("SELECT version_num FROM alembic_version")
        require(migration == BASELINE_MIGRATION, "baseline rollback kept the candidate database")
        # 沒有新 migration 時 head 兩版相同；上面的 verify_guest_image 已確認執行中的是 baseline
        # image，這裡再確認它和 candidate 是不同的 image，回滾才算分得出兩版。
        require(self.old_image["Id"] != self.new_image["Id"],
                "cannot tell the baseline image from the candidate")
        self.evidence["rollback_database"] = {"migration_head": migration, "image_id": self.old_image["Id"]}

    def tls(self):
        h, p = self.host, self.private
        h.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
               "-subj", "/CN=HAOS acceptance CA", "-keyout", str(p / "ca.key"),
               "-out", str(p / "ca.crt")])
        h.run(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
               "-keyout", str(p / "tls.key"), "-out", str(p / "tls.csr")])
        (p / "tls.ext").write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n"
                                  "extendedKeyUsage=serverAuth\n")
        h.run(["openssl", "x509", "-req", "-in", str(p / "tls.csr"), "-CA", str(p / "ca.crt"),
               "-CAkey", str(p / "ca.key"), "-CAcreateserial", "-days", "1",
               "-extfile", str(p / "tls.ext"), "-out", str(p / "tls.crt")])
        # This is an independent HTTPS MCP proxy; the HA Ingress proxy is
        # exercised separately by the browser. No request-bearing logs.
        conf = f"""
daemon off;
pid {p}/nginx.pid;
error_log {p}/nginx-startup.log warn;
events {{}}
http {{
  access_log off;
  error_log /dev/null crit;
  client_body_temp_path {p}/body;
  proxy_temp_path {p}/proxy;
  fastcgi_temp_path {p}/fastcgi;
  uwsgi_temp_path {p}/uwsgi;
  scgi_temp_path {p}/scgi;
  server {{
    listen 127.0.0.1:{urlsplit(PUBLIC_BASE).port} ssl;
    server_name localhost;
    ssl_certificate {p}/tls.crt;
    ssl_certificate_key {p}/tls.key;
    location /omnigent/mcp/ {{
      proxy_pass {DIRECT}/mcp/;
      proxy_http_version 1.1;
      proxy_set_header Host localhost;
      proxy_set_header Connection "";
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_next_upstream off;
      proxy_read_timeout 30s;
    }}
    location / {{ return 404; }}
  }}
}}
"""
        (p / "nginx.conf").write_text(conf)
        nginx = os.environ.get("NGINX_BINARY", "nginx")
        h.run([nginx, "-t", "-p", str(p), "-c", str(p / "nginx.conf")])
        h.start([nginx, "-p", str(p), "-c", str(p / "nginx.conf")])
        self.ssl_context = ssl.create_default_context(cafile=p / "ca.crt")
        origin = PUBLIC_BASE.removesuffix("/omnigent")
        wait_for(lambda: httpx.get(origin + "/", verify=self.ssl_context,
                                  trust_env=False, timeout=5).status_code == 404,
                 20, "trusted localhost TLS proxy")

    def tls_rpc(self, profile, method, params=None):
        expected = PUBLIC_BASE + "/mcp/private_" + profile["token"]
        require(profile["connection_url"] == expected, "canonical URL mismatch")
        progress = self.evidence.setdefault("tls_rpc", {})
        progress.clear()
        progress.update(method=method if method in ("initialize", "tools/list", "tools/call") else "other",
                        status=None, response_json=False, error=None)
        try:
            with httpx.Client(verify=self.ssl_context, trust_env=False, timeout=30) as c:
                require(not c.cookies, "MCP client unexpectedly has browser cookies")
                r = c.post(expected, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                          "params": params or {}},
                           headers={"Accept": "application/json, text/event-stream"})
                progress["status"] = r.status_code
                result = r.json()
                progress["response_json"] = True
                return r.status_code, result
        except httpx.TimeoutException:
            progress["error"] = "timeout"
            raise
        except httpx.HTTPError:
            progress["error"] = "transport_error"
            raise
        except ValueError:
            progress["error"] = "invalid_json"
            raise

    def tls_methods(self, profile):
        expected = PUBLIC_BASE + "/mcp/private_" + profile["token"]
        require(profile["connection_url"] == expected, "canonical URL mismatch")
        methods = self.evidence.setdefault("tls_methods", {})
        with httpx.Client(verify=self.ssl_context, trust_env=False, timeout=10) as c:
            require(not c.cookies, "MCP client unexpectedly has browser cookies")
            for method in ("GET", "DELETE"):
                progress = methods[method] = {"status": None, "sse": None, "closed": False}
                response = None
                try:
                    # SDK JSON mode affects POST replies. GET opens an SSE
                    # stream; waiting for its complete body times out normally.
                    with c.stream(method, expected, headers={"Accept": "application/json, text/event-stream"}) as response:
                        progress["status"] = response.status_code
                        progress["sse"] = response.headers.get("content-type", "").split(";", 1)[0].lower() == "text/event-stream"
                        if method == "GET":
                            require(response.status_code == 200 and progress["sse"], "MCP GET did not establish SSE")
                        else:
                            require(response.status_code == 405, "stateless MCP DELETE response changed")
                except httpx.TimeoutException:
                    progress["error"] = "timeout"
                    raise
                except httpx.HTTPError:
                    progress["error"] = "transport_error"
                    raise
                finally:
                    progress["closed"] = response is not None and response.is_closed

    def profiles(self):
        progress = self.evidence.setdefault("tls_profiles", {})
        progress["stage"] = "seed"
        api = self.api()
        self.hooks.seed_profiles(api, self.state)
        Path(self.hooks.state_path()).write_text(json.dumps(self.state))
        # Route the existing ACL/history/profile checks through the exact TLS
        # connection_url rather than the hook's direct-HTTP convenience path.
        self.hooks.rpc = self.tls_rpc
        progress["stage"] = "verify_saved_profiles"
        self.hooks.verify_profiles(api, self.state)
        progress["stage"] = "history_acl_and_revocation"
        self.hooks.new_profile_lifecycle(api, self.state)
        progress["stage"] = "tool_count"
        profile = self.state["profiles"]["active"]
        status, result = self.tls_rpc(profile, "tools/list")
        require(status == 200 and len(result["result"]["tools"]) == 15, "unexpected MCP tool count")
        progress["stage"] = "http_methods"
        self.tls_methods(profile)
        progress["stage"] = "complete"

    def invalidate_after_backup(self):
        api = self.api()
        profile = self.state["profiles"]["active"]
        api.ok("DELETE", self.hooks.PROFILE_API + "/" + profile["profile"]["id"])
        self.hooks.check_profile(profile, active=False)

    def candidate_restored(self):
        self.restore(self.candidate_backup, self.config["version"], self.new_image["Id"])
        # Active token was revoked after the backup. It must work again after
        # restoring the backup, while the originally revoked token stays denied.
        self.hooks.verify_profiles(self.api(), self.state)

    def cold_boot(self):
        before = self.host.ssh("cat /proc/sys/kernel/random/boot_id").stdout.strip()
        self.host.cold_shutdown()
        self.host.boot()
        self.host.registry_tunnel()
        after = self.host.ssh("cat /proc/sys/kernel/random/boot_id").stdout.strip()
        require(before != after, "cold boot did not create a new kernel boot")
        self.wait_addon(self.config["version"])
        self.host.verify_guest_image(self.new_image["Id"])
        self.data_preserved()
        self.hooks.verify_profiles(self.api(), self.state)

    def run(self):
        self.evidence["host"] = self.step("KVM and physical disk preflight", self.host.preflight)
        self.host.watch_disk()
        self.step("verified baseline and matching PR artifact", self.inputs)
        self.step("official fresh HAOS disk and one-time SSH key", self.host.prepare_vm)
        self.evidence["haos_image"] = {"url": HAOS_URL, "sha256": HAOS_SHA256}
        self.evidence["supervisor"] = self.step("real HAOS boot and Supervisor readiness", self.host.boot)
        base = self.step("HA Core readiness", self.find_ha)
        self.step("fresh HA owner onboarding", lambda: browser.onboard(base, "haos-owner", self.ha_password))
        self.step("private image registry and image identities", self.registry)
        self.step("Supervisor baseline installation", lambda: self.install(baseline=True))
        self.step("baseline data seed", lambda: self.hook("seed"))
        self.baseline_backup = self.step("Supervisor baseline cold backup", lambda: self.backup("baseline"))
        self.step("Supervisor candidate upgrade and exact wheel", lambda: self.install(baseline=False))
        self.step("old data and MCP lifecycle after upgrade", lambda: self.hook("verify"))
        self.step("trusted localhost HTTPS MCP proxy", self.tls)
        self.step("canonical TLS MCP URL, history ACL and revocation", self.profiles)
        created = self.step("real HA sidebar Ingress and browser URL copy", lambda: browser.ingress(
            base, "haos-owner", self.ha_password, self.username, self.password,
            self.state["member"], PUBLIC_BASE, progress=self.evidence.setdefault("browser", {})))
        self.step("browser-created MCP URL works without HA cookies",
                  lambda: self.hooks.check_profile(created, active=True))
        self.candidate_backup = self.step("Supervisor candidate cold backup", lambda: self.backup("candidate"))
        self.step("observable post-backup profile mutation", self.invalidate_after_backup)
        self.step("Supervisor candidate restore and original profile URLs", self.candidate_restored)
        self.step("clean shutdown and fresh kernel cold boot", self.cold_boot)
        self.step("Supervisor baseline backup rollback", self.baseline_rollback)


def main():
    os.umask(0o077)
    report_dir = Path(os.environ["HAOS_REPORT_DIR"])
    report_dir.mkdir(parents=True, exist_ok=True)
    failure = None
    suite = None
    def interrupted(signum, frame):
        raise InterruptedError("job interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with tempfile.TemporaryDirectory(prefix="haos-", dir=os.environ["RUNNER_TEMP"]) as directory:
        try:
            suite = Acceptance(Path(directory))
            suite.run()
        except Exception as error:
            stack = traceback.extract_tb(error.__traceback__)
            failure = {"phase": suite.phase if suite else "initialization",
                       "exception": type(error).__name__,
                       "source": Path(stack[-1].filename).name + ":" + str(stack[-1].lineno)}
            print("FAIL " + failure["phase"] + " (" + failure["exception"] + ")", flush=True)
        finally:
            if suite:
                try:
                    suite.host.cleanup()
                except Exception:
                    failure = failure or {"phase": "owned cleanup", "exception": "CleanupError"}
            result = safe_report(suite.checks if suite else [], suite.evidence if suite else {}, failure)
            (report_dir / "haos-acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
