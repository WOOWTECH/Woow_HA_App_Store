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
 *   - the marker is present in EVERY path-utils.js copy and in every bundle
 *     chunk that carries pi's tool-path code, and
 *   - the behaviour is actually correct, against a real filesystem, in the
 *     exact shape that corrupted data before: a U+3000 filename sitting next
 *     to an otherwise-identical ASCII-space sibling.
 *
 * TWO COPIES OF THE SAME CODE (pipeline #222)
 *
 * Since pi 0.84.3 the `pi` command (package.json "bin") is
 * dist/bundle/cli.js, which loads its own copy of the path code from
 * dist/bundle/chunks/. Terminal pi, the ACP sidebar (`pi --mode rpc`) and
 * Omnigent all run that copy; only library users import the module files
 * (dist/core/tools/path-utils.js). This script used to import the module
 * files only, so it passed while the CLI still folded every path. It now
 * checks both, and the bundle checks drive the real read/write/edit tools
 * exported by dist/bundle/index.js, the same chunk the CLI entry loads.
 *
 * F1_NODE_MODULES (colon-separated) replaces the default search roots; it is
 * for running this against a scratch pi install, not for the image.
 *
 * Exits non-zero with a per-check report on any failure.
 */
import { mkdtempSync, writeFileSync, readFileSync, existsSync, statSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";

const MARK = "PATCHED (Woow pi-agent image)";
const IDEO = "　"; // U+3000 IDEOGRAPHIC SPACE — ordinary in zh-TW/ja filenames
const NBSP = " "; // U+00A0 NO-BREAK SPACE — what a paste from a web page yields
const NNBSP = " "; // U+202F NARROW NO-BREAK SPACE — macOS screenshot names

// The pi install lives in a different prefix per deployment (/usr/lib on the
// podman/k3s image, /opt/node22/lib on the HA add-on), so discover it rather
// than hard-coding one.
const ROOTS = (process.env.F1_NODE_MODULES
  ? process.env.F1_NODE_MODULES.split(":")
  : ["/usr/lib/node_modules", "/usr/local/lib/node_modules", "/opt/node22/lib/node_modules"]
).filter((d) => d && existsSync(d) && statSync(d).isDirectory());

if (ROOTS.length === 0) {
  console.error("FAIL  no node_modules root found — cannot locate the pi install");
  process.exit(1);
}

const findFiles = (pattern) =>
  execFileSync("find", [...ROOTS, "-path", pattern], { encoding: "utf8" }).split("\n").filter(Boolean);

const found = findFiles("*/dist/*/tools/path-utils.js");
const chunks = findFiles("*/pi-coding-agent/dist/bundle/chunks/*.js");

const results = [];
const scratch = []; // temp dirs, removed at the end (this also runs in an image build layer)
const check = (name, pass, detail = "") => results.push({ name, pass, detail });
const body = (p) => (existsSync(p) ? readFileSync(p, "utf8") : "<MISSING>");

// 1. Every shipped module copy carries the marker. This is the check that
//    would have caught the original "the patch never ran" failure. Which
//    copies must EXIST is checked by shape below (pi 1.x ships fewer copies).
check(
  `all path-utils.js copies carry the patch marker (${found.length} found)`,
  found.length >= 1 && found.every((f) => readFileSync(f, "utf8").includes(MARK)),
  found.length < 1
    ? "no path-utils.js found — upstream layout changed"
    : found.filter((f) => !readFileSync(f, "utf8").includes(MARK)).join(", "),
);

// 2. The bundle the CLI runs: every chunk that defines the tool-path helpers
//    carries the marker, there is at least one, and no chunk still holds the
//    unpatched opt-in to folding on the tool path.
{
  const src = new Map(chunks.map((f) => [f, readFileSync(f, "utf8")]));
  const toolPath = chunks.filter((f) => /function (resolveToCwd|normalizeToolPath)\(/.test(src.get(f)));
  const unmarked = toolPath.filter((f) => !src.get(f).includes(MARK));
  const raw = chunks.filter((f) => src.get(f).includes("normalizeUnicodeSpaces:!0,stripAtPrefix:!0"));
  check(
    `bundle chunks with tool-path code carry the patch marker (${toolPath.length} found)`,
    toolPath.length >= 1 && unmarked.length === 0 && raw.length === 0,
    toolPath.length < 1
      ? "no bundle chunk defines resolveToCwd — upstream layout changed"
      : [...unmarked, ...raw.map((f) => "still folds: " + f)].join(", "),
  );
}

// 3..6 Behaviour, through the module pi's library users resolve paths with.
const mod = found.find((f) => f.includes("/pi-coding-agent/") && f.endsWith("/core/tools/path-utils.js"));
if (!mod) {
  check("pi-coding-agent core path-utils.js present", false, "not found under " + ROOTS.join(", "));
} else {
  const { resolveReadPath, resolveReadPathAsync, resolveToCwd } = await import(mod);
  const cwd = mkdtempSync(join(tmpdir(), "f1-"));
  scratch.push(cwd);

  const CONF = "Q1" + IDEO + "報告.txt"; // Q1<U+3000>報告.txt
  const PUB = "Q1 報告.txt"; // Q1<SPACE>報告.txt
  writeFileSync(join(cwd, CONF), "CONFIDENTIAL");
  writeFileSync(join(cwd, PUB), "PUBLIC");

  {
    const got = body(resolveReadPath(CONF, cwd));
    check("read of a U+3000 filename does not cross-read its ASCII sibling", got === "CONFIDENTIAL", `got ${got}`);
  }
  {
    const got = body(await resolveReadPathAsync(CONF, cwd));
    check("same through the async resolver", got === "CONFIDENTIAL", `got ${got}`);
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
    const got = body(resolveReadPath("note" + NBSP + "x.txt", cwd));
    check("a pasted NBSP path still falls back to the ASCII file", got === "FALLBACK-OK", `got ${got}`);
  }
}

// 7..11 Behaviour through the bundle: the real read/write/edit tools, as the
//       CLI (terminal pi, `pi --mode rpc`, Omnigent) runs them.
const pkg = mod ? dirname(dirname(dirname(dirname(mod)))) : null; // .../pi-coding-agent
const bundleIndex = pkg ? join(pkg, "dist/bundle/index.js") : null;
if (!bundleIndex || !existsSync(bundleIndex)) {
  check("pi-coding-agent dist/bundle/index.js present", false, "not found next to " + (mod ?? "<no module>"));
} else {
  const { createReadTool, createWriteTool, createEditTool } = await import(bundleIndex);
  const cwd = mkdtempSync(join(tmpdir(), "f1-bundle-"));
  scratch.push(cwd);
  const text = (r) => (r?.content ?? []).map((c) => c.text ?? "").join("");
  const run = async (tool, args) => {
    try {
      return { ok: true, out: text(await tool.execute("f1-verify", args)) };
    } catch (e) {
      return { ok: false, out: String(e?.message ?? e) };
    }
  };

  const CONF = "Q1" + IDEO + "報告.txt";
  writeFileSync(join(cwd, CONF), "CONFIDENTIAL");
  writeFileSync(join(cwd, "Q1 報告.txt"), "PUBLIC");
  {
    const r = await run(createReadTool(cwd), { path: CONF });
    check(
      "bundle: read of a U+3000 filename does not cross-read its ASCII sibling",
      r.ok && r.out.includes("CONFIDENTIAL") && !r.out.includes("PUBLIC"),
      `got ${r.out.slice(0, 80)}`,
    );
  }
  {
    const target = "新建" + IDEO + "檔案.txt";
    const r = await run(createWriteTool(cwd), { path: target, content: "WROTE" });
    check(
      "bundle: write to a U+3000 path lands at exactly that path",
      r.ok && body(join(cwd, target)) === "WROTE" && !existsSync(join(cwd, target.replace(IDEO, " "))),
      r.ok ? "" : r.out,
    );
  }
  {
    const target = "V1" + IDEO + "DOC.txt";
    writeFileSync(join(cwd, target), "alpha\n");
    writeFileSync(join(cwd, "V1 DOC.txt"), "alpha\n");
    const r = await run(createEditTool(cwd), { path: target, edits: [{ oldText: "alpha", newText: "beta" }] });
    check(
      "bundle: edit of a U+3000 path changes that file, not its ASCII sibling",
      r.ok && body(join(cwd, target)) === "beta\n" && body(join(cwd, "V1 DOC.txt")) === "alpha\n",
      r.ok ? "" : r.out,
    );
  }
  {
    writeFileSync(join(cwd, "note x.txt"), "FALLBACK-OK");
    const r = await run(createReadTool(cwd), { path: "note" + NBSP + "x.txt" });
    check("bundle: a pasted NBSP path still falls back to the ASCII file", r.ok && r.out.includes("FALLBACK-OK"), `got ${r.out.slice(0, 80)}`);
  }
  {
    // Upstream's own macOS fallback: typed " PM." finds the U+202F file.
    writeFileSync(join(cwd, "Shot 1.02.03" + NNBSP + "PM.txt"), "AMPM-OK");
    const r = await run(createReadTool(cwd), { path: "Shot 1.02.03 PM.txt" });
    check("bundle: the macOS AM/PM (U+202F) fallback still works", r.ok && r.out.includes("AMPM-OK"), `got ${r.out.slice(0, 80)}`);
  }
}

for (const d of scratch) rmSync(d, { recursive: true, force: true });

let failed = 0;
for (const r of results) {
  if (!r.pass) failed++;
  console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.name}${r.detail ? "  [" + r.detail + "]" : ""}`);
}
console.log(failed === 0 ? "F1 OK" : `F1 FAILED (${failed})`);
process.exit(failed === 0 ? 0 : 1);
