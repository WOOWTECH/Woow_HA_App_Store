export const meta = {
  id: 'p42', title: 'Webhook validator and router', category: 'Integration',
  description: 'Validate synthetic event payloads and preview every matching route without sending requests.',
  version: '1.1.0',
  example: {
    event: { id: 'evt-1', type: 'order.created', payload: { amount: 120, region: 'TW' } },
    schema: { required: ['amount', 'region'], properties: { amount: 'number', region: 'string' }, allowUnknown: false },
    routes: [
      { name: 'large-orders', eventType: 'order.created', conditions: [{ field: 'amount', op: 'gte', value: 100 }] },
      { name: 'taiwan', eventType: '*', conditions: [{ field: 'region', op: 'eq', value: 'TW' }] }
    ]
  }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const own = (o, k) => Object.hasOwn(o, k);
function check(ok, message) { if (!ok) throw new Error(message); }
function text(x) { return typeof x === 'string' && x.length > 0 && x.length <= 128; }
const types = ['string', 'number', 'integer', 'boolean', 'array', 'object', 'null'];
function isType(value, type) {
  if (type === 'integer') return Number.isSafeInteger(value);
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
  if (type === 'array') return Array.isArray(value);
  if (type === 'object') return object(value);
  if (type === 'null') return value === null;
  return typeof value === type;
}
function primitive(x) { return x === null || typeof x === 'string' || typeof x === 'boolean' || (typeof x === 'number' && Number.isFinite(x)); }

export function run(input) {
  check(object(input), 'Input must be an object');
  let encoded;
  try { encoded = JSON.stringify(input); } catch { throw new Error('Input must be JSON serializable'); }
  check(encoded.length <= 65536, 'Input exceeds 65536 characters');
  const { event, schema, routes } = input;
  check(object(event) && text(event.id) && text(event.type) && object(event.payload), 'event requires id, type and object payload');
  check(object(schema) && object(schema.properties), 'schema.properties must be an object');
  const properties = Object.entries(schema.properties);
  check(properties.length <= 100 && properties.every(([k, v]) => text(k) && types.includes(v)), 'schema properties require supported type names');
  const required = schema.required ?? [];
  check(Array.isArray(required) && required.length <= 100 && required.every(k => text(k) && own(schema.properties, k)) && new Set(required).size === required.length, 'required must contain unique declared properties');
  const allowUnknown = schema.allowUnknown ?? false;
  check(typeof allowUnknown === 'boolean', 'allowUnknown must be boolean');
  for (const key of required) check(own(event.payload, key), 'Missing required field: ' + key);
  for (const [key, value] of Object.entries(event.payload)) {
    check(own(schema.properties, key) || allowUnknown, 'Unknown payload field: ' + key);
    if (own(schema.properties, key)) check(isType(value, schema.properties[key]), 'Invalid type for payload field: ' + key);
  }
  check(Array.isArray(routes) && routes.length <= 50, 'routes must be an array of at most 50 routes');
  const names = new Set();
  const normalized = routes.map(route => {
    check(object(route) && text(route.name) && text(route.eventType), 'Each route needs name and eventType');
    check(!names.has(route.name), 'Duplicate route name: ' + route.name);
    names.add(route.name);
    const conditions = route.conditions ?? [];
    check(Array.isArray(conditions) && conditions.length <= 20, 'conditions must be an array of at most 20 predicates');
    for (const c of conditions) {
      check(object(c) && text(c.field) && ['eq', 'neq', 'exists', 'gt', 'gte', 'lt', 'lte', 'prefix'].includes(c.op), 'Invalid route condition');
      check(own(c, 'value') && primitive(c.value), 'Condition value must be a JSON scalar');
      if (c.op === 'exists') check(typeof c.value === 'boolean', 'exists requires a boolean value');
      if (['gt', 'gte', 'lt', 'lte'].includes(c.op)) check(typeof c.value === 'number' && Number.isFinite(c.value), 'Numeric comparison requires a finite number');
      if (c.op === 'prefix') check(typeof c.value === 'string', 'prefix requires a string');
    }
    return { ...route, conditions };
  });
  function matches(c) {
    const present = own(event.payload, c.field);
    if (c.op === 'exists') return present === c.value;
    if (!present) return false;
    const value = event.payload[c.field];
    if (c.op === 'eq') return value === c.value;
    if (c.op === 'neq') return value !== c.value;
    if (c.op === 'prefix') return typeof value === 'string' && value.startsWith(c.value);
    if (typeof value !== 'number' || !Number.isFinite(value)) return false;
    if (c.op === 'gt') return value > c.value;
    if (c.op === 'gte') return value >= c.value;
    if (c.op === 'lt') return value < c.value;
    return value <= c.value;
  }
  const matchedRoutes = normalized.filter(r => (r.eventType === '*' || r.eventType === event.type) && r.conditions.every(matches)).map(r => r.name);
  return { eventId: event.id, eventType: event.type, disposition: matchedRoutes.length ? 'routed' : 'unmatched', matchedRoutes, validatedFields: Object.keys(event.payload).sort() };
}
