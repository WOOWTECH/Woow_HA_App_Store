# Known upstream issues (pi 0.83.0)

Bugs that live in pi itself, not in our packaging. Recorded here so nobody
re-investigates them from scratch, and so a pi version bump has a checklist.

Contrast with `patches/fix-unicode-space-paths.mjs`: that one we *did* patch out
of the shipped image, because the fix is a local rewrite with no contract change.
Everything below is either unpatchable locally or not worth the risk.

---

## F4 — a signal-killed bash command is reported as success

**Status: still present in 0.83.0. Already reported upstream twice. Do not file a third.**

### Symptom

A command killed by a signal from outside pi's control — the OOM killer, a
`kill` from another process, SIGSEGV, a `timeout`/`ulimit` inside the user's own
command string — is returned to the model as a *successful* tool call with
whatever partial output it managed to produce.

Ground truth vs. what the model is told, reproduced on this deployment:

```
shell:  BEFORE_KILL / EXIT=143 / Terminated
pi:     {"type":"tool_execution_end","toolName":"bash",
         "result":{"content":[{"type":"text","text":"BEFORE_KILL\n"}]},
         "isError":false}
```

An ordinary non-zero exit is reported correctly (`Command exited with code 42`,
`isError:true`), so the agent has no way to tell "the build finished" from "the
build was OOM-killed halfway". It narrates the truncated output as a completed
command. This cost four rounds of the 2026-09 field test before it was spotted.

**Not affected:** pi's *own* abort and timeout paths, which do report correctly
(`bash.js` throws "Command aborted" / "Command timed out after N seconds"). Only
signals from outside pi are lost.

### Root cause

Node hands `exit` and `close` two arguments, `(code, signal)`. For a
signal-killed child, `code === null` and `signal` holds `SIGTERM`/`SIGKILL`.

1. `dist/utils/child-process.js:86` — `const onExit = (code) => {...}` takes only
   the first argument. `onClose` at :90 does the same. The signal is dropped
   inside the helper, and `waitForChildProcess` resolves the bare `null`.
2. `dist/core/tools/bash.js:343` — `if (exitCode !== 0 && exitCode !== null)`
   explicitly excludes `null` from the error path, so the signal death falls
   through to the success return.

Node still exposes the value on the child object, which is what makes this small
to fix: see the repro output below — `child.signalCode` is right there.

### Verifying after a pi bump

`patches/f4-signal-repro.mjs` ships inside the image. No model call, no auth:

```
$ node /opt/patches/f4-signal-repro.mjs
SIGTERM: waitForChildProcess -> null   (node knew: exitCode=null signalCode=SIGTERM)   still discards the signal
SIGKILL: waitForChildProcess -> null   (node knew: exitCode=null signalCode=SIGKILL)   still discards the signal
```

Exit 0 = still broken. **Exit 3 = upstream fixed it** — then delete the script and
this section.

### Upstream history — read before touching the tracker

Both of these are the same bug and both are **closed**:

- [earendil-works/pi#8882](https://github.com/earendil-works/pi/issues/8882) —
  "NodeExecutionEnv reports signal-terminated commands as exit code 0"
- [earendil-works/pi#8992](https://github.com/earendil-works/pi/issues/8992) —
  "Signal-killed shell commands report exit code 0" (labelled `no-action`)

They were **auto-closed by a bot, not rejected on merit**: that repo auto-closes
every issue from a new contributor and maintainers reopen the worthwhile ones.
Both name the same root helper and propose the same fix (map a signal death to
the shell's 128 + signum convention).

`CONTRIBUTING.md` there is explicit that agent-generated issue spam gets the
submitting **GitHub account permanently blocked**, and that issue text must be
written in the submitter's own voice. A third machine-written duplicate is
therefore both useless and actively risky to the WOOWTECH account. If someone
wants to push this along, the options in descending value are:

1. Ask on their Discord (CONTRIBUTING.md points there for anything urgent).
2. Add a short comment **in your own words** on #8992 making the one point
   neither issue makes: #8992 blames the `code ?? 0` mapping in
   `packages/agent/src/harness/env/nodejs.ts`, but `packages/coding-agent`'s
   `bash.js` is a *second, independent consumer* of the same helper with its own
   `exitCode !== null` guard. Fixing only the `nodejs.ts` mapping leaves the
   coding-agent path broken. Fixing `waitForChildProcess` itself fixes both.

### Mitigation available to us

None that is honest at the packaging layer — we cannot make `isError` true from
outside pi. The only real mitigation is per-command: append `; echo EXIT=$?` to
long-running or memory-hungry build and test commands, so a signal death at
least appears in the captured *output* even though the error flag stays wrong.

That belongs in a workspace `AGENTS.md`, which pi does read — but the workspace
is the user's own directory (`~/Desktop` on podman), so the packages do not
write one. Add it by hand if you are running big builds through the agent.
