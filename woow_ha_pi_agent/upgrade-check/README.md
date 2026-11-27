# Native-history upgrade fixtures

The Store runs `seed` on the comparison image, then `verify` after the candidate
starts on the same temporary data directories. Both executable Python3 hooks
run in the mock Supervisor, using only the standard library. They do not
contact the addon, import its SDK, invoke maintenance, or call a provider.

The current Store contract supplies `DATA_DIR_DATA`, `HOOK_STATE_DIR`,
`REPORT_DIR`, `PHASE`, `ADDON_VERSION` and `ADDON_IMAGE`. All helpers are inside
this directory because only `upgrade-check/` is mounted into the mock. The
existing default hook timeout applies; no skip or privilege change is needed.

`seed` creates three generated bridge roots below
`$DATA_DIR_DATA/pi-agent/home/.omnigent/codex-native` and writes two isolated
fixtures under `$DATA_DIR_DATA/pi-agent/pi-paseo/daemon`: a synthetic pairing
sentinel and a valid Better Paseo `plugin-data/better-paseo/tasks-stops.json`
record. The latter checks that Tasks plugin data survives the r1-to-r2 image
transition. Together these are eleven synthetic files; existing unrelated
native homes and daemon data are neither listed nor read. File mtimes model
the reviewed eight-day-old fixture. Repeated seed attempts refuse existing
state, including an existing Tasks state file.

The complete fixed-scope manifest and SHA256 seal are written with exclusive
creation into `HOOK_STATE_DIR`. Verification derives the required cases and
payload hashes from the fixture definition and nonce, so a narrowed/resealed
manifest is rejected. It binds the original shared data directory's device
and inode, requires distinct old/new image and version labels, and compares
all file hashes, sizes, modes, uid/gid and mtimes. Labels and hook state are
trusted CI inputs, not independent image provenance or authentication.
Version labels accept stable `X.Y.Z` and numbered `X.Y.Z-rc.N` candidates
(positive N, no leading zero, at most 32 characters). Both old and new labels
use the same check; identical versions or identical image labels still fail.

Descriptor traversal refuses symlink ancestors, directory/leaf links,
hard-linked/nonregular files, unexpected entries, incomplete manifests and
scope overlap. Bounds: four fixture roots, eleven files, 64 entries, depth8, 4096 bytes
per fixture file, 16384 bytes per state file. Reads check stable metadata.
The controlled CI directory is assumed quiescent during verification; this
is not a live transactional admission check against arbitrary concurrent
writers. A failed seed can leave its partial CI fixture; it never deletes
or overwrites existing data. Verification never repairs or reseeds data.

Reports at `$REPORT_DIR/seed.json` and `verify.json` contain status, counts
and a manifest hash, with `maintenanceExecuted: false`. Invalid report/scope
paths fail without writing a report. File reads may update filesystem atime;
no payload, mode, ownership or mtime rewrite occurs during verify.

These hooks prove survival of synthetic files across the Store image upgrade
only when that genuine CI run executes them. They do not prove that automatic
maintenance ran, provider compatibility, full-home completeness, recovery of
missing data, backup validity, production admission or actual HA acceptance.
The separate image-installed maintenance AST suite checks pruner behavior.

Run the local subprocess model with:

```sh
python3 -B tests/native-history-upgrade.test.py
```

This models old/new hook phases sharing an owned temporary directory; it does
not build or start old/new images. The source workflow also runs the five
maintenance integration checks before the genuine architecture builds.
