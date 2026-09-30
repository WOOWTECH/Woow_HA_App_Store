#!/usr/bin/env python3
"""The layer cache lives on ghcr, and what it depends on is pinned (issue #155).

A layer keeps its digest only on a cache hit -- a rebuild runs `apt-get
update` and gets new bytes -- and only an unchanged digest spares a host
the download. The GitHub Actions cache could not carry that: it is evicted
after 7 days unused and past 10 GB, and every PR writes to it, which is
how 0.4.1 -> 0.4.2 re-sent 718 MiB on aarch64 and 0 MiB on amd64.

So the Release build reads and writes a registry cache on the same public
package as the version images, CI reads it anonymously and still writes
only to the gha cache, and the two things that decide a layer's bytes --
the compression and the BuildKit version -- are pinned. This freezes that
arrangement the way `test_workflow_triggers.py` freezes the Live-tier
triggers: as a contract on the YAML, not on a build.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PUBLISH = ROOT / ".github/actions/publish-image/action.yml"
CI = ROOT / ".github/workflows/ci.yml"

IMAGE_BASE = "ghcr.io/woowtech/woow-ha-odoo"
ARCHES = ("amd64", "aarch64")
# What the registry cache export has to carry. mode=max keeps the
# intermediate layers; the other three keep the cache a plain OCI image
# that ghcr stores beside the version tags.
CACHE_TO_OPTIONS = ("mode=max", "compression=gzip",
                    "image-manifest=true", "oci-mediatypes=true")


def document(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def publish_step(uses_prefix: str) -> dict:
    """The `with:` inputs of the publish-image step that uses this action."""
    for step in document(PUBLISH)["runs"]["steps"]:
        if str(step.get("uses", "")).startswith(uses_prefix):
            return step.get("with", {})
    raise AssertionError(f"the publish-image action has no {uses_prefix} step")


def ci_build_step(arch: str) -> dict:
    """The `with:` inputs of CI's build step for this architecture."""
    job = document(CI)["jobs"][f"build-{arch}"]
    for step in job["steps"]:
        if str(step.get("uses", "")).startswith("docker/build-push-action"):
            return step.get("with", {})
    raise AssertionError(f"CI's build-{arch} job has no build-push-action step")


def lines(value: str) -> list:
    return [line.strip() for line in str(value).strip().splitlines() if line.strip()]


# --- the Release build ----------------------------------------------------

@pytest.mark.parametrize("arch", ARCHES)
def test_the_release_build_reads_the_registry_cache_first(arch: str) -> None:
    """The gha cache stays behind it, for the build that finds no :buildcache."""
    cache_from = lines(publish_step("docker/build-push-action")["cache-from"])
    assert cache_from == [
        "type=registry,ref=${{ inputs.image_base }}-${{ inputs.arch }}:buildcache",
        "type=gha,scope=${{ inputs.arch }}",
    ], "the registry cache is the Release build's own; gha is only the fallback"
    # The first line resolves to the package the version images live on.
    resolved = (cache_from[0].replace("${{ inputs.image_base }}", IMAGE_BASE)
                .replace("${{ inputs.arch }}", arch))
    assert resolved == f"type=registry,ref={IMAGE_BASE}-{arch}:buildcache"


def test_the_release_build_writes_the_registry_cache_only_from_main() -> None:
    cache_to = str(publish_step("docker/build-push-action")["cache-to"])
    assert "github.ref_name == 'main'" in cache_to, (
        "a manual images-only run on another ref may read the cache but must not write it")
    assert "type=registry" in cache_to and ":buildcache" in cache_to, cache_to
    for option in CACHE_TO_OPTIONS:
        assert option in cache_to, f"the cache export is missing {option}"
    assert "|| ''" in cache_to, "off main the export has to be empty, not something else"


def test_the_image_output_pins_the_compression() -> None:
    outputs = str(publish_step("docker/build-push-action")["outputs"])
    assert "compression=gzip" in outputs, (
        "unpinned, a BuildKit default would decide the layer bytes")
    assert "push=true" in outputs, "the Release build still pushes the version tag"


def test_buildkit_is_pinned_to_a_version() -> None:
    driver_opts = str(publish_step("docker/setup-buildx-action").get("driver-opts", ""))
    assert re.search(r"image=moby/buildkit:v\d+\.\d+\.\d+", driver_opts), (
        f"setup-buildx-action has to pin a BuildKit image version, got {driver_opts!r}")


@pytest.mark.parametrize("arch", ARCHES)
def test_ci_pins_the_same_buildkit(arch: str) -> None:
    """CI writes the gha cache the Release build reads as its fallback."""
    job = document(CI)["jobs"][f"build-{arch}"]
    pins = [step.get("with", {}).get("driver-opts") for step in job["steps"]
            if str(step.get("uses", "")).startswith("docker/setup-buildx-action")]
    release_pin = publish_step("docker/setup-buildx-action")["driver-opts"]
    assert pins == [release_pin], (
        f"build-{arch} builds with a different BuildKit than the Release does")


def test_the_pins_say_what_changing_them_costs() -> None:
    """Criterion 4: a comment, so nobody bumps either one by reflex."""
    comments = [line.strip().lstrip("#").strip()
                for line in PUBLISH.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("#")]
    text = " ".join(comments)
    assert "every digest" in text, "the BuildKit pin needs a comment about digests"
    assert "rebuilds every layer" in text, "the compression pin needs a comment"


# --- CI -------------------------------------------------------------------

@pytest.mark.parametrize("arch", ARCHES)
def test_ci_reads_the_registry_cache_first_then_the_gha_cache(arch: str) -> None:
    step = ci_build_step(arch)
    assert lines(step["cache-from"]) == [
        "type=registry,ref=${{ env.IMAGE_BASE }}-" + f"{arch}:buildcache",
        f"type=gha,scope={arch}",
    ], "the registry cache comes first; the gha cache stays as the fallback"
    assert document(CI)["env"]["IMAGE_BASE"] == IMAGE_BASE


@pytest.mark.parametrize("arch", ARCHES)
def test_ci_writes_only_the_gha_cache(arch: str) -> None:
    cache_to = str(ci_build_step(arch)["cache-to"])
    assert cache_to == f"type=gha,scope={arch},mode=max", (
        "a PR build must not publish its layers as the Release's cache")


@pytest.mark.parametrize("arch", ARCHES)
def test_ci_does_not_log_in_to_ghcr_to_read_the_cache(arch: str) -> None:
    """The package is public, so the read is anonymous and asks for no token."""
    job = document(CI)["jobs"][f"build-{arch}"]
    logins = [step for step in job["steps"]
              if str(step.get("uses", "")).startswith("docker/login-action")]
    assert not logins, f"build-{arch} logs in to a registry it only reads anonymously"
    assert "packages" not in str(job.get("permissions", {})), (
        f"build-{arch} needs no packages permission to read a public package")


# --- the Release notes ----------------------------------------------------

RELEASE = ROOT / ".github/workflows/release.yml"
SIZE_ACTION = "./.github/actions/download-size"


def release_steps() -> list:
    return document(RELEASE)["jobs"]["release"]["steps"]


def step_index(name_or_uses: str) -> int:
    for index, step in enumerate(release_steps()):
        if name_or_uses in (step.get("name"), step.get("uses")):
            return index
    raise AssertionError(f"the release job has no {name_or_uses!r} step")


def test_the_size_step_runs_after_the_images_and_before_the_notes() -> None:
    """It reads manifests, so it needs both images; the notes then read it."""
    assert (step_index("Both images are published")
            < step_index(SIZE_ACTION)
            < step_index("Release notes from the CHANGELOG"))


def test_the_size_step_never_blocks_a_release() -> None:
    step = release_steps()[step_index(SIZE_ACTION)]
    assert step.get("continue-on-error") is True, (
        "a size that cannot be computed must not cost a Release its tag")


def test_the_notes_fall_back_to_a_placeholder_line() -> None:
    notes = release_steps()[step_index("Release notes from the CHANGELOG")]["run"]
    assert "download-size.md" in notes, "the notes append the table the size step wrote"
    assert "Download size: not computed" in notes, (
        "with no table the notes say so rather than silently dropping the line")


def test_an_images_only_run_gets_the_table_in_its_step_summary() -> None:
    job = document(RELEASE)["jobs"]["images-only-size"]
    assert "needs.prepare.outputs.is_release != 'true'" in job["if"]
    assert any(step.get("uses") == SIZE_ACTION for step in job["steps"]), (
        "the images-only path uses the same action, so the table is the same table")


def test_a_release_listing_that_fails_fails_the_size_step() -> None:
    """An empty list of Releases means there is no earlier image at all.

    So the listing must not be allowed to fail quietly: the table would
    then tell every host it has the whole image to download, and the
    warning about the previous Release would never be reached.
    """
    action = yaml.safe_load(
        (ROOT / ".github/actions/download-size/action.yml").read_text(encoding="utf-8"))
    run = action["runs"]["steps"][0]["run"]
    assert "set -euo pipefail" in run
    # Join the backslash continuations so the whole command is one string.
    statements = run.replace("\\\n", " ").splitlines()
    listing = [line for line in statements if "gh release list" in line]
    assert len(listing) == 1, statements
    assert "||" not in listing[0], (
        "a listing that failed must fail the step, not compare against nothing")
