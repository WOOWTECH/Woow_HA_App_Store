Event stream window aggregation

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator provides standalone HTTP runtime and the interactive page.

Input: windowMs integer 1-86400000, allowedLatenessMs integer 0-86400000
(default 0), events array (0-10000). Events have integer timestamp 0-1e12,
nonempty key up to 64 characters, and finite value between -1e9 and 1e9.
Timestamps and durations use milliseconds on an arbitrary common epoch.

Arrival order matters. Before each event, watermark is the greatest
previously accepted timestamp minus allowedLatenessMs. Events strictly older
than that watermark are rejected; equality is accepted. The first event is
always accepted. Windows are epoch-aligned, half-open intervals [start,end).
Every accepted bucket is returned at end of input, including still-open
windows. No empty windows are generated.

Output: final watermark (possibly negative; null when empty), accepted and
rejectedLate counts, per-key windows with count/sum/min/max/average, and
zero-based indexes of rejected events. Windows sort by start then key.
Sums and averages round to 6 decimal places.

Worked example: width 10, lateness 5, arrivals 12,8,6 yield watermark 7.
Times 12 and 8 are accepted into [10,20) and [0,10); time 6 is rejected.

Limitations: finite in-memory stream, no deduplication or persistence. The
late policy is per-event age, not window-close grace. Floating point values
are unsuitable for exact financial arithmetic. No external stream access.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p47 .; podman run --rm -p 127.0.0.1:8080:8080 p47
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"windowMs":10,"events":[{"timestamp":1,"key":"review","value":4},{"timestamp":2,"key":"review","value":8}]}
Expected highlights: one [0,10) window, count 2, sum 12, average 6; watermark 2.
Supported limitation: finite arrival-order stream, with no deduplication or durable state.
