#!/usr/bin/env python3
"""Exact-source build patch. Never discovers/imports the installed runtime.

Requires an explicit --site-packages and --strict. Intended only for root's
reviewed image build; this sidecar exercises it on owned fixture directories.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import stat
import tempfile

HERE = Path(__file__).resolve().parent
TARGET = "omnigent/native/native_bridge_common.py"
BEFORE_SHA256 = "2a80d492f6f844a8da0e7dbb3e8aaec396a2bbd525f6d042ddc3cf2eed6bccc6"


class PatchRefused(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plain_directory(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise PatchRefused("absolute nontraversing site-packages required")
    for item in (path, *path.parents):
        if not stat.S_ISDIR(item.lstat().st_mode):
            raise PatchRefused("absent, nondirectory or symlinked build path")


def regular_bytes(path: Path) -> tuple[bytes, os.stat_result]:
    plain_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 128*1024:
            raise PatchRefused("nonregular, linked or oversized patch source")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(128*1024+1)
        after = os.fstat(fd)
        stable = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_uid,
                            s.st_gid, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if len(data) != info.st_size or stable(after) != stable(info):
            raise PatchRefused("patch source changed while reading")
        return data, info
    finally:
        os.close(fd)


def apply(site_packages: Path, *, check_only: bool = False) -> dict:
    plain_directory(site_packages)
    lock = json.loads((HERE / "source-lock.json").read_text())
    if lock.get("schema") != "native-maintenance-preservation-source-lock-v1" or len(lock["files"]) != 1:
        raise PatchRefused("unexpected patch lock schema or scope")
    spec = lock["files"][0]
    if spec["target"] != TARGET or spec["payload"] != "overlay/" + TARGET or spec["beforeSha256"] != BEFORE_SHA256:
        raise PatchRefused("unexpected exact-source anchor")
    payload, _ = regular_bytes(HERE / spec["payload"])
    if sha(payload) != spec["afterSha256"] or len(payload) != spec["afterBytes"]:
        raise PatchRefused("reviewed payload hash/size mismatch")
    compile(payload, TARGET, "exec")  # Syntax check only; imports are not executed.
    target = site_packages / TARGET
    original, info = regular_bytes(target)
    current = sha(original)
    if current not in (BEFORE_SHA256, spec["afterSha256"]):
        raise PatchRefused("installed source differs from both exact locked states")
    if current == BEFORE_SHA256 and len(original) != spec["beforeBytes"]:
        raise PatchRefused("original size mismatch")
    result = {"target": TARGET, "beforeSha256": current, "afterSha256": spec["afterSha256"],
              "state": "checked" if check_only else "already-applied" if current == spec["afterSha256"] else "applied"}
    if check_only:
        return result
    # Preflight pycache to prevent redirected output; compile under the image's
    # own interpreter so unchecked or optimized old pyc files cannot survive.
    cache = target.parent / "__pycache__"
    if cache.exists() or cache.is_symlink():
        plain_directory(cache)
    else:
        cache.mkdir(mode=0o755)
    for optimization in (0, 1, 2):
        pyc = Path(importlib.util.cache_from_source(str(target), optimization="" if optimization == 0 else optimization))
        if pyc.is_symlink() or (pyc.exists() and not stat.S_ISREG(pyc.lstat().st_mode)):
            raise PatchRefused("unsafe existing compiled-source path")
    if current != spec["afterSha256"]:
        fd, name = tempfile.mkstemp(prefix=".native-maintenance-", dir=target.parent)
        staged = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                if (info.st_uid, info.st_gid) != (os.geteuid(), os.getegid()):
                    os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                stream.flush()
                os.fsync(stream.fileno())
            again, again_info = regular_bytes(target)
            if again != original or (again_info.st_dev, again_info.st_ino) != (info.st_dev, info.st_ino):
                raise PatchRefused("installed source changed before patch commit")
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    for optimization in (0, 1, 2):
        py_compile.compile(str(target), doraise=True, optimize=optimization,
                           invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    if sha(regular_bytes(target)[0]) != spec["afterSha256"]:
        raise PatchRefused("installed patched bytes failed final verification")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(apply(args.site_packages, check_only=args.check_only), sort_keys=True))
    except (OSError, ValueError, KeyError, PatchRefused, py_compile.PyCompileError) as error:
        parser.exit(1, "maintenance preservation patch refused: " + str(error) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
