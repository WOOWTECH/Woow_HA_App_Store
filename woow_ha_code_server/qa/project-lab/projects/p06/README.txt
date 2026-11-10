Log Severity and Timeline Analyzer
==================================

Analyzes text log lines, counts normalized severities, groups events into UTC
time buckets, and reports repeated messages and malformed lines.

Fields
- log (required string, at most 200000 characters): each nonblank line is
  UTC_TIMESTAMP LEVEL message, e.g. 2026-01-01T10:00:00Z INFO Started.
- bucketMinutes (optional integer, 1–1440, default 60).
- strict (optional boolean, default false): reject the entire input on the
  first malformed line instead of collecting a rejection diagnostic.

Behavior
UTC timestamps require YYYY-MM-DDTHH:mm:ss[.s/ss/sss]Z, including valid calendar
dates. Offsets and leap seconds are not supported. Levels are case insensitive:
TRACE, DEBUG, INFO, WARN, ERROR, FATAL; WARNING maps to WARN and CRITICAL to FATAL.
Blank lines are ignored. totalLines counts nonblank lines, accepted counts
valid events, and rejected entries retain 1-based physical line numbers.
Buckets are anchored to the Unix epoch and returned in chronological order.
First/last use the actual timestamps regardless of input order. Message counts
use exact trimmed messages; the top ten sort by count descending, then lexical
message order. Empty valid input returns null first/last and empty buckets.

Limits
At most 5000 physical lines. Single-line logs only; no stack-trace merging or
parameter-template normalization. Severity names outside the supported list
are reported/rejected. No files, external services or live logs are read.

Worked example (manually specified fixture)
Input:
{
  "log": "2026-01-01T10:00:00Z INFO Started\n2026-01-01T10:05:00Z ERROR Timeout\n2026-01-01T11:00:00Z WARN Retrying",
  "bucketMinutes": 60
}

Expected result:
{
  "totalLines": 3,
  "accepted": 3,
  "rejected": [],
  "severityCounts": {
    "TRACE": 0,
    "DEBUG": 0,
    "INFO": 1,
    "WARN": 1,
    "ERROR": 1,
    "FATAL": 0
  },
  "first": "2026-01-01T10:00:00.000Z",
  "last": "2026-01-01T11:00:00.000Z",
  "buckets": [
    {
      "start": "2026-01-01T10:00:00.000Z",
      "total": 2,
      "counts": {
        "TRACE": 0,
        "DEBUG": 0,
        "INFO": 1,
        "WARN": 0,
        "ERROR": 1,
        "FATAL": 0
      }
    },
    {
      "start": "2026-01-01T11:00:00.000Z",
      "total": 1,
      "counts": {
        "TRACE": 0,
        "DEBUG": 0,
        "INFO": 0,
        "WARN": 1,
        "ERROR": 0,
        "FATAL": 0
      }
    }
  ],
  "topMessages": [
    {
      "message": "Retrying",
      "count": 1
    },
    {
      "message": "Started",
      "count": 1
    },
    {
      "message": "Timeout",
      "count": 1
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
Container: podman build -t p06 .; podman run --rm -p 127.0.0.1:8080:8080 p06
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"log":"2026-01-01T10:00:00Z INFO Started\n2026-01-01T10:05:00Z ERROR Timeout\n2026-01-01T11:00:00Z WARN Retrying","bucketMinutes":60}
  output: {"totalLines":3,"accepted":3,"rejected":[],"severityCounts":{"TRACE":0,"DEBUG":0,"INFO":1,"WARN":1,"ERROR":1,"FATAL":0},"first":"2026-01-01T10:00:00.000Z","last":"2026-01-01T11:00:00.000Z","buckets":[{"start":"2026-01-01T10:00:00.000Z","total":2,"counts":{"TRACE":0,"DEBUG":0,"INFO":1,"WARN":0,"ERROR":1,"FATAL":0}},{"start":"2026-01-01T11:00:00.000Z","total":1,"counts":{"TRACE":0,"DEBUG":0,"INFO":0,"WARN":1,"ERROR":0,"FATAL":0}}],"topMessages":[{"message":"Retrying","count":1},{"message":"Started","count":1},{"message":"Timeout","count":1}]}
Supported limitation: Single-line UTC logs only; no stack-trace merging or offsets; at most 5000 lines.
