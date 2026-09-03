#!/usr/bin/env python3
"""Static least-privilege and immutable-release checks for the CI workflow."""
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/build.yml"
PREFLIGHT_PATH = ROOT / ".github/scripts/release-preflight.sh"
workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
preflight_text = PREFLIGHT_PATH.read_text()
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


jobs = workflow.get("jobs", {})
required_jobs = {"validate", "smoke", "build-nonrelease", "release-preflight", "publish-release"}
check(required_jobs <= set(jobs), "workflow must separate validation, smoke, non-release build, preflight, and release publishing")
check(workflow.get("permissions") == {"contents": "read"}, "workflow default permissions must be contents:read only")

package_writers = [name for name, job in jobs.items() if job.get("permissions", {}).get("packages") == "write"]
check(package_writers == ["publish-release"], "only publish-release may receive packages:write")
for name in {"validate", "smoke", "build-nonrelease"}:
    check(jobs.get(name, {}).get("permissions") == {"contents": "read"}, f"{name} must explicitly have only contents:read")

nonrelease = jobs.get("build-nonrelease", {})
nonrelease_text = yaml.safe_dump(nonrelease)
check("github.ref_type != 'tag'" in str(nonrelease.get("if", "")), "non-release architecture builds must exclude tags")
check(set(nonrelease.get("needs", [])) == {"validate", "smoke"}, "non-release architecture builds must require validation and smoke")
check("push: false" in nonrelease_text, "non-release architecture builds must never push")
check("docker/login-action" not in nonrelease_text, "non-release architecture builds must not receive registry credentials")

preflight = jobs.get("release-preflight", {})
preflight_job_text = yaml.safe_dump(preflight)
check("github.ref_type == 'tag'" in str(preflight.get("if", "")), "release preflight must run only for tags")
check(set(preflight.get("needs", [])) == {"validate", "smoke"}, "release preflight must require validation and smoke")
check(preflight.get("permissions") == {"contents": "read", "packages": "read"}, "release preflight must have read-only contents/package access")
check("./.github/scripts/release-preflight.sh" in preflight_job_text, "release preflight job must invoke the immutable-release check")
check("GHCR_TOKEN" in preflight_job_text, "release preflight must authenticate its read-only registry query")

publish = jobs.get("publish-release", {})
publish_text = yaml.safe_dump(publish)
check("github.ref_type == 'tag'" in str(publish.get("if", "")), "publishing must run only for tags")
check(set(publish.get("needs", [])) == {"validate", "smoke", "release-preflight"}, "every publishing leg must wait for validation, smoke, and release preflight")
check(publish.get("permissions") == {"contents": "read", "packages": "write"}, "release publisher must have only contents:read and packages:write")
check("push: true" in publish_text, "release publisher must explicitly push")
check("docker/login-action" in publish_text, "release publisher must authenticate to GHCR")

for needle, message in [
    ('expected="v${version}"', "preflight must derive the exact release tag from config.version"),
    ('"${GITHUB_REF_NAME:-}" != "$expected"', "preflight must reject a non-matching release tag"),
    ('for arch in amd64 aarch64', "preflight must inspect both architecture image names"),
    ('--user "${GHCR_ACTOR}:${GHCR_TOKEN}"', "preflight must use its read-only token so private existing tags cannot be missed"),
    ('--request GET', "preflight must use a GET that works around GHCR HTTP/2 HEAD framing"),
    ('case "$status" in', "preflight must classify the registry response"),
    ("404)", "preflight may proceed only when the manifest is absent"),
    ("200)", "preflight must reject an existing manifest"),
    ("Registry returned HTTP", "preflight must fail closed on unexpected registry responses"),
]:
    check(needle in preflight_text, message)

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
print("workflow release policy validation: OK")
