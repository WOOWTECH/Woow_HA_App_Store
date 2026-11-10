Deterministic Data Masking
==========================

Masks selected fields in synthetic records while preserving other fields.
Provides stable tokens, partial redaction and email display masks.

Fields
- records (required array, at most 2000): JSON objects.
- rules (required array, 1–30): unique field names with a supported mode.
  Each rule has field (1–100 characters) and mode (token/redact/email).
  Only redact accepts keepLast (optional integer 0–16, default 0).
- salt (optional string, at most 128 characters, default empty): a synthetic
  deterministic label used as the HMAC key; never enter credentials.

Behavior
Token mode hashes String(value). With an empty salt it uses SHA-256; otherwise
it uses HMAC-SHA-256 keyed by salt. Output is tok_ plus 12 lowercase hex digits.
Equal text values receive equal tokens; numeric 1 and string "1" share a token.
Redact replaces Unicode code points with asterisks, optionally retaining a
suffix, and always masks at least one character of a nonempty value. Email
requires a simple local@domain.tld syntax, retains the first local character,
and emits first***@lowercase-domain. Null and absent fields stay unchanged.
maskedCells counts present non-null fields processed, including empty strings.
Nested objects/arrays cannot be masked by these flat rules.

Limits
Demonstration pseudonymization only: hashes of guessable values can be guessed,
48-bit prefixes can collide, and suffix/email masks intentionally retain data.
These transformations are not encryption or certified anonymization. The
known-vector fixture uses SHA-256("abc") and SHA-256("hello"); the keyed fixture
uses the standard quick-brown-fox HMAC example. No secrets are included.

Worked example (manually specified fixture)
Input:
{
  "records": [
    {
      "label": "abc",
      "keep": 5
    },
    {
      "label": "abc"
    },
    {
      "label": "hello"
    },
    {
      "label": null
    },
    {}
  ],
  "rules": [
    {
      "field": "label",
      "mode": "token"
    }
  ]
}

Expected result:
{
  "records": [
    {
      "label": "tok_ba7816bf8f01",
      "keep": 5
    },
    {
      "label": "tok_ba7816bf8f01"
    },
    {
      "label": "tok_2cf24dba5fb0"
    },
    {
      "label": null
    },
    {}
  ],
  "maskedCells": 3
}

Run locally (Node.js standard library only; no install or network needed)
  node test.mjs
  node --input-type=module -e "import {meta,run} from './app.mjs'; console.log(JSON.stringify(run(meta.example),null,2))"

To pass your own JSON on stdin:
  node --input-type=module -e "import {readFileSync} from 'node:fs'; import {run} from './app.mjs'; console.log(JSON.stringify(run(JSON.parse(readFileSync(0,'utf8'))),null,2))"

Integration
app.mjs exports meta and a synchronous run(input). The coordinator owns the
shared interactive page, runtime.mjs, main.mjs and package.json. This batch does
not create or change the shared server, deployment, packages or platform.

Shared safeguards
Input must be a JSON object with finite numbers and no cycles, at most 30000
JSON nodes, 32 levels of nesting, 1000000 total key/string characters, and no
individual string over 200000 characters. These shared bounds also apply when
per-field counts would otherwise permit larger data. Bad configuration/input
throws Error with a useful message. All examples are synthetic. No credentials,
external dependencies, network access, eval or production certification claims.

Tests
11 independent cases in cases.json, including correct outputs and useful
rejections. test.mjs also checks example execution, repeatability, JSON-safe
outputs, input immutability, cycles, nonfinite values, oversize strings and depth.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p05 .; podman run --rm -p 127.0.0.1:8080:8080 p05
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"records":[{"name":"Ava","email":"ava@example.test","phone":"5551234"},{"name":"Ava","email":"ava@example.test","phone":"5559876"}],"rules":[{"field":"name","mode":"token"},{"field":"email","mode":"email"},{"field":"phone","mode":"redact","keepLast":2}]}
  output: {"records":[{"name":"tok_149f7514de22","email":"a***@example.test","phone":"*****34"},{"name":"tok_149f7514de22","email":"a***@example.test","phone":"*****76"}],"maskedCells":6}
Supported limitation: Demonstration pseudonymization only; guessable values can be recovered by hashing guesses.
