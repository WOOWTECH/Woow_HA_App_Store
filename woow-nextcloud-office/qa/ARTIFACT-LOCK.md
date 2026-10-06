# Offline artifact lock — consistency, NOT acceptance

`artifact_lock.py` binds two image declarations and their inputs to one observation
bundle. It has no collector, network, subprocess, install, service or remediation
path. Use **only a curated PUBLIC directory** explicitly approved for this job;
never point it at credentials, business data, backups, PGDATA or private results.
It reads only the manifest and explicitly referenced files, never recursively
searches a directory, and writes only a JSON report to stdout.

```sh
python3 woow-nextcloud-office/qa/artifact_lock.py \
  --public-root /absolute/approved/public-artifacts --manifest lock.json
python3 woow-nextcloud-office/test/test-artifact-lock.py
```

`--manifest` and all artifact paths are relative to that root. The checked-in
`fixtures/artifact-lock.unresolved.json` is an intentionally **blocked template**,
not evidence. Temporary test fixtures fabricate consistent caller assertions to
exercise both exits; they are never collected runtime evidence.

## Exit and trust boundary

- **0**, `offline_lock_consistent`: supplied hashes/declarations agree and the
  existing candidate inventory evaluator accepts the supplied observations.
- **1**, `blocked`: unreadable/unsafe inputs, schema/JSON errors, missing pins,
  hash/binding mismatches, unresolved/stub declarations, or inventory drift.
- **2**: argparse usage error (stderr; no JSON report).

All JSON reports, even success, set `signed_source_verified`,
`image_build_verified`, `provenance_authenticated`, `runtime_verified`,
`haos_verified`, and `production_authorized` to **false**. The report never echoes
untrusted paths, field names or contents on failure. No waiver/repair option.

A receipt's `verification_status=verified` is **only a caller assertion**. Hashing
it binds that assertion but authenticates neither its author nor its truth. This
tool does not verify signatures, APT Release chains, dependency completeness,
Git object existence, deb/archive metadata or contents, OCI graph completeness,
base image/config/layers, builds, freshness or runtime identity. The image digest
hashes the **raw single-platform image-manifest JSON bytes**, not a Docker-save
tarball, image ID, registry tag, index or checksum of a reserialized manifest.
Only its v2 OCI/Docker manifest envelope is checked. Architecture is bound across
caller declarations/receipts; it is not independently inferred from binaries.

## Strict schema v1

Every listed field is mandatory; additional fields in lock/receipt objects are
rejected. Duplicate JSON keys, NaN/Infinity/overflow, duplicate IDs/paths/input
references, unreferenced artifacts and wrong types fail closed. Lists are bounded
and nonempty where described; booleans are not integers. Only lowercase SHA256
(64 hex) and full SHA1 Git commits (40 hex) are accepted. Repeated patterns of
length 1–16, including all-a/all-b/all-zero placeholders, are rejected. This
heuristic cannot distinguish an invented plausible hash from a real one.

Top level:

| Field | Contract |
| --- | --- |
| `schema_version` | integer `1` |
| `scope` | `isolated-synthetic`; authorization is not inferred |
| `evidence_kind` | `collected`, still an unauthenticated caller label |
| `architecture` | `amd64`, `arm64` or `armhf` |
| `observation` | ID of the sole bound `observation` artifact |
| `images` | object with exactly `source` and `candidate` |
| `artifacts` | 1–256 artifact objects; every entry must be referenced |

Each image contains exactly:

- `digest`: `sha256:` + hash of its referenced raw image manifest.
- `source_commit`: full 40-hex commit, also bound by its receipt.
- `architecture`: exactly the top-level architecture.
- `manifest`: ID of an `image-manifest` artifact.
- `inputs`: nonempty unique list of `package`/`archive` artifact IDs.
- `receipt`: ID of its `provenance` artifact.

Each artifact contains exactly `id`, `kind`, `path`, `sha256` (bare hash),
`size_bytes` (positive integer). Kinds: `image-manifest`, `observation`,
`provenance`, `package`, `archive`. The last two additionally require `name`,
`version`, `architecture` (the lock's architecture or `all`). Version must
contain a digit. IDs/names/versions are 1–128 ASCII characters, beginning with
alphanumeric then alphanumeric or `._+:~-`. Tokenized labels like `stub`,
`fixture`, `synthetic`, `placeholder`, `unknown`, `unresolved`, `pending`, `todo`,
`tbd`, `changeme`, `latest`, `rolling` are rejected (case-insensitive).

The observation file is the existing **unchanged** schema in
[CANDIDATE-INVENTORY.md](CANDIDATE-INVENTORY.md). Its evidence kind must be
`collected`, both digests must match this lock, and its evaluator must pass.
Changing its bytes breaks the locked hash and both receipts' observation binding.
There is no collation-drift waiver; a real bookworm→trixie migration still needs
a separately reviewed migration/index-rebuild workflow.

Each parsed provenance receipt contains exactly:

```json
{
  "schema_version": 1,
  "verification_status": "verified",
  "image_digest": "sha256:<same-as-image>",
  "source_commit": "<same-as-image>",
  "architecture": "<same-as-image>",
  "observation_sha256": "<hash-of-the-exact-observation-bytes>",
  "inputs": [{"id": "<input-id>", "sha256": "<same-as-artifact>"}]
}
```

The above explanatory placeholders **must not pass**. Receipt inputs must be an
exact ID→hash mapping of the image input list, with no duplicate/extra/omitted
rows. Shared artifacts are permitted if explicitly bound by both images.

## Read boundary and limits

Linux/Python standard library, descriptor-relative `open` with `O_NOFOLLOW` on
**every component including root ancestors**, `O_NONBLOCK` and `fstat` on files.
Only single-link regular files can be read. Absolute artifact paths, dot/hidden
components (including `.private`/`.ssh`), traversal, empty components, backslash,
control characters, `gnupg`/`PGDATA`, symlinks, hardlinks, devices, directories and
FIFOs are rejected. `/dev`, `/proc`, `/sys`, `/etc`, `/root` and `/` cannot be
public roots. Root naming checks are not a classification service: the operator
must still ensure that **all explicitly supplied files are public**. Do not use
a broad ancestor directory as the root. No discovery of arbitrary local files.

Limits: 1 MiB per JSON, 128 MiB per package/archive, 512 MiB total (including the
lock and a reserved growth probe per artifact), 256 artifacts, 64 path components,
4096 path characters. Declared total budget is checked before artifact reads;
actual reads are independently bounded and streamed in 64 KiB chunks. Size/hash
and pre/post inode/size/mtime/ctime checks reject changed inputs. This detects
ordinary concurrent mutation, not an authenticated immutable filesystem snapshot.
Large real inputs require a reviewed limit revision, not an override flag.

## Minimum path to real rehearsal

Do **not** add endless offline gates instead of obtaining the blocked environment:

1. Operator-approved repair/provisioning of the denied APT environment, then
   explicit authorization for isolated signed dependency resolution/build.
   Do not change `/dev/null`, ACLs, sandbox, identity, model or trust settings as
   a workaround. Produce real source/candidate manifests, pinned inputs and
   build/provenance evidence. Local archive hashes alone are insufficient.
2. Authorized collector and candidate service runtime: PHP CLI/FPM, nginx, CODE
   WOPI/WebSocket/persisted save and PG16; bind real observations, not this fixture.
3. Resolve actual source/candidate libc/ICU/collation drift with reviewed migration
   and index rebuild plus complete DB/files/config/image rollback. Run isolated
   synthetic NC33→34→35 and full rollback; unchanged inventory checks will block
   real drift until that workflow has an explicitly reviewed disposition.
4. ARM and HAOS/Supervisor acceptance, remaining OAuth→MCP/replica/fault/load/
   security acceptance, legally usable HERE key where needed. Production changes
   separately require scoped acceptance and an approved maintenance window.
