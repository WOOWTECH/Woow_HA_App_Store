import {createHash, createHmac} from 'node:crypto';
const MAX_NODES = 30000;
function fail(message) { throw new Error(message); }
function object(value, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) fail(`${label} must be an object`);
  const proto = Object.getPrototypeOf(value);
  if (proto !== Object.prototype && proto !== null) fail(`${label} must be a plain JSON object`);
  return value;
}
function string(value, label, max = 200000, min = 0) {
  if (typeof value !== 'string' || value.length < min || value.length > max) fail(`${label} must be a string of ${min}–${max} characters`);
  return value;
}
function list(value, label, max = 5000, min = 0) {
  if (!Array.isArray(value) || value.length < min || value.length > max) fail(`${label} must be an array with ${min}–${max} items`);
  return value;
}
function finite(value, label, min = -Number.MAX_VALUE, max = Number.MAX_VALUE) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) fail(`${label} must be a finite number between ${min} and ${max}`);
  return value;
}
function integer(value, label, min, max) {
  finite(value, label, min, max);
  if (!Number.isInteger(value)) fail(`${label} must be an integer`);
  return value;
}
function choice(value, label, choices) {
  if (!choices.includes(value)) fail(`${label} must be one of: ${choices.join(', ')}`);
  return value;
}
function boolean(value, label) {
  if (typeof value !== 'boolean') fail(`${label} must be boolean`);
  return value;
}
function scalar(value, label) {
  if (value !== null && !['string', 'number', 'boolean'].includes(typeof value)) fail(`${label} must be a scalar or null`);
  return value;
}
function validateInput(input) {
  object(input, 'input');
  let nodes = 0, size = 0;
  const active = new WeakSet();
  function visit(value, depth) {
    if (++nodes > MAX_NODES || depth > 32) fail('input exceeds 30000 nodes or 32 nesting levels');
    if (typeof value === 'string') { size += value.length; if (value.length > 200000) fail('a string exceeds 200000 characters'); }
    else if (typeof value === 'number') finite(value, 'JSON number');
    else if (value !== null && typeof value === 'object') {
      if (active.has(value)) fail('input must not contain cycles');
      active.add(value);
      if (!Array.isArray(value)) object(value, 'JSON value');
      for (const [key, child] of Object.entries(value)) { size += key.length; visit(child, depth + 1); }
      active.delete(value);
    } else if (value !== null && typeof value !== 'boolean') fail('input must contain only JSON values');
    if (size > 1000000) fail('input exceeds 1000000 characters');
  }
  visit(input, 0);
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function round(value) {
  if (!Number.isFinite(value)) fail('calculation exceeded finite numeric range');
  const rounded = Number(value.toFixed(6));
  return rounded === 0 ? 0 : rounded;
}
const own = (value, key) => Object.hasOwn(value, key);

export const meta = {
  id:'p05',title:'Deterministic Data Masking',category:'Data privacy demos',version:'1.1.0',
  description:'Apply repeatable SHA-256 tokens, partial redaction, or email display masks to selected synthetic record fields.',
  example:{records:[{name:'Ava',email:'ava@example.test',phone:'5551234'},{name:'Ava',email:'ava@example.test',phone:'5559876'}],rules:[{field:'name',mode:'token'},{field:'email',mode:'email'},{field:'phone',mode:'redact',keepLast:2}]},
  fields:[{key:'records',label:'Synthetic records',type:'json'},{key:'rules',label:'Masking rules',type:'json'},{key:'salt',label:'Optional deterministic salt',type:'text'}]
};
export function run(input) {
  validateInput(input);
  const records = list(input.records,'records',2000);
  const salt = string(input.salt ?? '', 'salt',128);
  const rules = list(input.rules,'rules',30,1).map((rule,i)=>{
    object(rule,`rules[${i}]`);
    const field = string(rule.field,'rule field',100,1);
    const mode = choice(rule.mode,'rule mode',['token','redact','email']);
    if (own(rule,'keepLast') && mode !== 'redact') fail('keepLast is only supported for redact rules');
    const keepLast = integer(rule.keepLast ?? 0,'keepLast',0,16);
    return {field,mode,keepLast};
  });
  if (new Set(rules.map(r=>r.field)).size !== rules.length) fail('rule fields must be unique');
  let maskedCells = 0;
  const masked = records.map((record,i)=>{
    object(record,`records[${i}]`);
    const fields = new Map(Object.entries(structuredClone(record)));
    for (const rule of rules) {
      if (!fields.has(rule.field) || fields.get(rule.field) === null) continue;
      const raw = fields.get(rule.field);
      if (!['string','number','boolean'].includes(typeof raw)) fail(`records[${i}].${rule.field} must be a string, number, boolean or null`);
      const text = String(raw);
      let value;
      if (rule.mode === 'token') {
        const digest = salt ? createHmac('sha256',salt).update(text).digest('hex') : createHash('sha256').update(text).digest('hex');
        value = 'tok_' + digest.slice(0,12);
      } else if (rule.mode === 'email') {
        if (typeof raw !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw)) fail(`records[${i}].${rule.field} must contain an email address`);
        const [local,domain] = raw.split('@');
        value = [...local][0] + '***@' + domain.toLowerCase();
      } else {
        const chars = [...text], keep = Math.min(rule.keepLast,Math.max(0,chars.length-1));
        value = '*'.repeat(chars.length-keep) + (keep ? chars.slice(-keep).join('') : '');
      }
      fields.set(rule.field,value); maskedCells++;
    }
    return Object.fromEntries(fields);
  });
  return {records:masked,maskedCells};
}
