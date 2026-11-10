Workflow DAG task executor simulation

Run tests: node test.mjs
Standalone API: import {run, meta} from './app.mjs'; run(meta.example).
The coordinator supplies main.mjs/runtime.mjs and the interactive HTTP UI.

Input: tasks (1-100), each with unique id, integer duration (1-100000),
optional deps (unique task ids), and outcome success/fail (default success).
concurrency is 1-16, default 2. Durations use arbitrary consistent time units.
The scheduler starts ready tasks in input order whenever workers free up.
Simultaneous completions are applied together. A failed dependency blocks all
descendants without running them; unrelated tasks continue. Cycles and missing
dependencies are rejected before execution. Input is not modified.

Worked example: a lasts 3, b lasts 2, c depends on both and lasts 4. With two
workers, a and b start at 0; c starts at 3 and finishes at 7. Output contains
makespan, status counts, and each task's status/start/end. Blocked tasks have
null times. meta.example additionally publishes after its build.

Limitations: synchronous deterministic simulation; no actual commands, wall
clock execution, retries, network, or persistence. Synthetic prototype.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p41 .; podman run --rm -p 127.0.0.1:8080:8080 p41
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"concurrency":1,"tasks":[{"id":"draft","duration":2},{"id":"review","duration":3,"deps":["draft"]}]}
Expected highlights: draft runs 0-2, review runs 2-5; makespan 5.
Supported limitation: durations simulate time; no tasks or commands actually execute.
