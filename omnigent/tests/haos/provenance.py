"""Bind the existing PR image to its actual producer checkout and add-on tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile


FILES = ("config.yaml", "Dockerfile", "build/artifact-pin.json")
MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json",
                  "application/vnd.docker.distribution.manifest.v2+json")
CONFIG_TYPES = ("application/vnd.oci.image.config.v1+json",
                "application/vnd.docker.container.image.v1+json")


def hashes(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in FILES}


def validate_source(receipt, head, tree, root):
    expected_head = os.environ["HAOS_HEAD_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", receipt.get("checkout_commit", "")):
        raise RuntimeError("invalid producer checkout")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.get("image_id", "")):
        raise RuntimeError("invalid producer image ID")
    if not (receipt.get("schema") == 1 and head == expected_head == receipt.get("pr_head")
            and tree == receipt.get("addon_tree") and receipt.get("files") == hashes(root)):
        raise RuntimeError("producer add-on content differs from acceptance PR head")


def archive_identity(path, producer_id, *, expected_tag="upgrade-comparison/woow-omnigent:new"):
    """Bind a producer config/manifest ID to the exact saved config bytes.

    Docker's containerd store reports the manifest ID; the legacy store reports
    the config ID. Accept this difference only with a verified archive hash link.
    No archive member is extracted to the filesystem.
    """
    def require(condition):
        if not condition:
            raise RuntimeError("candidate archive image identity mismatch")
    require(isinstance(producer_id, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", producer_id))
    with tarfile.open(path) as archive:
        names = archive.getnames()
        require(len(names) == len(set(names)))
        def read(name):
            require(isinstance(name, str) and not name.startswith("/") and ".." not in Path(name).parts)
            member = archive.getmember(name)
            require(member.isfile() and 0 < member.size <= 1024 * 1024)
            return archive.extractfile(member).read()
        saved = json.loads(read("manifest.json"))
        require(isinstance(saved, list) and len(saved) == 1
                and saved[0].get("RepoTags") == [expected_tag])
        config_name = saved[0]["Config"]
        config = read(config_name)
        config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
        require(config_name in (config_digest[7:] + ".json", "blobs/sha256/" + config_digest[7:]))
        kind = "config"
        if producer_id != config_digest:
            index = json.loads(read("index.json"))
            descriptors = index.get("manifests", [])
            require(index.get("schemaVersion") == 2 and len(descriptors) == 1)
            descriptor = descriptors[0]
            require(descriptor.get("digest") == producer_id and descriptor.get("mediaType") in MANIFEST_TYPES)
            raw = read("blobs/sha256/" + producer_id[7:])
            require("sha256:" + hashlib.sha256(raw).hexdigest() == producer_id
                    and descriptor.get("size") == len(raw))
            manifest = json.loads(raw)
            require(manifest.get("schemaVersion") == 2 and manifest.get("mediaType") in MANIFEST_TYPES)
            reference = manifest.get("config", {})
            require(reference.get("digest") == config_digest and reference.get("size") == len(config)
                    and reference.get("mediaType") in CONFIG_TYPES)
            kind = "manifest"
        return {"config_digest": config_digest, "producer_image_id": producer_id, "producer_id_kind": kind}


def registry_identity(raw_manifest, manifest_digest, raw_config, expected_config):
    """Verify the registry's current manifest against an independently anchored config."""
    def require(condition):
        if not condition:
            raise RuntimeError("registry manifest/config identity mismatch")
    require(isinstance(manifest_digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_digest))
    require(isinstance(expected_config, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_config))
    require("sha256:" + hashlib.sha256(raw_manifest).hexdigest() == manifest_digest)
    manifest = json.loads(raw_manifest)
    require(manifest.get("schemaVersion") == 2 and manifest.get("mediaType") in MANIFEST_TYPES)
    reference = manifest.get("config", {})
    require(reference.get("digest") == expected_config and reference.get("size") == len(raw_config)
            and reference.get("mediaType") in CONFIG_TYPES)
    require("sha256:" + hashlib.sha256(raw_config).hexdigest() == expected_config)
    config = json.loads(raw_config)
    require(config.get("architecture") == "amd64" and config.get("os") == "linux")
    return {"manifest_digest": manifest_digest, "config_digest": expected_config}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def command(argv):
        return subprocess.check_output(argv, text=True).strip()
    receipt = {
        "schema": 1,
        "pr_head": os.environ["HAOS_HEAD_SHA"],
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "checkout_commit": command(["git", "rev-parse", "HEAD"]),
        "addon_tree": command(["git", "rev-parse", "HEAD:omnigent"]),
        "files": hashes(Path("omnigent")),
        "image_id": command(["docker", "image", "inspect", "--format", "{{.Id}}", args.image]),
    }
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
