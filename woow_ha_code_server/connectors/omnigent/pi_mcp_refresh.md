# Native Pi MCP refresh

This helper replaces MCP connections inside the existing Pi process. It never
resumes, creates, or synthesizes a conversation, closes a terminal, aborts a
turn, rewrites native persistence, or changes provider credentials.

## Connector contract

```python
from native_resume import refresh_pi, NativeRefreshError
result = await refresh_pi(session_id, authorized_info, sync=synchronize)
```

`authorized_info.external_session_id` must be the original Pi UUID. `synchronize`
is the connector's canonical MCP synchronization callback and returns a SHA256.
The callback runs only after native idle/identity/persistence preflight. A
private Unix socket and peer UID check bind the bridge to the local user; a
nonblocking file lock serializes separate connector processes. The native
controller serializes requests again inside the actual Pi process.

Success uses `refresh.state="applied"`, `method="native-mcp-reload"`,
`historyPreserved=true`, the unchanged `nativeSessionId`, `configurationHash`,
`inventoryVerified=true`, `toolsVerified=false`, and `toolCount`. Inventory
registration does not prove that every tool works. Independent actual tool
calls are required for that claim. Errors expose only `NativeRefreshError.code`.
An unbootstrapped resident extension returns `MCP_NATIVE_UNAVAILABLE`.

## Preparation and publication

Pi 0.99.1 exports its built-in `createMcpExtension`. The helper stages that real
factory with buffered registrations and waits for its startup barrier. A failed
connection or timeout closes staged connections and preserves old tools. Native
`ctx.isIdle()`, pending messages, input/agent events, native UUID, and the existing
session file header are checked again immediately before synchronous publication.
No await occurs between the final checks and registration. Removed tools become
hidden and leave the active inventory. Retired factory callbacks cannot publish;
old-connection cleanup failure cannot turn a completed publication into a false
refusal. An unsuccessful prompt admission may conservatively block refresh until
another turn settles.

## Build patch and existing-session bootstrap

Run `patch-native-resume.py --site-packages /absolute/runtime/purelib` during the
image build. `--check` verifies without writes. It accepts only exact pinned
Omnigent 0.16.0 bridge/extension hashes, copies the helper resource, and records
hashes. Reapplication verifies source reconstruction and the receipt. Do not run
the build patch against a shared live installation.

The extension uses an ESM import so Pi's Jiti loader supplies the actual Pi API
and evaluates the updated source on `/reload`; a plain CommonJS require can use
the stale native module cache. It requires Pi 0.99.1 and Node 22.
On reload it also invalidates only the packaged helper's own CommonJS cache
entry, so an updated helper is actually evaluated. Other modules stay cached.

One supported `/reload` is needed to bootstrap an already resident unpatched
bridge, only while its original native process is idle and reserved by the
coordinator. No model call is needed for bootstrap. Verify the actual process,
original persisted session UUID, native bytes, and inbox first. Place patched
extension/helper files only in that session's private bridge. First bootstrap
requires owner-only `woow-mcp-bootstrap.json` containing the exact `sessionId`,
`nativeSessionId`, and current native `pid`. The native handler rechecks identity,
persistence, idle, and pending messages itself.

Omnigent 0.16.0 leaves its inbox timer running after extension shutdown. This
one-time compatibility shim uses **internal Node 22 timer-list fields** for
discovery, bounded to 4096 links. It creates and always clears a temporary probe,
matches the original 250ms callback's exact SHA256
`4efe03b5e290823384b6867e4619dcfce0b741687e7ab9ee9933123db7549772`, and calls public
`clearInterval` on that one handle. Unknown version/hash/list shape, zero matches
on first bootstrap, or more than one match refuse without clearing other timers.
Zero matches are accepted only for native startup or a known later patched
reload in the same process/session. All unrelated timers are preserved. Future
patched reloads use ordinary shutdown cleanup of their own inbox timer. The
probe receipt includes `legacyPollersRetired` for bootstrap evidence.

If the native process is absent, this bootstrap does not apply. Do not use the
upstream ensure/resume path as a substitute: its synthesis failure can fall back
to a fresh session. A separately verified strict native-file resume procedure
is required before bootstrap can be considered.

## Tests

Set `PI_TEST_PACKAGE` to an isolated npm installation of
`@earendil-works/pi-coding-agent@0.99.1` and
`OMNIGENT_TEST_SITE_PACKAGES` to an unmodified Omnigent 0.16.0 fixture:

```sh
node --test connectors/omnigent/tests/pi-mcp-refresh.test.cjs connectors/omnigent/tests/pi-mcp-bootstrap.test.cjs
python -m unittest discover -s connectors/omnigent/tests -p test_native_resume.py -v
```

Tests load the real factory and real JSON-RPC client, invoke nonce-bearing tools,
verify additions/removals and native byte identity, busy/concurrent refusals,
late callbacks, preparation and cleanup failures. Actual original/patched
extensions load through Pi's Jiti. Bootstrap tests retain an unrelated 250ms
timer, deliver a pending inbox file exactly once, reject ambiguous matches and
identity changes, and perform two consecutive reloads without an orphan poller.
