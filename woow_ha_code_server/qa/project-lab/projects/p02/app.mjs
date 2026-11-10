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
  id: 'p02', title: 'JSON Structural Diff', category: 'Data comparison', version:'1.1.0',
  description: 'Compare nested JSON using escaped JSON Pointer paths and deterministic add, remove and replace operations.',
  example: {before: {count:1,tags:['old']}, after: {count:2,tags:['new'],active:true}},
  fields: [{key:'before',label:'Before JSON',type:'json'},{key:'after',label:'After JSON',type:'json'}]
};
const pointer = key => String(key).replace(/~/g, '~0').replace(/\//g, '~1');
const kind = value => value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
export function run(input) {
  validateInput(input);
  if (!own(input, 'before') || !own(input, 'after')) fail('before and after are required');
  const changes = [];
  function add(change) { changes.push(change); if (changes.length > 5000) fail('diff exceeds 5000 changes'); }
  function diff(a, b, path) {
    if (a === b) return;
    if (kind(a) !== kind(b) || !['object','array'].includes(kind(a))) { add({op:'replace',path,before:a,after:b}); return; }
    if (Array.isArray(a)) {
      const common = Math.min(a.length, b.length);
      for (let i = 0; i < common; i++) diff(a[i], b[i], `${path}/${i}`);
      for (let i = a.length - 1; i >= common; i--) add({op:'remove',path:`${path}/${i}`,before:a[i]});
      for (let i = common; i < b.length; i++) add({op:'add',path:`${path}/${i}`,after:b[i]});
    } else {
      for (const key of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort()) {
        const next = `${path}/${pointer(key)}`;
        if (!own(a,key)) add({op:'add',path:next,after:b[key]});
        else if (!own(b,key)) add({op:'remove',path:next,before:a[key]});
        else diff(a[key],b[key],next);
      }
    }
  }
  diff(input.before, input.after, '');
  return {equal: changes.length === 0, added: changes.filter(c => c.op === 'add').length,
    removed: changes.filter(c => c.op === 'remove').length, replaced: changes.filter(c => c.op === 'replace').length, changes};
}
