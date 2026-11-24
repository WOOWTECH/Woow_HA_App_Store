# Disposable amd64 HAOS acceptance

`Test real HAOS add-on acceptance / HAOS acceptance (amd64)` runs on ordinary
pull requests. A passing local harness test is not evidence of a booted HAOS
guest. Acceptance requires this job's successful, complete JSON receipt for the
reviewed PR head. Missing KVM, space, artifacts or readiness fails the job.

## Bootstrap and resource bounds

The guest follows the official [HAOS QEMU tests](https://github.com/home-assistant/operating-system/blob/dev/tests/qemu-strategy.yaml)
and [CONFIG drive developer SSH bootstrap](https://contributors.home-assistant.io/os/operating-system/debugging/).
It uses the checksum-pinned official HAOS 18.1 OVA qcow2, OVMF, virtio and KVM.
A new key, CONFIG drive and writable disk are created for each job. Supervisor
and Core follow HAOS's normal first-boot installation. No prior guest is reused.

The harness saves the original `/dev/kvm` ACL and device identity before granting
only its current UID read/write access, then requires both `KVM_GET_API_VERSION`
and `KVM_CREATE_VM` to work. QEMU runs as the unprivileged runner. Before every
actual QEMU launch, including cold boot, it drains pending udev events with a
five-second settle bound and refreshes that UID's ACL. Each refresh verifies the
same character device and effective access; its final grant becomes the access
comparison baseline. Raw ACLs and numeric user/group identities stay private.
There is no software CPU
fallback. GitHub does not guarantee nested virtualization on hosted runners;
an unavailable accelerator is a failed acceptance prerequisite.

| Resource | Bound |
| --- | --- |
| Runner | Public Ubuntu 22.04 amd64 hosted runner |
| Guest | 2 vCPU, 6 GiB RAM |
| Guest disk | 32 GiB virtual qcow2, sparse physical allocation |
| Host disk | At least 12 GiB physically free before downloads; 2 GiB reserve monitored every 5 seconds |
| Time | 60-minute job; 50-minute acceptance process; individual commands/readiness also bounded |
| Networking | QEMU user networking; all forwarded ports and the registry listen on loopback |

The HA HTTP forwards use host ports 18080 and 18123 (guest ports 80 and 8123).
Port availability checks, QEMU forwarding and Core discovery share these values.
The receipt records only the selected allowlisted forwarded-port integer. Port
10080 is [restricted by Chromium](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/net/base/port_util.cc):
an HTTP client may reach it while browser navigation fails before sending HTTP.
The local regression discovers Core on each configured forward and requires real
Chromium navigation to succeed without disabling browser port protections.

Sparse capacity is not free physical capacity. The physical reserve aborts the
run if image pulls, backup data or guest writes consume it. The harness does not
delete preinstalled runner software to make space. A failed preflight requires a
runner with the stated capacity. HAOS release downloads, GitHub artifact reads,
the public baseline GHCR image, Docker Hub registry image and HAOS's normal
Supervisor/Core downloads must be reachable.

## Candidate and baseline identity

The baseline is the latest stable Release, version 0.1.25. Its version, config
source/checksum, published amd64 image digest and database migration head are
fixed in `host.py`, next to `CANDIDATE_VERSION`. Update them together when the
next Release becomes the baseline. The candidate is the current PR's existing
amd64 build tar, downloaded without publishing a PR tag or rebuilding it.

Acceptance checks out the explicit PR head. The existing producer retains its
default synthetic merge checkout and writes `producer-source.json` beside its
image artifact. Acceptance requires:

1. A successful `build (amd64)` in the matching PR-head producer run.
2. Image and source artifacts from that build job's actual `run_attempt`
   (including failed-jobs reruns), with GitHub artifact SHA256 validation.
3. The producer's `omnigent` Git tree to equal the PR-head tree. A merge checkout
   with different add-on content fails; no exact-commit equivalence is claimed.
4. Matching config, Dockerfile and artifact-pin hashes, plus the producer's
   recorded Docker image ID cryptographically linked to the saved image config.
   Docker's [containerd store reports a manifest ID](https://github.com/moby/moby/blob/master/daemon/containerd/image_inspect.go),
   while its legacy store reports a config ID. Before loading the verified tar,
   acceptance hashes its config bytes. A differing producer ID must equal the
   archive's single image manifest descriptor, whose bytes, digest, size and
   config reference are verified. Only that linked manifest or config digest is
   accepted for the loaded image; labels/version alone never establish identity.
   Duplicate members, unexpected tags, altered descriptors and unlinked IDs fail.
5. After each local registry push, hash the served manifest bytes against its
   `Docker-Content-Digest` header and verify its config descriptor and config blob
   against the anchored config digest. A push may rewrite the manifest, so the
   pushed digest is measured independently of the producer digest. The candidate
   anchor comes from its verified CI archive. The baseline anchor comes from an
   export of the image pulled by its fixed digest; this temporary tar is deleted
   immediately after verification. The actual Supervisor container must report
   either that config digest or that verified pushed manifest digest. Both versions
   use this check at install, before/after cold backup, restore and cold boot,
   with the installed candidate wheel also verified inside the guest.

Fresh [HAOS 18.1 enables the containerd image store](https://github.com/home-assistant/operating-system/blob/18.1/buildroot-external/rootfs-overlay/usr/libexec/docker-prepare).
Its container image ID can therefore differ from the runner's config ID. The
receipt records the independently verified registry/config digests for each
version; an unrelated ID or missing registry proof always fails. Registry metadata
requests stay on the job's loopback listener, disable redirects and environment
proxies, have a ten-second timeout, and read at most 1 MiB per object.

The source receipt is `haos-image-source-attempt-<attempt>`. The image remains
the Store-compatible `upgrade-comparison-image-woow-omnigent-attempt-<attempt>`;
its format is unchanged. Acceptance waits up to 15 minutes for a matching build.
If the build exceeds that window, rerun the failed acceptance job after it
finishes. An expired image requires a producer rerun.

Supervisor pulls the unchanged old/new images from a job-owned loopback registry
through a temporary SSH reverse forward. Only the disposable local add-on config's
`image` reference changes. Both versions use `local_woow-omnigent`, preserving
Supervisor's real data directory across the update.
The local config is written under Supervisor's existing `apps/local` directory,
as defined by [Supervisor 2026.11.0](https://github.com/home-assistant/supervisor/blob/2026.11.0/supervisor/config.py).
After store reload, acceptance requires the exact local slug, repository and
version in the catalog before install/update. It fails if the local root is absent
or the catalog differs; it does not create an alternate legacy directory.

## Checks and receipt

The sequence installs 0.1.25 through Supervisor, seeds the existing upgrade
fixtures (including an active and a revoked MCP profile, because the baseline
already has MCP), creates a Supervisor cold backup, updates to 0.1.26, and checks
the task/agent fields, member login, session ACLs, artifact bytes and the
original MCP profile URLs and revocation state.

The real HA owner signs in through Chromium and opens the HA sidebar Ingress.
The harness registers a filtered `framenavigated` expectation before clicking the
sidebar link, with a 60-second bound. This keeps Playwright's synchronous event
loop processing delayed frame navigation; Python sleep polling of cached frame
URLs can leave [Playwright state outdated](https://playwright.dev/python/docs/library#timesleep-leads-to-outdated-state).
Only an Ingress frame navigation satisfies the wait; unrelated frames do not.
The browser checks add-on login, lazy settings pages, MCP creation/copy, one-time
URL hiding, expired-session navigation and logout. After signing back in, it
opens the Ingress-prefixed `/settings/account` page and waits for the Account
heading before clicking the exact `Sign out` button. That control is absent from
the MCP settings page. The resulting login form must remain inside Ingress.
A separate localhost HTTPS proxy serves the complete `/omnigent` deployment prefix. Its generated CA is
explicitly trusted by the MCP client: certificate verification stays enabled.
The copied URL must equal the API's `connection_url`. The candidate UI awaits
asynchronous `writeText()` but exposes no copied/toast success state; a completed
Playwright click does not establish that clipboard writing has finished. The
browser awaits actual clipboard equality on animation frames, bounded to ten
seconds even if a read never resolves. The dialog's fixed copy-error message and
clipboard read errors fail the check. This uses the unchanged HA iframe policy
and real clipboard; no permission bypass, replacement clipboard or fixed sleep.
Cookie-free requests check initialize, 15 tools, session/history ACLs and
active/revoked profiles. The
candidate's MCP SDK 1.30.0 [GET handler](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/streamable_http.py)
opens SSE even with JSON POST replies and stateless sessions. The GET probe uses
a streaming client, requires HTTP 200 with `text/event-stream`, and closes the
response explicitly without waiting for an unbounded body. DELETE must return
405 because this candidate does not maintain transport sessions. This tests
stream establishment through TLS, not long-duration event delivery or reconnect.

Actual Supervisor backup/restore checks include:

- Both cold backups must restart the running add-on container.
- Revoke a saved active token after the candidate backup. Restore that backup;
  the original active URL must work again and the earlier revoked URL stay denied.
- Cleanly power off HAOS, start a new QEMU process with the same disk, require a
  changed kernel boot ID, and recheck data plus the original profile URLs.
- Restore the baseline backup; require the old image/version, original data,
  member credentials and the baseline database migration head. The running
  image must be the baseline image, which differs from the candidate image, so
  the check tells the two versions apart even when the head did not move.
- Migration head rule: list each version's `versions/*.py` (name, SHA-256) and
  alembic script heads in the running container. If the candidate has the same
  files as the baseline, the head must stay at the baseline head. If it adds
  files (a merge-only revision counts), the head must move to the candidate's
  single script head. A missing or changed baseline file fails.

Only `haos-acceptance.json` is uploaded. It includes controlled stage outcomes,
artifact/image/source identities, physical resource counts, Supervisor version,
database version and migration head. Failures contain a stage, exception type and
source line, without exception text. Passwords, keys, token URLs, backups, browser
traces, screenshots and raw command/guest logs remain private temporary files.
Boot diagnostics distinguish QEMU process exit, guest SSH wait and Supervisor
wait. The receipt includes process exit codes, attempt counts and allowlisted
error/console marker labels. During Supervisor readiness, both `/supervisor/info`
and `/info` retain separate HTTP statuses, curl/SSH exit codes and timeout flags.
The guest probe records Docker/curl/jq availability, container inspection,
token lookup, network count and address lookup exit codes, plus health and an
allowlisted system state. These diagnostics are captured before cleanup; raw
commands, response bodies, IP addresses, tokens and QEMU/SSH output stay private.
Supervisor supplies the CLI plugin's token through its
[container environment](https://github.com/home-assistant/supervisor/blob/main/supervisor/docker/cli.py).
Both readiness and later Supervisor operations read only that runtime variable
using `docker exec hassio_cli printenv SUPERVISOR_TOKEN`, captured inside the
guest shell. A stopped CLI or absent/empty token remains retryable during startup;
missing executables and jq usage/compile errors fail immediately. Health and root
state still require successful authenticated HTTP responses from both endpoints.
An exited QEMU process fails immediately instead of consuming the SSH timeout.
TLS MCP diagnostics retain fixed profile-check stages, the last allowlisted RPC
method/status/JSON-result flag, and GET/DELETE status/SSE-media-type/closed flags.
Timeout and transport failures use fixed labels; URLs, tokens, headers and
RPC parameters/results are excluded. HTTP client timeouts remain bounded.
Browser diagnostics retain fixed stages for Chromium startup, HA login, sidebar,
Ingress login/settings, profile creation/copy, expiry and logout. Document responses
record only HTTP status, HA/Ingress scope and same-origin boolean; JavaScript and
failed Ingress asset events retain counts only. Clipboard diagnostics retain the
iframe's secure-context/write-policy booleans and a fixed result code, never the
expected or actual clipboard value. Known Playwright error markers map
to fixed labels (for example ambiguous locator or connection refusal); other errors
remain unknown categories. No exception text, DOM, URLs or credentials are retained.
Context, browser and driver cleanup are attempted independently after success or
failure. Cleanup outcomes cannot replace the original browser failure. These
checkpoints do not change selectors, navigation or acceptance assertions.
Later Supervisor operations retain the last fixed operation label, method,
SSH exit/timeout, HTTP status and `ok`/`error`/unknown result. The two recognized
upstream error keys are `store_app_not_found_error` and `system_not_ready_error`;
all other failures use fixed HTTP/transport/response-shape categories. Error text,
extra fields, backup IDs and request/response bodies are excluded. Response JSON
classification is limited to 1 MiB. Local config diagnostics distinguish writing,
store reload and catalog discovery. These checks apply to install/update and the
existing backup/restore operations without weakening their success conditions.
Registry diagnostics distinguish the pinned image pull, container launch/state,
host HTTP readiness, guest forwarding, baseline/candidate tag/push/inspect,
metadata parsing, architecture/version checks and final producer/source guards.
The implicit Docker pull is split into a bounded explicit pull and a launch with
`--pull=never`, using the same pinned image and loopback binding. Each boundary
retains a pass/fail boolean. Only fixed stage names, command exit codes, timeout
flags and allowlisted exception classes/error markers are reported, including
certificate, missing-path and connection failures when Docker emits those markers.
Container creation/running state and exit code, host HTTP status and guest
probe/SSH tunnel exit codes distinguish server readiness from forwarding. The
loopback registry uses HTTP, so it has no local certificate/key paths to report.
Command arguments, output, exception text and registry response bodies stay
private; these checkpoints do not weaken any image identity or transport requirement.
Cleanup terminates the harness's processes and verifies the registry ownership
label before deleting it and its anonymous volume. A launch is marked attempted
before invoking Docker; container creation remains unknown if that command fails
or times out. Cleanup inspects the exact unique container name after every launch
attempt, including failed launches. An inspect error requires a successful empty
exact-name listing to confirm absence. Ownership mismatch or lookup failure
preserves the container and fails cleanup; only the matching ownership label
permits removal. Separate sanitized cleanup status preserves the original failure
stage. After QEMU is reaped, cleanup
settles pending udev events and restores the one original ACL only if the original
character device, inode, device numbers, owner and group still match. ACL-related
mode changes are excluded from identity. A mismatch skips the ACL write and fails
cleanup; a failed settle still attempts restoration on the verified original
device and remains a failure. The receipt contains only access/ACL-change booleans
and fixed cleanup status codes. Job teardown removes the
ephemeral runner and remaining Docker images.

## Limits

This covers actual amd64 HAOS/Supervisor on a newly provisioned CI guest. It does
not establish native arm64 runtime, Internet-public HTTPS or Pi connectivity,
external runner/terminal operation, LAN browser login, or long-lived SSE
behavior.
Poweroff/container-restart checks also do not assert the exact PostgreSQL shutdown
log lines in the manual H3 checklist. These remain separate acceptance evidence.

## Local harness validation

Install `requirements.txt`, nginx, jq and OpenSSL, install Chromium with
`python -m playwright install --with-deps chromium`, then run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=omnigent/tests \
  python -m unittest discover -s omnigent/tests -p 'test_haos_harness.py' -v
```

`NGINX_BINARY` can select a locally installed nginx executable. The tests exercise
artifact selection, source binding, fail-closed preflight, ownership checks,
sanitized failure output, real Chromium failure/cleanup fixtures on loopback, and a
real TLS proxy against a small HTTP fixture.
They neither download HAOS nor launch a VM. The acceptance entry point itself
requires the GitHub Actions environment and is invoked only by the PR workflow.
