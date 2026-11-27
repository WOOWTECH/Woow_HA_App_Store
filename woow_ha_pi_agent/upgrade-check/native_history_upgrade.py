"""Store CI data-survival hooks. No SDK, provider, API or maintenance invocation.

Only generated synthetic roots are inspected. The Store owns the environment,
shared data mount and private HOOK_STATE_DIR. These are test trust boundaries,
not an authentication mechanism or production backup/deployment admission.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time


SCHEMA = "ha-native-history-synthetic-seed/v1"
MANIFEST = "native-history-seed.json"
SEAL = "native-history-seed.sha256"
NATIVE = ("pi-agent", "home", ".omnigent", "codex-native")
PASEO = ("pi-agent", "pi-paseo", "daemon")
MAX_FILE = 4096
MAX_STATE = 16384
MAX_ENTRIES = 64
MAX_DEPTH = 8
DAY_NS = 86400 * 1_000_000_000
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class Refused(ValueError):
    """Stable codes contain no data paths or payload bytes."""


def require(condition, code):
    if not condition:
        raise Refused(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def absolute(value):
    require(type(value) is str and 0 < len(value) <= 4096 and "\x00" not in value, "path")
    path = Path(value)
    require(path.is_absolute() and str(path) == value and ".." not in path.parts, "path")
    return path


@contextmanager
def relative_directory(parent, parts, create=False):
    fd = os.dup(parent)
    try:
        for part in parts:
            require(part not in ("", ".", "..") and "/" not in part, "path")
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def directory(path):
    root = os.open("/", DIR_FLAGS)
    try:
        with relative_directory(root, absolute(str(path)).parts[1:]) as fd:
            yield fd
    finally:
        os.close(root)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_regular(parent, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit, "file_type_or_bound")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(4096, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= limit, "file_bound")
        require(size == before.st_size and fingerprint(before) == fingerprint(os.fstat(fd)), "file_changed")
        data = b"".join(chunks)
        return data, {"sha256": digest(data), "bytes": size, "mode": stat.S_IMODE(before.st_mode),
                      "uid": before.st_uid, "gid": before.st_gid, "mtimeNs": before.st_mtime_ns}
    finally:
        os.close(fd)


def write_new(parent, name, data, mode=0o600, aged_ns=None):
    require(len(data) <= MAX_STATE, "write_bound")
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            require(written > 0, "write")
            view = view[written:]
        if aged_ns is not None:
            os.utime(fd, ns=(aged_ns, aged_ns))
        os.fsync(fd)
    finally:
        os.close(fd)


def scopes():
    paths = {key: absolute(os.environ.get(key, "")) for key in ("DATA_DIR_DATA", "HOOK_STATE_DIR", "REPORT_DIR")}
    data, state, report = (paths[k] for k in ("DATA_DIR_DATA", "HOOK_STATE_DIR", "REPORT_DIR"))
    require(not any(a.is_relative_to(b) or b.is_relative_to(a) for a, b in ((data, state), (data, report), (state, report))), "overlapping_scope")
    return paths


def valid_version(value):
    # Store comparison labels include our numbered release candidates. Keep
    # the bounded grammar explicit; labels still do not prove image identity.
    return (type(value) is str and len(value) <= 32
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[1-9][0-9]*)?", value) is not None)


def context(hook):
    paths = scopes()
    require(hook in ("seed", "verify"), "hook")
    require(os.environ.get("PHASE") == ("old" if hook == "seed" else "new"), "phase")
    version, image = os.environ.get("ADDON_VERSION", ""), os.environ.get("ADDON_IMAGE", "")
    require(valid_version(version), "version")
    require(0 < len(image) <= 256 and "\x00" not in image, "image")
    return dict(paths, version=version, imageHash=digest(image.encode()))


def fixtures(nonce):
    require(type(nonce) is str and re.fullmatch(r"[0-9a-f]{32}", nonce) is not None, "nonce")
    homes = {case: digest((SCHEMA + ":" + nonce + ":" + case).encode())[:32]
             for case in ("history", "dead-letter", "zero-byte")}
    require(len(set(homes.values())) == 3, "home_collision")
    marker = nonce.encode()
    cases = {
        "history": {
            "owner.pid": (b"0", 0o600),
            "codex-home/sessions/2026/10/01/rollout-old.jsonl": (b'{"fixture":"' + marker + b'"}\n', 0o600),
            "codex-home/config.toml": (b'# synthetic upgrade fixture ' + marker + b'\n', 0o640),
            "codex-home/auth.json": (b'{"syntheticOnly":"' + marker + b'"}\n', 0o600),
        },
        "dead-letter": {"owner.pid": (b"0", 0o600),
                        "dead_letter.jsonl.1": (b"synthetic undelivered\x00" + marker, 0o640)},
        "zero-byte": {"owner.pid": (b"0", 0o600),
                      "codex-home/sessions/2026/10/01/rollout-empty.jsonl": (b"", 0o600),
                      "dead_letter.jsonl": (b"", 0o600)},
    }
    return homes, {homes[case] + "/" + name: spec for case, files in cases.items() for name, spec in files.items()}


def paseo_fixtures(nonce, aged_ns):
    pairing = ".ha-upgrade-pairing-" + nonce + ".json"
    task_id = "ha-upgrade-" + nonce[:16]
    return {
        pairing: (json.dumps({"syntheticPairingState": nonce}, sort_keys=True, separators=(",", ":")).encode() + b"\n", 0o600),
        "plugin-data/better-paseo/tasks-stops.json": (
            json.dumps({"stops": [{"agentId": task_id, "stoppedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(aged_ns / 1_000_000_000))}]},
                       sort_keys=True, separators=(",", ":")).encode() + b"\n", 0o600),
    }


def expected_records(specs, aged_ns):
    return {path: {"sha256": digest(data), "bytes": len(data), "mode": mode,
                   "uid": os.geteuid(), "gid": os.getegid(), "mtimeNs": aged_ns}
            for path, (data, mode) in specs.items()}


def snapshot(native, homes, specs):
    files, seen_dirs, expected_dirs = {}, set(), set()
    count = 0
    for path in specs:
        parts = path.split("/")
        expected_dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))

    def scan(fd, prefix, depth):
        nonlocal count
        require(depth <= MAX_DEPTH, "depth_bound")
        before = os.fstat(fd)
        with os.scandir(fd) as entries:
            for entry in entries:
                count += 1
                require(count <= MAX_ENTRIES, "entry_bound")
                path = prefix + "/" + entry.name
                info = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    require(path in expected_dirs, "unexpected_directory")
                    seen_dirs.add(path)
                    with relative_directory(fd, (entry.name,)) as child:
                        require((info.st_dev, info.st_ino) == (os.fstat(child).st_dev, os.fstat(child).st_ino), "directory_changed")
                        scan(child, path, depth + 1)
                else:
                    require(path in specs and stat.S_ISREG(info.st_mode), "unexpected_file_or_link")
                    _, files[path] = read_regular(fd, entry.name, MAX_FILE)
        require(fingerprint(before) == fingerprint(os.fstat(fd)), "directory_changed")

    for home in homes.values():
        with relative_directory(native, (home,)) as fd:
            seen_dirs.add(home)
            before = os.fstat(fd)
            scan(fd, home, 0)
            require(fingerprint(before) == fingerprint(os.stat(home, dir_fd=native, follow_symlinks=False)), "home_changed")
    require(set(files) == set(specs) and seen_dirs == expected_dirs, "incomplete_scope")
    return files


def paseo_snapshot(data, specs):
    files = {}
    with relative_directory(data, PASEO) as daemon:
        for path in specs:
            parts = path.split("/")
            with relative_directory(daemon, parts[:-1]) as parent:
                _, files[path] = read_regular(parent, parts[-1], MAX_FILE)
    require(set(files) == set(specs), "paseo_incomplete_scope")
    return files


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_state_key")
        result[key] = value
    return result


def seed(ctx):
    nonce = secrets.token_hex(16)
    homes, specs = fixtures(nonce)
    aged_ns = time.time_ns() - 8 * DAY_NS
    paseo_specs = paseo_fixtures(nonce, aged_ns)
    with directory(ctx["HOOK_STATE_DIR"]) as state:
        for name in (MANIFEST, SEAL):
            try:
                os.stat(name, dir_fd=state, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise Refused("existing_seed_state")
        with directory(ctx["DATA_DIR_DATA"]) as data:
            info = os.fstat(data)
            data_identity = {"dev": info.st_dev, "ino": info.st_ino}
            with relative_directory(data, NATIVE, create=True) as native:
                for home in homes.values():
                    # Atomic exclusive creation; never reuse an existing native home.
                    os.mkdir(home, 0o700, dir_fd=native)
                for path, (payload, mode) in specs.items():
                    parts = path.split("/")
                    with relative_directory(native, parts[:-1], create=True) as parent:
                        write_new(parent, parts[-1], payload, mode, aged_ns)
                captured = snapshot(native, homes, specs)
            with relative_directory(data, PASEO, create=True) as daemon:
                for path, (payload, mode) in paseo_specs.items():
                    parts = path.split("/")
                    with relative_directory(daemon, parts[:-1], create=True) as parent:
                        write_new(parent, parts[-1], payload, mode, aged_ns)
                paseo_captured = paseo_snapshot(data, paseo_specs)
        captured.update({"paseo/" + path: record for path, record in paseo_captured.items()})
        all_specs = {**specs, **{"paseo/" + path: value for path, value in paseo_specs.items()}}
        require(captured == expected_records(all_specs, aged_ns), "seed_readback")
        value = {"schema": SCHEMA, "nonce": nonce, "beforeVersion": ctx["version"],
                 "beforeImageHash": ctx["imageHash"], "dataIdentity": data_identity,
                 "agedNs": aged_ns, "files": captured}
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        write_new(state, MANIFEST, raw)
        write_new(state, SEAL, (digest(raw) + "\n").encode())
    return digest(raw)


def verify(ctx):
    with directory(ctx["HOOK_STATE_DIR"]) as state:
        raw, meta = read_regular(state, MANIFEST, MAX_STATE)
        seal, seal_meta = read_regular(state, SEAL, 65)
    require(meta["mode"] == seal_meta["mode"] == 0o600 and
            meta["uid"] == seal_meta["uid"] == os.geteuid() and
            meta["gid"] == seal_meta["gid"] == os.getegid(), "state_identity")
    require(seal == (digest(raw) + "\n").encode(), "seed_seal")
    value = json.loads(raw, object_pairs_hook=no_duplicates)
    require(type(value) is dict and set(value) == {"schema", "nonce", "beforeVersion", "beforeImageHash", "dataIdentity", "agedNs", "files"}, "state_schema")
    require(value["schema"] == SCHEMA, "state_schema")
    require(valid_version(value["beforeVersion"])
            and value["beforeVersion"] != ctx["version"], "distinct_version_labels")
    require(type(value["beforeImageHash"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["beforeImageHash"]) is not None
            and value["beforeImageHash"] != ctx["imageHash"], "distinct_image_labels")
    aged = value["agedNs"]
    require(type(aged) is int and 0 < aged < time.time_ns() - 7 * DAY_NS, "age_state")
    homes, specs = fixtures(value["nonce"])
    paseo_specs = paseo_fixtures(value["nonce"], aged)
    all_specs = {**specs, **{"paseo/" + path: spec for path, spec in paseo_specs.items()}}
    expected = expected_records(all_specs, aged)
    require(type(value["files"]) is dict and set(value["files"]) == set(expected), "state_scope")
    for path, record in value["files"].items():
        require(type(record) is dict and set(record) == set(expected[path]), "state_record")
        require(all(type(record[k]) is int for k in ("bytes", "mode", "uid", "gid", "mtimeNs")), "state_record_type")
        require(record == expected[path], "state_record")
    with directory(ctx["DATA_DIR_DATA"]) as data:
        identity = value["dataIdentity"]
        require(type(identity) is dict and set(identity) == {"dev", "ino"}
                and all(type(v) is int for v in identity.values()), "data_identity")
        info = os.fstat(data)
        require(identity == {"dev": info.st_dev, "ino": info.st_ino}, "data_identity")
        with relative_directory(data, NATIVE) as native:
            captured = snapshot(native, homes, specs)
        paseo_captured = paseo_snapshot(data, paseo_specs)
        captured.update({"paseo/" + path: record for path, record in paseo_captured.items()})
        require(captured == value["files"], "data_drift")
    return digest(raw)


def main(hook):
    code, manifest_hash = "pass", None
    try:
        ctx = context(hook)
        manifest_hash = seed(ctx) if hook == "seed" else verify(ctx)
    except Refused as error:
        code = str(error)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        code = "fixture_io_or_manifest_invalid"
    passed = code == "pass"
    record = {"checks": [{"name": "bounded-synthetic-native-and-paseo-file-survival", "result": "pass" if passed else "fail",
                           "detail": "native-fixture-v1:" + code}],
              "scope": {"syntheticFilesOnly": True, "maintenanceExecuted": False,
                        "fileSurvivalOnly": True, "productionAdmission": False},
              "files": 11 if passed else 0, "homes": 4 if passed else 0,
              "seedManifestSha256": manifest_hash}
    try:
        # An invalid/overlapping scope must not redirect even a failure report
        # into fixture data or state. Ambiguous environments fail without it.
        with directory(scopes()["REPORT_DIR"]) as report:
            # Store's host reader has a different UID from the hook writer.
            # This public summary has only fixed checks/counts and a synthetic
            # manifest hash; private fixture state keeps write_new's 0600.
            write_new(report, hook + ".json", (json.dumps(record, sort_keys=True) + "\n").encode(), mode=0o644)
    except (OSError, ValueError):
        print("native-fixture-v1:report_refused", file=sys.stderr)
        return 1
    print(json.dumps({"hook": hook, "result": "pass" if passed else "fail", "files": record["files"],
                      "seedManifestSha256": manifest_hash}, sort_keys=True))
    return 0 if passed else 1
