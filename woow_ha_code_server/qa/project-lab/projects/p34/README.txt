Pomodoro work/rest planner

Purpose: Build a static work-and-rest timeline with configurable break cadence,
totals, and explicit day offsets when the schedule crosses midnight.

Input object:
- sessions: required integer 1–96.
- workMinutes: integer 1–240, default 25.
- shortBreakMinutes: integer 0–120, default 5.
- longBreakMinutes: integer 0–240, default 15.
- longBreakEvery: integer 1–24, default 4.
- startTime: 24-hour HH:MM, default 09:00.

A long break replaces a short break after every Nth work session. There is no
break after the final session. Zero-length breaks are omitted. Each segment
has kind, session number, minutes, start/end clock times and startDay/endDay.
A break's session number identifies the work session preceding it. Day zero
is the starting day. finishDay may be greater than one for long schedules.

Worked example: {"sessions":2}
09:00–09:25 work, 09:25–09:30 short break, 09:30–09:55 work.
Totals: 50 work minutes, 5 rest minutes, 55 overall; finish 09:55, day 0.
{"sessions":1,"startTime":"23:50"} finishes at 00:15 on day 1.

Limitations: No live timers, alarms, calendar integration, dates, time zones,
DST, or interruption tracking. This planner computes elapsed clock minutes.

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
Container: podman build -t p34 .; podman run --rm -p 127.0.0.1:8080:8080 p34
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: midnight rollover.
Input: {"sessions":1,"startTime":"23:50"}
Expected output: {"sessions":1,"totalWorkMinutes":25,"totalRestMinutes":0,"totalMinutes":25,"finishTime":"00:15","finishDay":1,"segments":[{"kind":"work","session":1,"minutes":25,"start":"23:50","startDay":0,"end":"00:15","endDay":1}]}
Supported limitation: Static elapsed-minute schedule only; no live timers, time zones or DST.
