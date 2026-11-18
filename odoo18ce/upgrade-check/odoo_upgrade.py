"""The upgrade test's data check of Woow Odoo 18 (pipeline release-gating/149).

The Store's upgrade test (Woow_HA_App_Store .addon-sync/upgrade_runtime.py)
runs `seed` on the comparison target and `verify` on the new version, on the
same data directories, from the mock Supervisor's container (172.30.32.2).
Both go through Odoo's own XML-RPC API, never PostgreSQL:

seed     a database created through Odoo's database service (what the
         database manager does), a partner with a unique marker and an
         attachment kept in the filestore.
verify   Odoo answers, the database is still listed, the administrator logs
         in, the partner and the attachment read back unchanged, a write
         still commits, and the module update finished: no module is left to
         install, upgrade or remove, and every installed module's version in
         the database is the version its manifest in the new image declares.

ADDON_URL is the ingress port 5691: the add-on's nginx lets only the
Supervisor's address in there and proxies every path to Odoo. The 8069 origin
denies the whole add-on network (172.30.32.0/23), so it is not used.

Credentials: the master password is the admin_passwd option, read from
/data/options.json as the Store's hook interface requires (the upgrade test
gives the required admin_passwd one random value for both versions). seed
generates the database administrator's password; it and the record ids are
kept in HOOK_STATE_DIR for verify.

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
import xmlrpc.client

DB = "woow_upgrade"
LOGIN = "admin"
# Odoo's nginx answers 502 until Odoo serves, and a new version first runs the
# maintenance bootstrap over every database (odoo shell) before Odoo starts.
READY_TIMEOUT = 420
# Creating a database installs base and its auto-install modules in one request.
CREATE_TIMEOUT = 600
CALL_TIMEOUT = 120
# Module states that mean an install, upgrade or removal was scheduled and not run.
PENDING_STATES = ["to install", "to upgrade", "to remove"]


class _Transport(xmlrpc.client.Transport):
    """xmlrpc.client's HTTP transport with a socket timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):  # noqa: ANN001 - xmlrpc.client's signature
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class Odoo:
    """Odoo's XML-RPC services (db, common, object) at ADDON_URL."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def service(self, name: str, timeout: float = CALL_TIMEOUT) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(f"{self.base}/xmlrpc/2/{name}", transport=_Transport(timeout), allow_none=True)

    def wait_ready(self) -> str:
        """Odoo's common.version answers through nginx (it answers 502 until Odoo serves)."""
        deadline, last = time.monotonic() + READY_TIMEOUT, ""
        while True:
            try:
                info = self.service("common", timeout=15).version()
                return f"Odoo {info.get('server_version')} answers XML-RPC"
            except (xmlrpc.client.Error, OSError) as error:
                last = f"{type(error).__name__}: {str(error)[:200]}"
            if time.monotonic() > deadline:
                raise AssertionError(f"Odoo did not answer XML-RPC within {READY_TIMEOUT} s: {last}")
            time.sleep(3)

    def server_version(self) -> str:
        return str(self.service("common").version().get("server_version"))

    def databases(self) -> list[str]:
        return list(self.service("db").list())

    def login(self, password: str) -> int:
        uid = self.service("common").authenticate(DB, LOGIN, password, {})
        assert isinstance(uid, int) and uid > 0, f"{LOGIN} could not log in to {DB} (authenticate returned {uid!r})"
        return uid

    def call(self, uid: int, password: str, model: str, method: str, *args: object, **kwargs: object) -> object:
        return self.service("object").execute_kw(DB, uid, password, model, method, list(args), kwargs)


def master_password() -> str:
    """The admin_passwd option from /data/options.json, never printed."""
    path = os.path.join(os.environ["DATA_DIR_DATA"], "options.json")
    try:
        with open(path, encoding="utf-8") as f:
            options = json.load(f)
    except (OSError, ValueError) as exc:
        raise AssertionError(f"{path} is not readable JSON: {exc}") from None
    value = options.get("admin_passwd") if isinstance(options, dict) else None
    assert isinstance(value, str) and value, f"{path} has no admin_passwd"
    return value


def module_versions(odoo: Odoo, uid: int, password: str) -> dict[str, list[str]]:
    """{name: [version in the database, version the manifest on disk declares]} of every installed module."""
    rows = odoo.call(uid, password, "ir.module.module", "search_read", [["state", "=", "installed"]],
                     fields=["name", "latest_version", "installed_version"])
    return {r["name"]: [r["latest_version"] or "", r["installed_version"] or ""] for r in rows}


def modules_settled(odoo: Odoo, uid: int, password: str) -> str:
    """The module update finished: nothing scheduled, and the database is at the versions on disk."""
    pending = odoo.call(uid, password, "ir.module.module", "search_read", [["state", "in", PENDING_STATES]],
                        fields=["name", "state"])
    assert not pending, "modules left scheduled: " + ", ".join(f"{m['name']} ({m['state']})" for m in pending[:20])
    versions = module_versions(odoo, uid, password)
    assert "base" in versions, "base is not installed"
    stale = {n: v for n, v in versions.items() if v[0] != v[1]}
    assert not stale, "database not updated to the code's module versions: " + ", ".join(
        f"{n} {v[0]} (code {v[1]})" for n, v in sorted(stale.items())[:20])
    return f"{len(versions)} modules installed, none scheduled, base {versions['base'][0]}"


class Checks:
    """Each check runs even when an earlier one failed, unless it needs what that one made."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def run(self, name: str, check, needs: bool = True) -> object:  # noqa: ANN001 - any callable
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
    return os.path.join(os.environ["HOOK_STATE_DIR"], "odoo-seed.json")


def attachment_bytes(marker: str) -> bytes:
    return f"Woow Odoo upgrade test attachment {marker}\n".encode()


def seed() -> int:
    odoo, checks = Odoo(os.environ["ADDON_URL"]), Checks()
    marker = f"woow-upgrade-{secrets.token_hex(6)}"
    state: dict[str, object] = {"db": DB, "login": LOGIN, "password": secrets.token_urlsafe(18), "marker": marker}
    ready = checks.run("Odoo ready", odoo.wait_ready)

    def create_database() -> str:
        listed = odoo.databases()
        assert DB not in listed, f"{DB} already exists before seed ({listed})"
        started = time.monotonic()
        # db.create_database(master, name, demo, lang, user password, login): what /web/database/create calls.
        odoo.service("db", timeout=CREATE_TIMEOUT).create_database(master_password(), DB, False, "en_US", state["password"], LOGIN)
        assert DB in odoo.databases(), f"{DB} is not listed after create_database"
        return f"{DB} created through the database service in {time.monotonic() - started:.0f} s"
    created = checks.run("database created", create_database, bool(ready))
    uid = checks.run("administrator logs in", lambda: odoo.login(state["password"]), bool(created))

    def partner() -> str:
        pid = odoo.call(uid, state["password"], "res.partner", "create",
                        {"name": f"Woow upgrade {marker}", "ref": marker, "email": f"{marker}@example.com", "comment": marker})
        state["partner_id"] = pid
        read = odoo.call(uid, state["password"], "res.partner", "read", [pid], fields=["name", "ref"])
        assert read and read[0]["ref"] == marker, f"partner {pid} reads back {read}"
        return f"res.partner {pid} with ref {marker}"
    made = checks.run("partner created", partner, bool(uid))

    def attachment() -> str:
        data = attachment_bytes(marker)
        aid = odoo.call(uid, state["password"], "ir.attachment", "create",
                        {"name": "woow-upgrade.txt", "datas": base64.b64encode(data).decode(), "mimetype": "text/plain",
                         "res_model": "res.partner", "res_id": state["partner_id"]})
        state["attachment_id"] = aid
        read = odoo.call(uid, state["password"], "ir.attachment", "read", [aid], fields=["store_fname", "checksum"])[0]
        assert read["store_fname"], f"attachment {aid} is not in the filestore (store_fname empty)"
        assert read["checksum"] == hashlib.sha1(data).hexdigest(), f"attachment {aid} checksum {read['checksum']}"
        state["attachment_checksum"] = read["checksum"]
        return f"ir.attachment {aid} in the filestore ({read['store_fname']})"
    checks.run("attachment in filestore", attachment, bool(made))

    def versions() -> str:
        state["server_version"] = odoo.server_version()
        state["modules"] = module_versions(odoo, uid, state["password"])
        return modules_settled(odoo, uid, state["password"])
    checks.run("modules installed", versions, bool(uid))
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f)
    return checks.finish("seed")


def verify() -> int:
    odoo, checks = Odoo(os.environ["ADDON_URL"]), Checks()

    def read_state() -> dict[str, object]:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict) and loaded.get("partner_id"), f"seed state has no partner: {sorted(loaded)}"
        return loaded
    state = checks.run("seed state readable", read_state)
    seeded = state is not None
    ready = checks.run("Odoo ready", odoo.wait_ready)
    def database() -> str:
        names = odoo.databases()
        assert DB in names, f"{DB} is not listed: {names}"
        return f"{DB} listed by the database service"
    listed = checks.run("database listed", database, bool(ready))
    uid = checks.run("administrator logs in", lambda: odoo.login(state["password"]), bool(listed) and seeded)
    password = state["password"] if seeded else ""

    def partner() -> str:
        read = odoo.call(uid, password, "res.partner", "read", [state["partner_id"]], fields=["name", "ref", "email", "comment"])
        assert read, f"res.partner {state['partner_id']} is gone"
        marker = state["marker"]
        assert read[0]["ref"] == marker and read[0]["email"] == f"{marker}@example.com", f"res.partner reads back {read[0]}"
        found = odoo.call(uid, password, "res.partner", "search", [["ref", "=", marker]])
        assert found == [state["partner_id"]], f"searching ref {marker} finds {found}"
        return f"res.partner {state['partner_id']} reads back and is found by ref {marker}"
    checks.run("partner kept", partner, bool(uid))

    def attachment() -> str:
        read = odoo.call(uid, password, "ir.attachment", "read", [state["attachment_id"]], fields=["datas", "checksum"])
        assert read, f"ir.attachment {state['attachment_id']} is gone"
        data = base64.b64decode(read[0]["datas"] or "")
        assert data == attachment_bytes(state["marker"]), f"the attachment's content changed ({len(data)} bytes)"
        assert read[0]["checksum"] == state["attachment_checksum"], f"checksum {read[0]['checksum']}"
        return f"ir.attachment {state['attachment_id']} reads back from the filestore"
    checks.run("attachment kept", attachment, bool(uid) and bool(state and state.get("attachment_id")))

    def write() -> str:
        note = f"verified {state['marker']} after the upgrade"
        odoo.call(uid, password, "res.partner", "write", [state["partner_id"]], {"comment": note})
        read = odoo.call(uid, password, "res.partner", "read", [state["partner_id"]], fields=["comment"])
        assert note in (read[0]["comment"] or ""), f"comment reads back {read[0]['comment']!r}"
        return "a write commits and reads back"
    checks.run("database writable", write, bool(uid))

    def settled() -> str:
        detail = modules_settled(odoo, uid, password)
        before = state.get("modules") or {}
        return f"{detail}; Odoo {state.get('server_version')} -> {odoo.server_version()}, base {before.get('base', ['?'])[0]} before"
    checks.run("module update finished", settled, bool(uid))
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
