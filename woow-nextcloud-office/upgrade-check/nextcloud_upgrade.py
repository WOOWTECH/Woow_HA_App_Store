"""The upgrade test's data check of Woow Nextcloud Office (pipeline release-gating/150).

The Store's upgrade test (Woow_HA_App_Store .addon-sync/upgrade_runtime.py)
runs `seed` on the comparison target and `verify` on the new version, on the
same data directories, from the mock Supervisor's container (python3 and
busybox only: no occ, no curl). Both go through Nextcloud's own HTTP API at
ADDON_URL (nginx on port 8000), never its database:

seed     Nextcloud is installed and up (status.php), the admin logs in over
         WebDAV, a file with unique content is uploaded
         (PUT remote.php/dav/files/<admin>/...) and read back.
verify   status.php reports installed, no upgrade needed and not in
         maintenance mode (what `occ status` reports; the add-on runs
         `occ upgrade` before nginx starts), the admin still logs in, the
         file reads back with the same content and the same file id (its
         row in Nextcloud's file cache survived), and a new upload works.

Credentials: the admin the add-on installed with, ADMIN_USER and ADMIN_PASS
from the options the add-on booted with ($DATA_DIR_DATA/options.json, which
Supervisor, or the upgrade test, writes). Both hooks read them there
(pipeline release-gating/157: the upgrade test gives both versions the same
options); the seed state in HOOK_STATE_DIR never holds the password.

Requests carry `Host: localhost` (one of the add-on's trusted_domains); the
add-on's address is not one.

Each check goes to $REPORT_DIR/<hook>.json; the hook exits 1 when one fails.
Standard library only (the hooks run on python:3.12-alpine).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HOST = "localhost"
READY_TIMEOUT = 420
STATE_FILE = "nextcloud-seed.json"
PROPFIND = (b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            b"<d:prop><oc:fileid/><d:getcontentlength/></d:prop></d:propfind>")
NS = {"d": "DAV:", "oc": "http://owncloud.org/ns"}


class Client:
    """Nextcloud over HTTP: status.php, and WebDAV with the admin's basic auth."""

    def __init__(self, base: str, user: str = "", password: str = "") -> None:
        self.base = base.rstrip("/")
        self.user, self.password = user, password
        # No redirects: an answer that redirects (to the login page, to the public host) is reported as it is.
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None,
                auth: bool = True, timeout: float = 60) -> tuple[int, bytes]:
        h = {"Host": HOST, **(headers or {})}
        if auth and self.user:
            h["Authorization"] = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except (urllib.error.URLError, OSError) as error:
            return 0, str(error).encode()

    def status(self) -> dict[str, object]:
        """status.php: installed, maintenance, needsDbUpgrade, version, versionstring."""
        code, raw = self.request("GET", "/status.php", auth=False, timeout=10)
        if code != 200:
            raise AssertionError(f"status.php -> {code}: {raw[:200].decode(errors='replace')}")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AssertionError(f"status.php is not JSON: {raw[:200].decode(errors='replace')}") from error
        assert isinstance(data, dict), f"status.php is not an object: {data!r}"
        return data

    def wait_status(self) -> dict[str, object]:
        """status.php until it reports installed, not in maintenance and no upgrade needed (or the time runs out:
        then the last answer, which the checks report)."""
        deadline, last = time.monotonic() + READY_TIMEOUT, None
        while True:
            try:
                last = self.status()
                if last.get("installed") is True and last.get("maintenance") is False and last.get("needsDbUpgrade") is False:
                    return last
            except AssertionError as error:
                if time.monotonic() > deadline:
                    raise AssertionError(f"no status within {READY_TIMEOUT} s: {error}") from error
            if time.monotonic() > deadline:
                return last
            time.sleep(2)

    def dav(self, name: str = "") -> str:
        return f"/remote.php/dav/files/{urllib.parse.quote(self.user)}/{urllib.parse.quote(name)}"

    def propfind(self, name: str = "") -> dict[str, str]:
        """fileid and getcontentlength of `name` in the admin's files (its root when empty)."""
        code, raw = self.request("PROPFIND", self.dav(name), PROPFIND, {"Depth": "0", "Content-Type": "application/xml"})
        if code != 207:
            raise AssertionError(f"PROPFIND {self.dav(name)} -> {code}: {raw[:200].decode(errors='replace')}")
        root = ET.fromstring(raw)
        out = {}
        for key, tag in (("fileid", "oc:fileid"), ("length", "d:getcontentlength")):
            node = root.find(f".//d:propstat/d:prop/{tag}", NS)
            if node is not None and node.text:
                out[key] = node.text.strip()
        return out

    def login(self) -> str:
        self.propfind()
        return f"PROPFIND {self.dav()} as {self.user} -> 207"

    def put(self, name: str, content: bytes) -> None:
        code, raw = self.request("PUT", self.dav(name), content, {"Content-Type": "text/plain"})
        if code not in (201, 204):
            raise AssertionError(f"PUT {self.dav(name)} -> {code}: {raw[:200].decode(errors='replace')}")

    def get(self, name: str) -> bytes:
        code, raw = self.request("GET", self.dav(name))
        if code != 200:
            raise AssertionError(f"GET {self.dav(name)} -> {code}: {raw[:200].decode(errors='replace')}")
        return raw

    def delete(self, name: str) -> None:
        code, raw = self.request("DELETE", self.dav(name))
        if code not in (204, 200):
            raise AssertionError(f"DELETE {self.dav(name)} -> {code}: {raw[:200].decode(errors='replace')}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 - urllib's signature
        return None


class Checks:
    """Each check runs even when an earlier one failed, unless it needs what that one made."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def run(self, name: str, check, needs: bool = True) -> object:
        if not needs:
            self.items.append({"name": name, "result": "skip", "detail": "an earlier check it needs failed"})
            return None
        try:
            value = check()
        except Exception as error:  # noqa: BLE001 - every failure is a failed check with its reason
            self.items.append({"name": name, "result": "fail", "detail": f"{type(error).__name__}: {error}"[:500]})
            print(f"FAIL {name}: {error}", flush=True)
            return None
        detail = value if isinstance(value, str) else "ok"
        self.items.append({"name": name, "result": "pass", "detail": detail})
        print(f"pass {name}: {detail}", flush=True)
        return value if value is not None else True

    def finish(self, hook: str) -> int:
        with open(os.path.join(os.environ["REPORT_DIR"], f"{hook}.json"), "w", encoding="utf-8") as f:
            json.dump({"checks": self.items}, f, indent=1)
        return 1 if any(c["result"] != "pass" for c in self.items) else 0


def state_path() -> str:
    return os.path.join(os.environ["HOOK_STATE_DIR"], STATE_FILE)


def describe(status: dict[str, object]) -> str:
    keys = ("installed", "maintenance", "needsDbUpgrade", "versionstring")
    return ", ".join(f"{k}={status.get(k)!r}" for k in keys)


def admin_credentials() -> tuple[str, str]:
    """ADMIN_USER and ADMIN_PASS from the options the add-on booted with."""
    path = os.path.join(os.environ["DATA_DIR_DATA"], "options.json")
    with open(path, encoding="utf-8") as f:
        options = json.load(f)
    user, password = options.get("ADMIN_USER"), options.get("ADMIN_PASS")
    assert user, f"{path} has no ADMIN_USER"
    # ADMIN_PASS is required and has no default: without it the add-on installs with a random password it keeps
    # nowhere a hook can read (only in its own /run), so no API can be used as the admin.
    assert password, (f"{path} has no ADMIN_PASS, so the add-on installed with a random admin password; the upgrade "
                      "test must give it one (pipeline release-gating/157: test options)")
    return str(user), str(password)


def seed() -> int:
    checks, state = Checks(), {}
    nc = Client(os.environ["ADDON_URL"])

    def ready() -> str:
        status = nc.wait_status()
        assert status.get("installed") is True and status.get("maintenance") is False \
            and status.get("needsDbUpgrade") is False, describe(status)
        state["version"] = status.get("versionstring")
        return describe(status)
    up = checks.run("Nextcloud installed and up", ready)

    def credentials() -> str:
        nc.user, nc.password = admin_credentials()
        return f"ADMIN_USER {nc.user} from options.json"
    creds = checks.run("admin credentials known", credentials)
    login = checks.run("admin logs in (WebDAV)", nc.login, bool(up) and bool(creds))

    name = f"woow-upgrade-{secrets.token_hex(6)}.txt"
    content = (f"Woow upgrade check {secrets.token_hex(16)}\nseeded on {os.environ.get('ADDON_VERSION')} "
               f"(Nextcloud {state.get('version')})\n資料保留\n").encode()

    def upload() -> str:
        nc.put(name, content)
        assert nc.get(name) == content, "the file read back differs from what was uploaded"
        props = nc.propfind(name)
        assert props.get("fileid"), f"no oc:fileid for {name}: {props}"
        state.update(file=name, sha256=hashlib.sha256(content).hexdigest(), size=len(content), fileid=props["fileid"])
        return f"{name}: {len(content)} bytes, file id {props['fileid']}, reads back the same"
    checks.run("file uploaded (WebDAV PUT)", upload, bool(login))

    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f)
    return checks.finish("seed")


def verify() -> int:
    checks = Checks()
    nc = Client(os.environ["ADDON_URL"])

    def read_state() -> dict[str, object]:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict) and loaded.get("file"), f"seed state incomplete: {sorted(loaded)}"
        return loaded
    state = checks.run("seed state readable", read_state)
    seeded = state is not None

    def credentials() -> str:
        nc.user, nc.password = admin_credentials()
        return f"ADMIN_USER {nc.user} from options.json"
    creds = checks.run("admin credentials known", credentials)

    holder: dict[str, dict[str, object]] = {}

    def answers() -> str:
        holder["status"] = nc.wait_status()
        return describe(holder["status"])
    answered = checks.run("status.php answers", answers)

    def field(key: str, want: bool, meaning: str):
        def check() -> str:
            status = holder["status"]
            assert status.get(key) is want, f"{meaning}: {key}={status.get(key)!r} ({describe(status)})"
            old = state.get("version") if seeded else None
            return f"{key}={want} (Nextcloud {old} -> {status.get('versionstring')})" if key == "needsDbUpgrade" else f"{key}={want}"
        return check
    checks.run("Nextcloud installed", field("installed", True, "not installed"), bool(answered))
    checks.run("no upgrade needed (migrations finished)", field("needsDbUpgrade", False, "an upgrade is still needed"), bool(answered))
    checks.run("not in maintenance mode", field("maintenance", False, "in maintenance mode"), bool(answered))

    login = checks.run("admin logs in (WebDAV)", nc.login, bool(answered) and bool(creds))

    def file_kept() -> str:
        got = nc.get(state["file"])
        assert len(got) == state["size"], f"{state['file']} has {len(got)} bytes, not the {state['size']} seeded ones"
        assert hashlib.sha256(got).hexdigest() == state["sha256"], \
            f"{state['file']} has the seeded {len(got)} bytes but different content (sha256 differs)"
        return f"{state['file']}: same {len(got)} bytes"
    checks.run("file reads back the same", file_kept, bool(login) and seeded)

    def same_id() -> str:
        props = nc.propfind(state["file"])
        assert props.get("fileid") == state["fileid"], f"file id {props.get('fileid')}, {state['fileid']} before the upgrade"
        return f"file id {state['fileid']} (the file cache was kept, not rebuilt)"
    checks.run("file id unchanged", same_id, bool(login) and seeded)

    def new_upload() -> str:
        name, content = f"woow-upgrade-new-{secrets.token_hex(6)}.txt", secrets.token_hex(32).encode()
        nc.put(name, content)
        assert nc.get(name) == content, "the new file read back differs"
        nc.delete(name)
        return f"{name} uploaded, read back and deleted"
    checks.run("new upload works", new_upload, bool(login))
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
