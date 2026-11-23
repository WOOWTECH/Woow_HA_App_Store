#!/usr/bin/env python3
"""Validate the immutable image pin and shared MCP artifact; unresolved receipts fail closed."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
import subprocess
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

UI = "omnigent/server/static/web-ui/"
# 上游基底版本；WOOW build ID 每個基底版本從 mcp.1 起算。
CORE_VERSION = "0.23.0"
BUILD_ID = "mcp.1"
REQUIRED = (
    "omnigent/server/mcp_server.py",
    "omnigent/server/mcp_profile_store.py",
    "omnigent/server/routes/mcp_server_profiles.py",
    "omnigent/db/migrations/versions/za3b4c5d6e7f_add_mcp_server_profiles.py",
    UI + "index.html",
    # MCP profiles 分支與上游 v0.23.0 head 的 merge revision。
    "omnigent/db/migrations/versions/zb4c5d6e7f80_merge_mcp_profiles_and_v0230_head.py",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_receipt(path: Path) -> dict:
    data = json.loads(path.read_text())
    require(isinstance(data, dict), "receipt must be an object")
    require(data.get("schemaVersion") == 1, "unsupported receipt schema")
    require(data.get("coreVersion") == CORE_VERSION, f"expected upstream base {CORE_VERSION}")
    require(data.get("buildId") == BUILD_ID, f"expected WOOW build {BUILD_ID}")
    for name, length in (("sourceCommit", 40), ("wheelSha256", 64), ("uiSha256", 64)):
        require(isinstance(data.get(name), str) and
                re.fullmatch(r"[0-9a-f]{%d}" % length, data[name]) is not None,
                f"{name} unresolved or invalid; use the actual artifact receipt")
    require(isinstance(data.get("wheelImage"), str) and re.fullmatch(
        r"ghcr\.io/woowtech/omnigent-server-kubernetes@sha256:[0-9a-f]{64}", data["wheelImage"]) is not None,
        "wheelImage unresolved or invalid; pin the public Kubernetes candidate digest")
    require(data.get("wheelPath") == f"/opt/woow-artifact/omnigent-{CORE_VERSION}-py3-none-any.whl",
            "unexpected shared wheel path")
    return data


def ui_hash(files: dict[str, bytes]) -> str:
    """Producer contract: canonical JSON of wheel UI paths and file SHA-256."""
    hashes = {UI + name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_wheel(path: Path, receipt: dict) -> None:
    require(hashlib.sha256(path.read_bytes()).hexdigest() == receipt["wheelSha256"],
            "wheel SHA-256 does not match the pinned receipt")
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        require(len(names) == len(set(names)), "duplicate wheel entries")
        require(all(not n.startswith("/") and ".." not in PurePosixPath(n).parts for n in names),
                "unsafe wheel entry")
        require(all(n in names for n in REQUIRED), "wheel is missing MCP modules, migration or UI")
        metadata_names = [n for n in names if n.endswith(".dist-info/METADATA")]
        require(len(metadata_names) == 1, "wheel metadata is ambiguous")
        metadata = Parser().parsestr(wheel.read(metadata_names[0]).decode())
        require(metadata["Name"] == "omnigent" and metadata["Version"] == receipt["coreVersion"],
                "wheel package name/version does not match the receipt")
        ui = {n[len(UI):]: wheel.read(n) for n in names if n.startswith(UI) and not n.endswith("/")}
        require(ui_hash(ui) == receipt["uiSha256"], "UI SHA-256 does not match the pinned receipt")
        require(b"<head>" in ui["index.html"], "UI missing Ingress HTML injection point")
        js = b"\n".join(v for k, v in ui.items() if k.endswith(".js"))
        require(b"__OMNIGENT_BASE_PATH__" in js, "UI missing Ingress base path support")
        require(b"/admin/mcp-server/profiles" in js, "UI missing MCP profile management")
        server = wheel.read(REQUIRED[0])
        require(b"omnigent_session_history" in server, "wheel missing MCP history pagination")
        py = b"\n".join(wheel.read(n) for n in names if n.startswith("omnigent/") and n.endswith(".py"))
        require(b"OMNIGENT_MCP_PUBLIC_BASE_URL" in py and b"connection_url" in py,
                "wheel missing canonical public MCP URL contract")


def verify_artifact(directory: Path, pin: dict) -> None:
    receipt = json.loads((directory / "WOOW_BUILD_RECEIPT.json").read_text())
    require(receipt.get("publishable") is True, "unpublished snapshot cannot become an HA release")
    for name in ("coreVersion", "buildId", "sourceCommit", "wheelSha256", "uiSha256"):
        require(receipt.get(name) == pin[name], f"shared artifact does not match pinned {name}")
    verify_wheel(directory / Path(pin["wheelPath"]).name, pin)
    # The verifier is from the same digest-pinned image. It checks the payload
    # manifest, source identity, migration, UI and inherited security patches.
    subprocess.run([sys.executable, str(directory / "verify.py"), "verify", "--artifact", str(directory),
                    "--source-commit", pin["sourceCommit"]], check=True)


def verify_installed(receipt: dict) -> None:
    import importlib.metadata
    require(importlib.metadata.version("omnigent") == receipt["coreVersion"], "installed version mismatch")
    for module in ("omnigent.server.mcp_server", "omnigent.server.mcp_profile_store",
                   "omnigent.server.routes.mcp_server_profiles"):
        importlib.import_module(module)
    root = Path(importlib.import_module("omnigent").__file__).parent
    require((root / REQUIRED[3].removeprefix("omnigent/")).is_file(), "installed MCP migration missing")
    ui = root / "server/static/web-ui"
    require(ui_hash({p.relative_to(ui).as_posix(): p.read_bytes() for p in ui.rglob("*") if p.is_file()})
            == receipt["uiSha256"], "installed UI does not match the source receipt")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("validate", "pin", "verify-artifact", "verify-wheel", "verify-installed"))
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--wheel", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--dockerfile", type=Path, help="pin also writes defaults for Supervisor source builds")
    ap.add_argument("--artifact", type=Path)
    ap.add_argument("--source-commit")
    ap.add_argument("--wheel-image")
    args = ap.parse_args()
    try:
        receipt = read_receipt(args.receipt)
        if args.wheel_image is not None:
            require(args.wheel_image == receipt["wheelImage"], "build stage image must equal pinned wheelImage")
        if args.source_commit is not None:
            require(args.source_commit == receipt["sourceCommit"], "image revision must equal receipt sourceCommit")
        if args.command == "pin":
            require(args.output is not None, "pin needs --output")
            require(receipt.get("publishable") is True, "cannot pin an unpublished snapshot")
            require(receipt.get("variant") == "server-kubernetes", "use the Kubernetes candidate receipt")
            require(isinstance(receipt.get("architecture"), list) and
                    set(receipt["architecture"]) == {"linux/amd64", "linux/arm64"},
                    "pin needs the combined receipt for both architectures")
            platforms = receipt.get("platforms")
            require(isinstance(platforms, list) and len(platforms) == 2 and
                    {p.get("architecture") for p in platforms} == {"linux/amd64", "linux/arm64"},
                    "pin needs both architecture digests")
            for platform in platforms:
                require(re.fullmatch(r"ghcr\.io/woowtech/omnigent-server-kubernetes@sha256:[0-9a-f]{64}",
                                     platform.get("image", "")) is not None, "invalid architecture image pin")
            for field in ("runId", "runAttempt"):
                require(str(receipt.get(field, "")).isdigit(), f"missing candidate {field}")
            fields = ("schemaVersion", "coreVersion", "buildId", "sourceCommit", "wheelImage", "wheelPath",
                      "wheelSha256", "uiSha256", "platforms", "runId", "runAttempt")
            dockerfile = None
            if args.dockerfile:
                dockerfile = args.dockerfile.read_text()
                for name, value in (("OMNIGENT_WHEEL_IMAGE", receipt["wheelImage"]),
                                    ("OMNIGENT_SOURCE_COMMIT", receipt["sourceCommit"])):
                    dockerfile, count = re.subn(r"^ARG " + name + r"(?:=[^\n]*)?$", "ARG " + name + "=" + value,
                                                dockerfile, count=1, flags=re.M)
                    require(count == 1, f"Dockerfile missing {name}")
            args.output.write_text(json.dumps({k: receipt[k] for k in fields}, indent=2) + "\n")
            if dockerfile is not None:
                args.dockerfile.write_text(dockerfile)
        elif args.command == "verify-artifact":
            require(args.artifact is not None, "verify-artifact needs --artifact")
            verify_artifact(args.artifact, receipt)
        elif args.command == "verify-wheel":
            require(args.wheel is not None, "verify-wheel needs --wheel")
            verify_wheel(args.wheel, receipt)
        elif args.command == "verify-installed":
            verify_installed(receipt)
        print("MCP artifact validation passed")
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        # Keep paths and runtime exception payloads out of public build errors.
        print(f"MCP artifact validation failed: {error if isinstance(error, ValueError) else type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
