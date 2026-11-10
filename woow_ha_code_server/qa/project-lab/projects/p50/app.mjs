export const meta = {
  id: 'p50', title: 'Deployment manifest policy checker', category: 'Deployment',
  description: 'Check synthetic deployment configurations for resource, image and security policy violations.',
  version: '1.1.0',
  example: { deployment: { name: 'demo', replicas: 2, strategy: { maxUnavailable: 0 }, containers: [
    { name: 'web', image: 'registry.example.invalid/demo@sha256:' + 'a'.repeat(64),
      resources: { requests: { cpuMilli: 100, memoryMiB: 64 }, limits: { cpuMilli: 500, memoryMiB: 128 } },
      security: { runAsNonRoot: true, privileged: false, readOnlyRootFilesystem: true }, ports: [8080] }
  ] } }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const name = x => typeof x === 'string' && /^[a-z][a-z0-9-]{0,62}$/.test(x);
function check(ok, message) { if (!ok) throw new Error(message); }
function integer(value, label, min, max) {
  check(Number.isSafeInteger(value) && value >= min && value <= max, label + ' must be an integer from ' + min + ' to ' + max);
  return value;
}
export function run(input) {
  check(object(input) && object(input.deployment), 'Input requires deployment object');
  const deployment = input.deployment;
  check(name(deployment.name), 'deployment.name must be a lowercase identifier');
  const replicas = integer(deployment.replicas, 'replicas', 0, 100);
  check(object(deployment.strategy), 'strategy object is required');
  const unavailable = integer(deployment.strategy.maxUnavailable, 'maxUnavailable', 0, 100);
  check(Array.isArray(deployment.containers) && deployment.containers.length >= 1 && deployment.containers.length <= 20, 'containers must contain 1-20 entries');
  const policy = input.policy ?? {};
  check(object(policy), 'policy must be an object');
  const minReplicas = integer(policy.minReplicas ?? 2, 'minReplicas', 1, 100);
  const maxCpu = integer(policy.maxTotalCpuMilli ?? 8000, 'maxTotalCpuMilli', 1, 1000000000);
  const maxMemory = integer(policy.maxTotalMemoryMiB ?? 16384, 'maxTotalMemoryMiB', 1, 1000000000);
  const requireDigest = policy.requireDigest ?? true;
  const requireReadOnly = policy.requireReadOnlyRoot ?? true;
  check(typeof requireDigest === 'boolean' && typeof requireReadOnly === 'boolean', 'policy switches must be boolean');
  const registries = policy.allowedRegistries ?? ['registry.example.invalid'];
  check(Array.isArray(registries) && registries.length >= 1 && registries.length <= 20 && registries.every(r => typeof r === 'string' && r.length <= 253 && /^[a-z0-9][a-z0-9.-]*(?::[0-9]{1,5})?$/.test(r)) && new Set(registries).size === registries.length, 'allowedRegistries must contain 1-20 unique registry hosts');
  const names = new Set();
  const containers = deployment.containers.map(c => {
    check(object(c) && name(c.name), 'Each container needs a lowercase name');
    check(!names.has(c.name), 'Duplicate container name: ' + c.name); names.add(c.name);
    check(typeof c.image === 'string' && c.image.length <= 512 && /^[a-z0-9][a-z0-9.-]*(?::[0-9]{1,5})?\/[a-z0-9][a-z0-9._-]*(?:\/[a-z0-9][a-z0-9._-]*)*(?::[A-Za-z0-9_][A-Za-z0-9_.-]*|@sha256:[a-fA-F0-9]{64})$/.test(c.image), 'image must contain an explicit registry, repository, and tag or SHA-256 digest');
    check(object(c.resources) && object(c.resources.requests) && object(c.resources.limits), 'resources requires requests and limits');
    for (const kind of ['requests', 'limits']) {
      integer(c.resources[kind].cpuMilli, kind + '.cpuMilli', 0, 1000000);
      integer(c.resources[kind].memoryMiB, kind + '.memoryMiB', 0, 1000000);
    }
    check(object(c.security) && ['runAsNonRoot', 'privileged', 'readOnlyRootFilesystem'].every(k => typeof c.security[k] === 'boolean'), 'security requires explicit boolean settings');
    const ports = c.ports ?? [];
    check(Array.isArray(ports) && ports.length <= 20 && ports.every(p => Number.isInteger(p) && p >= 1 && p <= 65535) && new Set(ports).size === ports.length, 'ports must contain unique integers from 1 to 65535');
    return c;
  });
  const findings = [];
  const add = (code, path, message) => findings.push({ severity: 'error', code, path, message });
  if (replicas < minReplicas) add('minimum-replicas', 'deployment.replicas', 'Replica count is below policy minimum');
  if (unavailable > 0 && unavailable >= replicas) add('availability', 'deployment.strategy.maxUnavailable', 'Rollout may make every replica unavailable');
  const totals = { requestedCpuMilli: 0, requestedMemoryMiB: 0, limitCpuMilli: 0, limitMemoryMiB: 0 };
  containers.forEach((c, i) => {
    const path = 'deployment.containers[' + i + ']';
    if (!registries.includes(c.image.split('/')[0])) add('registry', path + '.image', 'Image registry is not allowed');
    if (requireDigest && !/@sha256:[a-fA-F0-9]{64}$/.test(c.image)) add('image-digest', path + '.image', 'Image must be pinned to a SHA-256 digest');
    if (/:latest$/i.test(c.image)) add('image-latest', path + '.image', 'Mutable latest tag is forbidden');
    if (!c.security.runAsNonRoot) add('nonroot', path + '.security.runAsNonRoot', 'Container must run as non-root');
    if (c.security.privileged) add('privileged', path + '.security.privileged', 'Privileged containers are forbidden');
    if (requireReadOnly && !c.security.readOnlyRootFilesystem) add('readonly', path + '.security.readOnlyRootFilesystem', 'Root filesystem must be read-only');
    const { requests, limits } = c.resources;
    if (requests.cpuMilli <= 0 || requests.memoryMiB <= 0) add('requests-positive', path + '.resources.requests', 'CPU and memory requests must be positive');
    if (limits.cpuMilli < requests.cpuMilli || limits.memoryMiB < requests.memoryMiB) add('limits', path + '.resources.limits', 'Limits must cover requests');
    totals.requestedCpuMilli += requests.cpuMilli * replicas;
    totals.requestedMemoryMiB += requests.memoryMiB * replicas;
    totals.limitCpuMilli += limits.cpuMilli * replicas;
    totals.limitMemoryMiB += limits.memoryMiB * replicas;
  });
  if (totals.limitCpuMilli > maxCpu) add('cpu-budget', 'deployment.containers', 'Total CPU limits exceed policy budget');
  if (totals.limitMemoryMiB > maxMemory) add('memory-budget', 'deployment.containers', 'Total memory limits exceed policy budget');
  return { name: deployment.name, compliant: findings.length === 0, totals, findings };
}
