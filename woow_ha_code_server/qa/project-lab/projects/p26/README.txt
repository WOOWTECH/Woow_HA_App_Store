Dependency Graph Planner

Purpose: Schedule a supplied directed dependency graph and explain cycles.
Run: node test.mjs. API: run(meta.example) from ./app.mjs.

Fields: nodes is an array of up to 200 unique names (1–64 characters, initial
letter/digit followed by letters/digits/dot/dash/underscore). edges is an array of
up to 5000 unique [prerequisite,dependent] pairs using declared nodes.
Duplicate nodes/edges and unknown endpoints throw errors. An empty graph is valid.

Worked example: build -> lint, build -> test, lint -> deploy, test -> deploy
produces levels [["build"],["lint","test"],["deploy"]] and flattened order
["build","lint","test","deploy"]. Each level can run after all earlier levels
finish; names within a level sort lexically for reproducibility.

On a cycle, acyclic=false. order/levels contain the independently runnable prefix;
blocked contains all remaining names, including downstream dependents. cycle is
one deterministic directed cycle with the starting name repeated at its end.
For a -> b -> a plus an independent c, c is runnable and cycle=["a","b","a"].
Self-loops are reported as ["a","a"]. No cycle yields cycle=[].

Limitations: prerequisite relations only; no durations, resource capacities,
filesystem scanning or task execution. The returned order is grouped by level,
not a globally lexicographically minimal topological ordering.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p26 .; podman run --rm -p 127.0.0.1:8080:8080 p26
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: cycle blocks downstream but independent node runs.
Input: {"nodes":["a","b","c","d"],"edges":[["a","b"],["b","a"],["b","d"]]}
Expected output: {"acyclic":false,"order":["c"],"levels":[["c"]],"blocked":["a","b","d"],"cycle":["a","b","a"]}
Supported limitation: Prerequisite ordering only; no durations or resource capacities.
