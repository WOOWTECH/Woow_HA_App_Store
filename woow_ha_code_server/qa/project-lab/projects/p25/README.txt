JSON Configuration Merge Inspector

Purpose: Deep merge two JSON objects and explain conflicts. Run: node test.mjs.
API: run(meta.example) from ./app.mjs.

Fields: base and overlay are objects. strategy is overlay (default), base, or
error. Unknown fields are rejected. Objects recursively merge; arrays, null and
scalar values are atomic. Equal values are not conflicts, including equivalent
objects with different property order. No deletion marker is provided.

Worked example: base={"service":{"port":80,"host":"demo"}}, overlay=
{"service":{"port":81},"enabled":true} produces port=81, retains host and adds
enabled. conflicts includes {path:"/service/port",base:80,overlay:81,
resolution:"overlay"}; added contains "/enabled".
The base strategy retains conflicting base values but still adds new keys.
The error strategy throws at the first conflict, including its path. Paths use
JSON Pointer escaping (~ -> ~0 and / -> ~1). Added object subtrees are reported
once at their added root. Traversal uses sorted overlay keys. Inputs are unchanged.

Limits: 20 nesting levels, 10000 combined values, 1000 entries per array,
10000 characters per string, 200000 combined string/key characters, 128 per key.
Only finite JSON values are accepted; __proto__, constructor and prototype keys
are rejected at every depth. No schema validation, filesystem or external state.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p25 .; podman run --rm -p 127.0.0.1:8080:8080 p25
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: base policy preserves array and null conflicts.
Input: {"base":{"a":[1,2],"b":null},"overlay":{"a":[3],"b":{},"c":4},"strategy":"base"}
Expected output: {"merged":{"a":[1,2],"b":null,"c":4},"conflicts":[{"path":"/a","base":[1,2],"overlay":[3],"resolution":"base"},{"path":"/b","base":null,"overlay":{},"resolution":"base"}],"added":["/c"]}
Supported limitation: Arrays are treated as complete values rather than merged element by element.
