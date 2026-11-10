Time-Series Moving Averages and Anomalies
=========================================

Computes trailing moving averages and flags deviations from the preceding full
window of observations, without including the current value in its baseline.

Fields
- points (required array, 1–5000): {time, value} objects in strict time order.
- time: UTC YYYY-MM-DDTHH:mm:ss[.s/ss/sss]Z, with a valid calendar date.
- value: finite number between -1000000000000 and 1000000000000.
- window (optional integer, 1–1000, default 3): observation count.
- threshold (optional number, 0.01–1000, default 3): strict absolute z-score
  cutoff, evaluated before rounding.

Behavior
Moving averages include the current value and up to window-1 prior values;
startup windows use all available observations. Baselines use exactly window
PREVIOUS observations. Before a full baseline exists, baseline statistics and
zScore are null and anomaly is false. Population standard deviation is used.
A constant baseline gives zScore 0 for an equal value; a different value is an
anomaly with zScore null because its z-score is undefined/infinite. Numeric
statistics round to six decimals. anomalyCount counts flagged points.
Duplicate or out-of-order timestamps are rejected.

Limits
Observation-based windows are not duration-based, so irregular time gaps are
not interpolated or weighted. UTC only; no offsets or leap seconds. Uses
floating-point arithmetic and a heuristic threshold, not a forecasting model.

Worked example (manually specified fixture)
Input:
{
  "points": [
    {
      "time": "2026-01-01T00:00:00Z",
      "value": 10
    },
    {
      "time": "2026-01-01T01:00:00Z",
      "value": 10
    },
    {
      "time": "2026-01-01T02:00:00Z",
      "value": 10
    },
    {
      "time": "2026-01-01T03:00:00Z",
      "value": 30
    }
  ],
  "window": 3,
  "threshold": 3
}

Expected result:
{
  "window": 3,
  "threshold": 3,
  "anomalyCount": 1,
  "points": [
    {
      "time": "2026-01-01T00:00:00.000Z",
      "value": 10,
      "movingAverage": 10,
      "baselineMean": null,
      "baselineStdDev": null,
      "zScore": null,
      "anomaly": false
    },
    {
      "time": "2026-01-01T01:00:00.000Z",
      "value": 10,
      "movingAverage": 10,
      "baselineMean": null,
      "baselineStdDev": null,
      "zScore": null,
      "anomaly": false
    },
    {
      "time": "2026-01-01T02:00:00.000Z",
      "value": 10,
      "movingAverage": 10,
      "baselineMean": null,
      "baselineStdDev": null,
      "zScore": null,
      "anomaly": false
    },
    {
      "time": "2026-01-01T03:00:00.000Z",
      "value": 30,
      "movingAverage": 16.666667,
      "baselineMean": 10,
      "baselineStdDev": 0,
      "zScore": null,
      "anomaly": true
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
Container: podman build -t p07 .; podman run --rm -p 127.0.0.1:8080:8080 p07
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"points":[{"time":"2026-01-01T00:00:00Z","value":10},{"time":"2026-01-01T01:00:00Z","value":10},{"time":"2026-01-01T02:00:00Z","value":10},{"time":"2026-01-01T03:00:00Z","value":30}],"window":3,"threshold":3}
  output: {"window":3,"threshold":3,"anomalyCount":1,"points":[{"time":"2026-01-01T00:00:00.000Z","value":10,"movingAverage":10,"baselineMean":null,"baselineStdDev":null,"zScore":null,"anomaly":false},{"time":"2026-01-01T01:00:00.000Z","value":10,"movingAverage":10,"baselineMean":null,"baselineStdDev":null,"zScore":null,"anomaly":false},{"time":"2026-01-01T02:00:00.000Z","value":10,"movingAverage":10,"baselineMean":null,"baselineStdDev":null,"zScore":null,"anomaly":false},{"time":"2026-01-01T03:00:00.000Z","value":30,"movingAverage":16.666667,"baselineMean":10,"baselineStdDev":0,"zScore":null,"anomaly":true}]}
Supported limitation: Windows are observation-count based, not duration based; irregular gaps are not weighted.
