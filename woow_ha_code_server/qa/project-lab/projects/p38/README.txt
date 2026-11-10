Coordinate route distance estimator

Purpose: Sum shortest great-circle distances through ordered coordinates, with
an optional closing leg and an average-speed travel-time estimate.

Input object:
- points: 2–500 objects with finite numeric lat (-90..90) and lon (-180..180).
- unit: km (default) or mi; miles use exactly 1.609344 km per mile.
- closedLoop: boolean, default false; true adds last-to-first leg.
- speedKph: optional finite 0.1–2000 km/h, regardless of output distance unit.

Uses the haversine formula with mean spherical Earth radius 6371.0088 km.
Each leg has 1-based from/to point indexes and distance rounded to 0.001 units.
Total distance is summed BEFORE rounding, so rounded legs can differ slightly
from the displayed total. travelMinutes is null without speed; otherwise
round(total km / speedKph * 60, 1). No network or map service is used.

Worked example:
{"points":[{"lat":0,"lon":0},{"lat":0,"lon":1}],"speedKph":60}
One equatorial degree is pi*6371.0088/180 = 111.195 km (displayed), giving
111.2 minutes at 60 km/h. Closing the same route gives 222.390 km.
The short arc from longitude 179 to -179 on the equator is two degrees,
222.390 km. Coincident points have zero distance and antipodal points are valid.

Limitations: Straight great-circle estimates, not road/walking routes. Ignores
terrain, elevation, ellipsoid variation, traffic, stops, and speed changes.
Synthetic example coordinates describe a sample route, not navigation advice.

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
Container: podman build -t p38 .; podman run --rm -p 127.0.0.1:8080:8080 p38
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"points":[{"lat":0,"lon":0},{"lat":0,"lon":2}],"speedKph":120}
Expected highlights: totalDistance 222.39 km and travelMinutes 111.2.
Supported limitation: great-circle distance ignores roads, terrain and traffic.
