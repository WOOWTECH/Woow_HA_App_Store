Pivot Table Aggregation
=======================

Aggregates records by one or more dimensions and computes group values and
grand totals for sum, mean, min, max or count.

Fields
- records (required array, at most 5000): JSON objects.
- groupBy (required array): 1–4 unique field names, each 1–100 characters.
- operation (optional sum/mean/min/max/count, default sum).
- valueField (required except count): name of a finite numeric field.

Behavior
Grouping fields must exist and be scalar values or null. Typed dimensions are
preserved: numeric 1 and string "1" form different groups. Group order follows
first appearance. Count requires no valueField. Other operations reject missing
or nonnumeric values, including numeric strings. Mean grand totals use all
records, not an unweighted mean of group means. Values round to six decimals;
negative zero normalizes to zero. Empty sum/count totals are zero; empty
mean/min/max totals are null.

Limits
No spreadsheet formulas, multiple measures or subtotals. Numeric calculations
use finite JavaScript numbers; sum/mean reject intermediate sum overflow.

Worked example (manually specified fixture)
Input:
{
  "records": [
    {
      "region": "East",
      "sales": 10
    },
    {
      "region": "West",
      "sales": 8
    },
    {
      "region": "East",
      "sales": 20
    }
  ],
  "groupBy": [
    "region"
  ],
  "valueField": "sales",
  "operation": "sum"
}

Expected result:
{
  "operation": "sum",
  "groupBy": [
    "region"
  ],
  "groups": [
    {
      "key": {
        "region": "East"
      },
      "count": 2,
      "value": 30
    },
    {
      "key": {
        "region": "West"
      },
      "count": 1,
      "value": 8
    }
  ],
  "totals": {
    "count": 3,
    "value": 38
  }
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
Container: podman build -t p04 .; podman run --rm -p 127.0.0.1:8080:8080 p04
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"records":[{"region":"East","sales":10},{"region":"West","sales":8},{"region":"East","sales":20}],"groupBy":["region"],"valueField":"sales","operation":"sum"}
  output: {"operation":"sum","groupBy":["region"],"groups":[{"key":{"region":"East"},"count":2,"value":30},{"key":{"region":"West"},"count":1,"value":8}],"totals":{"count":3,"value":38}}
Supported limitation: One measure and one operation per run; no subtotals or spreadsheet formulas.
