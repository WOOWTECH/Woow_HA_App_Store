CSV Profile and Anomaly Report
==============================

Parses CSV including quoted delimiters, doubled quotes, embedded newlines, CRLF,
and a leading UTF-8 BOM. Profiles columns and flags missing cells, mixed numeric
content, repeated rows, and population-z-score outliers.

Fields
- csv (required string, 1–200000 characters): first row contains headers.
- delimiter (optional one-character string, default comma): cannot be quote/CR/LF.
- zScoreThreshold (optional number, default 3, range 0.1–20): an outlier's
  absolute population z-score must strictly exceed this threshold.

Behavior
Headers are trimmed and must be unique and nonempty. Rows must have the same
width as the header. Column statistics trim cells; missing means blank after
trimming. Distinct counts exclude missing values. Numeric values accept signed
decimals and scientific notation, with finite conversion required. A column
containing both numeric and nonnumeric cells is mixed, with nonnumeric cells
flagged. Missing cells are always flagged. Duplicate rows compare exact parsed
cell strings, including whitespace. Row numbers are 1-based DATA row indices,
not physical line numbers; embedded newlines can span physical lines.
Numeric means are rounded to six decimals. Outliers use the unrounded mean and
population standard deviation of numeric cells only. Constant numeric columns
have no outliers. Blank lines are data rows; a final line terminator does not
create an additional row. Header-only CSV is valid.

Limits
At most 5000 data rows and 100 columns. The parser is strict: whitespace after a
closing quote is rejected. This is a quality report, not a CSV repair tool.
A mixed column may be intentional; an anomaly does not prove a data error.

Worked example (manually specified fixture)
Input:
{
  "csv": "name,amount\nAva,10\nBo,20\nAva,10\nCy,"
}

Expected result:
{
  "rowCount": 4,
  "columnCount": 2,
  "columns": [
    {
      "name": "name",
      "present": 4,
      "missing": 0,
      "distinct": 3,
      "type": "text",
      "anomalies": []
    },
    {
      "name": "amount",
      "present": 3,
      "missing": 1,
      "distinct": 2,
      "type": "number",
      "anomalies": [
        {
          "row": 4,
          "kind": "missing",
          "value": ""
        }
      ],
      "numeric": {
        "count": 3,
        "min": 10,
        "max": 20,
        "mean": 13.333333
      }
    }
  ],
  "duplicateRows": [
    {
      "row": 3,
      "firstRow": 1
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
11 independent cases in cases.json, including correct outputs and useful
rejections. test.mjs also checks example execution, repeatability, JSON-safe
outputs, input immutability, cycles, nonfinite values, oversize strings and depth.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p01 .; podman run --rm -p 127.0.0.1:8080:8080 p01
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"csv":"name,amount\nAva,10\nBo,20\nAva,10\nCy,","zScoreThreshold":3,"delimiter":","}
  output: {"rowCount":4,"columnCount":2,"columns":[{"name":"name","present":4,"missing":0,"distinct":3,"type":"text","anomalies":[]},{"name":"amount","present":3,"missing":1,"distinct":2,"type":"number","anomalies":[{"row":4,"kind":"missing","value":""}],"numeric":{"count":3,"min":10,"max":20,"mean":13.333333}}],"duplicateRows":[{"row":3,"firstRow":1}]}
Supported limitation: Row numbers are 1-based data rows; no type inference beyond numeric/mixed, and no streaming for large files.
