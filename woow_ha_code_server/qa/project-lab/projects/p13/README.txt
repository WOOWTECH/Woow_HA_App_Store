Meeting Slot Overlap Finder (p13)
Run: node test.mjs. Use import {meta, run} from ./app.mjs. Coordinator supplies
main.mjs/runtime.mjs and the shared interactive HTTP UI.

Input: durationMinutes (1..480), optional stepMinutes (1..180, default 15),
participants (1..30), each with unique name and availability (0..50 intervals).
Intervals are {start,end} in strict HH:MM, same day. End alone may be 24:00.
Overlapping/adjacent windows for one person are merged. Everyone's windows are
intersected. Candidate starts use multiples of stepMinutes from midnight;
a whole meeting must fit within a common window. Slots may overlap each other.
Empty availability means that person cannot attend. Short intersections are
reported even if no candidate meeting fits. Inputs remain unchanged.

Worked example: A is free 09:00-12:00, B 10:00-11:00. A 30-minute meeting on a
30-minute grid can run 10:00-10:30 or 10:30-11:00. Full sample: meta.example.

Limitations: one shared local day and timezone; no calendar integrations,
dates, travel buffers, overnight windows or daylight-saving conversion.
Tests use independently calculated expected windows and validation errors.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p13 .; podman run --rm -p 127.0.0.1:8080:8080 p13
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"durationMinutes":30,"stepMinutes":30,"participants":[{"name":"Ada","availability":[{"start":"09:00","end":"12:00"}]},{"name":"Ben","availability":[{"start":"10:00","end":"11:00"}]}]}
  output: {"commonWindows":[{"start":"10:00","end":"11:00","durationMinutes":60}],"slots":[{"start":"10:00","end":"10:30"},{"start":"10:30","end":"11:00"}],"slotCount":2}
Supported limitation: One shared local day; no dates, time zones, overnight windows or calendar integrations.
