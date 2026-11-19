"""The upgrade test's data check of Frigate (pipeline release-gating/177).

The Store's upgrade test (Woow_HA_App_Store .addon-sync/upgrade_runtime.py)
runs `seed` on the comparison target and `verify` on the new version, on the
same data directories, from the mock Supervisor's container (python3 and
busybox only). mirror-sync copies this directory from .mirror/frigate/ into
frigate/ on every rebuild.

There is no camera, so the data is a Frigate user: the one record Frigate's
own HTTP API creates and reads back without a camera that lives in its
database (frigate.db in /config, the add-on_config directory). Events,
exports and review items all need a camera or recordings. Both hooks go
through ADDON_URL, the unauthenticated web interface on port 5000, where
Frigate's nginx gives every request the admin role. They never touch
frigate.db or config.yml:

seed     Frigate is up (/api/version), a viewer user with a random 24-character
         password is created (POST /api/users), listed back with its role
         (GET /api/users), and logs in with that password (POST /api/login).
verify   Frigate is up on the new version and reports ADDON_VERSION. Frigate
         runs its database migrations (peewee_migrate) in its start-up, before
         its API binds, and exits when one fails, so an answering API means
         they finished. The user is
         still listed with the same role, still logs in with the same
         password (its stored hash survived), and creating (then deleting) a
         new user works on the migrated database.

The password is test-only: it is kept in HOOK_STATE_DIR, never mounted in the
add-on and never printed. Each check goes to $REPORT_DIR/<hook>.json; the hook
exits 1 when one fails. Standard library only (the hooks run on
python:3.12-alpine).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import string
import sys
import time
import urllib.error
import urllib.request

READY_TIMEOUT = 300
STATE_FILE = "frigate-seed.json"
ROLE = "viewer"
LIST_WAIT = 30


def hook_timeout() -> int:
    """The Store's hook_timeout: this directory's settings.yaml if it sets one, else the Store's default 600 s.

    Only a top-level `hook_timeout: <seconds>` line is read (the hooks have no YAML library).
    """
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.yaml"), encoding="utf-8") as f:
            for line in f:
                match = re.match(r"""hook_timeout\s*:\s*["']?(\d+)["']?\s*(#.*)?$""", line.rstrip())
                if match:
                    return int(match.group(1))
    except OSError:
        pass
    return 600


HOOK_TIMEOUT = hook_timeout()
# The whole hook ends this far inside hook_timeout, so it always writes its
# report before the Store kills it.
HOOK_BUDGET = max(HOOK_TIMEOUT - 120, HOOK_TIMEOUT // 2)
DEADLINE = time.monotonic() + HOOK_BUDGET


def time_left(cap: float) -> float:
    """At most `cap` seconds, and no more than the hook has left; fails the check once the budget is used up."""
    left = DEADLINE - time.monotonic()
    if left < 1:
        raise AssertionError(f"the hook's {HOOK_BUDGET} s budget is used up (hook_timeout is {HOOK_TIMEOUT} s)")
    return min(cap, left)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 - urllib's signature
        return None


class Client:
    """Frigate's HTTP API on the unauthenticated port (ADDON_URL, port 5000)."""

    def __init__(self) -> None:
        self.base = os.environ["ADDON_URL"].rstrip("/")
        # No redirects: an answer that redirects (to /login) is reported as it is.
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method: str, path: str, body: object | None = None,
                timeout: float = 30) -> tuple[int, bytes, dict[str, str]]:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        timeout = time_left(timeout)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers or {})
        except (urllib.error.URLError, OSError) as error:
            return 0, str(error).encode(), {}

    def call(self, method: str, path: str, body: object | None = None) -> object:
        code, raw, _ = self.request(method, path, body)
        if code != 200:
            raise AssertionError(f"{method} /api{path.removeprefix('/api')} -> {code}: {raw[:300].decode(errors='replace')}")
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as error:
            raise AssertionError(f"{method} {path} is not JSON: {raw[:200].decode(errors='replace')}") from error

    def wait_version(self) -> str:
        """/api/version until it answers 200: Frigate has migrated its database and its API is up."""
        deadline = time.monotonic() + time_left(READY_TIMEOUT)
        while True:
            code, raw, _ = self.request("GET", "/api/version", timeout=10)
            text = raw.decode(errors="replace").strip()
            if code == 200 and text:
                return text
            if time.monotonic() > deadline - 2:
                raise AssertionError(f"no /api/version within the wait: last {code} {text[:200]}")
            time.sleep(3)

    def users(self) -> list[dict]:
        users = self.call("GET", "/api/users")
        assert isinstance(users, list), f"GET /api/users is not a list: {users!r}"[:300]
        return users

    def login(self, user: str, password: str) -> str:
        """POST /api/login: 200 with a JWT cookie when the stored password hash matches."""
        code, raw, headers = self.request("POST", "/api/login", {"user": user, "password": password})
        if code != 200:
            raise AssertionError(f"POST /api/login as {user} -> {code}: {raw[:200].decode(errors='replace')}")
        cookie = next((v for k, v in headers.items() if k.lower() == "set-cookie"), "")
        assert "=" in cookie, f"POST /api/login as {user} -> 200 without a session cookie"
        return f"{user} logs in with its password (POST /api/login -> 200, session cookie {cookie.split('=', 1)[0]})"


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


def listed(fr: Client, name: str, present: bool = True) -> dict:
    """The user named `name` from GET /api/users, or (present=False) that none is listed.

    Frigate queues its database writes (SqliteQueueDatabase) and answers POST and DELETE before the write is
    done, so a user created or deleted a moment ago may not be listed yet: retry for up to LIST_WAIT seconds.
    """
    deadline = time.monotonic() + time_left(LIST_WAIT)
    while True:
        matches = [u for u in fr.users() if isinstance(u, dict) and u.get("username") == name]
        if len(matches) == (1 if present else 0):
            return matches[0] if present else {}
        if time.monotonic() > deadline:
            want = "1 user" if present else "no user"
            raise AssertionError(f"GET /api/users lists {len(matches)} users named {name} after {LIST_WAIT} s, "
                                 f"{want} expected")
        time.sleep(1)


def new_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(24))


def seed() -> int:
    checks, state = Checks(), {}
    fr = Client()

    def up() -> str:
        state["version"] = fr.wait_version()
        return f"/api/version -> {state['version']}"
    ready = checks.run("Frigate up (/api/version)", up)

    name = f"woow_upgrade_{secrets.token_hex(4)}"
    password = new_password()

    def user() -> str:
        fr.call("POST", "/api/users", {"username": name, "password": password, "role": ROLE})
        got = listed(fr, name)
        assert got.get("role") == ROLE, f"user {name} is listed with role {got.get('role')!r}, created as {ROLE!r}"
        state["user"] = {"username": name, "password": password, "role": ROLE}
        # Written now, so verify still has the user when a later check fails.
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f)
        return f"user {name} (role {ROLE}) created and listed (POST/GET /api/users)"
    made = checks.run("user created", user, bool(ready))

    checks.run("user logs in", lambda: fr.login(name, password), bool(made))
    return checks.finish("seed")


def verify() -> int:
    checks = Checks()
    fr = Client()

    def read_state() -> dict:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict) and isinstance(loaded.get("user"), dict), \
            f"seed state incomplete: {sorted(loaded) if isinstance(loaded, dict) else loaded!r}"
        return loaded
    state = checks.run("seed state readable", read_state)

    def up() -> str:
        version = fr.wait_version()
        want = os.environ.get("ADDON_VERSION", "")
        assert version.split("-")[0] == want, f"/api/version -> {version}, the new version is {want}"
        before = state.get("version") if state else "unknown"
        return (f"/api/version -> {version} ({before} before the upgrade); Frigate runs its database migrations "
                f"before its API binds")
    ready = checks.run("Frigate up on the new version (migrations finished)", up)

    def user_kept() -> str:
        want = state["user"]
        got = listed(fr, want["username"])
        assert got.get("role") == want["role"], \
            f"user {want['username']} has role {got.get('role')!r}, {want['role']!r} before the upgrade"
        return f"user {want['username']} still listed with role {want['role']}"
    kept = checks.run("user still exists", user_kept, bool(ready) and state is not None)

    checks.run("user still logs in with its password",
               lambda: fr.login(state["user"]["username"], state["user"]["password"]), bool(kept))

    def new_user() -> str:
        name = f"woow_upgrade_new_{secrets.token_hex(4)}"
        fr.call("POST", "/api/users", {"username": name, "password": new_password(), "role": ROLE})
        listed(fr, name)
        fr.call("DELETE", f"/api/users/{name}")
        listed(fr, name, present=False)
        return f"user {name} created and deleted"
    checks.run("new user can be created", new_user, bool(ready))
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
