Retry/backoff job scheduler simulation

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
The coordinator provides the HTTP entry point and interactive page.

Input: 1-100 jobs with unique id, failuresBeforeSuccess (0-20), optional
maxAttempts (1-21, default 3), submittedAt (0-1e9, default 0).
Global workers 1-16 (default 1), attemptDuration 1-3600 (default 1),
baseDelay 0-86400 (default 2), factor 1-10 (default 2), and maxDelay
0-86400 (default 3600). All numeric settings are integers in arbitrary
consistent time units. After failed attempt n, delay is
min(maxDelay, baseDelay * factor^(n-1)), measured from that attempt's end.

Available jobs are ordered by ready time then input order. Free workers are
assigned by ascending worker number. A zero delay still waits for a worker.
Each job has its own retry limit. Output lists all attempts with start/end,
worker/outcome, final job states, and overall finish time.

Worked example: one job fails twice with duration 1 and delays 2 then 4.
Its attempts occupy [0,1], [3,4], [8,9], succeeding at 9.
With maxAttempts 2 it instead exhausts after its second failure.

Limitations: no real sleeping, job execution, persistence, jitter, or network.
Failure outcomes are synthetic and deterministic.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p43 .; podman run --rm -p 127.0.0.1:8080:8080 p43
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"baseDelay":3,"jobs":[{"id":"review","failuresBeforeSuccess":1}]}
Expected highlights: attempts 0-1 and 4-5; succeeded 1, finishedAt 5.
Supported limitation: deterministic synthetic failures; no jitter or real sleeping.
