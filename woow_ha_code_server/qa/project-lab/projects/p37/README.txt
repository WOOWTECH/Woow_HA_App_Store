Color palette RGB/HSL transforms

Purpose: Convert hex colors to RGB/HSL, adjust HSL channels, and produce a
complementary color. All processing is local, with no dependencies.

Input object:
- color: required 3- or 6-digit hexadecimal string, optional #.
- hueShift: finite -3600..3600 degrees, default 0.
- saturationDelta: finite -100..100 percentage points, default 0.
- lightnessDelta: finite -100..100 percentage points, default 0.

Hue wraps modulo 360. Saturation and lightness clamp to 0..100. Complementary
color rotates the transformed hue by 180 degrees. Each of original,
transformed, and complementary contains hex, rgb [R,G,B], and hsl {h,s,l}.
RGB channels round to integer 0..255; reported HSL is recomputed from these
integer RGB channels and rounded to two decimals, so it describes actual
output colors. Achromatic output uses hue 0. HSL here is conventional sRGB
HSL, not a perceptually uniform color space.

Worked example: {"color":"#f00","hueShift":120}
Original: #FF0000, [255,0,0], HSL (0,100,50).
Transformed: #00FF00, [0,255,0], HSL (120,100,50).
Complementary: #FF00FF, [255,0,255], HSL (300,100,50).
Removing 100 saturation points from red produces #808080 with HSL (0,0,50.2).

Limitations: No alpha, color names, CSS parsing, gamut profiles, perceptual
lightness correction, or contrast guarantee. The original hue of a gray color
is undefined and represented as zero, so adding saturation uses that base hue.

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
Container: podman build -t p37 .; podman run --rm -p 127.0.0.1:8080:8080 p37
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"color":"#00f","hueShift":120}
Expected highlights: transformed #FF0000 and complementary #00FFFF.
Supported limitation: HSL rotation is not perceptually uniform or a contrast guarantee.
