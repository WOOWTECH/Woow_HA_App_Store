Kanban Transition Validator (p12)
Run: node test.mjs; import {meta, run} from ./app.mjs. The coordinator provides
the common main.mjs/runtime.mjs HTTP entry and editable UI.

Input: tasks (1..100) with unique id, status, optional dependencies (default []).
Dependencies must be unique known IDs and form an acyclic graph. transitions
(0..200) is an ordered list of {id,to}. IDs are nonempty strings, max 80 chars.
Allowed moves:
backlog -> ready; ready -> in_progress or backlog;
in_progress -> review or blocked; review -> done or in_progress;
blocked -> in_progress or backlog; done -> ready.
Every in_progress/review/done task requires all dependencies to be done.
This invariant is checked initially and after each move, including reopening.
No-op and skipped transitions are invalid. The whole request succeeds or throws;
input is never mutated. Results include normalized tasks, history and counts.

Worked example: A is done; B is ready and depends on A. B moves in_progress,
review, done. Both finish done; history has three entries. A cannot then reopen
while B remains done. meta.example contains a complete runnable sample.

Limitations: no users, permissions, storage, concurrency or external issue API.
Blocked tasks may wait on incomplete dependencies; ready means queued, not
necessarily startable. Synthetic workflow prototype, not process certification.
Cases have hand-derived expected boards, histories and rejection cases.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p12 .; podman run --rm -p 127.0.0.1:8080:8080 p12
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"tasks":[{"id":"DESIGN","status":"done"},{"id":"BUILD","status":"ready","dependencies":["DESIGN"]}],"transitions":[{"id":"BUILD","to":"in_progress"},{"id":"BUILD","to":"review"},{"id":"BUILD","to":"done"}]}
  output: {"tasks":[{"id":"DESIGN","status":"done","dependencies":[]},{"id":"BUILD","status":"done","dependencies":["DESIGN"]}],"history":[{"id":"BUILD","from":"ready","to":"in_progress"},{"id":"BUILD","from":"in_progress","to":"review"},{"id":"BUILD","from":"review","to":"done"}],"counts":{"backlog":0,"ready":0,"in_progress":0,"review":0,"done":2,"blocked":0}}
Supported limitation: No users, permissions, persistence or concurrency; ready means queued, not necessarily startable.
