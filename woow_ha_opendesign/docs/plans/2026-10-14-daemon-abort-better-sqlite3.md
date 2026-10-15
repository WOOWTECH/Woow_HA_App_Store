# Intermittent OpenDesign daemon abort (exit 134) — root cause is in the core image

Observed once in about 13 browser e2e runs of the 0.2.0 add-on (team ha-shell, `crash1.log`):

```
#  /usr/local/bin/node[51]: void node::RemoveEnvironmentCleanupHook(v8::Isolate*, CleanupHook, void*) at ../src/api/hooks.cc:142
#  Assertion failed: (env) != nullptr
Aborted (core dumped)
[ha-opendesign] required process opendesign exited (status=134); stopping its peers
```

## Verdict

Not the HA layer (`headless-entry.mjs`, its `startServer` import or its shutdown path). It is a Node.js 24
addon-ABI defect hit by the core image's `better-sqlite3`:

- The core runs Node `v24.21.0`; its daemon loads exactly one native addon at runtime,
  `better-sqlite3@12.10.0` (`/proc/<daemon>/maps` of a running add-on; sharp/onnxruntime are not loaded).
- That binary was compiled from source against Node 24.19+ headers (the fork's build uses the local Node
  headers). Since 24.19.0 the header-only `node::ObjectWrap` constructor/destructor add/remove an environment
  cleanup hook via `v8::Isolate::GetCurrent()`; the runtime support that makes the removal safe outside a
  current Environment was not backported to 24.x (nodejs/node#65446, open). `objdump -d -C better_sqlite3.node`
  shows `Statement::~Statement`, `StatementIterator::~StatementIterator`, `Backup::~Backup`,
  `Database::~Database` and `node::ObjectWrap::~ObjectWrap` calling `node::RemoveEnvironmentCleanupHook`.
- When an allocation-driven GC reclaims a dropped prepared `Statement`, its destructor runs with no current
  Environment and the CHECK aborts the process. The daemon prepares statements per request, so in normal use
  it is a rare, GC-timing-dependent crash; the PaaS image (`od-p1-candidate:local` is the PaaS P1 build) is
  affected the same way.

## Reproduction (core image only, no HA layer)

`docs/repro/better-sqlite3-objectwrap-abort.cjs` prepares and drops statements with the daemon's own
`better-sqlite3`:

```sh
docker run --rm --user 1001:1001 --entrypoint /sbin/tini \
  -v "$PWD/docs/repro/better-sqlite3-objectwrap-abort.cjs:/tmp/r.cjs:ro" \
  od-p1-candidate:local -- node /tmp/r.cjs 2000000
# node v24.21.0, better-sqlite3@12.10.0 / prepared 0 / Assertion failed: (env) != nullptr / exit 134
```

Builder VM, 2026-10-14: 4 of 4 runs aborted (exit 134 under tini, 139 with node as PID 1); the fully logged run
aborted before its 200 000th statement.
The same script against `better-sqlite3@13.0.3` (Node-API `Napi::ObjectWrap`, installed into a throwaway
directory of the same image) survived 2 000 000 statements.

## Fix (core, not this repository)

One of, in order of preference for the core owner:

1. Move the fork's daemon to `better-sqlite3` 13.x (Node-API; no `node::ObjectWrap`). Needs an API check of
   the daemon's usage.
2. Build `better-sqlite3` 12.x against Node 24.18.1 headers (`npm_config_target=24.18.1` / `--nodedir`), or
   use a prebuilt binary that does not import `RemoveEnvironmentCleanupHook`.
3. Change the runtime: Node 22, or a Node release that carries the fix for nodejs/node#65446.

Suggested core gate: fail the build when
`grep -c RemoveEnvironmentCleanupHook .../better_sqlite3.node` is non-zero, and run the repro script above.

## Effect on the add-on until then

The launcher treats the abort like any required-process exit: it stops its peers and exits non-zero, and the
Supervisor watchdog restarts the add-on (about 20 s in the container proof, same MCP token). Nothing in the HA
layer can avoid it without replacing the core's native module, which would break the "same core for PaaS and
HA" rule.
