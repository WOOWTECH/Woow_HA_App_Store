export const meta = {
  id: 'p49', title: 'Redaction-safe structured audit report', category: 'Audit',
  description: 'Summarize synthetic audit events with actor aliases and fully masked detail values.',
  version: '1.1.0',
  example: { events: [
    { at: '2024-01-01T00:00:00Z', actor: 'operator-a', action: 'create', resource: 'record', outcome: 'success',
      details: { email: 'sample-address', changes: [{ field: 'tier', before: 'basic', after: 'plus' }] } },
    { at: '2024-01-01T00:01:00Z', actor: 'operator-a', action: 'update', resource: 'policy', outcome: 'denied',
      details: { reason: 'synthetic policy denial' } }
  ] }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const actions = ['create', 'read', 'update', 'delete', 'login', 'deploy'];
const resources = ['record', 'account', 'service', 'file', 'policy'];
const outcomes = ['success', 'failure', 'denied'];
const safeKeys = new Set(['before', 'after', 'changes', 'count', 'enabled', 'reason', 'metadata', 'field', 'email', 'token', 'password', 'secret', 'authorization', 'apiKey', 'value', 'items', 'status']);
function check(ok, message) { if (!ok) throw new Error(message); }
function timestamp(value) {
  check(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value), 'at must be UTC YYYY-MM-DDTHH:mm:ssZ');
  const ms = Date.parse(value);
  check(Number.isFinite(ms) && new Date(ms).toISOString() === value.replace('Z', '.000Z'), 'at must be a real calendar date');
  return value;
}
export function run(input) {
  check(object(input) && Array.isArray(input.events) && input.events.length <= 200, 'Input requires events array of at most 200 entries');
  let nodes = 0;
  let totalRedacted = 0;
  function redact(value, depth) {
    nodes++;
    check(nodes <= 20000 && depth <= 8, 'details exceed node or nesting limits');
    if (value === null) return null;
    if (typeof value !== 'object') {
      check((typeof value === 'string' && value.length <= 2000) || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value)), 'details must contain bounded JSON scalar values');
      totalRedacted++;
      return '[REDACTED]';
    }
    if (Array.isArray(value)) {
      check(value.length <= 100, 'details arrays may contain at most 100 entries');
      return value.map(v => redact(v, depth + 1));
    }
    check(Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null, 'details must contain plain JSON objects');
    const entries = Object.entries(value);
    check(entries.length <= 100 && entries.every(([k]) => k.length <= 128), 'details object keys exceed limits');
    let unknown = 0;
    return Object.fromEntries(entries.map(([key, v]) => [safeKeys.has(key) ? key : 'field_' + (++unknown), redact(v, depth + 1)]));
  }
  const actorAliases = new Map(), actionCounts = new Map();
  const outcomeCounts = { success: 0, failure: 0, denied: 0 };
  const records = input.events.map((event, index) => {
    check(object(event), 'Each event must be an object');
    const at = timestamp(event.at);
    check(typeof event.actor === 'string' && event.actor.trim().length > 0 && event.actor.length <= 200, 'actor must contain 1-200 characters');
    check(actions.includes(event.action), 'Unsupported audit action');
    check(resources.includes(event.resource), 'Unsupported resource type');
    check(outcomes.includes(event.outcome), 'Unsupported audit outcome');
    const details = event.details ?? {};
    check(object(details), 'details must be an object');
    if (!actorAliases.has(event.actor)) actorAliases.set(event.actor, 'actor-' + (actorAliases.size + 1));
    actionCounts.set(event.action, (actionCounts.get(event.action) ?? 0) + 1);
    outcomeCounts[event.outcome]++;
    const before = totalRedacted;
    const sanitized = redact(details, 0);
    return { sequence: index + 1, at, actor: actorAliases.get(event.actor), action: event.action,
      resource: event.resource, outcome: event.outcome, details: sanitized, redactedValues: totalRedacted - before };
  });
  return { total: records.length, actors: actorAliases.size, redactedValues: totalRedacted, outcomes: outcomeCounts,
    actions: [...actionCounts.keys()].sort().map(action => ({ action, count: actionCounts.get(action) })), records };
}
