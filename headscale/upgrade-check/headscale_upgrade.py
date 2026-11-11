"""The upgrade test's data check of Woow Headscale VPN (pipeline release-gating/151).

The Store's upgrade test (Woow_HA_App_Store .addon-sync/upgrade_runtime.py)
runs `seed` on the comparison target and `verify` on the new version, on the
same data directories, from the mock Supervisor's container (python3 and
busybox only: no headscale CLI, no curl). Both go through Headscale's own REST
API (/api/v1 on the control plane, port 8080), never its SQLite database:

seed     Headscale is up (/health), the add-on's API key authenticates, a user
         and a reusable pre-auth key for it are created and listed back.
verify   Headscale is up on the new version (it runs its database migrations
         before it serves /health), the add-on still hands out the same API
         key and it still authenticates, the user is still there with the same
         id and name, the pre-auth key is still there with the same id, user,
         reusable and ephemeral flags and expiration time, and creating (then
         deleting) a new user works. The key text and the timestamp's form are
         not compared: a version may list only the key's prefix, or write the
         time another way, and the key is still the same one.

Credentials: the full-admin API key the add-on issues for Headplane on its
first start (services.d/headplane/run, kept in its data directory) and serves
at /_ha_key on the ingress port (ADDON_URL, port 3000), which only answers the
Supervisor's address (172.30.32.2, where the hooks run). The seed state in
HOOK_STATE_DIR keeps only the key's sha256, never the key.

Each check goes to $REPORT_DIR/<hook>.json; the hook exits 1 when one fails.
Standard library only (the hooks run on python:3.12-alpine).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_PORT = 8080
READY_TIMEOUT = 300
STATE_FILE = "headscale-seed.json"
KEY_DAYS = 30


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


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def when(text: object) -> datetime.datetime:
    """A Headscale timestamp, whatever its form (Z or +00:00, with or without fractional seconds), in UTC."""
    plain = re.sub(r"\.\d+", "", str(text)).replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(plain).astimezone(datetime.timezone.utc)


def time_left(cap: float) -> float:
    """At most `cap` seconds, and no more than the hook has left; fails the check once the budget is used up."""
    left = DEADLINE - time.monotonic()
    if left < 1:
        raise AssertionError(f"the hook's {HOOK_BUDGET} s budget is used up (hook_timeout is {HOOK_TIMEOUT} s)")
    return min(cap, left)


class Client:
    """Headscale's REST API with a bearer API key, and the add-on's /_ha_key on the ingress port."""

    def __init__(self) -> None:
        self.api = f"http://{os.environ['ADDON_HOST']}:{API_PORT}"
        self.ingress = os.environ["ADDON_URL"].rstrip("/")
        self.key = ""
        # No redirects: an answer that redirects is reported as it is.
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method: str, url: str, body: object | None = None, auth: bool = True,
                timeout: float = 30) -> tuple[int, bytes]:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth and self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        timeout = time_left(timeout)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except (urllib.error.URLError, OSError) as error:
            return 0, str(error).encode()

    def call(self, method: str, path: str, body: object | None = None, want: int = 200) -> dict:
        code, raw = self.request(method, self.api + path, body)
        if code != want:
            raise AssertionError(f"{method} {path} -> {code}: {raw[:300].decode(errors='replace')}")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as error:
            raise AssertionError(f"{method} {path} is not JSON: {raw[:200].decode(errors='replace')}") from error
        assert isinstance(data, dict), f"{method} {path} is not an object: {data!r}"[:300]
        return data

    def wait_health(self) -> str:
        """/health until it answers 200 (Headscale has opened and migrated its database)."""
        deadline = time.monotonic() + time_left(READY_TIMEOUT)
        while True:
            code, raw = self.request("GET", self.api + "/health", auth=False, timeout=10)
            if code == 200:
                return f"/health -> 200 {raw[:100].decode(errors='replace').strip()}"
            if time.monotonic() > deadline - 2:
                raise AssertionError(f"no /health within the wait: last {code} {raw[:200].decode(errors='replace')}")
            time.sleep(2)

    def version(self) -> str:
        try:
            code, raw = self.request("GET", self.api + "/version", auth=False, timeout=10)
        except AssertionError:  # out of time: the version is only report text
            return "unknown"
        if code != 200:
            return "unknown"
        try:
            return str(json.loads(raw).get("version") or "unknown")
        except (ValueError, AttributeError):
            return raw[:40].decode(errors="replace").strip() or "unknown"

    def wait_key(self) -> str:
        """The add-on's API key from /_ha_key (Headplane's service issues it once Headscale is up)."""
        deadline = time.monotonic() + time_left(READY_TIMEOUT)
        while True:
            code, raw = self.request("GET", self.ingress + "/_ha_key", auth=False, timeout=10)
            key = raw.decode(errors="replace").strip() if code == 200 else ""
            if key and "\n" not in key and " " not in key:
                self.key = key
                return key
            if time.monotonic() > deadline - 2:
                shown = "an empty body" if code == 200 else raw[:120].decode(errors="replace")
                raise AssertionError(f"GET {self.ingress}/_ha_key gave no API key within the wait: {code} {shown}")
            time.sleep(2)

    def users(self) -> list[dict]:
        users = self.call("GET", "/api/v1/user").get("users") or []
        assert isinstance(users, list), f"users is not a list: {users!r}"[:300]
        return users

    def preauthkeys(self, user_id: str) -> list[dict]:
        """Every pre-auth key of the user (the list filtered to it: some versions list every user's keys)."""
        data = self.call("GET", "/api/v1/preauthkey?" + urllib.parse.urlencode({"user": user_id}))
        keys = data.get("preAuthKeys") or []
        assert isinstance(keys, list), f"preAuthKeys is not a list: {keys!r}"[:300]
        return [k for k in keys if str((k.get("user") or {}).get("id")) == str(user_id)]


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


def flag(key: dict, field: str) -> bool:
    """A pre-auth key's boolean field. Headscale always lists it, false too, so a missing or
    non-boolean value means the field was renamed: fail instead of reading it as False."""
    value = key.get(field)
    assert isinstance(value, bool), f"pre-auth key has no boolean {field!r} (fields: {sorted(key)})"
    return value


def key_fields(key: dict) -> dict[str, object]:
    """What verify compares of a pre-auth key."""
    return {"id": str(key.get("id")), "user": str((key.get("user") or {}).get("id")),
            "reusable": flag(key, "reusable"), "ephemeral": flag(key, "ephemeral"),
            "expiration": key.get("expiration")}


def seed() -> int:
    checks, state = Checks(), {}
    hs = Client()
    up = checks.run("Headscale up (/health)", hs.wait_health)
    state["version"] = hs.version() if up else "unknown"

    def api_key() -> str:
        state["api_key_sha256"] = sha256(hs.wait_key())
        hs.users()
        return f"/_ha_key gives the add-on's API key; GET /api/v1/user -> 200 (Headscale {state['version']})"
    auth = checks.run("add-on API key authenticates", api_key, bool(up))

    name = f"woow-upgrade-{secrets.token_hex(4)}"

    def user() -> str:
        made = hs.call("POST", "/api/v1/user", {"name": name}).get("user") or {}
        assert made.get("name") == name and made.get("id"), f"created user is {made!r}"[:300]
        listed = [u for u in hs.users() if u.get("name") == name]
        assert len(listed) == 1 and str(listed[0].get("id")) == str(made["id"]), f"GET /api/v1/user lists {listed!r}"[:300]
        state["user"] = {"id": str(made["id"]), "name": name}
        return f"user {name} (id {made['id']}) created and listed"
    made_user = checks.run("user created", user, bool(auth))

    def preauthkey() -> str:
        expiration = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=KEY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        uid = state["user"]["id"]
        made = hs.call("POST", "/api/v1/preauthkey", {"user": uid, "reusable": True, "ephemeral": False,
                                                       "expiration": expiration, "aclTags": []}).get("preAuthKey") or {}
        assert made.get("id") and made.get("key"), f"created pre-auth key has no id or key: {sorted(made)}"
        listed = [k for k in hs.preauthkeys(uid) if str(k.get("id")) == str(made["id"])]
        assert len(listed) == 1, f"GET /api/v1/preauthkey lists {len(listed)} keys with id {made['id']}"
        fields = key_fields(listed[0])
        assert fields["user"] == uid and fields["reusable"] is True, f"listed key is {fields}"
        when(fields["expiration"])  # verify compares it as a time, so it must read as one now
        state["preauthkey"] = fields
        return f"reusable pre-auth key id {made['id']} for {state['user']['name']}, expires {fields['expiration']}"
    checks.run("pre-auth key created", preauthkey, bool(made_user))

    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f)
    return checks.finish("seed")


def verify() -> int:
    checks = Checks()
    hs = Client()

    def read_state() -> dict[str, object]:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict) and loaded.get("user") and loaded.get("preauthkey"), \
            f"seed state incomplete: {sorted(loaded) if isinstance(loaded, dict) else loaded!r}"
        return loaded
    state = checks.run("seed state readable", read_state)
    seeded = state is not None

    up = checks.run("Headscale up (/health; migrations finished)", hs.wait_health)

    def same_key() -> str:
        key = hs.wait_key()
        assert sha256(key) == state["api_key_sha256"], "/_ha_key gives a different API key than before the upgrade"
        return "/_ha_key gives the API key issued before the upgrade"
    kept = checks.run("add-on API key kept", same_key, bool(up) and seeded)

    def authenticates() -> str:
        hs.users()
        return f"GET /api/v1/user -> 200 (Headscale {state.get('version')} -> {hs.version()})"
    auth = checks.run("add-on API key authenticates", authenticates, bool(kept))

    def user_kept() -> str:
        want = state["user"]
        listed = [u for u in hs.users() if u.get("name") == want["name"]]
        assert len(listed) == 1, f"{len(listed)} users named {want['name']}"
        assert str(listed[0].get("id")) == want["id"], f"user {want['name']} has id {listed[0].get('id')}, {want['id']} before"
        return f"user {want['name']} (id {want['id']})"
    has_user = checks.run("user still exists", user_kept, bool(auth))

    def key_kept() -> str:
        want = state["preauthkey"]
        listed = [k for k in hs.preauthkeys(want["user"]) if str(k.get("id")) == want["id"]]
        assert len(listed) == 1, f"no pre-auth key with id {want['id']} for user id {want['user']}"
        got = key_fields(listed[0])
        for field in ("user", "reusable", "ephemeral"):
            assert got[field] == want[field], f"{field} is {got[field]!r}, {want[field]!r} before the upgrade"
        expires = when(got["expiration"])
        assert expires == when(want["expiration"]), \
            f"expiration is {got['expiration']}, {want['expiration']} before the upgrade"
        assert expires > datetime.datetime.now(datetime.timezone.utc), f"the key expired at {got['expiration']}"
        return f"pre-auth key id {want['id']}: same user, reusable, ephemeral, expiration {got['expiration']}"
    checks.run("pre-auth key still exists", key_kept, bool(has_user))

    def new_user() -> str:
        name = f"woow-upgrade-new-{secrets.token_hex(4)}"
        made = hs.call("POST", "/api/v1/user", {"name": name}).get("user") or {}
        assert made.get("id"), f"created user is {made!r}"[:300]
        hs.call("DELETE", f"/api/v1/user/{made['id']}")
        assert not [u for u in hs.users() if u.get("name") == name], f"{name} is still listed after DELETE"
        return f"user {name} created and deleted"
    checks.run("new user can be created", new_user, bool(auth))
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
