#!/usr/bin/env python3
"""Keep HA bootstrap tokens out of inherited Hermes exec boundaries.

Pinned installed sources: test/fixtures/exec-boundary/PROVENANCE.md.
Validate all sources and the optional installed shim before writing any file.
Exact source hashes and unique anchors
fail closed on drift; reapplication accepts only the complete expected patch.
"""
import argparse
import hashlib
import stat
from pathlib import Path

CLEAR = "# woow: HA bootstrap tokens must not cross an agent exec boundary\nunset SUPERVISOR_TOKEN HASSIO_TOKEN\n"
SPECS = {
    "hermes-exec-shim.sh": (
        "57637e73c8db76aa84a38e4a2edb1b155bfd86a2e89a8d4c38c4546ee1175985",
        ("set -e\n",),
    ),
    "main-wrapper.sh": (
        "d01d7ece5198f79496cf8ce64552665699995f0bf2cabbac78205b6b1779fb9b",
        # Clear before the helper exec AND after it rehydrates the environment.
        ("set -e\n", "unset HERMES_MAIN_WRAPPER_ENV_READY\n"),
    ),
}


def original_source(name, source):
    digest, anchors = SPECS[name]
    original = source
    if CLEAR in source:
        for anchor in anchors:
            if original.count(anchor + CLEAR) != 1:
                raise ValueError(f"{name}: incomplete or duplicate token boundary patch")
            original = original.replace(anchor + CLEAR, anchor, 1)
    if hashlib.sha256(original.encode()).hexdigest() != digest:
        raise ValueError(f"{name}: source hash differs from pinned base; review required")
    for anchor in anchors:
        if original.count(anchor) != 1:
            raise ValueError(f"{name}: expected one anchor {anchor!r}")
    return original


def patched_source(name, source):
    result = original_source(name, source)
    for anchor in SPECS[name][1]:
        result = result.replace(anchor, anchor + CLEAR, 1)
    return result


def check_source(name, source):
    if source != patched_source(name, source):
        raise ValueError(f"{name}: HA exec boundary patch missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/opt/hermes/docker"))
    parser.add_argument("--installed-shim", type=Path,
                        help="Also patch the independent /opt/hermes/bin/hermes copy")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    pending = {}
    targets = [(args.directory / name, name) for name in SPECS]
    if args.installed_shim is not None:
        targets.append((args.installed_shim, "hermes-exec-shim.sh"))
    for path, name in targets:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f"{path.name}: expected regular file, not symlink")
        source = path.read_bytes().decode("utf-8")
        if args.check:
            check_source(name, source)
        else:
            pending[path] = patched_source(name, source)
    for path, source in pending.items():
        path.write_bytes(source.encode("utf-8"))
    print("HA exec token boundaries: " + ("verified" if args.check else "patched/verified"))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(f"[FAIL] {error}")
