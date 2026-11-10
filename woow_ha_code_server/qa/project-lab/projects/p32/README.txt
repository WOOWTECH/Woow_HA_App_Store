Spaced repetition review planner

Purpose: Update a set of just-reviewed cards with a bounded SM-2 style policy.
All dates are explicit UTC calendar dates, making plans repeatable offline.

Input object:
- reviewDate: real YYYY-MM-DD date, years 1900–2100.
- cards: 1–500 objects with unique trimmed id strings of 1–80 characters.
- quality: required integer 0–5 (0–2 fail, 3–5 pass).
- repetitions: prior consecutive successful reviews, integer 0–10000, default 0.
- intervalDays: previous interval, integer 0–36500, default 0. Must be positive
  when repetitions is positive.
- easeFactor: finite 1.3–5, default 2.5.

For q=quality, new ease = old ease + 0.1 - (5-q)*(0.08 + (5-q)*0.02),
clamped to [1.3,5] and rounded to two decimals. A failure resets repetitions to
zero and schedules tomorrow. Passing intervals are 1 day, then 6 days, then
round(previous interval * PREVIOUS ease). Intervals cap at 36500 days and
repetition counts cap at 10000, so returned states can be reused. Input order
is retained. dueDate is reviewDate plus the new interval; no local time/DST.

Worked example:
{"reviewDate":"2026-12-25","cards":[{"id":"mature","quality":5,"repetitions":2,"intervalDays":6,"easeFactor":2.5}]}
Returns successfulReviews 3, easeFactor 2.6, intervalDays 15, dueDate 2027-01-09.
A new quality-5 card instead gets interval 1 and repetitions 1.

Limitations: This is a transparent scheduling heuristic, not a prediction of
memory retention. It updates cards reviewed on a common date; it does not store
a deck, select due cards, or account for overdue history. When feeding output
back as input, map successfulReviews to repetitions.

Running and integration:
From this project directory, run: node test.mjs
No installation, external dependencies, network, credentials, or persistent
storage are required. app.mjs exports meta and synchronous run(input).
The shared interactive UI, runtime.mjs, package.json, and HTTP server entry
are supplied by the coordinator under CONTRACT.txt; this batch owns only
app.mjs, cases.json, test.mjs, and this README.txt.

cases.json contains independent, manually derived complete expected outputs
and rejection fixtures. test.mjs checks them with node:assert/strict, verifies
useful errors, input immutability, JSON serialization and deterministic results,
and smoke-tests meta.example. A mismatch exits nonzero.

To call the standalone computation directly from this directory:
node --input-type=module -e 'import {meta,run} from "./app.mjs"; console.log(JSON.stringify(run(meta.example),null,2))'

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p32 .; podman run --rm -p 127.0.0.1:8080:8080 p32
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: mature review and failed card.
Input: {"reviewDate":"2026-12-25","cards":[{"id":"mature","quality":5,"repetitions":2,"intervalDays":6,"easeFactor":2.5},{"id":"failed","quality":2,"repetitions":4,"intervalDays":20,"easeFactor":1.4}]}
Expected output: {"reviewDate":"2026-12-25","total":2,"scheduled":[{"id":"mature","quality":5,"successfulReviews":3,"easeFactor":2.6,"intervalDays":15,"dueDate":"2027-01-09"},{"id":"failed","quality":2,"successfulReviews":0,"easeFactor":1.3,"intervalDays":1,"dueDate":"2026-12-26"}]}
Supported limitation: Scheduling heuristic only; no stored deck or overdue-history handling.
