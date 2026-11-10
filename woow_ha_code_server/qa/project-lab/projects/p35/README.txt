Reading-time and content structure report

Purpose: Summarize basic Markdown/prose structure and estimate reading time.
Input: {"text":"Hello world. Read this!","wpm":200}
text is a string of at most 100000 UTF-16 code units; empty text is accepted.
wpm is an integer 50–1000, default 200.

Output definitions:
- characters: UTF-16 code units after CRLF/CR normalization to LF.
- lines: LF-separated lines, including a final empty line; empty text has zero.
- words: Unicode letters/numbers, optionally joined by apostrophes or hyphens.
  Heading and list contents count; fenced code and fence markers do not.
- uniqueWords: lowercase distinct words (no stemming or Unicode normalization).
- sentences: nonempty word-containing spans separated by . ! ? or CJK equivalents;
  a final unterminated span counts. Headings/list lines join the same text stream.
- paragraphs: consecutive prose lines separated by blank lines, headings, lists,
  or code fences; heading/list/code blocks do not themselves count as paragraphs.
- headings: ATX # through ###### with level, title and 1-based source line.
- listItems: lines beginning with -, +, *, or an integer followed by . or ).
- codeBlocks: opened fences of at least three backticks or tildes. A closing
  fence must use the same character, at least the opening length, and no suffix.
  An unclosed fence excludes the rest of the document.
- readingSeconds: ceiling(words * 60 / wpm), excluding fenced code.

Worked example: "Hello world. Read this!" at 200 wpm has 23 characters,
4 words, 4 unique words, 2 sentences, 1 paragraph, and 2 estimated seconds.
"# Guide

- Read daily
- Take notes

Done." has 6 words, one heading,
two list items, and one prose paragraph.

Limitations: A basic heuristic, not a full Markdown or natural-language parser.
Inline code/links/HTML can contribute words. Abbreviations/decimal punctuation
may affect sentence counts. Unspaced CJK sequences count as one token; this
reading-time model works best with whitespace-delimited prose.

Running and integration:
From this project directory, run: node test.mjs
No installation, external dependencies, network, credentials, or persistent
storage are required. app.mjs exports meta and synchronous run(input).
The shared interactive UI, runtime.mjs, package.json, and HTTP server entry
are supplied by the coordinator under CONTRACT.txt; this batch owns only
app.mjs, cases.json, test.mjs, and this README.txt.

cases.json contains independent, manually derived complete expected outputs
and rejection fixtures. test.mjs checks them with node:assert/strict, verifies
useful errors, input immutability, JSON serialization and deterministic results,
and smoke-tests meta.example. A mismatch exits nonzero.

To call the standalone computation directly from this directory:
node --input-type=module -e 'import {meta,run} from "./app.mjs"; console.log(JSON.stringify(run(meta.example),null,2))'

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p35 .; podman run --rm -p 127.0.0.1:8080:8080 p35
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"text":"# Notes\n\nRead slowly.","wpm":60}
Expected highlights: 3 words, one heading, one paragraph, readingSeconds 3.
Supported limitation: fenced code is excluded, but inline Markdown is not fully parsed.
