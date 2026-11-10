Record Deduplication
====================

Finds duplicate records using one or more scalar key fields. Retains first or
last records, or fills missing values from duplicates, with original row indices.

Fields
- records (required array, at most 5000): JSON objects.
- keys (required array, 1–10 unique strings, at most 100 characters each).
- mode (optional first/last/merge, default first).
- trim (optional boolean, default true): trim string keys for matching.
- caseSensitive (optional boolean, default false): preserve string-key case.
- rejectDuplicates (optional boolean, default false): throw on any duplicated normalized key.
  Omission defaults to false; an explicitly supplied value must be boolean.
  null is rejected with "rejectDuplicates must be boolean", even for empty records.

Behavior
Every record must contain every key field. Key values may be strings, numbers,
booleans or null. String normalization changes comparisons only; retained
records keep their original key spelling. Numeric 1 differs from string "1".
Output groups follow their first appearance, including in last-retention mode.
Merge starts with the first record and fills absent, null or empty-string
NON-KEY fields from later duplicates. Zero, false, whitespace-only strings and
existing nonempty values remain unchanged. Merge is shallow, not recursive.
Conflicting nonempty fields retain the first value. Duplicate groups identify
0-based original indices and the 0-based output index.

Limits
No fuzzy matching, conflict resolution or automatic field discovery. Missing
key fields and object/array keys are rejected rather than merged silently.

Worked example (manually specified fixture)
Input:
{
  "records": [
    {
      "id": 1,
      "name": "",
      "score": 0,
      "active": false,
      "info": null
    },
    {
      "id": 1,
      "name": "Ava",
      "score": 9,
      "active": true,
      "info": {
        "x": 1
      },
      "extra": "y"
    }
  ],
  "keys": [
    "id"
  ],
  "mode": "merge"
}

Expected result:
{
  "inputCount": 2,
  "uniqueCount": 1,
  "duplicatesRemoved": 1,
  "records": [
    {
      "id": 1,
      "name": "Ava",
      "score": 0,
      "active": false,
      "info": {
        "x": 1
      },
      "extra": "y"
    }
  ],
  "duplicateGroups": [
    {
      "indices": [
        0,
        1
      ],
      "outputIndex": 0
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
17 independent cases in cases.json, including correct outputs and useful
rejections. test.mjs also checks example execution, repeatability, JSON-safe
outputs, input immutability, cycles, nonfinite values, oversize strings and depth.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p03 .; podman run --rm -p 127.0.0.1:8080:8080 p03
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"records":[{"email":" Ava@example.test ","name":"Ava"},{"email":"ava@example.test","phone":"1234"},{"email":"bo@example.test","name":"Bo"}],"keys":["email"],"mode":"merge"}
  output: {"inputCount":3,"uniqueCount":2,"duplicatesRemoved":1,"records":[{"email":" Ava@example.test ","name":"Ava","phone":"1234"},{"email":"bo@example.test","name":"Bo"}],"duplicateGroups":[{"indices":[0,1],"outputIndex":0}]}
Supported limitation: Matching is exact after trim/case normalization only; no fuzzy matching or conflict resolution. rejectDuplicates reports only the first duplicate encountered.
New option rejectDuplicates (boolean, default false): when true, any duplicated normalized composite key throws instead of silently deduplicating.
  input:  {"records":[{"id":" A "},{"id":"B"},{"id":"a"}],"keys":["id"],"rejectDuplicates":true}
  error:  duplicate key ["a"] at records[0] and records[2]
  unique input {records:[{id:'A'},{id:'B'}],keys:['id'],rejectDuplicates:true} -> {"inputCount":2,"uniqueCount":2,"duplicatesRemoved":0,"records":[{"id":"A"},{"id":"B"}],"duplicateGroups":[]}
  Non-boolean values are rejected: "rejectDuplicates must be boolean".
