Deterministic Pairwise Test Generator

Purpose: Generate a reproducible test suite covering every pair of factor values.
Run: node test.mjs. API: run(meta.example) from ./app.mjs.

Fields: factors is an ordered array of 2–8 {name,values} objects. Names are unique,
up to 40 letters/digits/underscores starting with a letter; unsafe property names
reject. values contains 1–8 unique JSON scalars: null, boolean, finite number or
string up to 80 characters. Number 1 and string "1" are distinct. maxCases is an
optional integer 1–256, default 256. Unknown fields reject.
The full Cartesian space may not exceed 4096 combinations. Candidate order follows
factor order, then value order, with the last factor varying fastest. Greedily
choose the candidate covering the most uncovered pairs; first candidate wins ties.
If maxCases cannot achieve full coverage, throw an error rather than return an
incomplete suite.

Worked example: A,B,C each have [0,1]. Eight Cartesian combinations contain twelve
cross-factor value pairs. The deterministic suite is 000, 011, 101, 110: four
cases cover all twelve pairs. Two binary factors require all four combinations.
Output: factorOrder, cartesianCount, totalPairs, coveredPairs, testCount and cases
with a 1-based case number and a named values object. Each suite is complete and
repeatable for identical ordered inputs.

Limitations: independent factors only, no exclusions/constraints. Pairwise coverage
does not guarantee coverage of three-way interactions, and greedy selection does
not guarantee the smallest possible suite. All work is local and dependency-free.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p30 .; podman run --rm -p 127.0.0.1:8080:8080 p30
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: two factors require full Cartesian product.
Input: {"factors":[{"name":"browser","values":["a","b"]},{"name":"mode","values":["x","y"]}]}
Expected output: {"factorOrder":["browser","mode"],"cartesianCount":4,"totalPairs":4,"coveredPairs":4,"testCount":4,"cases":[{"case":1,"values":{"browser":"a","mode":"x"}},{"case":2,"values":{"browser":"a","mode":"y"}},{"case":3,"values":{"browser":"b","mode":"x"}},{"case":4,"values":{"browser":"b","mode":"y"}}]}
Supported limitation: Independent factors only; pairwise coverage does not cover all three-way interactions.
