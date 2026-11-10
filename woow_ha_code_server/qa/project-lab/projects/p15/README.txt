Service Ticket Priority Triage (p15)
Run: node test.mjs. Import {meta, run} from ./app.mjs. The coordinator provides
the shared main.mjs/runtime.mjs HTTP interface.

Input: tickets (0..200) with unique id, impact (one/many/all), urgency
(low/normal/high), ageHours (integer 0..87600). Optional outage and
securityIncident are booleans, default false. Unknown fields are rejected.
Scoring: impact one/many/all = 10/30/50; urgency low/normal/high = 0/15/30;
outage adds 20; security incident adds 40. Scores >=80 are P1, >=50 P2,
>=25 P3, otherwise P4. Response targets are P1 1h, P2 4h, P3 24h, P4 72h.
Remaining time is signed. Exact target age is due; later is breached.
Sort by priority, remaining time ascending, score descending, then ID using
case-sensitive code-unit ordering. Reasons explain all score contributions.

Worked example: many + high = 60 -> P2; at age 5h, a 4h target is breached by
1h. all + high = 80 -> P1 and is placed ahead of it. A one/normal ticket with
outage and security flags scores 85. See meta.example for runnable input.

Limitations: illustrative policy, not an incident-response standard; priorities
require human review. Age is supplied, with no clocks, timers or external APIs.
This is not security diagnosis or a guarantee of service. Synthetic fixtures
have independently derived scores, queues, deadline boundaries and errors.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p15 .; podman run --rm -p 127.0.0.1:8080:8080 p15
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"tickets":[{"id":"T-101","impact":"one","urgency":"low","ageHours":0},{"id":"T-102","impact":"many","urgency":"high","ageHours":5},{"id":"T-103","impact":"all","urgency":"high","ageHours":0}]}
  output: {"queue":[{"id":"T-103","score":80,"priority":"P1","slaHours":1,"elapsedHours":0,"remainingHours":1,"slaState":"within_sla","reasons":["impact:all","urgency:high"]},{"id":"T-102","score":60,"priority":"P2","slaHours":4,"elapsedHours":5,"remainingHours":-1,"slaState":"breached","reasons":["impact:many","urgency:high"]},{"id":"T-101","score":10,"priority":"P4","slaHours":72,"elapsedHours":0,"remainingHours":72,"slaState":"within_sla","reasons":["impact:one","urgency:low"]}],"counts":{"P1":1,"P2":1,"P3":0,"P4":1},"breachedCount":1,"dueCount":0}
Supported limitation: Illustrative scoring policy with caller-supplied age; priorities need human review.
