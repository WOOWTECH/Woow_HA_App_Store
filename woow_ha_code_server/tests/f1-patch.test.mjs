// fix-unicode-space-paths.mjs must fail the build whenever it cannot apply the
// whole fix (pipeline #222). Driven through its CLI, as the image build runs
// it, against real pi 0.99.1 path code in tests/fixtures/pi-0.99.1-path-code/.
// The behaviour of the patched code is checked end to end by
// patches/f1-verify.mjs inside the image build; this covers the refusals.
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, copyFileSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = fileURLToPath(new URL("../patches/fix-unicode-space-paths.mjs", import.meta.url));
const FIX = fileURLToPath(new URL("./fixtures/pi-0.99.1-path-code/", import.meta.url));
const MARK = "PATCHED (Woow pi-agent image)";
const NAMES = { core: "core-path-utils.js", harness: "harness-path-utils.js", bundle: "bundle-chunk-excerpt.js" };

/** Fresh copies of the chosen fixtures; edit(name, src) may break one first. */
function stage(which = ["core", "harness", "bundle"], edit = (_n, s) => s) {
  const dir = mkdtempSync(join(tmpdir(), "f1-patch-"));
  return which.map((k) => {
    const to = join(dir, NAMES[k]);
    copyFileSync(join(FIX, NAMES[k]), to);
    writeFileSync(to, edit(k, readFileSync(to, "utf8")));
    return to;
  });
}
const run = (files) => spawnSync(process.execPath, [SCRIPT, ...files], { encoding: "utf8" });
const replaceOnce = (s, from, to) => {
  assert.equal(s.split(from).length - 1, 1, `fixture should contain exactly one ${JSON.stringify(from)}`);
  return s.replace(from, to);
};

test("pi 0.99.1: patches every copy, bundle included, and a re-run is a no-op", () => {
  const files = stage();
  const first = run(files);
  assert.equal(first.status, 0, first.stderr);
  const bundle = readFileSync(files[2], "utf8");
  assert.ok(bundle.includes(MARK));
  assert.ok(!bundle.includes("normalizeUnicodeSpaces:!0,stripAtPrefix:!0"), "bundle resolveToCwd still folds");
  assert.ok(!/let normalized=path10\.replace\(UNICODE_SPACES/.test(bundle), "bundle normalizeToolPath still folds");
  const before = files.map((f) => readFileSync(f, "utf8"));
  const second = run(files);
  assert.equal(second.status, 0, second.stderr);
  assert.match(second.stdout, /0 patched, 3 already patched/);
  assert.deepEqual(files.map((f) => readFileSync(f, "utf8")), before);
});

test("pi 1.x layout without the pi-agent-core harness copies still passes", () => {
  const files = stage(["core", "bundle"], (k, s) =>
    k === "bundle" ? s.slice(s.indexOf("function tryMacOSScreenshotPath")) : s,
  );
  const r = run(files);
  assert.equal(r.status, 0, r.stderr);
});

// Each entry removes the text exactly one hunk targets. Every one must fail.
const BROKEN_HUNKS = {
  "bundle core: resolveToCwd": ["bundle", "normalizeUnicodeSpaces:!0,stripAtPrefix:!0", "normalizeUnicodeSpaces:!0"],
  "bundle core: sync read fallback": ["bundle", "&&fileExists(amPmVariant))return amPmVariant;", "&&fileExists(amPmVariant))return null;"],
  "bundle core: async read fallback": ["bundle", "&&await pathExists(amPmVariant))return amPmVariant;", "&&await pathExists(amPmVariant))return null;"],
  "bundle harness: normalizeToolPath": ["bundle", 'let normalized=path10.replace(UNICODE_SPACES," ");', 'let normalized=path10.trim();'],
  "bundle harness: read variants": ["bundle", "variants=[resolved,resolved.replace(", "variants=[resolved.replace("],
  "module core: expandPath": ["core", "return normalizePath(filePath, { normalizeUnicodeSpaces: true, stripAtPrefix: true });", "return normalizePath(filePath, { normalizeUnicodeSpaces: true });"],
  "module core: sync read fallback": ["core", "if (amPmVariant !== resolved && fileExists(amPmVariant)) {", "if (fileExists(amPmVariant)) {"],
  "module harness: read variants": ["harness", "const variants = [\n        resolved,", "const variants = [resolved,"],
};
for (const [name, [file, from, to]] of Object.entries(BROKEN_HUNKS)) {
  test(`fails when a hunk no longer matches: ${name}`, () => {
    const r = run(stage(undefined, (k, s) => (k === file ? replaceOnce(s, from, to) : s)));
    assert.notEqual(r.status, 0, r.stdout);
    assert.match(r.stderr, /FAIL: hunk matched 0 times/);
  });
}

test("fails when a hunk target appears twice", () => {
  const r = run(stage(undefined, (k, s) => (k === "bundle" ? s + s : s)));
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /matched 2 times/);
});

test("fails on a file that matches no known shape", () => {
  const [odd] = stage(["bundle"], () => "function somethingElse(a){return a}\n");
  const r = run([...stage(["core"]), odd, ...stage(["bundle"])]);
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /unrecognised shape/);
});

test("fails when no bundle chunk is given (the pre-#222 file list)", () => {
  const r = run(stage(["core", "harness"]));
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /required shape\(s\) not found.*bundle: pi-coding-agent core tools/);
});

test("fails when the module core copy is missing", () => {
  const r = run(stage(["harness", "bundle"]));
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /required shape\(s\) not found.*pi-coding-agent core tools/);
});

test("fails with no files at all", () => {
  const r = run([]);
  assert.notEqual(r.status, 0);
});
