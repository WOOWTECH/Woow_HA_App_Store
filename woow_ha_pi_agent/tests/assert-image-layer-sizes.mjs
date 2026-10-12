#!/usr/bin/env node

// Reject images with an OCI layer larger than the transport-safe budget.
// Elmohome's Docker pull repeatedly ended with unexpected EOF on the 377 MiB
// CLI layer; two layers at 215 MiB and 156 MiB completed the local sizing test.
const maxBytes = Number(process.env.PI_MAX_LAYER_BYTES ?? 256 * 1024 * 1024);
const baselinePath = process.argv[2];
if (!baselinePath) {
  console.error("usage: assert-image-layer-sizes.mjs <baseline-manifest.json> < current-manifest.json");
  process.exit(2);
}
let input = "";
for await (const chunk of process.stdin) input += chunk;

let manifest;
let baseline;
try {
  manifest = JSON.parse(input);
  baseline = JSON.parse(await (await import("node:fs/promises")).readFile(baselinePath, "utf8"));
} catch (error) {
  console.error(`invalid image manifest or baseline: ${error.message}`);
  process.exit(2);
}

if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) {
  console.error(`invalid PI_MAX_LAYER_BYTES: ${process.env.PI_MAX_LAYER_BYTES}`);
  process.exit(2);
}

if (!Array.isArray(manifest.layers) || manifest.layers.length === 0 || !Array.isArray(baseline.layers)) {
  console.error("expected a single-platform OCI/Docker image manifest with layers");
  process.exit(2);
}

const baselineDigests = new Set(baseline.layers.map((layer) => layer.digest));
const changedLayers = manifest.layers
  .map((layer, index) => ({ index, digest: layer.digest, size: layer.size }))
  .filter((layer) => !baselineDigests.has(layer.digest));
const oversized = changedLayers.filter((layer) => !Number.isSafeInteger(layer.size) || layer.size > maxBytes);

const largest = changedLayers.reduce((size, layer) => Math.max(size, layer.size ?? 0), 0);
console.log(`${changedLayers.length} new/changed layers; largest ${(largest / 1048576).toFixed(1)} MiB; limit ${(maxBytes / 1048576).toFixed(1)} MiB`);

if (changedLayers.length === 0) {
  console.error("image introduced no new layer digests; verify the version and baseline tags");
  process.exit(2);
}

if (oversized.length > 0) {
  for (const layer of oversized) {
    console.error(`layer ${layer.index} ${layer.digest ?? "<unknown>"} is ${Number.isFinite(layer.size) ? `${(layer.size / 1048576).toFixed(1)} MiB` : "missing a valid size"}`);
  }
  process.exit(1);
}
