# Explicit original Pi cold resume

This is separate from `refresh_pi`, which updates MCP in the running Pi process.
Cold resume creates a new process with the original native ID and full original
history prefix. It never claims to preserve a process that has already exited.

Bohr owns the shared runner/app.py and native/orchestration.py patch. Its explicit
bound cold-init dispatch must run **before** ordinary native initialization,
under the per-session ensure lock and ordinary input-admission fence:

```python
from omnigent.runner.native.woow_pi_strict_resume import cold_resume
result, receipt = await cold_resume(ctx, request, launch_kwargs=launch_kwargs)
```

This matches Bohr's `woow_native_strict_bootstrap.strict_cold_launch`. Its private
envelope binds `sessionId`, `nativeSessionId`, `workspace`, `originalBytes` and
`originalSHA256`. `ctx` carries the original session ID, server client and resource
registry. The adapter takes `launch_kwargs.ensure_locks`, resolves the original
agent spec through `resolve_agent_spec`/`build_context`, fetches fresh server
detail, checks the bound bytes, and invokes the lower-level `launch_pi_strict`.
It publishes the resource-created event and returns `(True, receipt)` only after
the native probe and history checks pass. The receipt explicitly reports
`sameProcess:false` and the new PID. Propagate `PiResumeError.code`; never fall
back to ordinary ensure.

Install these mappings under the runtime site-packages `omnigent/` directory:

| Runtime path | Connector source |
| --- | --- |
| `runner/native/woow_pi_strict_resume.py` | `pi_strict_resume.py` |
| `runner/native/pi_strict_launcher.mjs` | `pi_strict_launcher.mjs` |
| `runner/native/woow_pi_native_resume.py` | `native_resume.py` |

The original bridge needs the already tested
patched native extension and `woow_pi_mcp_refresh.cjs`. No shared patch is supplied
here, avoiding conflicting source hashes with Bohr's Claude integration.

Do not POST the internal spec carrier to central for a cold runner. Central's
`ensure_runner_connected` may run normal session initialization before forwarding
the request, bypassing an explicit request marker. The shared dispatcher owns
that lifecycle exclusion. A standalone preparation result is not authorization
to bypass it and is not an attachment receipt.

The validator derives the bridge from the SDK and the native file from the
authorized external ID. It rejects busy/pending sessions, custom terminal args,
wrong harness/workspace/UUID, missing/empty/malformed/old-version history, unsafe
owners or symlinks, existing native processes, and undelivered inbox entries.
It records every byte and entry, snapshots native history under the configured
persistent PI_AGENT_DATA_DIR, and issues a two-minute private launch ticket.
Under the SDK bridge-preparation lock, the callback updates only `owner.pid` to
the new runner PID so orphan maintenance cannot reap the resumed live history.
An additional per-bridge flock reservation remains held across preparation,
owner assignment, terminal spawn and native confirmation, including asynchronous
waits. Each caller gets a unique immutable ticket path and retains its request ID
in memory; confirmation cannot adopt another initializer's ticket. The native
receipt PID must match both the registered terminal pane PID and the Unix socket
peer PID. A losing initializer refuses before changing ticket or owner state.
Concurrent preparation uses flock; concurrent launcher starts use an exclusive
private directory claim. A killed process can leave that claim behind; recovery
must prove the original process is absent before removing only that claim.

Pi 0.99.1's public bundled `main` and `SessionManager` share the same implementation.
The launcher wraps the synchronous initial `SessionManager.open`, verifies the
exact file hash and UUID, and temporarily refuses `newSession` and `_rewriteFile`.
It then verifies every loaded entry and the unchanged original file. The guard
is restored after that initial open; normal later native commands remain native
behavior. Startup may append native metadata; the complete prior byte prefix
must remain unchanged. The native extension's private socket confirms the
original session, and the callback verifies the full original prefix again.

Auth files, provider configuration, model selection, trust and tool permissions
are not rewritten. The original native history restores its model/thinking.
Existing agent directory and sandbox/credential denylist are retained. There is
no `--approve` or new trust acceptance: project resources require an existing
native trust decision. Unexpected custom launch arguments refuse for separate
review instead of silently changing native behavior.

## Deployment persistence

Omnigent 0.16 `pi_native/bridge.py:prune_orphaned_bridge_dirs` delegates to a
dead-owner sweep that deletes the **whole bridge directory, including sessions**.
Normal Pi resume preserves an existing native file, but synthesizes central
history when it is missing, and upstream orchestration can fall back to fresh.
Therefore packaged normal startup alone does not guarantee original continuity.

Before a runner/image transition, stop admitting new work to the three owned
sessions, wait for native idle, and retain owner-private durable history copies
outside the bridge roots. For this task, the sanitized receipt is
`mcp/live/pi-original-history-snapshots.json` and copies are under
`/data/pi-agent/connectors/native-history-backup-20261110/<sessionID>/`.
Only native history is copied; no auth/config is included.

If cleanup pruned persistence, restore the receipt's exact bytes to the original
internally derived bridge/sessions filename with the original owner and mode0600.
First validate backup owner, regular file/no symlink, SHA, complete native UUID
and version3 header. Refuse an existing different target. Verify bytes after an
atomic copy; never reconstruct from central items. The shared dispatcher must
also arrange the original native bridge configuration before strict launch;
the history snapshot intentionally does not contain credentials. Revalidate the
full original prefix after native attachment and after the acceptance turn.

## Tests

```sh
PI_TEST_PACKAGE=/path/to/exact/pi-0.99.1 node --test connectors/omnigent/tests/pi-strict-resume.test.mjs
OMNIGENT_TEST_SITE_PACKAGES=/path/to/pinned/omnigent/site-packages python -m unittest discover -s connectors/omnigent/tests -p test_pi_strict_resume.py -v
```

The JS suite opens real pinned native persistence and runs public `main` in RPC
mode with fixture history, observing original messages/ID without a model call.
It forces native fresh/rewrite attempts, missing-file races, unsafe paths,
changed history and duplicate claims to prove refusal. Python tests cover
internal path derivation, preserved config/history, private snapshots, busy and
pending input, incompatible args/harness, and concurrent preparation.
The exact adapter also uses the actual Omnigent 0.16 context/spec/serialization
classes with a controlled registry, proving the required native role and OS
environment survive, busy/epoch changes refuse, and the bound request cannot
select different history.

## Explicit recovery after bridge pruning

The same callback accepts `restoreSnapshot:true` only on its private bound cold
request. `expectedAgentDir` must equal the original persistent agent directory.
`inspect_pi_recovery(session_id, authorized_info, request)` derives the snapshot
from `PI_AGENT_DATA_DIR/connectors/native-history-backup-20261110/<SID>/` and the
native UUID plus exact SHA; it accepts no caller-selected snapshot or native path.
The verified V3 header timestamp determines the original Pi filename.

The task recovery driver registers a guarded runner unbound, restores the exact
missing bytes under the SDK preparation lock, and sets `owner.pid` to that live
registered runner before owner PATCH. The callback revalidates the bytes and
regenerates disposable bridge controls with current SDK authorization, routing
and runner binding. It retains the attachment reservation through native proof.
Existing different bytes, another native process, queued inbox input, admission
epoch changes or failed metadata preparation refuse without a fresh fallback.
Only successful recovery adds `restoredFromSnapshot:true` to the attachment
receipt. Provider credentials and model/trust settings are never restored or
recreated from backups.

Parent's separate Pi retention patch must be packaged before boot so subsequent
orphan cleanup retains native JSONL. The runner cleanup ownership flag alone does
not disable host maintenance. Recovery does not relax the all-files rollout
manifest or establish preservation for unrelated historical sessions.
