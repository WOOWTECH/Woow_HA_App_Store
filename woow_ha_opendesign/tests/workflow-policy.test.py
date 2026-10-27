#!/usr/bin/env python3
"""Static least-privilege and immutable-release checks for the CI workflow."""
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/build.yml"
PREFLIGHT_PATH = ROOT / ".github/scripts/release-preflight.sh"
workflow_text = WORKFLOW_PATH.read_text()
workflow = yaml.safe_load(workflow_text)
preflight_text = PREFLIGHT_PATH.read_text()
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


jobs = workflow.get("jobs", {})
required_jobs = {"validate", "smoke", "build-nonrelease", "release-plan", "release-preflight", "release-architecture-gate", "publish-release", "release", "publish-candidate"}
check(required_jobs <= set(jobs), "workflow must separate validation, smoke, non-release build, release plan, preflight, release architecture gate, release publishing, and the Release")
check(workflow.get("permissions") == {"contents": "read"}, "workflow default permissions must be contents:read only")

# A release is a merged version bump on main; a pushed tag must not start one,
# because it would skip the pull request checks (WOOW addon pipeline ADR-0005).
triggers = workflow.get(True, workflow.get("on", {})) or {}
check("tags" not in (triggers.get("push") or {}), "pushing a tag must not trigger the workflow")
check((triggers.get("push") or {}).get("branches") == ["main"], "push must trigger only on main")
check("ref_type" not in workflow_text, "no job may depend on a tag ref")
check("cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow_text, "a newer push must never cancel a main run that may be publishing")
RELEASE_IF = "needs.release-plan.outputs.release == 'true'"

plan = jobs.get("release-plan", {})
plan_text = yaml.safe_dump(plan)
check(plan.get("if") == "github.event_name != 'pull_request' && github.ref == 'refs/heads/main' && ! inputs.candidate_core_image", "release plan must run only on main, never for pull requests")
check(plan.get("permissions") == {"contents": "read"}, "release plan must have only contents:read")
check("gh release view" in plan_text, "release plan must skip a version that already has a Release")

package_writers = [name for name, job in jobs.items() if job.get("permissions", {}).get("packages") == "write"]
check(set(package_writers) == {"publish-release", "publish-candidate"}, "only gated publishers may receive packages:write")
for name in {"validate", "smoke", "build-nonrelease", "release-architecture-gate"}:
    check(jobs.get(name, {}).get("permissions") == {"contents": "read"}, f"{name} must explicitly have only contents:read")

nonrelease = jobs.get("build-nonrelease", {})
nonrelease_text = yaml.safe_dump(nonrelease)
check(set(nonrelease.get("needs", [])) == {"validate", "smoke"}, "non-release architecture builds must require validation and smoke")
check("push: false" in nonrelease_text, "non-release architecture builds must never push")
check("docker/login-action" not in nonrelease_text, "non-release architecture builds must not receive registry credentials")

preflight = jobs.get("release-preflight", {})
preflight_job_text = yaml.safe_dump(preflight)
check(preflight.get("if") == RELEASE_IF, "release preflight must run only when the release plan says so")
check(set(preflight.get("needs", [])) == {"validate", "smoke", "release-plan"}, "release preflight must require validation, smoke, and the release plan")
check(preflight.get("permissions") == {"contents": "read", "packages": "read"}, "release preflight must have read-only contents/package access")
check("./.github/scripts/release-preflight.sh" in preflight_job_text, "release preflight job must invoke the immutable-release check")
check("GHCR_TOKEN" in preflight_job_text, "release preflight must authenticate its read-only registry query")

release_gate = jobs.get("release-architecture-gate", {})
release_gate_job_text = yaml.safe_dump(release_gate)
release_gate_run_text = "\n".join(str(step.get("run", "")) for step in release_gate.get("steps", []))
check(release_gate.get("if") == RELEASE_IF, "release architecture gate must run only when the release plan says so")
check(set(release_gate.get("needs", [])) == {"validate", "smoke", "release-plan", "release-preflight"}, "release architecture gate must wait for validation, smoke, the release plan, and release preflight")
check(release_gate.get("permissions") == {"contents": "read"}, "release architecture gate must have only contents:read")
check("push: false" in release_gate_job_text and "load: true" in release_gate_job_text, "release architecture gate must build local images without publishing")
for needle, message in [
    ("linux/amd64", "release architecture gate must build amd64"),
    ('test "$(id -u)" = 1001', "release architecture gate must execute OpenCode as UID 1001"),
    ('test "$(opencode --version)" = 1.18.33', "release architecture gate must verify the core OpenCode version"),
    ("docker cp tests/container-opencode-byok-e2e.mjs", "release architecture gate must run the native BYOK streaming mock"),
    ("node /tmp/container-opencode-byok-e2e.mjs", "release architecture gate must execute the native BYOK streaming mock in the built image"),
    ("fake BYOK key leaked to container logs", "release architecture gate must reject BYOK key log leakage"),
    ("fake BYOK key leaked to /data persisted artifacts", "release architecture gate must reject BYOK key persistence"),
]:
    check(needle in (release_gate_job_text if needle.startswith("linux/") else release_gate_run_text), message)

publish = jobs.get("publish-release", {})
publish_text = yaml.safe_dump(publish)
check(publish.get("if") == RELEASE_IF, "publishing must run only when the release plan says so")
check(set(publish.get("needs", [])) == {"validate", "smoke", "release-plan", "release-preflight", "release-architecture-gate"}, "every publishing leg must wait for validation, smoke, the release plan, release preflight, and the release architecture gate")
check(publish.get("permissions") == {"contents": "read", "packages": "write"}, "release publisher must have only contents:read and packages:write")
check("push: true" in publish_text, "release publisher must explicitly push")
check("docker/login-action" in publish_text, "release publisher must authenticate to GHCR")

release_job = jobs.get("release", {})
check(release_job.get("if") == RELEASE_IF, "the Release must be created only when the release plan says so")
check(set(release_job.get("needs", [])) == {"release-plan", "publish-release"}, "the Release must wait for the published image")
check(str(release_job.get("uses", "")).startswith("WOOWTECH/Woow_HA_App_Store/.github/workflows/woow-addon-release.yml@"), "the Release must come from the Store's shared workflow")

for needle, message in [
    ('"${GITHUB_REF:-}" != "refs/heads/main"', "preflight must refuse every ref except main"),
    ("version=$(awk -F'\"' '/^version:/ { print $2 }' config.yaml)", "preflight must derive the release version from config.yaml"),
    ('architectures="amd64"', "preflight must inspect the amd64 image name"),
    ('for arch in $architectures; do', "preflight must check every published architecture"),
    ('--user "${GHCR_ACTOR}:${GHCR_TOKEN}"', "preflight must use its read-only token so private existing tags cannot be missed"),
    ('--request GET', "preflight must use a GET that works around GHCR HTTP/2 HEAD framing"),
    ('case "$status" in', "preflight must classify the registry response"),
    ("404)", "preflight may proceed only when the manifest is absent"),
    ("200)", "preflight must reject an existing manifest"),
    ("Registry returned HTTP", "preflight must fail closed on unexpected registry responses"),
]:
    check(needle in preflight_text, message)

candidate = jobs.get("publish-candidate", {})
check(candidate.get("if") == "github.event_name == 'workflow_dispatch' && inputs.candidate_core_image != '' && github.ref != 'refs/heads/main'", "candidate must require explicit non-main dispatch")
check(candidate.get("needs") == "validate", "candidate must require validation")
check(candidate.get("permissions") == {"contents": "read", "packages": "write"}, "candidate cannot write repository contents")
steps = candidate.get("steps", [])
step_names = [step.get("name") for step in steps]
ordered = ["Validate candidate scope and immutable core", "Build candidate locally", "Full candidate container smoke", "Refuse existing candidate tag", "Log in to GHCR after smoke", "Push tested candidate and verify anonymous manifest"]
check(all(name in step_names for name in ordered) and [step_names.index(name) for name in ordered] == sorted(step_names.index(name) for name in ordered), "candidate must smoke before credentials/push with immutable preflight")
build = next((step for step in steps if step.get("name") == "Build candidate locally"), {})
check(build.get("with", {}).get("load") is True and build.get("with", {}).get("push") is False, "candidate build must load without publishing")
check('run: ./tests/container-smoke.sh "$CANDIDATE_IMAGE"' in workflow_text, "candidate must run full container suite")
check('docker push "$CANDIDATE_IMAGE"' in workflow_text, "candidate pushes the tested image without a rebuild")
for name in ["smoke", "build-nonrelease"]:
    check(jobs[name].get("if") == "${{ ! inputs.candidate_core_image }}", "normal builds must defer to the candidate smoke when dispatched")

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
print("workflow release policy validation: OK")
