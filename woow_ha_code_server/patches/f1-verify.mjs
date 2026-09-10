#!/usr/bin/env node
/**
 * Runtime verification for the fix-unicode-space-paths.mjs build patch.
 *
 * Ships inside the image (COPY patches/ /opt/patches/) so the smoke tests of
 * all three deployments can run it the same way:
 *
 *     node /opt/patches/f1-verify.mjs
 *
 * WHY A RUNTIME CHECK AND NOT JUST A BUILD ASSERTION
 *
 * The original incident was not a broken patch script — it was a patch script
 * that was never invoked. A build-time assertion cannot catch that; only
 * something that inspects the image as shipped can. So this asserts both:
 *
 *   - the marker is present in EVERY path-utils.js copy in the image, and
 *   - the behaviour is actually correct, against a real filesystem, in the
 *     exact shape that corrupted data before: a U+3000 filename sitting next
 *     to an otherwise-identical ASCII-space sibling.
 *
 * Exits non-zero with a per-check report on any failure.
 */
import { mkdtempSync, writeFileSync, readFileSync, existsSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

const MARK = "PATCHED (Woow pi-agent image)";
const IDEO = "　"; // U+3000 IDEOGRAPHIC SPACE — ordinary in zh-TW/ja filenames
const NBSP = " "; // U+00A0 NO-BREAK SPACE — what a paste from a web page yields

// The pi install lives in a different prefix per deployment (/usr/lib on the
// podman/k3s image, /opt/node22/lib on the HA add-on), so discover it rather
// than hard-coding one.
const ROOTS = ["/usr/lib/node_modules", "/usr/local/lib/node_modules", "/opt/node22/lib/node_modules"]
  .filter((d) => existsSync(d) && statSync(d).isDirectory());

if (ROOTS.length === 0) {
  console.error("FAIL  no node_modules root found — cannot locate the pi install");
  process.exit(1);
}

const found = execFileSync("find", [...ROOTS, "-path", "*/dist/*/tools/path-utils.js"], { encoding: "utf8" })
  .split("\n")
  .filter(Boolean);

const results = [];
const check = (name, pass, detail = "") => results.push({ name, pass, detail });

// 1. Every shipped copy carries the marker. This is the check that would have
//    caught the original "the patch never ran" failure.
check(
  `all path-utils.js copies carry the patch marker (${found.length} found)`,
  found.length >= 2 && found.every((f) => readFileSync(f, "utf8").includes(MARK)),
  found.length < 2
    ? "expected at least 2 copies — upstream layout changed"
    : found.filter((f) => !readFileSync(f, "utf8").includes(MARK)).join(", "),
);

// 2..5 Behaviour, through the module pi's read/write/edit tools resolve paths
//      with. Skipped (as a failure) if the module cannot be located at all.
const mod = found.find((f) => f.includes("/pi-coding-agent/") && f.endsWith("/core/tools/path-utils.js"));
if (!mod) {
  check("pi-coding-agent core path-utils.js present", false, "not found under " + ROOTS.join(", "));
} else {
  const { resolveReadPath, resolveReadPathAsync, resolveToCwd } = await import(mod);
  const cwd = mkdtempSync(join(tmpdir(), "f1-"));

  const CONF = "Q1" + IDEO + "報告.txt"; // Q1<U+3000>報告.txt
  const PUB = "Q1 報告.txt"; // Q1<SPACE>報告.txt
  writeFileSync(join(cwd, CONF), "CONFIDENTIAL");
  writeFileSync(join(cwd, PUB), "PUBLIC");

  {
    const got = resolveReadPath(CONF, cwd);
    const body = existsSync(got) ? readFileSync(got, "utf8") : "<MISSING>";
    check("read of a U+3000 filename does not cross-read its ASCII sibling", body === "CONFIDENTIAL", `got ${body}`);
  }
  {
    const got = await resolveReadPathAsync(CONF, cwd);
    const body = existsSync(got) ? readFileSync(got, "utf8") : "<MISSING>";
    check("same through the async resolver", body === "CONFIDENTIAL", `got ${body}`);
  }
  {
    const target = "新建" + IDEO + "檔案.txt"; // 新建<U+3000>檔案.txt
    writeFileSync(resolveToCwd(target, cwd), "WROTE");
    check(
      "write to a U+3000 path lands at exactly that path",
      existsSync(join(cwd, target)) && !existsSync(join(cwd, target.replace(IDEO, " "))),
      "",
    );
  }
  {
    // The folding must survive as a read-only fallback — this is the behaviour
    // the patch deliberately keeps, so a regression in either direction fails.
    writeFileSync(join(cwd, "note x.txt"), "FALLBACK-OK");
    const got = resolveReadPath("note" + NBSP + "x.txt", cwd);
    const body = existsSync(got) ? readFileSync(got, "utf8") : "<MISSING>";
    check("a pasted NBSP path still falls back to the ASCII file", body === "FALLBACK-OK", `got ${body}`);
  }
}

let failed = 0;
for (const r of results) {
  if (!r.pass) failed++;
  console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.name}${r.detail ? "  [" + r.detail + "]" : ""}`);
}
console.log(failed === 0 ? "F1 OK" : `F1 FAILED (${failed})`);
process.exit(failed === 0 ? 0 : 1);
