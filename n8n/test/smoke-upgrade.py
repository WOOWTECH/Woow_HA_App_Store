#!/usr/bin/env python3
"""Upgrade a real add-on data set from an older add-on image to a new one.

Usage: smoke-upgrade.py <old-image> <new-image> [--executions N]

1. Seeds /data and /config with the old image: owner, an encrypted
   credential, a public API key, an active webhook workflow (JavaScript and
   Python Code nodes) and N executions.
2. Starts the new image on the same directories while a Supervisor-side
   poller records the watchdog endpoint and n8n's readiness every 0.5 s.
3. Verifies the migration: same encryption key, the credential decrypts to
   the seeded value, the workflow is still active and runs, executions and
   the API key survive.
4. Starts the old image on the migrated data to document what a downgrade
   without a backup restore does, then restores the pre-upgrade copy and
   proves the old image runs again from it.
Manual tool (pulls two images); not part of CI.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from smoke_lib import (
    ADDON_IP,
    SUPERVISOR_IP,
    Addon,
    N8nClient,
    activate,
    assert_code_nodes,
    call_webhook,
    docker,
    smoke_workflow,
)

CREDENTIAL_SECRET = "woow-upgrade-credential-secret"
POLL_SCRIPT = (
    "while :; do "
    "w=$(curl -s -o /tmp/w -w '%{http_code}' --max-time 5 http://ADDON:5690/_woow/watchdog); "
    "r=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://ADDON:5678/healthz/readiness); "
    "printf '%s %s %s %s\\n' \"$(date +%s.%N)\" \"$w\" \"$r\" \"$(head -c 20 /tmp/w | tr -d '\\n')\"; "
    "sleep 0.5; done"
).replace("ADDON", ADDON_IP)


def encryption_key(addon: Addon) -> str:
    raw = docker("run", "--rm", "-v", f"{addon.config}:/c:ro", "--entrypoint", "cat",
                 addon.image, "/c/.n8n/config")
    return json.loads(raw)["encryptionKey"]


def api_get(addon: Addon, path: str, key: str) -> tuple[int, object]:
    req = urllib.request.Request(addon.url(path), headers={"X-N8N-API-KEY": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")[:300]


def seed(addon: Addon, executions: int) -> dict[str, object]:
    addon.start()
    print("seed ready:", addon.wait_ready())
    client = N8nClient(addon.url(""))
    client.setup_owner()
    credential = client.ok(
        "POST",
        "/rest/credentials",
        {"name": "Woow upgrade header", "type": "httpHeaderAuth",
         "data": {"name": "X-Woow-Upgrade", "value": CREDENTIAL_SECRET}},
    )
    workflow = client.ok("POST", "/rest/workflows", smoke_workflow("woow-upgrade", "Woow upgrade"))
    activate(client, workflow)
    first = call_webhook(addon, "woow-upgrade")
    print("seed code nodes:", json.dumps(first))
    for _ in range(executions - 1):
        call_webhook(addon, "woow-upgrade")
    _status, scopes = client.request("GET", "/rest/api-keys/scopes")
    scope_list = scopes.get("data", []) if isinstance(scopes, dict) else []
    api_key = client.ok(
        "POST", "/rest/api-keys",
        {"label": "woow-upgrade", "expiresAt": None, "scopes": scope_list},
    )
    key = api_key.get("rawApiKey") or api_key.get("apiKey")
    assert key, f"no API key returned: {api_key}"
    seeded = {
        "credentialId": credential["id"],
        "workflowId": workflow["id"],
        "encryptionKey": encryption_key(addon),
        "apiKey": key,
        "apiKeyScopes": len(scope_list),
        "apiWorkflowsStatus": api_get(addon, "/api/v1/workflows", key)[0],
    }
    print("seeded:", {k: v for k, v in seeded.items() if k not in ("encryptionKey", "apiKey")})
    addon.stop(remove=True)
    return seeded


def upgrade(addon: Addon, seeded: dict[str, object]) -> dict[str, object]:
    poller = f"{addon.name}-supervisor"
    docker("run", "-d", "--name", poller, "--network", addon.network, "--ip", SUPERVISOR_IP,
           "--entrypoint", "sh", addon.image, "-c", POLL_SCRIPT)
    try:
        started = time.time()
        addon.start()
        timings = addon.wait_ready()
        time.sleep(3)
    finally:
        samples = docker("logs", poller)
        docker("rm", "-f", poller, check=False)
    logs = addon.logs()
    migrations = re.findall(r"^Starting migration (\S+)", logs, re.MULTILINE)
    rows = []
    for line in samples.splitlines():
        parts = line.split(" ", 3)
        if len(parts) == 4:
            # (seconds since start, watchdog status, watchdog body, readiness status)
            rows.append((round(float(parts[0]) - started, 1), parts[1], parts[3], parts[2]))
    summary = {
        "timings": timings,
        "migrationsRun": len(migrations),
        "firstMigration": migrations[0] if migrations else None,
        "lastMigration": migrations[-1] if migrations else None,
        "watchdogNon200WhileReadinessFailing": [
            r for r in rows if r[1] not in ("200", "000") and r[3] != "200"
        ],
        "watchdogSamples": len(rows),
        "readinessNot200": sum(1 for r in rows if r[3] != "200"),
        "watchdogStarting": sum(1 for r in rows if r[2].startswith("n8n is starting")),
        "firstReady": next((r[0] for r in rows if r[3] == "200"), None),
        "firstNotReady503": next((r[0] for r in rows if r[3] == "503"), None),
    }
    if summary["firstReady"] is not None and summary["firstNotReady503"] is not None:
        # n8n listens while it migrates: readiness 503 until migrations end.
        summary["migrationWindowSeconds"] = round(
            summary["firstReady"] - summary["firstNotReady503"], 1
        )
    print("watchdog samples (t, watchdog, watchdog body, readiness):")
    for row in rows:
        print("   ", row)

    client = N8nClient(addon.url(""))
    client.login()
    # The REST API blanks secret fields, so decrypt with n8n's own CLI.
    exported = addon.exec(
        f"n8n export:credentials --id={seeded['credentialId']} --decrypted "
        "--output=/tmp/woow-cred.json >/dev/null 2>&1; cat /tmp/woow-cred.json; rm -f /tmp/woow-cred.json"
    )
    credential = json.loads(exported)
    credential = credential[0] if isinstance(credential, list) else credential
    assert credential["data"]["value"] == CREDENTIAL_SECRET, "credential no longer decrypts"
    assert encryption_key(addon) == seeded["encryptionKey"], "encryption key changed"
    workflow = client.ok("GET", f"/rest/workflows/{seeded['workflowId']}")
    assert workflow["active"], "the active workflow was deactivated by the upgrade"
    result = call_webhook(addon, "woow-upgrade")
    assert_code_nodes(result)
    executions = client.ok("GET", f"/rest/executions?filter=%7B%22workflowId%22%3A%22{seeded['workflowId']}%22%7D&limit=100")
    count = executions.get("count", len(executions.get("results", [])))
    status, body = api_get(addon, "/api/v1/workflows", str(seeded["apiKey"]))
    summary.update(
        {
            "credentialDecrypts": True,
            "encryptionKeyReused": True,
            "workflowActive": workflow["active"],
            "codeNodes": result,
            "executionsAfter": count,
            "oldApiKeyListWorkflows": status,
        }
    )
    req = urllib.request.Request(
        addon.url(f"/api/v1/workflows/{seeded['workflowId']}/deactivate"),
        method="POST", headers={"X-N8N-API-KEY": str(seeded["apiKey"])},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            summary["oldApiKeyDeactivate"] = response.status
    except urllib.error.HTTPError as error:
        summary["oldApiKeyDeactivate"] = f"{error.code} {error.read()[:200]!r}"
    req = urllib.request.Request(
        addon.url(f"/api/v1/workflows/{seeded['workflowId']}/activate"),
        method="POST", headers={"X-N8N-API-KEY": str(seeded["apiKey"])},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            summary["oldApiKeyActivate"] = response.status
    except urllib.error.HTTPError as error:
        summary["oldApiKeyActivate"] = f"{error.code} {error.read()[:200]!r}"
    addon.stop(remove=True)
    return summary


def downgrade_attempt(old_image: str, addon: Addon) -> str:
    """Start the old image on migrated data; report what happens in 120 s."""
    old = Addon(old_image, addon.workdir, network=addon.network)
    old.start()
    deadline = time.monotonic() + 120
    state = "no answer"
    while time.monotonic() < deadline:
        running = docker("inspect", "-f", "{{.State.Running}}", old.name).strip() == "true"
        try:
            with urllib.request.urlopen(old.url("/healthz/readiness"), timeout=5) as response:
                state = f"readiness {response.status}"
                break
        except urllib.error.HTTPError as error:
            state = f"readiness {error.code}"
        except OSError:
            pass
        if not running:
            state = "container exited"
            break
        time.sleep(2)
    lines = [
        line for line in old.logs().splitlines()
        if not line.startswith("s6-rc") and "Supervisor API" not in line
        and "contacting the API" not in line and "[notice]" not in line
    ]
    tail = "\n".join(lines[-30:])[-3000:]
    old.stop(remove=True)
    return f"{state}\n{tail}"


def main() -> None:
    args = sys.argv[1:]
    executions = 25
    if "--executions" in args:
        index = args.index("--executions")
        executions = int(args[index + 1])
        del args[index:index + 2]
    if len(args) != 2:
        raise SystemExit(__doc__)
    old_image, new_image = args
    with tempfile.TemporaryDirectory(prefix="woow-n8n-upgrade-") as tmp_name:
        workdir = Path(tmp_name)
        addon = Addon(old_image, workdir)
        try:
            seeded = seed(addon, executions)
            size = (addon.config / ".n8n/database.sqlite").stat().st_size
            print(f"pre-upgrade database.sqlite: {size} bytes")
            docker("run", "--rm", "-v", f"{workdir}:/w", "--entrypoint", "sh", old_image, "-c",
                   "mkdir -p /w/backup && cp -a /w/data /w/config /w/backup/")

            addon.image = new_image
            summary = upgrade(addon, seeded)
            size_after = (addon.config / ".n8n/database.sqlite").stat().st_size
            summary["databaseBytes"] = {"before": size, "after": size_after}
            print("upgrade summary:", json.dumps(summary, indent=2, default=str))

            print("downgrade on migrated data:", downgrade_attempt(old_image, addon))

            docker("run", "--rm", "-v", f"{workdir}:/w", "--entrypoint", "sh", old_image, "-c",
                   "rm -rf /w/data /w/config && cp -a /w/backup/data /w/backup/config /w/")
            restored = Addon(old_image, workdir, network=addon.network)
            restored.start()
            print("restored backup on the old image:", restored.wait_ready())
            old_result = call_webhook(restored, "woow-upgrade")
            print("old image after restore:", json.dumps(old_result))
            assert old_result.get("js") == 6 and old_result.get("py") == 45, old_result
            restored.stop(remove=True)
            print("upgrade smoke test passed")
        finally:
            addon.destroy()
            docker("run", "--rm", "-v", f"{workdir}:/w", "--entrypoint", "sh", new_image, "-c",
                   "rm -rf /w/data /w/config /w/backup", check=False)
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
