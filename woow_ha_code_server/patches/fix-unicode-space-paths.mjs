#!/usr/bin/env node
/**
 * Build-time patch: stop silently rewriting Unicode spaces in tool paths.
 *
 * Usage: node fix-unicode-space-paths.mjs <file> [more...]
 * The files are every dist/<dir>/tools/path-utils.js plus every
 * pi-coding-agent dist/bundle/chunks/*.js that defines resolveToCwd or
 * normalizeToolPath (picked by content: chunk names change every release).
 * The Dockerfile feeds the list in via find/grep, so this script does not
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
 * THE BUNDLE (pipeline #222)
 *
 * Since pi 0.84.3 the `pi` command is dist/bundle/cli.js, and the bundle
 * carries its OWN minified copy of both implementations in one of
 * dist/bundle/chunks/*.js (chunk-GUORCHFS.js in 0.99.1). Terminal pi, the ACP
 * sidebar (`pi --mode rpc`) and Omnigent run that copy, never the module
 * files. Patching only the module files left every shipped image from 0.84.3
 * to 0.99.1 still folding. The bundle shapes below give the bundle the same
 * semantics. Their hunks are regular expressions with captures, so a renamed
 * minifier identifier (path10 -> path11) does not need a redesign; anything
 * more than that fails the build and needs a look.
 *
 * Every hunk must match EXACTLY once. Shapes marked `required` must be found
 * somewhere in the file list, or the build fails: a pi bump that moves the
 * code must not turn into "nothing matched, nothing patched, build green".
 * The pi-agent-core harness copies are optional because pi 1.x drops them.
 *
 * Unchanged on purpose: the generic normalizePath helper (dist/utils/paths.js
 * and its bundle copy) only folds when a caller passes
 * normalizeUnicodeSpaces:true, and extension loading opts in for its own
 * paths. Neither is a read/write/edit tool path.
 *
 * Patching compiled output inside node_modules is not something to do lightly.
 * It is done here because the alternative is shipping known silent data
 * corruption to zh-TW customers while waiting on upstream.
 */
import { readFileSync, writeFileSync } from "node:fs";

const MARK = "PATCHED (Woow pi-agent image)";

/** Shape A — @earendil-works/pi-agent-core/dist/harness/tools/path-utils.js */
const SHAPE_A = {
  id: "A",
  name: "pi-agent-core harness tools",
  required: false,
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
  id: "B",
  name: "pi-coding-agent core tools",
  required: true,
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

/** The tag a regex hunk leaves behind, so a re-run knows it is applied. */
const tag = (id) => `/*${MARK} [f1:${id}]*/`;

/**
 * Bundle, pi-coding-agent core tools — the minified copy of Shape B inside
 * dist/bundle/chunks/*.js. resolveToCwd is what read, write, edit, ls, grep
 * and find resolve through.
 */
const SHAPE_BUNDLE_CORE = {
  id: "bundle-core",
  name: "bundle: pi-coding-agent core tools",
  required: true,
  detect: (s) => /function resolveToCwd\(\w+,\w+\)\{/.test(s),
  hunks: [
    {
      // Writes and edits resolve through here: never rewrite the path.
      tag: tag("bundle-core-1"),
      from: /function resolveToCwd\((\w+),(\w+)\)\{return (\w+)\(\1,\2,\{normalizeUnicodeSpaces:!0,stripAtPrefix:!0\}\)\}/,
      to:
        `function resolveToCwd($1,$2){${tag("bundle-core-1")}return $3($1,$2,{normalizeUnicodeSpaces:!1,stripAtPrefix:!0})}` +
        `function __woowFoldUnicodeSpaces(p){return p.replace(/[\\u00A0\\u2000-\\u200A\\u202F\\u205F\\u3000]/g," ")}`,
    },
    {
      // resolveReadPath: folded-space fallback, after the exact path missed.
      tag: tag("bundle-core-2"),
      from: /let (\w+)=tryMacOSScreenshotPath\((\w+)\);if\(\1!==\2&&(\w+)\(\1\)\)return \1;/,
      to: `${tag("bundle-core-2")}let __woowFolded=__woowFoldUnicodeSpaces($2);if(__woowFolded!==$2&&$3(__woowFolded))return __woowFolded;$&`,
    },
    {
      // resolveReadPathAsync: same, async.
      tag: tag("bundle-core-3"),
      from: /let (\w+)=tryMacOSScreenshotPath\((\w+)\);if\(\1!==\2&&await (\w+)\(\1\)\)return \1;/,
      to: `${tag("bundle-core-3")}let __woowFolded=__woowFoldUnicodeSpaces($2);if(__woowFolded!==$2&&await $3(__woowFolded))return __woowFolded;$&`,
    },
  ],
};

/** Bundle, pi-agent-core harness tools — the minified copy of Shape A. */
const SHAPE_BUNDLE_HARNESS = {
  id: "bundle-harness",
  name: "bundle: pi-agent-core harness tools",
  required: false,
  detect: (s) => /function normalizeToolPath\(\w+\)\{/.test(s),
  hunks: [
    {
      tag: tag("bundle-harness-1"),
      from: /function normalizeToolPath\((\w+)\)\{let (\w+)=\1\.replace\((\w+)," "\);return \2\.startsWith\("@"\)\?\2\.slice\(1\):\2\}/,
      to:
        `function normalizeToolPath($1){${tag("bundle-harness-1")}return $1.startsWith("@")?$1.slice(1):$1}` +
        `function __woowFoldForRead(p){return p.replace($3," ")}`,
    },
    {
      tag: tag("bundle-harness-2"),
      from: /(\w+)=\[(\w+),\2\.replace\(\/ \(AM\|PM\)\\\.\/gi,/,
      to: `$1=[$2,${tag("bundle-harness-2")}__woowFoldForRead($2),$2.replace(/ (AM|PM)\\./gi,`,
    },
  ],
};

const SHAPES = [SHAPE_A, SHAPE_B, SHAPE_BUNDLE_CORE, SHAPE_BUNDLE_HARNESS];

const fail = (...lines) => {
  for (const l of lines) console.error("[patch] " + l);
  process.exit(1);
};
const isApplied = (h, src) => src.includes(h.tag ?? h.to);
const countMatches = (h, src) =>
  typeof h.from === "string"
    ? src.split(h.from).length - 1
    : [...src.matchAll(new RegExp(h.from.source, h.from.flags + "g"))].length;

const files = process.argv.slice(2);
if (files.length === 0) {
  fail("FAIL: no files given.", "The upstream layout changed, or find matched nothing.");
}

let patched = 0;
let already = 0;
const seen = new Set();

for (const file of files) {
  let src = readFileSync(file, "utf8");

  const shapes = SHAPES.filter((s) => s.detect(src) || s.hunks.every((h) => isApplied(h, src)));
  if (shapes.length === 0) {
    fail("FAIL: unrecognised shape: " + file, "Upstream refactored this file. Re-verify the fix before shipping.");
  }

  let changed = false;
  for (const shape of shapes) {
    for (const h of shape.hunks) {
      if (isApplied(h, src)) continue;
      const n = countMatches(h, src);
      if (n !== 1) {
        fail(`FAIL: hunk matched ${n} times (want exactly 1) in ${file} (shape: ${shape.name})`, "Expected:\n" + h.from);
      }
      src = src.replace(h.from, h.to);
      changed = true;
    }
    seen.add(shape.id);
  }

  if (changed) {
    writeFileSync(file, src);
    console.log(`[patch] patched (${shapes.map((s) => s.name).join(" + ")}):`, file);
    patched++;
  } else {
    console.log("[patch] already patched:", file);
    already++;
  }
}

const missing = SHAPES.filter((s) => s.required && !seen.has(s.id));
if (missing.length > 0) {
  fail(
    "FAIL: required shape(s) not found in any given file: " + missing.map((s) => s.name).join(", "),
    "pi moved this code. Find where it went before shipping; do not drop the shape.",
  );
}

console.log(`[patch] done — ${patched} patched, ${already} already patched`);
