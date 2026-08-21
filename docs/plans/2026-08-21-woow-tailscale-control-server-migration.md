# Woow Tailscale Control-Server Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a WoowTech-maintained Home Assistant Tailscale add-on whose `login_server` can be changed in the HAOS Configuration UI without the upstream `can't change --login-server without --force-reauth` crash-loop.

**Architecture:** Vendor the MIT-licensed `hassio-addons/app-tailscale` `tailscale/` add-on at upstream commit `24464c97a779bdd64c9975f514bff6e1d9058cca` as a new `woow-tailscale` add-on. A new s6 oneshot service runs before `tailscaled`; it compares the configured, normalized control-server URL with a private marker in `/data`. On a real change it securely archives and removes the Tailscale state before the daemon starts, then records the new URL; unchanged starts preserve the existing identity and session.

**Tech Stack:** Home Assistant add-on manifest/schema, Alpine/bash/bashio, s6-overlay, Tailscale v1.102.3, shell test harness, Docker/HA Supervisor integration test.

---

## Scope and non-goals

- The add-on ID is `1b7b4ce7_woow-tailscale`; its slug is `woow-tailscale`. It deliberately does **not** replace `a0d7b954_tailscale` in place.
- The new configuration page is `/config/app/1b7b4ce7_woow-tailscale/config`. It retains the `login_server: url` field.
- The feature changes local client state only. It does not create Headscale users, generate pre-auth keys, approve registrations, or delete old nodes from Headscale.
- A changed URL deliberately creates a fresh device identity and requires normal Headscale approval. This is safer than attempting to reuse keys across control planes.
- Do not add a permanent `--force-reauth` flag: that would reauthenticate every restart and break normal operation.

## Baseline references

- Destination repository: `/data/pi-agent/home/pi-cwd-20260817/repos/Woow_HA_App_Store`
- Upstream source: `/data/pi-agent/home/pi-cwd-20260817/repos/app-tailscale/tailscale`
- Upstream version/commit: `v0.28.1` add-on, Tailscale `v1.102.3`, commit `24464c97a779bdd64c9975f514bff6e1d9058cca`
- Upstream failure location: `rootfs/etc/s6-overlay/s6-rc.d/post-tailscaled/run` calls `/opt/tailscale up --login-server=<configured URL>` after `tailscaled` has already opened `/data/tailscaled.state`.
- State files: `/data/tailscaled.state`, `/data/state/`, and `/data/final_serve_reset_is_done`.

### Task 1: Vendor upstream add-on as a separately installable Woow add-on

**Files:**
- Create: `woow-tailscale/` (copy all upstream `tailscale/` files, including `rootfs/`, `translations/`, `Dockerfile`, `DOCS.md`, `apparmor.txt`, icons, and build metadata)
- Create: `woow-tailscale/LICENSE.md` (upstream MIT license, unchanged)
- Modify: `woow-tailscale/config.yaml`
- Modify: `woow-tailscale/Dockerfile`

**Step 1: Copy the upstream directory without its Git metadata.**

Run from the App Store worktree:

```bash
cp -a /data/pi-agent/home/pi-cwd-20260817/repos/app-tailscale/tailscale \
  woow-tailscale
```

Confirm all rootfs scripts remain executable:

```bash
find woow-tailscale/rootfs -type f -name run -exec test -x {} \;
```

**Step 2: Brand and isolate the manifest.**

Update the copied `woow-tailscale/config.yaml` fields to:

```yaml
name: "Woow Tailscale"
version: "0.1.0"
slug: "woow-tailscale"
description: "Tailscale client with safe Headscale/control-server migration"
url: "https://github.com/WOOWTECH/Woow_HA_App_Store"
panel_title: "Woow Tailscale"
```

Keep all upstream architecture, privilege, network, port, `options`, and `schema` fields. Keep `login_server: url` in the schema and the default `https://controlplane.tailscale.com`: this is what renders the editable HAOS Configuration UI control.

**Step 3: Add provenance labels/comments.**

At the top of `woow-tailscale/Dockerfile` and `woow-tailscale/DOCS.md`, add a concise notice that this is an MIT-licensed fork of `hassio-addons/app-tailscale`, state the upstream commit above, and describe the Woow-only control-server migration behavior. Preserve `LICENSE.md` unchanged.

**Step 4: Check manifest syntax and source completeness.**

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
p = Path('woow-tailscale/config.yaml')
d = yaml.safe_load(p.read_text())
assert d['slug'] == 'woow-tailscale'
assert d['schema']['login_server'] == 'url'
assert set(d['arch']) == {'aarch64', 'amd64'}
PY
find woow-tailscale/rootfs -type f | wc -l
```

Expected: the manifest assertions pass and the copied rootfs contains the upstream service files.

**Step 5: Commit the vendored baseline.**

```bash
git add woow-tailscale
git commit -m "feat: add Woow Tailscale add-on fork"
```

### Task 2: Add a testable state-reconciliation helper

**Files:**
- Create: `woow-tailscale/rootfs/usr/local/lib/woow-tailscale/reconcile-login-server`
- Create: `woow-tailscale/tests/test-reconcile-login-server.sh`

**Step 1: Write the failing shell tests.**

Create `tests/test-reconcile-login-server.sh` using `set -euo pipefail`, `mktemp -d`, and a cleanup trap. Execute the helper with `DATA_DIR` pointed to a temporary fixture directory and one positional requested URL. Assert all of the following cases:

1. **Fresh install:** no marker and no state writes normalized URL (`https://hs.example/` becomes `https://hs.example`) to `.woow-login-server`; creates no backup.
2. **Unchanged server:** marker and state already exist; the helper preserves `tailscaled.state` and `state/` and creates no backup.
3. **Changed server:** old marker and fixture state exist; helper creates exactly one readable `state-backups/*.tar.gz`, removes `tailscaled.state`, `state/`, and `final_serve_reset_is_done`, then writes the new normalized URL.
4. **Safety guard:** marker is absent while state exists; helper exits nonzero and does not alter state.
5. **Retention:** after creating more than three archives, only the newest three are retained.

Run before implementation:

```bash
bash woow-tailscale/tests/test-reconcile-login-server.sh
```

Expected: FAIL because `reconcile-login-server` does not exist.

**Step 2: Implement a pure Bash helper.**

Create an executable script with this public contract:

```bash
# DATA_DIR defaults to /data; URL is required positional argument.
DATA_DIR="${DATA_DIR:-/data}"
requested_url="$1"
```

Implement the following exact rules:

```bash
marker="$DATA_DIR/.woow-login-server"
state_file="$DATA_DIR/tailscaled.state"
state_dir="$DATA_DIR/state"
serve_marker="$DATA_DIR/final_serve_reset_is_done"
backup_dir="$DATA_DIR/state-backups"
```

- Normalize only the URL’s trailing slash (`https://host///` becomes `https://host`). Reject an empty result.
- If neither state path exists and no marker exists, atomically write the normalized requested URL to a `mktemp` file in `$DATA_DIR`, `chmod 600` it, then `mv` it to `$marker`.
- If marker exists and matches the normalized requested URL, exit success without altering state.
- If marker exists and differs, create `$backup_dir` mode `0700`; create an archive named `YYYYmmddTHHMMSSZ-control-server-state.tar.gz` mode `0600` containing every existing item among `tailscaled.state`, `state`, and `final_serve_reset_is_done`. Do not use wildcard expansion that could archive unrelated `/data` files. Verify `tar -tzf` succeeds before deletion. Remove those three existing state items only, atomically replace marker, and prune archives to the newest three using predictable fixed filenames.
- If marker does not exist but either state path exists, print an actionable error to stderr and exit `20`; do not back up, delete, or create a marker. This protects installations whose origin cannot be proven.

Keep the helper independent of `bashio`, so it is unit-testable outside a running add-on. Its logs must contain URLs and file names only—never state file contents or private keys.

**Step 3: Run the tests.**

```bash
bash woow-tailscale/tests/test-reconcile-login-server.sh
```

Expected: all five cases pass.

**Step 4: Validate shell syntax and permissions.**

```bash
bash -n woow-tailscale/rootfs/usr/local/lib/woow-tailscale/reconcile-login-server
bash -n woow-tailscale/tests/test-reconcile-login-server.sh
test -x woow-tailscale/rootfs/usr/local/lib/woow-tailscale/reconcile-login-server
```

**Step 5: Commit.**

```bash
git add woow-tailscale/rootfs/usr/local/lib/woow-tailscale/reconcile-login-server \
  woow-tailscale/tests/test-reconcile-login-server.sh
git commit -m "feat: reconcile Tailscale state when control server changes"
```

### Task 3: Run reconciliation before `tailscaled` opens the state database

**Files:**
- Create: `woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration/type`
- Create: `woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration/run`
- Create: `woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration/dependencies.d/base`
- Create: `woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/tailscaled/dependencies.d/init-login-server-migration`
- Modify: `woow-tailscale/Dockerfile`

**Step 1: Write an integration-layout assertion.**

Extend `tests/test-reconcile-login-server.sh`, or add `tests/test-s6-layout.sh`, to assert:

```bash
test -f woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration/type
test -x woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration/run
test -f woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/tailscaled/dependencies.d/init-login-server-migration
grep -Fq '/usr/local/lib/woow-tailscale/reconcile-login-server' \
  woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration/run
```

Run it and confirm it fails before creating the service.

**Step 2: Create the s6 oneshot service.**

Set `type` to `oneshot`. Its `run` script must be a `#!/command/with-contenv bashio` executable and call the helper before `tailscaled`:

```bash
#!/command/with-contenv bashio
# shellcheck shell=bash
set -euo pipefail

login_server="$(bashio::config 'login_server')"
bashio::log.info "Checking configured Tailscale control server"
if ! /usr/local/lib/woow-tailscale/reconcile-login-server "$login_server"; then
  bashio::exit.nok \
    "Control-server migration safety check failed; existing Tailscale state was not changed"
fi
```

Add a `base` dependency to this service. Add `init-login-server-migration` as a dependency of `tailscaled`, preserving all existing `tailscaled` dependencies. This ordering is mandatory: never remove or mutate `tailscaled.state` from `post-tailscaled/run`, since the daemon has already read it by then.

**Step 3: Ensure all scripts are executable at image build.**

Replace the narrow chmod in `Dockerfile` with a safe command that additionally grants execute permissions to the new helper and every s6 `run` script, without changing unrelated data:

```dockerfile
RUN chmod +x /etc/s6-overlay/s6-rc.d/*/run \
    /usr/local/lib/woow-tailscale/reconcile-login-server
```

Retain any existing chmod needed by the upstream image.

**Step 4: Run helper and layout tests.**

```bash
bash woow-tailscale/tests/test-reconcile-login-server.sh
bash woow-tailscale/tests/test-s6-layout.sh
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add woow-tailscale/rootfs woow-tailscale/Dockerfile woow-tailscale/tests
git commit -m "feat: run control-server migration before tailscaled"
```

### Task 4: Document HAOS migration and recovery

**Files:**
- Modify: `woow-tailscale/DOCS.md`
- Modify: `woow-tailscale/README.md`
- Create: `woow-tailscale/CHANGELOG.md`

**Step 1: Replace official-account-only prerequisite text.**

State that the add-on supports both Tailscale’s official control plane and Headscale-compatible control planes. Do not imply that a Tailscale account is required for Headscale.

**Step 2: Add a `Control server / Headscale migration` section immediately after the configuration example.**

Include this exact user-facing procedure:

1. Stop `a0d7b954_tailscale`; do not operate both add-ons at once.
2. Install `Woow Tailscale` and open its Configuration page.
3. Copy desired routing/DNS settings and set `login_server` to the Headscale public URL, for example `https://loving-woodcock-cleanly.ngrok-free.app`.
4. Start it and get the `/register/hskey-authreq-...` URL from the add-on log.
5. Register the pending node via Headplane or `headscale auth register --user <user> --auth-id <id>`.
6. Verify `active login: <user>` and a `100.x.x.x` peer API address in the log.

Explicitly warn that changing `login_server` backs up and removes the local identity, requires new approval, and may leave an offline old node that an administrator should remove from Headscale.

**Step 3: Document recovery.**

Document `/data/state-backups/` as an emergency backup only. Do not give a blind restore command; instruct users to stop the add-on and contact/consult support before restoring a private-key-bearing state archive. State that the add-on only retains three latest archives.

**Step 4: Create changelog entry.**

```markdown
## 0.1.0

- Initial WoowTech fork of Home Assistant Community Tailscale add-on.
- Added safe automatic state migration when `login_server` changes.
```

**Step 5: Commit.**

```bash
git add woow-tailscale/DOCS.md woow-tailscale/README.md woow-tailscale/CHANGELOG.md
git commit -m "docs: explain Woow Tailscale Headscale migration"
```

### Task 5: Build and verify the add-on end to end

**Files:**
- Verify: `woow-tailscale/config.yaml`
- Verify: `woow-tailscale/Dockerfile`
- Verify: `woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration/run`

**Step 1: Run all fast validation.**

```bash
bash woow-tailscale/tests/test-reconcile-login-server.sh
bash woow-tailscale/tests/test-s6-layout.sh
bash -n woow-tailscale/rootfs/usr/local/lib/woow-tailscale/reconcile-login-server
```

Expected: all pass.

**Step 2: Build for amd64.**

From `woow-tailscale/`, build using the same base image and architecture declared by `build.yaml`:

```bash
docker build \
  --build-arg BUILD_FROM=ghcr.io/hassio-addons/base/amd64:21.0.2 \
  --build-arg BUILD_ARCH=amd64 \
  --build-arg BUILD_VERSION=0.1.0 \
  -t woow-tailscale:test .
```

Expected: successful image build; executable-bit and s6 path errors fail the build rather than deploying a broken image.

**Step 3: Deploy as a local test add-on on HAOS.**

Copy the `woow-tailscale/` directory into HAOS local add-ons, refresh local add-ons, install it, and leave the official `a0d7b954_tailscale` stopped throughout the test. Configure the Woow add-on with the existing Headscale public URL.

Expected initial logs:

```text
Checking configured Tailscale control server
Starting Tailscale...
To authenticate, visit:
https://<headscale>/register/hskey-authreq-...
```

Approve that auth request under a dedicated test Headscale user, then verify `headscale nodes list` reports the node online.

**Step 4: Exercise the actual configuration-page change.**

In the HAOS Configuration page, save an alternate test URL (a distinct Headscale endpoint; do not use an invalid URL), restart, and verify logs report exactly one state backup and a new registration URL—not `can't change --login-server without --force-reauth`. Approve the node. Restart again without changing the URL and verify no additional backup and no new registration prompt.

**Step 5: Restore production configuration and clean test nodes.**

Set `login_server` back to the intended production Headscale URL; approve the resulting final node; remove any deliberately created test nodes from Headscale. Confirm no official Tailscale add-on is running before enabling Woow Tailscale as the active client.

**Step 6: Commit verification-related fixes, then final review.**

```bash
git status --short
git diff main...HEAD --check
git log --oneline main..HEAD
```

Expected: no whitespace errors, no untracked test artifacts, and commits limited to the new `woow-tailscale` add-on and its documentation/tests.

### Task 6: Publish safely

**Files:**
- Verify: `repository.yaml`
- Verify: `woow-tailscale/`

**Step 1: Confirm repository discovery.**

Ensure no repository index generation is required beyond the root `repository.yaml`; existing add-ons are discovered as top-level directories containing `config.yaml`.

**Step 2: Push feature branch and open a reviewable PR.**

```bash
git push -u origin feat/woow-tailscale-control-server-migration
```

PR description must include: upstream commit/vendor version, state-clearing behavior, three-backup retention, functional HAOS test evidence, and explicit note that users must migrate from the official add-on rather than run both.

**Step 3: Merge only after reviewer verifies destructive behavior.**

Reviewer acceptance criteria:

- no URL change preserves state;
- a URL change archives state before deletion;
- marker-absent state is never auto-deleted;
- the new add-on can register to Headscale from the HAOS Configuration UI;
- a plain restart does not reauthenticate.
