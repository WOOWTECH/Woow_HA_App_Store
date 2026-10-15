"""omnigent-host kit helper (run by supervisor.sh with the omnigent CLI's python).

Canonical copy: woow-paas-charts/shared/omnigent-host/og_helper.py. Charts carry a
byte-identical vendored copy in charts/<chart>/files/omnigent-host/ (see
scripts/sync-omnigent-host-kit.sh); never edit a vendored copy.

Needs only the standard library plus PyYAML (a dependency of omnigent, so its
python always has it). It never prints, logs or returns a token.

Subcommands
-----------
state   Classify the stored Omnigent login. Prints ``key=value`` lines (no secrets):
            verdict=ok|absent|rejected|unreachable
            reason=<short machine word>
            server=<URL the login is stored for, "" when none>
            login_url=<URL to show in "omnigent login <URL>" hints, may be "">
            account=<12 hex chars of sha256(user_id), "-" when unknown>
        Exit codes: 0 ok, 3 absent (never logged in), 4 rejected, 5 unreachable.

        "rejected" is only returned on a DEFINITIVE answer from the server:
          * the access token is fresh (or was just refreshed) and GET /v1/me
            answers 401, and a refresh attempt is refused too (server-side
            revocation, e.g. the Omnigent user was deleted), or
          * the access token has expired and POST /oauth/token answers
            401, or 400 with ``invalid_grant`` / ``expired_token`` (the
            refresh grant was revoked or is past its absolute lifetime), or
          * the token has expired and no refresh material is stored.
        Anything else -- connection errors, timeouts, 5xx, 403, redirects,
        unexpected bodies -- is "unreachable": the host keeps riding the
        outage. The supervisor additionally requires two consecutive
        "rejected" verdicts before it stops a host.

        A refresh performed here is persisted exactly like omnigent does it
        (same JSON shape, flock on <data-dir>/auth_tokens.lock, 0600 temp
        file + atomic rename, parent directory 0700), so the host and the
        tenant's CLI keep working with the renewed token.

seed    Merge the platform defaults into config.yaml without destroying tenant
        settings. Prints one line per change/decision (no secrets).
          * identity: if a ``host:`` mapping exists, its host_id is kept and
            only ``name`` is set to $OG_HOST_NAME; if there is no ``host:``
            block, ``host: {name: $OG_HOST_NAME}`` is written and omnigent
            generates the host_id on first start (ids are never invented
            here). Empty $OG_HOST_NAME leaves the block alone.
          * telemetry: ``telemetry: false`` is enforced (platform policy).
          * providers: each entry named in $OG_PROVIDERS (claude-subscription,
            pi-original) is added at most once per volume (marker file in
            $OG_STATE_DIR), and only when the tenant has no entry of that name
            and no other entry already claims the same default.
        Exit 1 when config.yaml cannot be parsed (it is then left untouched).

workspace
        Seed the session workspace $OG_WORKSPACE from $OG_WORKSPACE_SEED_DIR
        (flat ConfigMap keys: "a__b" means "a/b") and keep a manifest of what was
        seeded in $OG_STATE_DIR/workspace-seed.json (no secrets). The tenant
        always wins:
          * a file is written only if it does not exist yet; an existing file
            the kit did not write is recorded as the tenant's and never touched;
          * a seeded file the tenant deleted is recorded as deleted and never
            re-created (opt-out survives restarts and chart upgrades);
          * a seeded file the tenant has not edited (its sha256 still equals
            what was seeded) is updated to a newer seed version only when its
            path is listed in $OG_WORKSPACE_SEED_UPDATE (comma separated);
          * otherwise a newer version is only OFFERED: written next to the
            workspace as .omnigent-seed-updates/<path> and reported once.
        Prints one line per change/decision. Exit 0 unless the arguments are
        unusable.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REFRESH_MIN_REMAINING_SECONDS = 90.0  # same margin omnigent.cli_auth uses
USER_AGENT = "woow-omnigent-host-supervisor"

PROVIDERS: dict[str, dict[str, object]] = {
    # Claude family through the tenant's own `claude` (Claude Code) login.
    "claude-subscription": {"kind": "subscription", "cli": "claude", "default": True},
    # Omnigent's Pi harness uses pi's own login (PI_CODING_AGENT_DIR).
    "pi-original": {"kind": "subscription", "cli": "pi", "default": "pi"},
}


# ── paths ────────────────────────────────────────────────────────────────────
def _home() -> Path:
    return Path(os.path.expanduser("~"))


def config_path() -> Path:
    ch = os.environ.get("OMNIGENT_CONFIG_HOME")
    return (Path(ch).expanduser() if ch else _home() / ".omnigent") / "config.yaml"


def data_dir() -> Path:
    dd = os.environ.get("OMNIGENT_DATA_DIR")
    return Path(dd).expanduser() if dd else _home() / ".omnigent"


def tokens_path() -> Path:
    return data_dir() / "auth_tokens.json"


def state_dir() -> Path:
    sd = os.environ.get("OG_STATE_DIR")
    return Path(sd).expanduser() if sd else data_dir() / "omnigent-host"


def _norm(url: object) -> str:
    return str(url or "").strip().rstrip("/")


def _clean(value: object) -> str:
    """One-line, printable rendering for key=value output."""
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value))


# ── config.yaml ──────────────────────────────────────────────────────────────
def load_config() -> tuple[dict | None, str | None]:
    """Return (config, None), or (None, reason) when it must not be rewritten."""
    p = config_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, None
    except OSError as exc:
        return None, f"cannot read {p}: {exc.strerror}"
    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None, f"{p} is not valid YAML; left untouched"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"{p} is not a mapping; left untouched"
    return data, None


def env_text(name: str) -> str:
    """$name decoded as UTF-8 (chart values are UTF-8) whatever the locale.

    os.environ decodes with the locale encoding; under an ASCII locale a value
    such as "pi-agent · svc-20c1c915" would become surrogate escapes and be
    written to config.yaml as "\\uDCC2\\uDCB7" garbage.
    """
    envb = getattr(os, "environb", None)
    if envb is not None:
        raw = envb.get(os.fsencode(name))
        return "" if raw is None else raw.decode("utf-8", "replace")
    return os.environ.get(name, "")


def unicode_ok() -> bool:
    """True when omnigent (same python, same env) decodes config.yaml as UTF-8.

    omnigent opens config.yaml with the locale encoding; UTF-8 mode or a UTF-8
    locale (the C/POSIX locale is coerced to UTF-8 since Python 3.7) means a
    host name such as "pi-agent · svc-20c1c915" can be written readably.
    """
    import locale

    if sys.flags.utf8_mode:
        return True
    enc = (locale.getpreferredencoding(False) or "").lower().replace("-", "").replace("_", "")
    return enc == "utf8"


def write_config(cfg: dict) -> None:
    import yaml

    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".config.yaml.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            # Readable UTF-8 ("pi-agent · svc-…") whenever omnigent reads the file as
            # UTF-8; \u escapes otherwise (readable under any locale).
            yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=True, allow_unicode=unicode_ok())
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


# ── auth_tokens.json (omnigent 0.16 format: {server_url: {token, user_id,
#    expires_at, refresh_token?, org_id?}}) ──────────────────────────────────
def load_tokens() -> dict:
    try:
        data = json.loads(tokens_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entry(tokens: dict, server: str) -> dict | None:
    e = tokens.get(_norm(server)) if server else None
    return e if isinstance(e, dict) and isinstance(e.get("token"), str) and e["token"] else None


def write_tokens(data: dict) -> None:
    path = tokens_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, stat.S_IRWXU)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def tokens_lock():
    lock_path = tokens_path().with_suffix(".lock")  # <data-dir>/auth_tokens.lock, as omnigent
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _expires_soon(entry: dict) -> bool:
    exp = entry.get("expires_at", 0)
    if not isinstance(exp, (int, float)):
        return False  # omnigent treats a non-numeric expiry as "does not expire"
    return exp - time.time() < REFRESH_MIN_REMAINING_SECONDS


def _coerce_expires_in(raw: object) -> float:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 3600.0
    return value if math.isfinite(value) and value > 0 else 3600.0


# ── HTTP (no redirects, no Origin header, short timeout) ─────────────────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _http(method: str, url: str, *, data: bytes | None = None, headers: dict | None = None):
    """Return (status, body). status is None on a transport error."""
    timeout = float(os.environ.get("OG_HTTP_TIMEOUT") or 10)
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read(65536)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(65536)
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, body
    except Exception:  # noqa: BLE001 - DNS, refused, timeout, TLS ...: not an auth verdict
        return None, b""


def _json(body: bytes) -> dict:
    try:
        v = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def check_me(server: str, token: str) -> tuple[str, str]:
    """('ok'|'rejected'|'unreachable', reason) for GET /v1/me with this token."""
    status, body = _http("GET", f"{server}/v1/me", headers={"Authorization": f"Bearer {token}"})
    if status is None:
        return "unreachable", "me-transport-error"
    if status == 401:
        return "rejected", "me-401"
    if 200 <= status < 300 and _json(body).get("user_id"):
        return "ok", "me-200"
    return "unreachable", f"me-{status}"


def refresh(server: str, seen_token: str | None) -> tuple[str, str | None, str]:
    """Renew the access token. Returns (verdict, token|None, reason).

    verdict: ok | rejected | unreachable | absent.
    ``seen_token`` is the token the caller already found unusable; a different,
    fresh token found after taking the lock means another process (the host)
    refreshed meanwhile and is used as is.
    """
    with tokens_lock():
        tokens = load_tokens()
        entry = _entry(tokens, server)
        if entry is None:
            return "absent", None, "no-token"
        if entry["token"] != seen_token and not _expires_soon(entry):
            return "ok", entry["token"], "refreshed-elsewhere"
        rt = entry.get("refresh_token")
        if not isinstance(rt, str) or not rt:
            return "rejected", None, "expired-no-refresh-token"
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": rt}).encode()
        status, resp = _http(
            "POST",
            f"{server}/oauth/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status is None:
            return "unreachable", None, "refresh-transport-error"
        if status == 200:
            payload = _json(resp)
            access = payload.get("access_token")
            if not isinstance(access, str) or not access:
                return "unreachable", None, "refresh-malformed"
            new_rt = payload.get("refresh_token")
            new_entry = dict(entry)
            new_entry["token"] = access
            new_entry["expires_at"] = time.time() + _coerce_expires_in(payload.get("expires_in"))
            new_entry["refresh_token"] = new_rt if isinstance(new_rt, str) and new_rt else rt
            tokens[_norm(server)] = new_entry
            try:
                write_tokens(tokens)
            except OSError:
                return "unreachable", None, "refresh-not-persisted"
            return "ok", access, "refreshed"
        err = str(_json(resp).get("error") or "")
        if status == 401:
            return "rejected", None, "refresh-401"
        if status == 400 and err in ("invalid_grant", "expired_token"):
            return "rejected", None, f"refresh-{err}"
        return "unreachable", None, f"refresh-{status}"


def safe_refresh(server: str, seen_token: str | None) -> tuple[str, str | None, str]:
    try:
        return refresh(server, seen_token)
    except OSError:  # lock/state dir unusable: no verdict about the login
        return "unreachable", None, "refresh-state-dir-unusable"


def _account(entry: dict | None) -> str:
    uid = entry.get("user_id") if entry else None
    if not isinstance(uid, str) or not uid:
        return "-"
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:12]


# ── subcommands ──────────────────────────────────────────────────────────────
def cmd_state() -> int:
    cfg, _err = load_config()
    cfg = cfg or {}
    cfg_server = _norm(cfg.get("server"))
    env_server = _norm(os.environ.get("OG_SERVER_URL"))
    tokens = load_tokens()

    server, entry = "", None
    for cand in (cfg_server, env_server):  # the URL of the latest `omnigent login` wins
        e = _entry(tokens, cand)
        if e is not None:
            server, entry = cand, e
            break
    login_url = env_server or cfg_server or server

    def out(verdict: str, reason: str, rc: int) -> int:
        print(f"verdict={verdict}")
        print(f"reason={_clean(reason)}")
        print(f"server={_clean(server)}")
        print(f"login_url={_clean(login_url)}")
        print(f"account={_account(entry)}")
        return rc

    if entry is None:
        return out("absent", "no-token-for-server", 3)

    def after_refresh(rv: str, tok: str | None, why: str, rejected_reason: str) -> int:
        if rv == "ok" and tok:
            v2, why2 = check_me(server, tok)
            if v2 == "ok":
                return out("ok", why, 0)
            if v2 == "rejected":
                return out("rejected", f"revoked:{why2}", 4)
            return out("unreachable", why2, 5)
        if rv == "rejected":
            return out("rejected", f"{rejected_reason}:{why}", 4)
        if rv == "absent":
            return out("absent", why, 3)
        return out("unreachable", why, 5)

    token = entry["token"]
    if not _expires_soon(entry):
        verdict, why = check_me(server, token)
        if verdict == "ok":
            return out("ok", why, 0)
        if verdict == "unreachable":
            return out("unreachable", why, 5)
        # 401 although the local token has not expired: revoked server-side, or
        # only this access token is dead. A refresh tells the two apart.
        rv, tok, rwhy = safe_refresh(server, token)
        return after_refresh(rv, tok, rwhy, "revoked")
    rv, tok, rwhy = safe_refresh(server, token)
    return after_refresh(rv, tok, rwhy, "expired")


def _claims_default(entry: object, scope: str) -> bool:
    if not isinstance(entry, dict):
        return False
    d = entry.get("default")
    if isinstance(d, list):
        return scope in [str(x) for x in d]
    if scope == "pi":
        return str(d) == "pi"
    # claude-subscription's `default: true` claims its family (anthropic)
    return d is True or str(d).lower() in ("true", "anthropic")


def cmd_seed() -> int:
    cfg, err = load_config()
    if cfg is None:
        print(err)
        return 1
    changed: list[str] = []
    markers: list[Path] = []

    want = env_text("OG_HOST_NAME").strip()
    host = cfg.get("host")
    if want:
        if isinstance(host, dict):
            if host.get("name") == want and not want.isascii() and unicode_ok():
                # omnigent rewrites config.yaml with \u escapes (e.g. when it mints
                # the host_id); write the name readably again.
                with contextlib.suppress(OSError):
                    if want not in config_path().read_text(encoding="utf-8"):
                        changed.append(f"host.name {want!r} rewritten readably (was escaped)")
            if host.get("name") != want:
                old = host.get("name")
                host = dict(host)
                host["name"] = want  # host_id (if any) is kept untouched
                cfg["host"] = host
                keep = "host_id kept" if host.get("host_id") else "host_id will be generated by omnigent"
                changed.append(f"host.name -> {want!r} (was {old!r}; {keep})")
        elif host is None:
            cfg["host"] = {"name": want}
            changed.append(f"host.name -> {want!r} (new identity; host_id will be generated by omnigent)")
        else:
            print("host: is not a mapping; identity left untouched")

    if cfg.get("telemetry") is not False:
        cfg["telemetry"] = False
        changed.append("telemetry -> false")

    wanted = [p for p in re.split(r"[,\s]+", os.environ.get("OG_PROVIDERS", "")) if p]
    provs = cfg.get("providers")
    if wanted and provs is not None and not isinstance(provs, dict):
        print("providers: is not a mapping; left untouched")
        wanted = []
    sdir = state_dir()
    for name in wanted:
        if name not in PROVIDERS:
            print(f"unknown provider entry {name!r} in OG_PROVIDERS; ignored")
            continue
        marker = sdir / f"seeded-provider-{name}"
        if marker.exists():
            continue  # decided once per volume; a tenant who removed it keeps it removed
        scope = "pi" if name == "pi-original" else "anthropic"
        current = provs if isinstance(provs, dict) else {}
        if name in current:
            print(f"providers.{name}: kept the tenant's entry")
        elif any(_claims_default(e, scope) for e in current.values()):
            print(f"providers.{name}: not added, another entry already claims the {scope} default")
        else:
            provs = dict(current)
            provs[name] = dict(PROVIDERS[name])
            cfg["providers"] = provs
            changed.append(f"providers.{name} added")
        markers.append(marker)

    if changed:
        write_config(cfg)
        for c in changed:
            print(f"config.yaml: {c}")
    if markers:
        sdir.mkdir(parents=True, exist_ok=True)
        for m in markers:
            m.write_text("1\n", encoding="utf-8")
    return 0


# ── workspace seed (manifest-tracked; the tenant always wins) ───────────────
SEED_MANIFEST = "workspace-seed.json"
SEED_OFFER_DIR = ".omnigent-seed-updates"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _seed_rel(key: str) -> str | None:
    """ConfigMap key -> relative path; None when unsafe."""
    if key.startswith(".."):  # ConfigMap volume internals (..data, ..2026_...)
        return None
    rel = key.replace("__", "/")
    parts = rel.split("/")
    if rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
        return None
    if re.search(r"[\x00-\x1f\x7f\\]", rel):
        return None
    return rel


def _inside(root: Path, target: Path) -> bool:
    """True when target (or, if missing, its nearest existing ancestor) resolves inside root."""
    while not os.path.lexists(target) and target != target.parent:
        target = target.parent
    r = os.path.realpath(root)
    t = os.path.realpath(target)
    return t == r or t.startswith(r + os.sep)


def _write_atomic(dst: Path, src: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".og-seed.", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            out.write(inp.read())
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def cmd_workspace() -> int:
    ws_env = os.environ.get("OG_WORKSPACE", "").strip()
    seed_env = os.environ.get("OG_WORKSPACE_SEED_DIR", "").strip()
    if not ws_env or not seed_env or not os.path.isdir(seed_env):
        return 0
    ws, seed = Path(ws_env), Path(seed_env)
    if not ws.is_absolute():
        print(f"OG_WORKSPACE {ws_env!r} is not absolute; not seeded")
        return 2
    updatable = {u.strip().strip("/") for u in os.environ.get("OG_WORKSPACE_SEED_UPDATE", "").split(",") if u.strip()}
    sdir = state_dir()
    mpath = sdir / SEED_MANIFEST
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, dict):
            raise ValueError
    except FileNotFoundError:
        files = {}
    except (OSError, ValueError):
        print(f"{mpath} is unreadable; not seeding (it is never guessed)")
        return 0
    try:
        ws.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"cannot create {ws}: {exc.strerror}; not seeded")
        return 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    changed = False

    def offer(rel: str, src: Path, src_sha: str, entry: dict, why: str) -> None:
        nonlocal changed
        target = ws / SEED_OFFER_DIR / rel
        if not _inside(ws, target.parent):
            return
        if not (target.exists() and _sha256_file(target) == src_sha):
            _write_atomic(target, src)
        if entry.get("offered") != src_sha:
            print(f"{rel}: {why}; a newer version is at {target} (not applied)")
            entry["offered"] = src_sha
            changed = True

    def drop_offer(rel: str, entry: dict) -> None:
        nonlocal changed
        target = ws / SEED_OFFER_DIR / rel
        if target.is_file() and _inside(ws, target):
            with contextlib.suppress(OSError):
                target.unlink()
        if entry.pop("offered", None) is not None:
            changed = True

    for src in sorted(seed.iterdir()):
        rel = _seed_rel(src.name)
        if rel is None:
            if not src.name.startswith(".."):
                print(f"skipping unsafe seed name {src.name!r}")
            continue
        if not src.is_file():
            continue
        src_sha = _sha256_file(src)
        dst = ws / rel
        if not _inside(ws, dst.parent) or (dst.is_symlink() and not _inside(ws, dst)):
            print(f"{rel}: path leaves the workspace (symlink); left alone")
            continue
        entry = files.get(rel)
        if not isinstance(entry, dict):
            if not dst.exists() and not dst.is_symlink():
                _write_atomic(dst, src)
                files[rel] = {"state": "seeded", "sha256": src_sha, "at": now}
                print(f"{rel}: seeded")
            elif dst.is_file() and _sha256_file(dst) == src_sha:
                files[rel] = {"state": "seeded", "sha256": src_sha, "at": now}
                print(f"{rel}: already identical to the seed; tracked")
            else:
                files[rel] = {"state": "tenant", "at": now}
                print(f"{rel}: exists and is the tenant's; never touched")
            changed = True
            continue
        state = entry.get("state")
        if state in ("tenant", "deleted"):
            continue
        if not dst.exists() and not dst.is_symlink():
            entry.update(state="deleted", at=now)
            entry.pop("offered", None)
            print(f"{rel}: deleted by the tenant; will not be re-created")
            changed = True
            continue
        if not dst.is_file():
            continue
        dst_sha = _sha256_file(dst)
        if dst_sha == src_sha:
            if entry.get("sha256") != src_sha:
                entry.update(sha256=src_sha, at=now)
                changed = True
            drop_offer(rel, entry)
            continue
        if dst_sha == entry.get("sha256"):
            if rel in updatable:
                _write_atomic(dst, src)
                entry.update(sha256=src_sha, at=now)
                drop_offer(rel, entry)
                print(f"{rel}: updated to the new seed version (the tenant had not edited it)")
                changed = True
            else:
                offer(rel, src, src_sha, entry, "unedited but not auto-updated")
        else:
            offer(rel, src, src_sha, entry, "edited by the tenant")

    if changed:
        sdir.mkdir(parents=True, exist_ok=True)
        tmp = mpath.with_name(mpath.name + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps({"schema": 1, "workspace": str(ws), "files": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, mpath)
    return 0


def main(argv: list[str]) -> int:
    cmds = {"state": cmd_state, "seed": cmd_seed, "workspace": cmd_workspace}
    # Never crash on a non-ASCII value (host name) under an ASCII locale.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="backslashreplace")
    if len(argv) != 2 or argv[1] not in cmds:
        print("usage: og_helper.py state|seed|workspace", file=sys.stderr)
        return 2
    return cmds[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
