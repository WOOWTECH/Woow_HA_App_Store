#!/usr/bin/env node
/**
 * Build-time patch: stop silently rewriting Unicode spaces in tool paths.
 *
 * Usage: node fix-unicode-space-paths.mjs <path-utils.js> [more...]
 * The Dockerfile feeds the file list in via find, so this script does not
 * depend on fs.globSync (still experimental on Node 22 — not something an
 * image build should bet on).
 *
 * WHY THIS EXISTS
 *
 * Upstream folds U+00A0, U+2000-200A, U+202F, U+205F and U+3000 to an ASCII
 * space on EVERY read, write and edit, and the read fallback chain is built
 * from the already-folded path — so the exact path the caller asked for is
 * never tried.
 *
 * Three consequences, all silent, all reproduced on this deployment against
 * both configured models:
 *   1. write/edit land at a different path than requested, while the success
 *      message is built from the ORIGINAL path — "Successfully wrote 10 bytes
 *      to 新建　檔案.txt" against a file that does not exist.
 *   2. read of `台灣<U+3000>報告.txt` misses the real file.
 *   3. worst: with `Q1<U+3000>報告.txt` and `Q1<U+0020>報告.txt` both present,
 *      reading the first returns the SECOND file's contents with isError=false.
 *      A confidential/public pair differing only by space type cross-reads.
 *
 * U+3000 IDEOGRAPHIC SPACE is ordinary in Traditional Chinese and Japanese
 * filenames, so this is not an edge case for a zh-TW deployment.
 *
 * THE FIX
 *
 * Folding becomes a READ-ONLY FALLBACK — someone pasting a path with a
 * non-breaking space from a web page still gets a hit — but the exact path is
 * tried first, and writes are never rewritten.
 *
 * pi-web ships two different path-utils implementations (pi-agent-core's
 * harness tools, and pi-coding-agent's core tools). Both fold. Each gets its
 * own hunk set below; a file matching neither shape fails the build rather
 * than being skipped, so an upstream refactor cannot silently drop this fix.
 *
 * Patching compiled output inside node_modules is not something to do lightly.
 * It is done here because the alternative is shipping known silent data
 * corruption to zh-TW customers while waiting on upstream.
 */
import { readFileSync, writeFileSync } from "node:fs";

const MARK = "PATCHED (Woow pi-agent image)";

/** Shape A — @earendil-works/pi-agent-core/dist/harness/tools/path-utils.js */
const SHAPE_A = {
  name: "pi-agent-core harness tools",
  detect: (s) => s.includes("function normalizeToolPath(path) {") && s.includes("UNICODE_SPACES"),
  hunks: [
    {
      from: `function normalizeToolPath(path) {
    const normalized = path.replace(UNICODE_SPACES, " ");
    return normalized.startsWith("@") ? normalized.slice(1) : normalized;
}`,
      to: `function normalizeToolPath(path) {
    // ${MARK}: do NOT fold Unicode spaces here. A write must land at exactly
    // the path requested, or fail visibly. The @ strip is kept because it is a
    // deliberate UX affordance, not a silent rewrite.
    return path.startsWith("@") ? path.slice(1) : path;
}
function foldUnicodeSpacesForRead(path) {
    return path.replace(UNICODE_SPACES, " ");
}`,
    },
    {
      from: `    const variants = [
        resolved,`,
      to: `    const variants = [
        resolved,
        // ${MARK}: the folded form is a FALLBACK, tried only when the exact
        // path does not exist. Upstream had it as the only form, which made a
        // near-miss filename silently resolve to a different file.
        foldUnicodeSpacesForRead(resolved),`,
    },
  ],
};

/** Shape B — @earendil-works/pi-coding-agent/dist/core/tools/path-utils.js */
const SHAPE_B = {
  name: "pi-coding-agent core tools",
  detect: (s) => s.includes("export function resolveToCwd(filePath, cwd) {") && s.includes("normalizeUnicodeSpaces: true"),
  hunks: [
    {
      from: `export function expandPath(filePath) {
    return normalizePath(filePath, { normalizeUnicodeSpaces: true, stripAtPrefix: true });
}`,
      to: `export function expandPath(filePath) {
    // ${MARK}: folding moved to a read-only fallback (see resolveReadPath).
    return normalizePath(filePath, { normalizeUnicodeSpaces: false, stripAtPrefix: true });
}
function tryUnicodeSpaceFold(filePath) {
    // ${MARK}: U+00A0, U+2000-200A, U+202F, U+205F, U+3000 -> ASCII space.
    return filePath.replace(/[\\u00A0\\u2000-\\u200A\\u202F\\u205F\\u3000]/g, " ");
}`,
    },
    {
      from: `export function resolveToCwd(filePath, cwd) {
    return resolvePath(filePath, cwd, { normalizeUnicodeSpaces: true, stripAtPrefix: true });
}`,
      to: `export function resolveToCwd(filePath, cwd) {
    // ${MARK}: writes and edits resolve through here. Never rewrite the path.
    return resolvePath(filePath, cwd, { normalizeUnicodeSpaces: false, stripAtPrefix: true });
}`,
    },
    {
      from: `    // Try macOS AM/PM variant (narrow no-break space before AM/PM)
    const amPmVariant = tryMacOSScreenshotPath(resolved);
    if (amPmVariant !== resolved && fileExists(amPmVariant)) {
        return amPmVariant;
    }`,
      to: `    // ${MARK}: folded-space fallback, after the exact path has missed.
    const foldedVariant = tryUnicodeSpaceFold(resolved);
    if (foldedVariant !== resolved && fileExists(foldedVariant)) {
        return foldedVariant;
    }
    // Try macOS AM/PM variant (narrow no-break space before AM/PM)
    const amPmVariant = tryMacOSScreenshotPath(resolved);
    if (amPmVariant !== resolved && fileExists(amPmVariant)) {
        return amPmVariant;
    }`,
    },
    {
      from: `    // Try macOS AM/PM variant (narrow no-break space before AM/PM)
    const amPmVariant = tryMacOSScreenshotPath(resolved);
    if (amPmVariant !== resolved && (await pathExists(amPmVariant))) {
        return amPmVariant;
    }`,
      to: `    // ${MARK}: folded-space fallback, after the exact path has missed.
    const foldedVariant = tryUnicodeSpaceFold(resolved);
    if (foldedVariant !== resolved && (await pathExists(foldedVariant))) {
        return foldedVariant;
    }
    // Try macOS AM/PM variant (narrow no-break space before AM/PM)
    const amPmVariant = tryMacOSScreenshotPath(resolved);
    if (amPmVariant !== resolved && (await pathExists(amPmVariant))) {
        return amPmVariant;
    }`,
    },
  ],
};

const SHAPES = [SHAPE_A, SHAPE_B];

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("[patch] FAIL: no path-utils.js files given.");
  console.error("[patch] The upstream layout changed, or find matched nothing.");
  process.exit(1);
}

let patched = 0;
let already = 0;

for (const file of files) {
  let src = readFileSync(file, "utf8");

  if (src.includes(MARK)) {
    console.log("[patch] already patched:", file);
    already++;
    continue;
  }

  const shape = SHAPES.find((s) => s.detect(src));
  if (!shape) {
    console.error("[patch] FAIL: unrecognised path-utils shape:", file);
    console.error("[patch] Upstream refactored this file. Re-verify the fix before shipping.");
    process.exit(1);
  }

  for (const h of shape.hunks) {
    if (!src.includes(h.from)) {
      console.error(`[patch] FAIL: hunk did not match in ${file} (shape: ${shape.name})`);
      console.error("[patch] Expected:\n" + h.from);
      process.exit(1);
    }
    src = src.replace(h.from, h.to);
  }

  writeFileSync(file, src);
  console.log(`[patch] patched (${shape.name}):`, file);
  patched++;
}

console.log(`[patch] done — ${patched} patched, ${already} already patched`);
if (patched + already === 0) process.exit(1);
