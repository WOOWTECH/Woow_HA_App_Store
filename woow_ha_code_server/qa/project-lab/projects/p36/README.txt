Accessibility contrast checker

Purpose: Compute opaque sRGB contrast ratios and common accessibility threshold
comparisons. Input: {"foreground":"#777777","background":"#FFFFFF"}
Both colors must be 3- or 6-digit hexadecimal strings, with optional #.
Case is ignored. Color names, alpha channels, surrounding spaces, and CSS
functions are rejected. Output colors are expanded uppercase #RRGGBB.

For each channel c in [0,1], linearize as c/12.92 if c<=0.04045, otherwise
((c+0.055)/1.055)^2.4. Relative luminance is 0.2126R+0.7152G+0.0722B.
Contrast = (lighter luminance + 0.05)/(darker luminance + 0.05).

passes compares the UNROUNDED ratio against:
- aaNormal: 4.5; aaaNormal: 7
- aaLarge: 3; aaaLarge: 4.5; nonText: 3
Large text convention is at least 18 pt regular or 14 pt bold. The application
reports both categories; it does not infer font sizes from a rendered page.
Luminances display six decimals and the ratio two. preferredTextOnBackground
selects whichever of black/white yields greater contrast, with black on ties.

Worked examples: #000 on #fff has ratio 21 and passes every listed threshold.
#ff0000 on white has ratio about 4 (displayed), passing large AA and non-text
but failing normal AA. #777777 on white displays 4.48 and fails normal AA.

Limitations: No transparency, gradients, images, text size inspection, or screen
rendering analysis. A contrast comparison is not full accessibility certification.

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
Container: podman build -t p36 .; podman run --rm -p 127.0.0.1:8080:8080 p36
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"foreground":"#00f","background":"#fff"}
Expected highlights: contrastRatio 8.59; all reported thresholds pass.
Supported limitation: opaque hex colors only; alpha blending is not modeled.
