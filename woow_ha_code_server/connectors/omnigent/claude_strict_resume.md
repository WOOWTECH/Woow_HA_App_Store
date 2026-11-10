# Explicit native cold resume

Refresh shared MCP operates on an attached native conversation. It does not
create a conversation or silently invoke Omnigent's ordinary cold ensure. In
Omnigent 0.16.0 that ordinary Claude path reconstructs the native transcript from
server messages and can fall back to a fresh process without `--resume`.

The packaged strict path is an explicit operator operation for an existing idle
Claude/Pi conversation. Default initialization, fork and rewind keep their
upstream behavior. Only a runner launched with
`WOOW_NATIVE_STRICT_RESUME_REQUEST=/absolute/private/request.json` enters the
strict cold dispatcher. It runs before the initial native terminal launch,
including initialization triggered by an owner-authorized `runner_id` rebind.
The optional strict plan survives native context enrichment.

The request directory must be owned by the runner user and mode 0700; the
regular request file must be owner-only, without symlink parents. Its version-1
JSON contains `engine` (`claude` or `pi`), `sessionId`, `nativeSessionId`,
`workspace`, `originalBytes`, `originalSHA256`, a random 32-hex `requestId`, and
Unix `issuedAt`/`expiresAt` timestamps (at most one hour apart). Obtain these from
fresh authorized session detail and the actual existing native file. Never infer
them from a newly generated or reconstructed transcript. Keep a private durable
copy of the verified original outside bridge roots before any process transition;
upstream orphan maintenance can remove a dead bridge and its Pi history.

The loader takes an exclusive nonblocking request lock, checks the authoritative
session and original bytes, and holds the native launch lock. Claude additionally
requires existing onboarding/workspace trust, rejects competing supported Claude
processes (npm, native and versioned installer forms), and launches exactly one
`--resume ORIGINAL_UUID`. It never synthesizes native JSONL, accepts trust, uses
fork/fresh flags, and refuses a launch that would clear the persisted model pick. The original native
file inode and hash are checked before spawn; every original byte must remain a
prefix afterward. The launcher-selected bridge is validated, including the
`-cleared` bridge of a superseded original conversation. Success requires a
fresh `SessionStart` hook after this launch's spawn boundary, the exact native
and visible IDs and transcript path, and the registered terminal's actual live
Claude process. Its PID/start ticks must belong to the new launch, its arguments
must contain the exact `--resume`, and its environment or private `--settings`
hooks must bind this bridge. The pane/process identity is checked again after
reading the hook and history. An old hook or a surviving tmux server with a dead
Claude pane cannot confirm attachment. The receipt includes the verified PID,
start ticks and hook generation; it describes that verification instant, not
permanent liveness of a subsequently stopped process.
Pi uses its separate [strict launcher](pi_strict_resume.md), including native
no-new/no-rewrite guards and its actual native socket confirmation.

An attached result is written to `request.json.attached.json` with the request
digest, original IDs and prefix hash. The request is one-shot. A failed armed
bootstrap blocks later ordinary Claude/Pi ensures before any forwarder cancel,
bridge clear or transcript synthesis. It must not be retried by sending a chat
message. Inspect the error and original process first. An operator can prepare a
fresh bounded request only after confirming no competing native process and the
exact original history. Nothing is killed automatically to make a retry succeed.

For staging, use an isolated vendor copy/PYTHONPATH and the existing SDK login,
host identity, provider configuration and persistent volumes. The official manual
runner registration plus owner-authorized PATCH of **only** `runner_id` can bind
that protected runner to the original session. That PATCH can initialize the
runner immediately: the strict request must already be armed. Check native,
workspace and host invariants before and after the PATCH. A server timeout is
not attachment proof; inspect the durable receipt and current binding. Never
blindly restore an offline previous runner ID or overwrite native history from a
backup. A scoped rollback may stop only the task-owned unbound process after PID
identity verification. No host/add-on restart is part of this feature.

The explicit terminal API (`woow_strict_claude_resume: true`,
`ensure_native_terminal: true`, `terminal: claude`, `session_key: main`, plus
`expected_external_session_id` and `expected_workspace`) is usable only with an
already connected protected runner. First read its
`woow-strict-resume-capability-v1` terminal resource. Older runners ignore unknown
POST fields, and central terminal POST can wake a cold runner before forwarding
the body. Do not use this endpoint as a cold-runner capability probe. Existing
central EDIT/OWNER authorization remains in force.

The image installer applies an exact-hash Omnigent 0.16.0 patch and verifies
idempotence against reconstructed SHA-pinned originals. Tests execute the actual
pinned launch/context/persistence branches and cover busy admission, removal of
the ordinary fallback, alternate executable forms, immutable history, cleared
bridges, duplicate requests, unsafe files, failed attachment and forged receipts.
Cold attachment and native reload receipts are separate from model/tool-call
proof; neither sets `toolsVerified: true`.
