# Scoped prompt garbage collection regressions

The addon builds upstream Hermes from the digest in `hermes/Dockerfile`. Its
versioned product change lives in `hermes/patches/scoped-prompt-gc.py`; no upstream
checkout is vendored into the addon. The build applies the patch and verifies
its complete output hash. A source change, partial patch, unknown split module
or symlink fails closed. The base digest and addon version are unchanged.

Deleting one session previously collected **every** unreferenced prompt in the
store. Both deletion methods now capture the prompt hashes of the actual
session deletion set (including existing delegate cascades) inside the write
transaction, then reclaim only those hashes without surviving references.
Compression deletion captures after lineage expansion and active-write guard
filtering. Existing return values, cascade/branch behavior, transactions,
guards and public signatures are preserved. Other maintenance GC is unchanged.

## Reviewed inputs

| Source | Original SHA-256 | Patched SHA-256 |
| --- | --- | --- |
| `hermes_state.py` | `696fd2d37d66a599228f5b1be5d5b76423b744149c83a2fbd59bf3f45a5f3891` | `8a17f82d934ddc454c1e8251a3bd862b2ffa11f21bf916f57da803ae43932d48` |
| `hermes_state_sessions.py` | `f1bfa82b4010b054001a8344f1b00a6b25694ae4cd439f8c8355f8a74f0fe084` | `2dfef303c1650e5a51478372a753ee36891d1c78d546d3ba937e2a66f7427305` |

The monolithic source was extracted read-only from addon 0.1.7, image
`ghcr.io/woowtech/woow-ha-hermes-amd64@sha256:b95837d15bd8ef856c2a87e1ea723573c805b6d72675515242e1190cab828e15`.
The split source is the newer 2026-10-13 dependency-repair bundle, with separate
source provenance; it is **not** the 0.1.7 image. That image has no
`include_compression_chain` parameter. The split pin makes drift explicit; it
does not authorize a base upgrade or establish the source loaded on HA.

Fixtures contain unchanged method/helper excerpts from those complete sources,
plus imports and a minimal class wrapper. Split SQL helpers are unchanged
excerpts from `hermes_state_common.py`, whose hash is in `provenance.json`.
Each variant uses its own original global-GC helper for the negative control.
Newer upstream also interns `tool_names` in `system_prompts`; the split patch
captures both columns and preserves rows referenced by either surviving column.
This corrects an additional missed-reference defect in the earlier R5 split
candidate; the monolithic candidate bytes remain unchanged. `LICENSE` preserves the upstream MIT notice.

## Local and image commands

From the repository root:

```sh
# Expected nonzero: the original source deletes unrelated orphan prompts.
PYTHONDONTWRITEBYTECODE=1 python3 hermes/test/test-scoped-prompt-gc.py --unpatched
# Expected zero: both variants, including compression-chain routes.
PYTHONDONTWRITEBYTECODE=1 python3 hermes/test/test-scoped-prompt-gc.py
PYTHONDONTWRITEBYTECODE=1 python3 hermes/test/test-scoped-prompt-gc-patch.py

# In an environment with the existing cached 0.1.7 image and Docker:
# negative control, then the product patch applied to a complete tmpfs copy
python3 hermes/test/run-scoped-prompt-gc-image.py --unpatched
python3 hermes/test/run-scoped-prompt-gc-image.py --apply-build-patch
# Already-built candidate, referenced by its immutable digest/image ID:
python3 hermes/test/run-scoped-prompt-gc-image.py --image sha256:<image-id>
```

The image runner uses `--pull never`, no network/host ports, a read-only rootfs
and test mount, UID 10000, dropped capabilities and private tmpfs. It neither
builds nor tags nor publishes images. It only removes its own unique container
on timeout. `--describe` prints its exact flags without invoking Docker.
The PR candidate CI gate imports the real installed SessionDB in the built
image, so build wiring, complete output hashes and runtime behavior are checked
together. Running the local excerpt suite alone is not that gate.

Default tests execute upstream deletion and compression SQL against real
SQLite, with a small schema/transaction/guard adapter. Runtime mode imports the
complete SessionDB with its real schema, guards, transaction code and cleanup;
`--runtime-root /path/to/upstream --overlay-root /path/to/patched-module`
selects that mode. Optional `--temp-root` confines all fresh synthetic stores.
`test-scoped-prompt-gc-patch.py --source-dir /path/to/original-module`
also exercises exact full-file apply/check/idempotence/drift contracts.
No user store, real credentials, models or gateway are used. Neither mode
exercises authentication, MCP transport, application lifespan or HA deployment.

Covered behaviors: exact single/batch deletion, shared prompts until the last
reference, unrelated orphans, null prompts, delegate grandchildren, branch
survivors, unknown/repeated/invalid batch IDs, expected-delete-set mismatch,
SQL-abort rollback of prompts/messages/sessions and post-commit files, and
transaction ordering. Split tests also cover chain-tip single/batch expansion,
sibling continuations, branch/reset/tool exclusions, default non-chain delete,
partial/all active-write-guard filtering and chain rollback. Chain-only cases
are explicitly skipped for the monolithic source.
