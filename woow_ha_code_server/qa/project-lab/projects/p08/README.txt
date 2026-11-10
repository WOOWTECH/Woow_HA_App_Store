Record Schema Validator
=======================

Checks records against a small explicit field schema and returns per-record
errors. Invalid schema definitions throw; invalid records produce diagnostics.

Fields
- schema (required object): 1–50 field rules, field names 1–100 characters.
- records (required array, at most 5000): rows to validate; nonobjects produce
  a record error with field "$" rather than stopping other rows.
- allowUnknown (optional boolean, default false).

Each schema field has type: string, number, integer or boolean. Optional rules:
- required and nullable: booleans, each defaults to false.
- min/max: finite numeric bounds; only number/integer fields; inclusive.
- minLength/maxLength: integers 0–200000; only strings; Unicode code points.
- enum: 1–50 unique values matching the type; null requires nullable=true.
- format: email or date; string fields only. Date requires a valid YYYY-MM-DD.
Unknown rule names, inconsistent types and contradictory bounds are rejected.

Behavior
Fields are validated in lexical order. Missing optional fields are skipped.
Null is accepted only with nullable=true and, if enum exists, explicit enum
membership. Types are strict: numeric strings are not numbers. Invalid types
skip further rules for that field. Unknown input fields produce errors unless
allowUnknown=true. Record results identify a 0-based index, valid flag and
field/code/message errors. Empty record arrays are valid.

Limits
This is an intentionally small flat schema language, not JSON Schema. It does
not coerce values, insert defaults, check nested schemas or execute regex/code.
Email format is a simple syntax check, not mailbox verification.

Worked example (manually specified fixture)
Input:
{
  "schema": {
    "name": {
      "type": "string",
      "required": true,
      "minLength": 1
    },
    "age": {
      "type": "integer",
      "min": 0,
      "max": 120
    }
  },
  "records": [
    {
      "name": "Ava",
      "age": 30
    },
    {
      "name": "",
      "age": -2
    }
  ]
}

Expected result:
{
  "valid": false,
  "total": 2,
  "validCount": 1,
  "invalidCount": 1,
  "results": [
    {
      "index": 0,
      "valid": true,
      "errors": []
    },
    {
      "index": 1,
      "valid": false,
      "errors": [
        {
          "field": "age",
          "code": "min",
          "message": "must be at least 0"
        },
        {
          "field": "name",
          "code": "minLength",
          "message": "must contain at least 1 characters"
        }
      ]
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
Container: podman build -t p08 .; podman run --rm -p 127.0.0.1:8080:8080 p08
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"schema":{"name":{"type":"string","required":true,"minLength":1},"age":{"type":"integer","min":0,"max":120}},"records":[{"name":"Ava","age":30},{"name":"","age":-2}],"allowUnknown":false}
  output: {"valid":false,"total":2,"validCount":1,"invalidCount":1,"results":[{"index":0,"valid":true,"errors":[]},{"index":1,"valid":false,"errors":[{"field":"age","code":"min","message":"must be at least 0"},{"field":"name","code":"minLength","message":"must contain at least 1 characters"}]}]}
Supported limitation: Flat schema language only, not JSON Schema; no coercion, nested schemas or regex.
