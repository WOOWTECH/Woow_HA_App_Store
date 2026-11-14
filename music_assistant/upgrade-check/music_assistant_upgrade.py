"""The upgrade test's data check of Music Assistant (pipeline release-gating/178).

The Store's upgrade test (Woow_HA_App_Store .addon-sync/upgrade_runtime.py)
runs `seed` on the comparison target and `verify` on the new version, on the
same data directories, from the mock Supervisor's container (172.30.32.2).
Both go through Music Assistant's own HTTP API, never its databases:

seed     the first-time setup (POST /setup, what the setup page posts while no
         user exists) creates a Music Assistant administrator with a password,
         then that administrator creates a playlist with a unique marker in the
         builtin provider (music/playlists/create_playlist on the JSON-RPC
         /api), and it reads back.
verify   Music Assistant answers as the new version, the administrator still
         logs in with its password and the token seed got still works (the
         auth database was kept and migrated), the playlist reads back
         unchanged by id and is found by its marker, a new playlist still
         commits, and the library database is at the new code's schema: a
         failed migration makes Music Assistant start over with an empty
         library, so the seeded playlist surviving a schema change shows the
         migration ran; library.db.backup, the copy it takes before migrating,
         is only looked at (never opened).

The port: ADDON_URL is the ingress port 8094, where Music Assistant signs a
request in only from the X-Remote-User-* headers of a Home Assistant user it
confirms through HA Core; the hooks have no such user. They use Music
Assistant's own webserver on 8095 instead (its default port, on all
interfaces of the add-on's host network, so at ADDON_HOST), with its own
users and Bearer tokens, as any client outside Home Assistant does.

The administrator's password, its token and the playlist's id stay in
HOOK_STATE_DIR for verify, never in the report. Each check goes to
$REPORT_DIR/<hook>.json; the hook exits 1 when one fails.
Standard library only (the hooks run on python:3.12-alpine).
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

PORT = 8095
USERNAME = "woow-upgrade"
# The webserver answers once every core controller is set up; a new version first migrates its databases.
READY_TIMEOUT = 300
CALL_TIMEOUT = 60
# The builtin provider's instance id (create_playlist picks it when no provider is given).
BUILTIN = "builtin"


class HTTPError(AssertionError):
    """An answer that is not 2xx: its status and the start of its body."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path} answered HTTP {status}: {body[:200]}")
        self.status = status


class MusicAssistant:
    """Music Assistant's webserver at http://ADDON_HOST:8095."""

    def __init__(self, host: str) -> None:
        self.base = f"http://{host}:{PORT}"
        self.token = ""

    def request(self, method: str, path: str, body: object = None, token: str | None = None,
                timeout: float = CALL_TIMEOUT) -> object:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        token = self.token if token is None else token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as answer:
                raw = answer.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            raise HTTPError(method, path, error.code, error.read().decode("utf-8", "replace")) from None
        return json.loads(raw) if raw.strip() else None

    def command(self, command: str, token: str | None = None, **args: object) -> object:
        """One command on the JSON-RPC API (POST /api): its result."""
        return self.request("POST", "/api", {"command": command, "message_id": secrets.token_hex(4), "args": args}, token=token)

    def wait_ready(self) -> dict:
        """GET /info answers (it does without a user) with this server's info."""
        deadline, last = time.monotonic() + READY_TIMEOUT, ""
        while True:
            try:
                info = self.request("GET", "/info", timeout=10)
                assert isinstance(info, dict) and info.get("server_version"), f"/info answered {str(info)[:200]}"
                return info
            except (AssertionError, OSError, ValueError) as error:
                last = f"{type(error).__name__}: {str(error)[:200]}"
            if time.monotonic() > deadline:
                raise AssertionError(f"Music Assistant did not answer {self.base}/info within {READY_TIMEOUT} s: {last}")
            time.sleep(3)

    def login(self, password: str) -> str:
        answer = self.request("POST", "/auth/login", {"provider_id": "builtin", "device_name": "woow upgrade test",
                                                      "credentials": {"username": USERNAME, "password": password}}, token="")
        assert isinstance(answer, dict) and answer.get("success") and answer.get("token"), f"/auth/login answered {str(answer)[:200]}"
        return str(answer["token"])

    def playlist(self, item_id: str) -> dict:
        found = self.command("music/playlists/get", item_id=item_id, provider_instance_id_or_domain="library")
        assert isinstance(found, dict), f"music/playlists/get {item_id} answered {str(found)[:200]}"
        return found

    def schema(self) -> dict:
        """{version, db_schema_version} from diagnostics/get (db_schema_version None when the report has no such section)."""
        report = self.command("diagnostics/get")
        assert isinstance(report, dict), f"diagnostics/get answered {str(report)[:200]}"
        music = ((report.get("sections") or {}).get("core.music") or {})
        return {"version": (report.get("system") or {}).get("version"), "db_schema_version": music.get("db_schema_version")}


class Checks:
    """Each check runs even when an earlier one failed, unless it needs what that one made."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def run(self, name: str, check, needs: bool = True) -> object:  # noqa: ANN001 - any callable
        if not needs:
            self.items.append({"name": name, "result": "skip", "detail": "an earlier check it needs failed"})
            print(f"skip {name}", flush=True)
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
    return os.path.join(os.environ["HOOK_STATE_DIR"], "music-assistant-seed.json")


def backup_path() -> str:
    return os.path.join(os.environ["DATA_DIR_DATA"], "library.db.backup")


def seed() -> int:
    ma, checks = MusicAssistant(os.environ["ADDON_HOST"]), Checks()
    marker = f"woow-upgrade-{secrets.token_hex(6)}"
    state: dict[str, object] = {"username": USERNAME, "password": secrets.token_urlsafe(18), "marker": marker}

    def ready() -> str:
        info = ma.wait_ready()
        state["server_version"] = info.get("server_version")
        state["api_schema_version"] = info.get("schema_version")
        return f"Music Assistant {info.get('server_version')} answers {ma.base}/info (API schema {info.get('schema_version')})"
    up = checks.run("Music Assistant ready", ready)

    def setup() -> str:
        answer = ma.request("POST", "/setup", {"username": USERNAME, "password": state["password"],
                                               "display_name": "Woow upgrade test", "device_name": "woow upgrade test"}, token="")
        assert isinstance(answer, dict) and answer.get("success") and answer.get("token"), f"/setup answered {str(answer)[:200]}"
        ma.token = state["token"] = str(answer["token"])
        role = (answer.get("user") or {}).get("role")
        return f"administrator {USERNAME} created through the first-time setup (role {role})"
    admin = checks.run("administrator created", setup, bool(up))

    def playlist() -> str:
        made = ma.command("music/playlists/create_playlist", name=marker)
        assert isinstance(made, dict) and made.get("item_id"), f"create_playlist answered {str(made)[:200]}"
        state["playlist_id"], state["playlist_uri"] = str(made["item_id"]), made.get("uri")
        read = ma.playlist(state["playlist_id"])
        assert read.get("name") == marker, f"playlist {state['playlist_id']} reads back named {read.get('name')!r}"
        return f"playlist {made.get('uri')} named {marker} (library id {state['playlist_id']})"
    checks.run("playlist created", playlist, bool(admin))

    def schema() -> str:
        found = ma.schema()
        state["db_schema_version"] = found["db_schema_version"]
        return f"Music Assistant {found['version']}, library schema {found['db_schema_version']}"
    checks.run("library schema read", schema, bool(admin))
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f)
    return checks.finish("seed")


def verify() -> int:
    ma, checks = MusicAssistant(os.environ["ADDON_HOST"]), Checks()

    def read_state() -> dict[str, object]:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict) and loaded.get("playlist_id") and loaded.get("token"), f"seed state is incomplete: {sorted(loaded)}"
        return loaded
    state = checks.run("seed state readable", read_state) or {}
    seeded = bool(state)
    expected = os.environ.get("ADDON_VERSION", "")

    def ready() -> str:
        info = ma.wait_ready()
        version = str(info.get("server_version"))
        assert not expected or version == expected, f"/info reports Music Assistant {version}, the new version is {expected}"
        return f"Music Assistant {version} answers (was {state.get('server_version')}; API schema {info.get('schema_version')})"
    up = checks.run("new version answers", ready)

    def old_token() -> str:
        ma.command("music/playlists/count", token=str(state["token"]))
        return "the token seed got still authenticates"
    checks.run("token kept", old_token, bool(up) and seeded)

    def login() -> str:
        ma.token = ma.login(str(state["password"]))
        return f"{USERNAME} logs in with its password"
    signed_in = checks.run("administrator logs in", login, bool(up) and seeded)

    def playlist() -> str:
        read = ma.playlist(str(state["playlist_id"]))
        marker = state["marker"]
        assert read.get("name") == marker, f"playlist {state['playlist_id']} reads back named {read.get('name')!r}"
        listed = ma.command("music/playlists/library_items", search=marker, limit=50)
        ids = [str(p.get("item_id")) for p in listed or [] if isinstance(p, dict)]
        assert ids == [str(state["playlist_id"])], f"searching {marker} finds playlists {ids}"
        return f"playlist {state.get('playlist_uri')} reads back named {marker} and is found by its name"
    kept = checks.run("playlist kept", playlist, bool(signed_in))

    def write() -> str:
        name = f"{state['marker']}-after"
        made = ma.command("music/playlists/create_playlist", name=name)
        assert isinstance(made, dict) and made.get("item_id"), f"create_playlist answered {str(made)[:200]}"
        read = ma.playlist(str(made["item_id"]))
        assert read.get("name") == name, f"the new playlist reads back named {read.get('name')!r}"
        return f"a new playlist commits and reads back ({made.get('uri')})"
    checks.run("library writable", write, bool(signed_in))

    def migrated() -> str:
        found = ma.schema()
        before, after = state.get("db_schema_version"), found["db_schema_version"]
        assert after is not None, "diagnostics/get has no core.music db_schema_version"
        backup = os.path.exists(backup_path())
        if before is None:
            return f"library schema {after} (the comparison target did not report one); library.db.backup {'present' if backup else 'absent'}"
        if before == after:
            return f"library schema {after} on both versions: nothing to migrate"
        # Music Assistant copies library.db before migrating and starts over with an empty library when the migration
        # fails: the backup plus the seeded playlist read back above mean the migration ran and kept the library.
        assert backup, f"library schema {before} -> {after} but there is no library.db.backup (Music Assistant takes it before migrating)"
        assert kept, f"library schema {before} -> {after} and the seeded playlist is gone: the migration failed and the library was reset"
        return f"library migrated from schema {before} to {after} and kept the seeded playlist"
    checks.run("library migration finished", migrated, bool(signed_in))
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
