HTTP Error Budget Analyzer

Purpose: Analyze an explicitly supplied request sample against a success SLO.
Run: node test.mjs
API: import { meta, run } from './app.mjs'; run(meta.example).

Fields:
- observations: 1–1000 objects {status,count}. Status is integer 100–599;
  count is positive integer. Combined count cannot exceed one billion.
- sloPercent: optional number 0–100, at most four decimal places; default 99.9.
- failureStatuses: optional array of up to 500 codes. When omitted, all 5xx
  responses fail. An empty array explicitly treats every supplied status as good.
Unknown fields are rejected. Duplicate statuses are aggregated.

Worked example: 995 HTTP 200 and five HTTP 500 at a 99% SLO gives 1000 requests,
99.5% success, ten allowed failures, five remaining, burn rate 0.5 and
withinBudget=true. Status rows are numerically sorted.

Allowed failures can be fractional. Remaining failures may be negative. Numeric
metrics round to six decimals; the budget decision uses integer-scaled SLO units.
At a 100% SLO, burnRate is zero if there are no failures, otherwise null (undefined).
Limitations: request-based accounting over supplied observations only; no time
window, latency objective, telemetry collection, network or production monitoring.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p21 .; podman run --rm -p 127.0.0.1:8080:8080 p21
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: custom failures aggregate and exhaust budget.
Input: {"observations":[{"status":429,"count":2},{"status":200,"count":5},{"status":200,"count":3}],"sloPercent":90,"failureStatuses":[429]}
Expected output: {"totalRequests":10,"successfulRequests":8,"failedRequests":2,"successPercent":80,"allowedFailures":1,"remainingFailures":-1,"burnRate":2,"withinBudget":false,"byStatus":[{"status":200,"count":8},{"status":429,"count":2}]}
Supported limitation: Only supplied request counts are analyzed; no telemetry or time window.
