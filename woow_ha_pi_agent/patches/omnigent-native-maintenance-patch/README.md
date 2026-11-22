# Native bridge maintenance preservation: source-only candidate

The candidate vetoes automatic orphan pruning for any native bridge containing a file other than its root `owner.pid`. Old rollouts, arbitrary history formats, dead letters (including empty/rotated files), generated auth/config and symlinks stay in their exact original directory. There is no archive, quarantine, credential copy, repair, restore or runtime monkeypatch. **The missing 15 native histories are not restored. Pi3 migration remains HOLD; Pi4 remains NO APPLY.**

Only `omnigent/native/native_bridge_common.py` is overlaid. Its exact captured original SHA256 is `2a80d492f6f844a8da0e7dbb3e8aaec396a2bbd525f6d042ddc3cf2eed6bccc6`; the candidate SHA256 is `68f4c2a3c0a3aa75436a15828e325bd279995435d83931d93b12516cca303962`. Both old 6144 and new 5164 captured sources have the original hash. This is core Omnigent code, shared across native harnesses, rather than the plugin adapter. See `source-lock.json` and `maintenance-preservation.diff`.

The safety rule intentionally proves a small disposable subset rather than guessing history filenames. A marker-only bridge, including empty nested directories, remains eligible if the existing owner, stable lock and harness-specific age predicates permit it. Every other leaf is retained, even a generated config with no history. This reduces automatic reclamation; retained data consumes its existing storage until a deliberate explicit deletion. It creates no hidden duplicate or new credential store. Existing inode, ownership, file bytes, modes, paths and auth/config aliases remain in place for retained bridges. Directory metadata is read; credential/file contents are not read by the new guard.

The metadata scanner rejects root/ancestor/child symlinks, regular hardlinked owner markers, special entries, filesystem crossings, errors, observed changes, more than 1,024 entries or depth beyond 16. Directory traversal uses `O_NOFOLLOW` and directory descriptors. The guard runs before reading an owner alias or acquiring a cleanup lock, then again under the existing preparation lock immediately before deletion. Lock directory/file symlinks veto cleanup. Two snapshots compare device/inode/mode/ownership/size/mtime/ctime. Scan failure or uncertainty means retain, never permission to delete a partial inventory. Retained bridges are not counted as cleaned.

The common lock and owner/liveness reread remain in use. Codex's original seven-day predicate is unchanged and remains an additional condition for an otherwise disposable bridge. The unmodified Codex bridge docstring still describes the old age-only policy; under this patch, age is necessary but no longer sufficient. The new common pruner docstring and this proposal describe the effective veto.

## Explicit deletion and privacy

The exact captured `_delete_native_bridge_dirs` and both HTTP DELETE callers are untouched. Intentional session deletion remains destructive and scoped to the original ordinary/rotated bridge IDs and attachment caches; no retained copy is made. The existing resource DELETE endpoint also remains destructive. The captured call sites do not prove that an external caller automatically uses that endpoint as an idle/uninstall operation, so this candidate does not invent new semantics. If such automation is established, its caller needs a separately reviewed preservation contract before using destructive cleanup. **This is not uninstall/resource-teardown protection.**

This candidate protects against the maintenance path; it cannot override an explicit DELETE, other deletion tools, external storage loss or an uncoordinated writer arriving after the final check. The existing bridge preparation lock protects cooperating preparation, not arbitrary writers. No file-inventory check can atomically exclude a writer that ignores that lock. No race-free writer protocol, purge workflow, secure-erasure claim, or broader refactor is introduced. Automatic maintenance never resolves, reads or deletes attachment caches, even after removing a genuinely empty bridge. Empty/nonempty/symlinked/unreadable caches remain in place for deliberate explicit cleanup. This also avoids creating a second cache scan/delete race. Retaining a bridge on `/tmp` does not make it durable across host/volume loss.

## Root event evidence

Root's saved `persistent-maintenance-events.json` is bound at SHA256 `15cf3deb88cda84c42cbcd14555e986479c757c472e089c58fd54bda41bdee9e`. Root reported a 1,164-byte host log `host-20261122-074130-586844.log`, SHA256 `16232268ace2a17f4b6f6b4b4d41414906969f214c51131cf248f237dd8ef463`, mtime_ns `1795304501492196643`, with `stage=native_bridge_orphans cleaned_items=15`; terminal orphans were zero. The count and timing strongly correlate with the missing 15 native homes. No per-directory identity audit exists, so this is not exact per-file deletion proof. The earlier diagnosis remains immutable; this note adds the new event context. Root separately owns the two-field Claude proof, ledger proof, logs and recovery investigation.

## Local verification

Run inside this directory:

```sh
python3 -B verify_source_patch.py
```

The recorded local suite has 57 tests on Python 3.11.2 / Linux with filelock 3.32.5. The two red baseline regressions demonstrated that the original pruner deletes old rollout/dead-letter fixtures, then passed with the candidate. Tests execute AST-extracted functions with owned path resolvers and exact source fragments; they never import/execute the live SDK, provider, host or runner package. Tests use `tempfile.TemporaryDirectory()` with standard `TMPDIR` support, so they can run from a read-only installed package. During this sidecar review, `TMPDIR` is set to this child's `tmp/`; fixtures are removed. The strict applicator is exercised against fixture site-packages only, including actual application and pyc regeneration. No image build, container, Kubernetes/production call, provider execution, SDK turn, main-repo integration, data inventory or deployment ran.

`fixtures/captured/` carries 16,308 bytes of exact source/function fragments for portable tests. The additional 43-source check runs when the parent diagnosis capture exists, as it does in this review workspace. In a copied build package that one check is explicitly skipped; all portable behavior/lock checks still run. `fixtures/captured-fragments.json` binds fragments to their full captured source hashes. Tests and proof show the original 43 files unchanged, not an installed production fix. Python 3.12/image-interpreter verification remains root's integration step.

Set `PI_NATIVE_MAINTENANCE_TEST_SOURCE` to the absolute installed `native_bridge_common.py` for final-image verification. The override must hash exactly to `afterSha256` in `source-lock.json` or test collection fails. Without an override the selected file is the overlay. All maintenance behavior tests AST-execute the selected actual source with controlled fixture dependencies; this proves the source behavior without importing the live SDK.

Read `INTEGRATION.md` for the concrete build seam. Root owns source integration, image build, review, and any later normal rollout/admission. Pi1 capture remains paused.

The deterministic source archive is `native-maintenance-preservation-source-v1.tar.gz`; it extracts as `omnigent-native-maintenance-patch/`. `SOURCE-BUNDLE-MANIFEST.json` records each included source/test/fixture hash. `SOURCE-HANDOFF.json` binds the archive, manifest, exact payload, lock and source-only proof. Generated logs/receipts and temporary fixtures are excluded from the source archive.
