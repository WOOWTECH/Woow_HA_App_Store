#!/usr/bin/env python3
"""Static least-privilege checks for the open-design-core GHCR import workflow."""
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/import-core.yml"
SCRIPT_PATH = ROOT / ".github/scripts/import-core.sh"
text = WORKFLOW_PATH.read_text()
workflow = yaml.safe_load(text)
script = SCRIPT_PATH.read_text()
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


# PyYAML reads the bare key `on` as True.
triggers = workflow.get("on", workflow.get(True))
check(isinstance(triggers, dict) and set(triggers) == {"workflow_dispatch"}, "import must be manual (workflow_dispatch only)")
inputs = (triggers or {}).get("workflow_dispatch", {}).get("inputs", {})
check({"tag", "digest"} <= set(inputs) and inputs["tag"].get("required") and inputs["digest"].get("required"), "tag and digest inputs are required")
check(workflow.get("permissions") == {"contents": "read"}, "workflow default permissions must be contents:read only")
jobs = workflow.get("jobs", {})
check(list(jobs) == ["import"], "exactly one import job")
job = jobs.get("import", {})
check(job.get("permissions") == {"contents": "read", "packages": "write"}, "import job gets only contents:read and packages:write")
check(job.get("if") == "github.ref == 'refs/heads/main'", "only the workflow on main may publish")
for ref in re.findall(r"uses:\s*[^\s]+@([^\s#]+)", text):
    check(re.fullmatch(r"[0-9a-f]{40}", ref) is not None, f"action ref must be a full commit SHA: {ref}")
check("persist-credentials: false" in text, "checkout must not persist credentials")
check("secrets.JCR_RO_USERNAME" in text and "secrets.JCR_RO_PASSWORD" in text, "JCR access uses the read-only secrets")
check("secrets.GITHUB_TOKEN" in text and "GHCR_PAT" not in text, "GHCR access uses the job GITHUB_TOKEN, no PAT")
check("${{ inputs." not in "\n".join(str(s.get("run", "")) for s in job.get("steps", [])), "inputs reach run blocks only through env")
check("latest" not in text.lower() and ":latest" not in script, "no latest tag")
for needle, message in [
    ("--preserve-digests", "copy must preserve the manifest digest"),
    ('[ "$(sha_of "$WORK/src.json")" = "$CORE_DIGEST" ]', "source manifest must hash to the input digest"),
    ('"docker://${SRC_IMAGE}:${CORE_TAG}"', "the approved JCR tag must resolve to the same digest"),
    ("^[0-9]{8}\\.[0-9]{4}$", "only approved YYYYMMDD.HHMM tags (no -pending-approval candidates)"),
    ('[ "$platform" = "amd64/linux" ]', "core must be amd64/linux"),
    ("io.woow.opendesign.source-revision", "core provenance label must be present"),
    ("tags are immutable", "an existing destination tag with another digest must be refused"),
    ("anonymous", "the job must verify anonymous pulls for Home Assistant"),
]:
    check(needle in script, message)

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
print("import-core workflow policy validation: OK")
