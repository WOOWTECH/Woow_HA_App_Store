Deployment manifest policy checker (synthetic configuration)

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator supplies HTTP runtime and interactive page.

Input is simplified JSON, not Kubernetes YAML:
deployment {name,replicas,strategy:{maxUnavailable},containers:[...]}.
Each container has name, image, resources:{requests,limits}, security and
optional ports. Requests and limits each require integer cpuMilli and
memoryMiB (0-1000000). Security requires booleans runAsNonRoot, privileged,
readOnlyRootFilesystem. Image needs an explicit registry/repository plus
tag or sha256 digest. Names use lowercase letters, digits and hyphens.
Bounds: 0-100 replicas, 1-20 containers, 0-20 unique ports in 1-65535.

Optional policy: minReplicas (default 2); maxTotalCpuMilli (8000);
maxTotalMemoryMiB (16384); requireDigest (true); requireReadOnlyRoot (true);
allowedRegistries (default ["registry.example.invalid"], 1-20 unique hosts).
Budgets count per-container LIMITS multiplied by replicas. A pinned digest,
approved registry, non-root execution, no privilege, positive requests,
limits covering requests and a rollout preserving a replica are required.
latest is always forbidden, even when requireDigest is false.

Malformed schema throws Error. Valid but insecure configurations return
compliant:false and all deterministic findings with code/path/message.
Output also reports requested and limit totals across all replicas.

Worked example: two replicas with requests 100m CPU/64MiB and limits
500m CPU/128MiB yield totals 200m/128MiB requested, 1000m/256MiB limits.
The meta.example pinned image and security settings pass default policy.

Limitations: no YAML parsing, Kubernetes API, image inspection, cluster
access, deployment, or production certification. Checks synthetic supplied
configuration only. Unmodeled fields are ignored.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p50 .; podman run --rm -p 127.0.0.1:8080:8080 p50
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"deployment":{"name":"review","replicas":2,"strategy":{"maxUnavailable":0},"containers":[{"name":"web","image":"registry.example.invalid/review:v1","resources":{"requests":{"cpuMilli":50,"memoryMiB":32},"limits":{"cpuMilli":100,"memoryMiB":64}},"security":{"runAsNonRoot":true,"privileged":false,"readOnlyRootFilesystem":true}}]},"policy":{"requireDigest":false}}
Expected highlights: compliant true, requested CPU 100/memory 64, limit CPU 200/memory 128.
Supported limitation: simplified supplied JSON only; no image inspection or deployment.
