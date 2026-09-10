#!/usr/bin/env node
/**
 * Deterministic reproduction of the upstream signal-reporting bug (F4).
 *
 * NOT a fix and NOT a smoke-test assertion — this is an UPSTREAM bug in pi that
 * we cannot patch out the way we did the Unicode-path one (F1), because the
 * correct behaviour is a semantic change to pi's tool contract, not a local
 * rewrite. This script exists so that the next time pi is bumped, one command
 * says whether the bug is still there:
 *
 *     node /opt/patches/f4-signal-repro.mjs
 *
 * Exit 0 = still broken (signal discarded).  Exit 3 = upstream fixed it.
 *
 * WHAT IT PROVES
 *
 * Node hands `exit`/`close` two arguments, (code, signal). For a
 * signal-killed child, code === null and signal carries SIGTERM/SIGKILL.
 * pi's waitForChildProcess registers `(code) => ...` and drops the second
 * argument on the floor, then resolves the bare code — null. So the signal is
 * lost inside the helper, even though Node had it and still exposes it on the
 * child object, which is what makes this a two-line fix upstream.
 *
 * See KNOWN_UPSTREAM_ISSUES.md for the downstream consequence (the bash tool
 * returning isError:false for an OOM-killed build) and the issue history.
 */
import { execFileSync } from "node:child_process";
import { existsSync, statSync } from "node:fs";

// The pi install prefix differs per deployment (/usr/lib on the podman/k3s
// image, /opt/node22/lib on the HA add-on), so discover it rather than
// hard-coding one — same approach as f1-verify.mjs.
const ROOTS = ["/usr/lib/node_modules", "/usr/local/lib/node_modules", "/opt/node22/lib/node_modules"]
  .filter((d) => existsSync(d) && statSync(d).isDirectory());
if (ROOTS.length === 0) {
  console.error("FAIL: no node_modules root found — cannot locate the pi install");
  process.exit(1);
}
const found = execFileSync("find", [...ROOTS, "-path", "*/pi-coding-agent/dist/utils/child-process.js"], { encoding: "utf8" })
  .split("\n")
  .filter(Boolean);
if (found.length === 0) {
  console.error("FAIL: child-process.js not found — upstream layout changed, re-verify this repro");
  process.exit(1);
}
const { spawnProcess, waitForChildProcess } = await import(found[0]);

let broken = 0;
for (const sig of ["TERM", "KILL"]) {
  const child = spawnProcess("sh", ["-c", `echo BEFORE_KILL; kill -${sig} $$`]);
  const resolved = await waitForChildProcess(child);
  // The shell convention for a signal death is 128 + signum: 143 / 137.
  const ok = resolved !== null && resolved !== 0;
  if (!ok) broken++;
  console.log(
    `SIG${sig}: waitForChildProcess -> ${JSON.stringify(resolved)}` +
      `   (node knew: exitCode=${child.exitCode} signalCode=${child.signalCode})` +
      `   ${ok ? "FIXED UPSTREAM" : "still discards the signal"}`,
  );
}

if (broken === 0) {
  console.log("\nF4 APPEARS FIXED upstream — re-read KNOWN_UPSTREAM_ISSUES.md and drop this file.");
  process.exit(3);
}
console.log("\nF4 STILL PRESENT: a signal-killed command is indistinguishable from a clean exit.");
process.exit(0);
