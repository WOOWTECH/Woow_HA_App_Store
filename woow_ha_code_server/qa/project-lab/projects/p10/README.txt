Data Reconciliation by Key
==========================

Matches records from two datasets by unique composite keys, reports field
changes and unmatched records, and distinguishes missing fields from null.

Fields
- left/right (required arrays, each at most 5000): JSON objects.
- keys (required array): 1–10 unique field names, each 1–100 characters.
- fields (optional array): 1–100 unique comparison fields, excluding keys.
  If omitted, compare the union of non-key fields for each matched pair.
- numericTolerance (optional finite number, 0–1000000000000, default 0):
  inclusive absolute tolerance for top-level numeric comparison fields.

Behavior
Every key must exist and contain a scalar or null. Matching is exact and typed;
there is no string trimming/case folding, and numeric 1 differs from string "1".
Duplicate keys in either dataset are rejected to prevent ambiguous matches.
Object-valued fields compare structurally independent of object property order;
array order matters. Numeric tolerance applies only to top-level numeric fields,
not numbers nested inside objects/arrays. Differences include presence flags
and left/right values only when present. Changes follow left record order;
fields sort lexically. Unmatched records preserve their respective source order.
matchedCount includes both changed and unchanged matches. Inputs are not mutated.

Limits
No fuzzy entity matching, value coercion or automatic duplicate resolution.
Floating-point values use JavaScript semantics. Key fields cannot be selected
as comparison fields. This is a comparison report, not a write-back operation.

Worked example (manually specified fixture)
Input:
{
  "left": [
    {
      "id": "A",
      "quantity": 5
    },
    {
      "id": "B",
      "quantity": 2
    }
  ],
  "right": [
    {
      "id": "A",
      "quantity": 6
    },
    {
      "id": "C",
      "quantity": 9
    }
  ],
  "keys": [
    "id"
  ]
}

Expected result:
{
  "summary": {
    "leftCount": 2,
    "rightCount": 2,
    "matchedCount": 1,
    "unchangedCount": 0,
    "changedCount": 1,
    "leftOnlyCount": 1,
    "rightOnlyCount": 1
  },
  "changes": [
    {
      "key": {
        "id": "A"
      },
      "differences": [
        {
          "field": "quantity",
          "leftPresent": true,
          "rightPresent": true,
          "left": 5,
          "right": 6
        }
      ]
    }
  ],
  "leftOnly": [
    {
      "id": "B",
      "quantity": 2
    }
  ],
  "rightOnly": [
    {
      "id": "C",
      "quantity": 9
    }
  ]
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
12 independent cases in cases.json, including correct outputs and useful
rejections. test.mjs also checks example execution, repeatability, JSON-safe
outputs, input immutability, cycles, nonfinite values, oversize strings and depth.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p10 .; podman run --rm -p 127.0.0.1:8080:8080 p10
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"left":[{"id":"A","quantity":5},{"id":"B","quantity":2}],"right":[{"id":"A","quantity":6},{"id":"C","quantity":9}],"keys":["id"],"numericTolerance":0}
  output: {"summary":{"leftCount":2,"rightCount":2,"matchedCount":1,"unchangedCount":0,"changedCount":1,"leftOnlyCount":1,"rightOnlyCount":1},"changes":[{"key":{"id":"A"},"differences":[{"field":"quantity","leftPresent":true,"rightPresent":true,"left":5,"right":6}]}],"leftOnly":[{"id":"B","quantity":2}],"rightOnly":[{"id":"C","quantity":9}]}
Supported limitation: Exact typed key matching; duplicate keys are rejected; tolerance applies to top-level numbers only.
