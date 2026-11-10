export const meta = {
  id: 'p29', title: 'Token Bucket Rate-Limit Simulator', category: 'Reliability', version: '1.1.0',
  description: 'Simulate timestamped token costs, refill, burst limits, and earliest retry delays using fixed-point arithmetic.',
  example: { capacity: 5, refillPerSecond: 2, requests: [{ atMs: 0, cost: 4 }, { atMs: 500, cost: 3 }, { atMs: 1000, cost: 3 }] },
  fields: [{ key: 'capacity', label: 'Bucket capacity', type: 'number' }, { key: 'refillPerSecond', label: 'Tokens refilled per second', type: 'number' }, { key: 'requests', label: 'Requests in time order', type: 'json' }]
};
function amount(value, label, allowZero = false) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < (allowZero ? 0 : 0.001) || value > 1000000 || Math.abs(value * 1000 - Math.round(value * 1000)) > 1e-6) throw new Error(`${label} must be ${allowZero ? '0' : '0.001'}–1000000 with at most three decimal places`);
  return Math.round(value * 1000) * 1000;
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['capacity', 'refillPerSecond', 'initialTokens', 'requests'].includes(k))) throw new Error('Input must contain supported token-bucket fields');
  const capacity = amount(input.capacity, 'capacity'), refill = amount(input.refillPerSecond, 'refillPerSecond', true) / 1000;
  let tokens = input.initialTokens === undefined ? capacity : amount(input.initialTokens, 'initialTokens', true);
  if (tokens > capacity) throw new Error('initialTokens cannot exceed capacity');
  if (!Array.isArray(input.requests) || input.requests.length > 1000) throw new Error('requests must be an array of at most 1000 events');
  const events = [];
  let lastTime = 0, accepted = 0;
  for (const request of input.requests) {
    if (!request || typeof request !== 'object' || Array.isArray(request) || Object.keys(request).some(k => !['atMs', 'cost'].includes(k))) throw new Error('Each request must contain atMs and cost');
    if (!Number.isInteger(request.atMs) || request.atMs < lastTime || request.atMs > 86400000) throw new Error('atMs must be nondecreasing integer milliseconds between 0 and 86400000');
    const cost = amount(request.cost, 'cost'), elapsed = request.atMs - lastTime;
    // Clamp before multiplying so even a long idle time never exceeds safe integer precision.
    if (refill > 0) tokens = elapsed >= (capacity - tokens) / refill ? capacity : tokens + elapsed * refill;
    const before = tokens, allowed = tokens >= cost;
    if (allowed) { tokens -= cost; accepted++; }
    const retryAfterMs = allowed ? 0 : cost > capacity || refill === 0 ? null : Math.ceil((cost - tokens) / refill);
    events.push({ atMs: request.atMs, cost: request.cost, accepted: allowed, tokensBefore: before / 1000000, tokensAfter: tokens / 1000000, retryAfterMs });
    lastTime = request.atMs;
  }
  return { accepted, rejected: events.length - accepted, finalTokens: tokens / 1000000, events };
}
