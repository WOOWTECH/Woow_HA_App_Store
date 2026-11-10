Reservation Collision Detector (p16)
Run: node test.mjs; import {meta, run} from ./app.mjs. The coordinator supplies
the shared main.mjs/runtime.mjs HTTP entry.

Input: optional turnaroundMinutes (integer 0..1440, default 0); reservations
(0..200), each with unique id, resource, start, end. Times use strict UTC minute
precision YYYY-MM-DDTHH:MMZ, years 2000..2099. Invalid dates, zero/reversed
intervals, or bookings longer than seven days fail. Resource names are exact,
case-sensitive strings. Inputs are never mutated.
Reservations occupy [start, end + turnaround). Endpoints that merely touch do
not collide. Reports contain every colliding pair, sorted by resource then
start then ID; kind is overlap if the actual bookings overlap, otherwise
turnaround. conflictStart/End/Minutes describe the overlap of occupied
intervals INCLUDING turnaround, so they may extend past a booking's actual end.

Worked example: Room A booked 09:00-10:00 then 10:00-11:00 is valid with no
buffer. A 15-minute turnaround produces a 10:00-10:15 turnaround conflict.
Moving the second start to 10:15 clears it. See meta.example for complete data.

Limitations: no recurring reservations, time-zone conversion, resource capacity,
booking persistence or concurrency control. This is a pairwise detector for
exclusive resources. Hand-derived fixtures cover nesting, adjacency and errors.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p16 .; podman run --rm -p 127.0.0.1:8080:8080 p16
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"turnaroundMinutes":15,"reservations":[{"id":"R1","resource":"Room A","start":"2026-11-10T09:00Z","end":"2026-11-10T10:00Z"},{"id":"R2","resource":"Room A","start":"2026-11-10T10:00Z","end":"2026-11-10T11:00Z"}]}
  output: {"valid":false,"conflicts":[{"resource":"Room A","firstId":"R1","secondId":"R2","kind":"turnaround","conflictStart":"2026-11-10T10:00Z","conflictEnd":"2026-11-10T10:15Z","conflictMinutes":15}],"resourceCount":1,"reservationCount":2}
Supported limitation: Pairwise detection for exclusive resources in UTC; no recurrence, time zones or capacity.
