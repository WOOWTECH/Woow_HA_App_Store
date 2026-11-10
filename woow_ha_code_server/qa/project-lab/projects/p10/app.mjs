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
  id:'p10',title:'Data Reconciliation by Key',category:'Data comparison',version:'1.1.0',
  description:'Reconcile two record sets by unique composite keys, with explicit missing values and optional numeric tolerance.',
  example:{left:[{id:'A',quantity:5},{id:'B',quantity:2}],right:[{id:'A',quantity:6},{id:'C',quantity:9}],keys:['id'],numericTolerance:0},
  fields:[{key:'left',label:'Left records',type:'json'},{key:'right',label:'Right records',type:'json'},{key:'keys',label:'Key fields',type:'json'},{key:'numericTolerance',label:'Absolute numeric tolerance',type:'number'}]
};
export function run(input) {
  validateInput(input);
  const left = list(input.left,'left',5000), right = list(input.right,'right',5000);
  const keys = list(input.keys,'keys',10,1).map(key=>string(key,'key',100,1));
  if (new Set(keys).size!==keys.length) fail('keys must be unique');
  const tolerance = finite(input.numericTolerance ?? 0,'numericTolerance',0,1e12);
  let fields = null;
  if (own(input,'fields')) {
    fields = list(input.fields,'fields',100,1).map(field=>string(field,'field',100,1));
    if (new Set(fields).size!==fields.length || fields.some(field=>keys.includes(field))) fail('comparison fields must be unique and exclude key fields');
    fields.sort();
  }
  function index(records,label) {
    const result = new Map();
    records.forEach((record,i)=>{
      object(record,`${label}[${i}]`);
      const values = keys.map(key=>{ if (!own(record,key)) fail(`${label}[${i}] missing key ${key}`); return scalar(record[key],`${label}[${i}].${key}`); });
      const signature = JSON.stringify(values);
      if (result.has(signature)) fail(`${label}[${i}] has a duplicate key`);
      result.set(signature,{record,key:Object.fromEntries(keys.map((key,j)=>[key,values[j]]))});
    });
    return result;
  }
  const lhs = index(left,'left'), rhs = index(right,'right');
  const changes = [], leftOnly = [], rightOnly = []; let matchedCount = 0, unchangedCount = 0;
  for (const [signature,{record:a,key}] of lhs) {
    if (!rhs.has(signature)) { leftOnly.push(structuredClone(a)); continue; }
    matchedCount++;
    const b = rhs.get(signature).record, differences = [];
    const compare = fields ?? [...new Set([...Object.keys(a),...Object.keys(b)])].filter(field=>!keys.includes(field)).sort();
    for (const field of compare) {
      const leftPresent = own(a,field), rightPresent = own(b,field);
      let equal = leftPresent===rightPresent;
      if (equal && leftPresent) {
        equal = typeof a[field]==='number' && typeof b[field]==='number'
          ? Math.abs(a[field]-b[field])<=tolerance : canonical(a[field])===canonical(b[field]);
      }
      if (!equal) {
        const difference = {field,leftPresent,rightPresent};
        if (leftPresent) difference.left = structuredClone(a[field]);
        if (rightPresent) difference.right = structuredClone(b[field]);
        differences.push(difference);
      }
    }
    if (differences.length) changes.push({key,differences}); else unchangedCount++;
  }
  for (const [signature,{record}] of rhs) if (!lhs.has(signature)) rightOnly.push(structuredClone(record));
  return {summary:{leftCount:left.length,rightCount:right.length,matchedCount,unchangedCount,changedCount:changes.length,leftOnlyCount:leftOnly.length,rightOnlyCount:rightOnly.length},changes,leftOnly,rightOnly};
}
