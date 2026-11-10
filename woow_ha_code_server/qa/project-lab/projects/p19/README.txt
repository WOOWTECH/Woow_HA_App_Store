Staff Coverage Matrix (p19)
Run: node test.mjs; import {meta, run} from ./app.mjs. The coordinator provides
the common main.mjs/runtime.mjs HTTP entry and UI.

Input: requirements (1..100) of {role,start,end,minimumStaff}; shifts (0..200)
of {staff,role,start,end}. Staff/role names are nonempty, max 80 chars.
minimumStaff is an integer 1..100. Times are same-day strict HH:MM; end alone
may be 24:00. Unknown fields and zero/reversed windows fail.
Overlapping requirements ADD demand. Shifts for the same staff must never
overlap, even across roles; adjacent shifts are allowed. Roles require exact
matching. Requirements and shifts define boundaries; each resulting demand
interval reports assigned people, required/available staff, shortage and surplus.
Intervals without demand are omitted; unrelated roles do not cover demand.
Rows sort by role then time; assigned names sort lexically. Summary uses
staff-minutes: interval minutes multiplied by required or missing staff.

Worked example: Support needs two people 09:00-11:00. Ada works both hours,
Ben starts 10:00. First hour is short one; second is covered. Required=240
staff-minutes; uncovered=60. meta.example is a complete runnable input.

Limitations: one local day/timezone, no credentials, skills, breaks, labor-rule
compliance or automatic shift optimization. Different names mean different
people. Synthetic planning data only; expected fixtures are hand-derived.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p19 .; podman run --rm -p 127.0.0.1:8080:8080 p19
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: shift extending outside demand is clipped.
Input: {"requirements":[{"role":"Desk","start":"09:00","end":"10:00","minimumStaff":1}],"shifts":[{"staff":"A","role":"Desk","start":"08:00","end":"11:00"}]}
Expected output: {"coverage":[{"role":"Desk","start":"09:00","end":"10:00","requiredStaff":1,"assignedStaff":["A"],"availableStaff":1,"shortfall":0,"surplus":0}],"covered":true,"totalRequiredStaffMinutes":60,"totalUncoveredStaffMinutes":0}
Supported limitation: Same-day intervals only; no labor-rule compliance or shift optimization.
