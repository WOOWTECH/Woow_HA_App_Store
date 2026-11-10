export const meta = {
  id: 'p48', title: 'Deterministic feature flag evaluator', category: 'Configuration',
  description: 'Evaluate kill switches, overrides, attribute rules and stable percentage rollouts.',
  version: '1.1.0',
  example: { flag: { key: 'demo', enabled: true, rolloutPercent: 50, allow: [], deny: [],
    rules: [{ id: 'beta-users', attribute: 'group', equals: 'beta', enabled: true }] },
    subject: { id: 'u1', attributes: { group: 'general' } } }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const identifier = x => typeof x === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(x);
const scalar = x => x === null || typeof x === 'boolean' || (typeof x === 'string' && x.length <= 200) || (typeof x === 'number' && Number.isFinite(x));
function check(ok, message) { if (!ok) throw new Error(message); }
function idList(value, name) {
  check(Array.isArray(value) && value.length <= 1000 && value.every(identifier) && new Set(value).size === value.length, name + ' must contain at most 1000 unique subject ids');
  return value;
}
export function run(input) {
  check(object(input) && object(input.flag) && object(input.subject), 'Input requires flag and subject objects');
  const { flag, subject } = input;
  check(identifier(flag.key) && identifier(subject.id), 'flag.key and subject.id must be 1-64 ASCII identifier characters');
  const enabled = flag.enabled ?? true;
  check(typeof enabled === 'boolean', 'flag.enabled must be boolean');
  const percent = flag.rolloutPercent ?? 0;
  check(typeof percent === 'number' && Number.isFinite(percent) && percent >= 0 && percent <= 100 && Math.abs(percent * 100 - Math.round(percent * 100)) < 1e-8, 'rolloutPercent must be 0-100 with at most two decimal places');
  const allow = idList(flag.allow ?? [], 'allow'), deny = idList(flag.deny ?? [], 'deny');
  const attributes = subject.attributes ?? {};
  check(object(attributes) && Object.keys(attributes).length <= 50 && Object.entries(attributes).every(([k, v]) => identifier(k) && scalar(v)), 'attributes must contain at most 50 scalar fields');
  const rules = flag.rules ?? [];
  check(Array.isArray(rules) && rules.length <= 50, 'rules must be an array of at most 50 entries');
  const ruleIds = new Set();
  for (const rule of rules) {
    check(object(rule) && identifier(rule.id) && identifier(rule.attribute) && Object.hasOwn(rule, 'equals') && scalar(rule.equals) && typeof rule.enabled === 'boolean', 'Each rule requires id, attribute, scalar equals, and boolean enabled');
    check(!ruleIds.has(rule.id), 'Duplicate rule id: ' + rule.id); ruleIds.add(rule.id);
  }
  // Transparent, stable noncryptographic polynomial hash. Colon is disallowed
  // inside identifiers, so the flag/subject separator is unambiguous.
  let bucket = 0;
  for (const ch of flag.key + ':' + subject.id) bucket = (bucket * 31 + ch.charCodeAt(0)) % 10000;
  const result = (enabled, reason, rule = null) => ({ flag: flag.key, subject: subject.id, enabled, reason, rule, bucket });
  if (!enabled) return result(false, 'disabled');
  if (deny.includes(subject.id)) return result(false, 'deny');
  if (allow.includes(subject.id)) return result(true, 'allow');
  for (const rule of rules) {
    if (Object.hasOwn(attributes, rule.attribute) && attributes[rule.attribute] === rule.equals) return result(rule.enabled, 'rule', rule.id);
  }
  return result(bucket < Math.round(percent * 100), 'rollout');
}
