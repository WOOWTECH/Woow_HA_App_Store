# Native maintenance preservation implementation plan

**Goal:** Prevent automatic native bridge maintenance from deleting persisted state, without changing intentional explicit session deletion or copying credentials.

**Architecture:** In an isolated copy of the exact captured common pruner, add a fail-closed disposal predicate under the existing preparation/cleanup lock. Only owner.pid plus empty directory trees qualify. Every other leaf, symlink, special entry, error, limit breach or changed scan vetoes maintenance. Preserve the existing owner/lock/age predicates. No archive or restore.

**Scope:** All source, tests, fixtures and receipts stay in this new child. Original 43 captured sources and operational assets are read only. The earlier archive idea was not implemented; it is superseded by the user's maintenance-only refinement. No deployment, image build, SDK/provider import, network, user data read, Pi1 work or production acceptance.

1. Record exact original hashes. Write a red regression using AST-extracted captured pruner and real stdlib fixture deletion; no live package imports. Demonstrate old seven-day logic deleting old persisted rollout bytes in an owned fixture.
2. Add a bounded, metadata-only disposal predicate to the common source copy. Guard the root and each candidate; run it before the age predicate and again immediately before deletion. Keep permissions, aliases, filenames and bytes in place when retained. Do not inspect credential contents.
3. Test original rollout/deadletter regression, unknown history formats, empty eligibility, live/changing owners, locks, age checks, unreadability, symlinks/path escape, special entries, depth/entry bounds, concurrent additions, and exact fixture bytes/modes before/after. Prove explicit delete functions/callers untouched.
4. Supply an exact-source strict build overlay applicator with payload hash checks and source drift rejection. Exercise it only in owned fixture site-packages. Recommend the root-provided PaaS image seam after existing strict patches; leave main/frozen assets unchanged.
5. Recheck all 43 original sources, run source-only tests and AST/compile checks, record root's event evidence as correlation with no per-file proof. Produce source-lock, unified diff, tests and receipt. Root owns integration and all later build/rollout/admission. Lost 15 histories are not restored; Pi3 HOLD/Pi4 NO APPLY remain.
