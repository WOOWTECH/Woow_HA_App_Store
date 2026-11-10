JSON Structural Diff
====================

Compares JSON recursively and returns deterministic structural changes with
JSON Pointer paths. Supports nested objects, arrays, primitive values and null.

Fields
- before (required JSON value): original document.
- after (required JSON value): comparison document.

Behavior
Object keys are compared in lexical order. Key order alone is not a change.
The root path is the empty string; path segments escape ~ as ~0 and / as ~1.
Array elements are compared by index. Tail removals are emitted from the last
index downward; additions are emitted upward. A value or type change produces
replace with before/after, an addition has after, and a removal has before.
The summary reports equal plus added/removed/replaced operation counts.

Limits
At most 5000 changes. Array reordering is represented as index changes, not
move detection. The result resembles a patch but uses before/after fields;
it is not directly an RFC 6902 JSON Patch document. Numbers use JavaScript
finite-number semantics. Root before/after properties must exist even for null.

Worked example (manually specified fixture)
Input:
{
  "before": {
    "count": 1,
    "tags": [
      "old"
    ]
  },
  "after": {
    "count": 2,
    "tags": [
      "new"
    ],
    "active": true
  }
}

Expected result:
{
  "equal": false,
  "added": 1,
  "removed": 0,
  "replaced": 2,
  "changes": [
    {
      "op": "add",
      "path": "/active",
      "after": true
    },
    {
      "op": "replace",
      "path": "/count",
      "before": 1,
      "after": 2
    },
    {
      "op": "replace",
      "path": "/tags/0",
      "before": "old",
      "after": "new"
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
10 independent cases in cases.json, including correct outputs and useful
rejections. test.mjs also checks example execution, repeatability, JSON-safe
outputs, input immutability, cycles, nonfinite values, oversize strings and depth.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p02 .; podman run --rm -p 127.0.0.1:8080:8080 p02
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"before":{"count":1,"tags":["old"]},"after":{"count":2,"tags":["new"],"active":true}}
  output: {"equal":false,"added":1,"removed":0,"replaced":2,"changes":[{"op":"add","path":"/active","after":true},{"op":"replace","path":"/count","before":1,"after":2},{"op":"replace","path":"/tags/0","before":"old","after":"new"}]}
Supported limitation: Array reordering appears as index changes, not moves; output is not RFC 6902 JSON Patch; at most 5000 changes.
