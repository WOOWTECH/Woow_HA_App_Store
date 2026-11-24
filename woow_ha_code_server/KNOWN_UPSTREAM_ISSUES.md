# Known upstream issues (pi 0.83.0; carried forward to 0.99.1)

Bugs that live in pi itself, not in our packaging. Recorded here so nobody
re-investigates them from scratch, and so a pi version bump has a checklist.

F1 is the one we *did* patch out of the shipped image
(`patches/fix-unicode-space-paths.mjs`), because the fix is a local rewrite with
no contract change. Everything after it is either unpatchable locally or not
worth the risk.

---

## F1 — Unicode spaces in tool paths are silently folded to ASCII spaces

**Status: present upstream in 0.83.0 through 0.99.1. Patched in our images by
`patches/fix-unicode-space-paths.mjs`; the bundle half of that patch only since
pipeline #222. Images shipped with pi 0.84.3 – 0.99.1 before #222 did NOT
have the fix in the code the `pi` command runs** (see "Scope" below).

### Symptom

pi rewrites U+00A0, U+2000–U+200A, U+202F, U+205F and U+3000 to an ASCII space
in every path a read, write or edit tool is given, and builds the read fallback
chain from the already-folded path, so the exact path is never tried:

- reading `Q1<U+3000>報告.txt` next to `Q1<SPACE>報告.txt` returns the second
  file's contents with `isError:false` (a confidential/public pair cross-reads);
- writing `新建<U+3000>檔案.txt` reports success and creates
  `新建<SPACE>檔案.txt`, or overwrites it if it exists;
- an existing file whose name contains U+3000 cannot be read at all.

U+3000 is an ordinary character in Traditional Chinese and Japanese filenames.

### Root cause

`resolveToCwd` passes `normalizeUnicodeSpaces: true` to the generic
`resolvePath`, and the pi-agent-core harness `normalizeToolPath` folds
unconditionally. There are two copies of that code in the package:

1. the module files, `dist/core/tools/path-utils.js` (pi-coding-agent) and
   `dist/harness/tools/path-utils.js` (pi-agent-core). Only library users
   that import `@earendil-works/pi-coding-agent` load these;
2. since **0.84.3**, the bundle. `package.json` `bin.pi` is
   `dist/bundle/cli.js`, which loads `dist/bundle/cli-runtime.js` for every
   mode, `--mode rpc` included. It imports one large chunk under
   `dist/bundle/chunks/` that carries its own minified copy of both
   implementations (the `./rpc-entry` package export imports it too). In 0.99.1 that is `chunk-GUORCHFS.js`; the name
   changes every release. `dist/bundle/index.js` re-exports the same tools.

Terminal `pi`, the ACP sidebar (`pi-code` → `pi-acp` → `pi --mode rpc`) and
Omnigent all run copy 2.

### Scope of our patch

`patches/fix-unicode-space-paths.mjs` makes folding a read-only fallback in
both copies:

- write and edit resolve the exact path; nothing is rewritten;
- read tries the exact path first, then the folded path, then upstream's own
  fallbacks (macOS AM/PM U+202F, NFD, curly quote);
- the leading `@` strip is kept.

Left alone on purpose: the generic `normalizePath` helper (only folds when a
caller opts in) and extension loading, which opts in for extension paths.

The image build passes every `dist/*/tools/path-utils.js` and every bundle
chunk that defines `resolveToCwd` or `normalizeToolPath` (found by content).
The script fails the build when a hunk does not match exactly once, when a
file matches no known shape, or when a required shape (module core tools,
bundle core tools) is not in the list. The pi-agent-core harness shapes are
optional, because pi 1.x no longer ships them.

Before #222 the script only received the module files and `f1-verify.mjs`
only imported the module files, so both passed while the CLI kept folding.

### Verifying after a pi bump

1. Build the image. The patch step and `node /opt/patches/f1-verify.mjs` run
   in the build; any hunk that no longer matches fails it with the expected
   text. A renamed minifier identifier is absorbed by the regex hunks; a
   restructured function needs the hunk rewritten and re-verified.
2. `f1-verify.mjs` checks the marker in every copy, then drives the module
   resolvers AND the bundle's own `createReadTool` / `createWriteTool` /
   `createEditTool` against a real directory with a U+3000 file next to its
   ASCII-space sibling, plus the NBSP and AM/PM fallbacks. It must print
   `F1 OK`.
3. On a deployed instance, run it again (`tests/smoke-pi-integration.sh`
   does), and check once by hand in terminal `pi` and in the ACP sidebar:
   ask pi to read a U+3000 file that has an ASCII-space sibling, and to write
   a new U+3000 file, then `ls | od -c` to see which bytes landed.
4. If upstream fixes it (the exact path is tried first and writes are not
   rewritten), the hunks stop matching: delete the patch and this section.

---

## F4 — a signal-killed bash command is reported as success

**Status: present in 0.83.0; not re-verified on 0.99.1 yet (the 2026-09-30 bump) — re-run `patches/f4-signal-repro.mjs` before relying on it. Already reported upstream twice. Do not file a third.**

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
