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
  id:'p03',title:'Record Deduplication',category:'Data cleaning',version:'1.1.0',
  description:'Group records by normalized composite keys; retain first or last records, or fill missing values from duplicates.',
  example:{records:[{email:' Ava@example.test ',name:'Ava'},{email:'ava@example.test',phone:'1234'},{email:'bo@example.test',name:'Bo'}],keys:['email'],mode:'merge'},
  fields:[{key:'records',label:'Records',type:'json'},{key:'keys',label:'Key fields',type:'json'},{key:'mode',label:'Retention mode',type:'select',options:['first','last','merge']}]
};
export function run(input) {
  validateInput(input);
  const records = list(input.records,'records',5000);
  const keys = list(input.keys,'keys',10,1).map(k => string(k,'key',100,1));
  if (new Set(keys).size !== keys.length) fail('keys must be unique');
  const mode = choice(input.mode ?? 'first','mode',['first','last','merge']);
  const trim = boolean(input.trim ?? true,'trim');
  const caseSensitive = boolean(input.caseSensitive ?? false,'caseSensitive');
  const rejectDuplicates = own(input,'rejectDuplicates') ? boolean(input.rejectDuplicates,'rejectDuplicates') : false;
  const groups = new Map();
  records.forEach((record, index) => {
    object(record,`records[${index}]`);
    const key = JSON.stringify(keys.map(field => {
      if (!own(record,field)) fail(`records[${index}] is missing key ${field}`);
      let value = scalar(record[field],`records[${index}].${field}`);
      if (typeof value === 'string') { if (trim) value = value.trim(); if (!caseSensitive) value = value.toLowerCase(); }
      return value;
    }));
    if (!groups.has(key)) groups.set(key,{indices:[index],record:structuredClone(record)});
    else {
      const group = groups.get(key);
      if (rejectDuplicates) fail(`duplicate key ${key} at records[${group.indices[0]}] and records[${index}]`);
      group.indices.push(index);
      if (mode === 'last') group.record = structuredClone(record);
      if (mode === 'merge') {
        const fields = new Map(Object.entries(group.record));
        for (const [field,value] of Object.entries(record)) {
          if (!keys.includes(field) && (!fields.has(field) || fields.get(field) === null || fields.get(field) === '')) fields.set(field,structuredClone(value));
        }
        group.record = Object.fromEntries(fields);
      }
    }
  });
  const grouped = [...groups.values()];
  return {inputCount:records.length,uniqueCount:grouped.length,duplicatesRemoved:records.length-grouped.length,
    records:grouped.map(g=>g.record), duplicateGroups:grouped.flatMap((g,outputIndex)=>g.indices.length>1?[{indices:g.indices,outputIndex}]:[])};
}
