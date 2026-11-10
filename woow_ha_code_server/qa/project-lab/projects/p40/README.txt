Weighted decision matrix

Purpose: Compare alternatives using normalized cost/benefit criteria and
explicit weights. Explain each score with per-criterion contributions.

Input object:
- criteria: 1–20 objects with unique trimmed id (1–80 characters), finite
  weight 0–1000000, and direction "benefit" (higher better) or "cost" (lower).
  At least one weight must be positive. Zero-weight criteria are allowed.
- alternatives: 2–100 objects with unique trimmed name (1–80 characters) and
  values object containing exactly the criterion IDs. Each value must be a
  finite JSON number with magnitude <=1e12; negative values are allowed.

For each criterion, take the minimum and maximum across submitted alternatives.
Benefit score = (value-min)/(max-min); cost score = (max-value)/(max-min).
If all values are identical, each gets 1 for that criterion (no discrimination).
Normalize weights by their sum. Contribution = normalized value * normalized
weight * 100. Overall score sums unrounded contributions, then rounds to four
decimals. Displayed contributions also round to four and may not sum exactly.
Normalized weights display six decimals. This precision is display-only.

Rank by displayed score descending, preserving input order on ties. Ties share
competition ranks (1,1,3). winnerNames includes all alternatives ranked first.
criteria output includes the range used, allowing the normalization to be audited.

Worked example: price is cost, weight 3; battery is benefit, weight 2.
A: price 800, battery 8. B: price 1000, battery 12. C: price 900, battery 10.
Normalized weights are 0.6 and 0.4. A earns 60+0=60, C earns 30+20=50,
and B earns 0+40=40. Ranked order is A, C, B; winnerNames is ["A"].

Limitations: Min-max normalization is relative to the submitted alternatives,
so adding/removing an option can change rankings. Scores are a transparent
preference model, not an objective recommendation or certified decision process.

Running and integration:
From this project directory, run: node test.mjs
No installation, external dependencies, network, credentials, or persistent
storage are required. app.mjs exports meta and synchronous run(input).
The shared interactive UI, runtime.mjs, package.json, and HTTP server entry
are supplied by the coordinator under CONTRACT.txt; this batch owns only
app.mjs, cases.json, test.mjs, and this README.txt.

cases.json contains independent, manually derived complete expected outputs
and rejection fixtures. test.mjs checks them with node:assert/strict, verifies
useful errors, input immutability, JSON serialization and deterministic results,
and smoke-tests meta.example. A mismatch exits nonzero.

To call the standalone computation directly from this directory:
node --input-type=module -e 'import {meta,run} from "./app.mjs"; console.log(JSON.stringify(run(meta.example),null,2))'

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p40 .; podman run --rm -p 127.0.0.1:8080:8080 p40
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"criteria":[{"id":"cost","weight":1,"direction":"cost"}],"alternatives":[{"name":"Low","values":{"cost":2}},{"name":"High","values":{"cost":4}}]}
Expected highlights: Low scores 100, High scores 0; winnerNames ["Low"].
Supported limitation: normalization depends on the submitted alternatives.
