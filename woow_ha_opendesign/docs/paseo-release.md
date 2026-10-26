# Paseo 0.2.7 release gate

This branch is based on remote HA main a296fffc (0.2.6). It prepares 0.2.7;
it does not establish a published or live-tested release. Merge publishes this
version through the existing Store workflow, so main integration review and the
actual shared-core immutable digest are prerequisites.

`paseo-runtime/VENDOR.json` records runtime 0.2.1 at commit
`21af10e178c00a4b4f3608f87321f200c410915a`, the same source/package used by the PaaS
wrapper. The checked-in npm archive and separately copied package-lock.json have
SHA-256 checksums. `install.sh` verifies them and runs npm ci with lifecycle
scripts disabled. It then compares the bundled native launcher byte-for-byte
and requires native MCP CAS route artifacts. Nothing is copied into native core
sources. A pre-Paseo core must fail this installation.

To regenerate: check out the reviewed runtime commit, run `npm pack --json`, copy
that archive and its source `package-lock.json`, and update both recorded hashes
and source commit. Run the runtime suite and archive check before accepting a
new pin. Keep PaaS and HA pins synchronized.

The reviewed public core is `20261026.0712` at
`sha256:366e337dc7ea192526468de33ad3f2f0ce97be3ffba9b8382a0c1d9ab88b1404`,
from native fork `c8ae3900f9ff5d58f50d11f4055756f6e7f14a25`. Main verified
anonymous GHCR access and preservation of the promoted JCR manifest digest.
Future pins use `.github/scripts/pin-core.sh TAG sha256:DIGEST`; review CLI
contracts and rerun image/HA checks against those exact bytes. Static validation
is not evidence of a successful image build.

Validation:

- `tests/run.sh`: package integrity, metadata, lifecycle, ingress shim, existing
  renderer/export/MCP checks; with nginx installed it also runs the real local
  nginx-to-Unix bridge fixture (`tests/paseo-ingress-e2e.sh`).
- `tests/container-smoke.sh IMAGE`: existing export, CLI, MCP, persistence smoke
  plus native launcher/CAS and bridge packaging checks. Requires the new core.
- Main/environment owner: normal HA 0.2.6 → 0.2.7 upgrade and fresh install,
  native launcher click/new tab, login/pairing, target-local model conversation,
  manual stop/start, restart/backup persistence, forged-header/origin rejection.

The local nginx fixture substitutes a loopback peer for Supervisor only within
its temporary configuration; the shipped config continues to allow only
172.30.32.2. It does not mutate a real HA host or claim real HA acceptance.

Trust references: [HA Core ingress forwarding](https://github.com/home-assistant/core/blob/dev/homeassistant/components/hassio/ingress.py)
and [Supervisor authenticated user forwarding](https://github.com/home-assistant/supervisor/blob/main/supervisor/api/ingress.py).
Forwarded host/proto are deliberately not accepted as browser-origin authority.

## Candidate publication before stable merge

Dispatch the existing `build.yml` workflow at this review branch with the
`candidate_core_image` input set to main's verified immutable core reference.
It accepts `ghcr.io/woowtech/open-design-core:YYYYMMDD.HHMM@sha256:…` or the
read-only JCR equivalent (including a `-pending-approval` tag). A candidate
input never starts the main release plan. The job also refuses main, forks,
mutable core references, and existing candidate tags.

```sh
# CORE_IMAGE is the exact verified reference delivered by the core owner.
# Run from an authenticated maintenance terminal; do not put credentials here.
gh workflow run build.yml --repo WOOWTECH/Woow_ha_opendesign_add_on \
  --ref feat/ha-paseo-0.2.7-20261026 -f candidate_core_image="$CORE_IMAGE"
gh run list --repo WOOWTECH/Woow_ha_opendesign_add_on \
  --workflow build.yml --branch feat/ha-paseo-0.2.7-20261026
# After the candidate run succeeds:
gh run download "$RUN_ID" --repo WOOWTECH/Woow_ha_opendesign_add_on \
  --name ha-candidate-receipt
```

Validation must pass first. The candidate job builds with the input core,
loads the image, runs the entire `container-smoke.sh` suite, checks that its
unique tag is absent, and pushes that exact loaded image without rebuilding.
It verifies the anonymously readable registry manifest against the pushed
image digest and uploads `candidate-receipt.json` with source, core, runtime,
version, and image pins. Any smoke failure prevents publication.
The candidate tag is `0.2.7-rc.<run-id>.<run-attempt>` in the existing public
`ghcr.io/woowtech/woow-ha-opendesign-amd64` package. No stable image tag,
Git tag, GitHub Release, or Store publication is created.

The actual image smoke waits for native onboarding and managed daemon
readiness before checking all TCP listeners. It permits precisely the four
existing listeners plus the `127.0.0.1:<port>` recorded consistently in Paseo
state and daemon config and one internal OpenCode tool bridge. Paseo 0.11.2
starts that bearer-protected bridge on an ephemeral IPv4 loopback port. The
fixture resolves the private runtime-reported worker PID, verifies UID 1001,
and matches socket inodes from `/proc/<pid>/fd` with the kernel TCP tables.
Exactly two listeners must belong to that worker; the auxiliary endpoint must
return 401 for missing and invalid bearer tokens. Additional public, IPv6,
unowned or duplicate listeners fail. It then requires only the four existing listeners
after manual stop and after volume restore/restart. The bridge executable is
also tested locally against a late native bind and temporarily unhealthy
native endpoint: MCP reconciliation starts only after native health is ready.

The isolated HA environment owner stages the candidate in the **existing
canonical repository entry**, preserving its repository ID, add-on slug,
options, and `/data`; changing the staged catalog version selects the candidate
tag above without changing the image repository. Use Supervisor's normal
update with an add-on backup. Do not uninstall, add a second repository, or
rename the slug. Confirm catalog reload preserves the staged source before
updating; source staging is a test-only VM operation owned by that agent.
Record baseline/full slug and options, then verify native `0.2.6 → candidate`
update, Ingress launcher/auth, runtime lifecycle, and data persistence. Exercise
fresh install from a separate clean snapshot. Candidate image success alone is
not HA acceptance. Stable merge remains held for main review, the final public
core pin, and both image and real-HA evidence.
