Milestone Dependency Scheduling (p20)
Run: node test.mjs; import {meta, run} from ./app.mjs. The coordinator supplies
the shared main.mjs/runtime.mjs standalone HTTP interface.

Input: startDate (valid YYYY-MM-DD, years 2000..2099); optional holidays (0..366
unique dates, same format, default []); milestones (1..100), each with unique
id, durationDays (integer 1..365), optional dependsOn (0..99 unique known IDs,
default []). Dependencies must be acyclic. Unknown fields are rejected.
All milestones use one Monday-Friday calendar excluding holidays. Starts on
nonworking days move forward. Dependencies are finish-to-start: a successor
starts on the next workday after its last prerequisite finishes. Independent
milestones may run simultaneously. Ties in topological order use input order.
Forward/backward passes compute earliest starts and total slack. Critical means
zero slack relative to the earliest project finish. Offsets are zero-based
working-day indices; finishOffset is EXCLUSIVE. Displayed finishDate is the
INCLUSIVE last working date, so a one-day milestone starts and ends together.

Worked example, start Mon 2026-11-09: A=2d; B=3d after A; C=1d after A; D=1d
after B/C. A ends Nov10; B Nov13; C Nov11; D Nov16. Duration=6 working days;
A/B/D are critical; C has 2 days total slack. See meta.example for full input.

Limitations: durations are whole working days, resources are unlimited, no
lags, deadlines, partial days, custom workweeks or automatic updates. Output
can extend beyond 2099 for very long plans. This synthetic tool is not a
resource-leveled commitment. Hand-derived fixtures include graphs and calendars.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p20 .; podman run --rm -p 127.0.0.1:8080:8080 p20
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: diamond graph identifies shorter branch slack and weekend.
Input: {"startDate":"2026-11-09","milestones":[{"id":"A","durationDays":2,"dependsOn":[]},{"id":"B","durationDays":3,"dependsOn":["A"]},{"id":"C","durationDays":1,"dependsOn":["A"]},{"id":"D","durationDays":1,"dependsOn":["B","C"]}]}
Expected output: {"schedule":[{"id":"A","durationDays":2,"startOffset":0,"finishOffset":2,"startDate":"2026-11-09","finishDate":"2026-11-10","slackDays":0,"critical":true},{"id":"B","durationDays":3,"startOffset":2,"finishOffset":5,"startDate":"2026-11-11","finishDate":"2026-11-13","slackDays":0,"critical":true},{"id":"C","durationDays":1,"startOffset":2,"finishOffset":3,"startDate":"2026-11-11","finishDate":"2026-11-11","slackDays":2,"critical":false},{"id":"D","durationDays":1,"startOffset":5,"finishOffset":6,"startDate":"2026-11-16","finishDate":"2026-11-16","slackDays":0,"critical":true}],"projectDurationDays":6,"projectStartDate":"2026-11-09","projectFinishDate":"2026-11-16","criticalMilestones":["A","B","D"],"topologicalOrder":["A","B","C","D"]}
Supported limitation: Whole business days and unlimited resources; no resource leveling.
