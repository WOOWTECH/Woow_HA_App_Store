Dimension-aware unit converter

Purpose: Convert quantities only between compatible dimensions, including
affine temperature conversion with an absolute-zero check.

Input: {"value":60,"from":"mph","to":"km/h"}
value must be a JSON number, finite, with absolute value <=1e12. Unit names are
case-sensitive. Numeric strings are rejected.

Supported units:
- length: m, km, cm, mm, in, ft, yd, mi
- mass: kg, g, mg, lb, oz (avoirdupois)
- time: s, min, h, day (day = exactly 86400 seconds)
- volume: L, mL, m3, us_gal (US liquid gallon)
- speed: m/s, km/h, mph
- energy: J, kJ, Wh, kWh (factors 1, 1000, 3600, 3600000 joules)
- temperature: C, F, K (absolute temperatures, not temperature differences)

The output includes dimension, original value and units, and result rounded to
nine decimal places. Standard factors include 1 mi=1609.344 m,
1 lb=0.45359237 kg, and 1 US liquid gallon=3.785411784 L.

Worked examples: 60 mph = 96.56064 km/h; 32 F = 0 C; 100 C = 212 F.
-459.67 F = 0 K is accepted. Negative Kelvin and temperatures below -273.15 C
or -459.67 F are rejected. Converting m to kg rejects incompatible dimensions.

Limitations: No compound expression parsing or arbitrary units. Signed values
are supported for non-temperature quantities. Uses floating-point arithmetic;
very small results round to zero, and very large results can lose precision.
This is an educational converter, not a metrology certification tool.

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
Container: podman build -t p33 .; podman run --rm -p 127.0.0.1:8080:8080 p33
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: one kilowatt-hour in joules.
Input: {"value":1,"from":"kWh","to":"J"}
Expected output: {"dimension":"energy","value":1,"from":"kWh","to":"J","result":3600000}
Supported limitation: Case-sensitive listed units only; no compound expressions; floating-point results round to nine decimal places.
Hand derivation: 1 kWh = 1000 W * 3600 s = 3600000 J; 7200 J / 3600 J per Wh = 2 Wh. Energy-to-length conversion rejects incompatible dimensions.
