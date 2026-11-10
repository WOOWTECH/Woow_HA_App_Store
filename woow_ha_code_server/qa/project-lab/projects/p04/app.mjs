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
  id:'p04',title:'Pivot Table Aggregation',category:'Data analysis',version:'1.1.0',
  description:'Group records by one or more dimensions and calculate counts, sums, means, minima or maxima with grand totals.',
  example:{records:[{region:'East',sales:10},{region:'West',sales:8},{region:'East',sales:20}],groupBy:['region'],valueField:'sales',operation:'sum'},
  fields:[{key:'records',label:'Records',type:'json'},{key:'groupBy',label:'Grouping fields',type:'json'},{key:'valueField',label:'Numeric field',type:'text'},{key:'operation',label:'Aggregation',type:'select',options:['sum','mean','min','max','count']}]
};
export function run(input) {
  validateInput(input);
  const records = list(input.records,'records',5000);
  const groupBy = list(input.groupBy,'groupBy',4,1).map(k=>string(k,'groupBy field',100,1));
  if (new Set(groupBy).size !== groupBy.length) fail('groupBy fields must be unique');
  const operation = choice(input.operation ?? 'sum','operation',['sum','mean','min','max','count']);
  const valueField = operation === 'count' ? null : string(input.valueField,'valueField',100,1);
  const fresh = () => ({count:0,sum:0,min:Infinity,max:-Infinity});
  const total = fresh(), groups = new Map();
  function accumulate(acc, n) {
    acc.count++;
    if (operation === 'sum' || operation === 'mean') { acc.sum += n; if (!Number.isFinite(acc.sum)) fail('aggregate sum exceeds finite numeric range'); }
    if (operation !== 'count') { acc.min = Math.min(acc.min,n); acc.max = Math.max(acc.max,n); }
  }
  function value(acc) {
    if (operation === 'count') return acc.count;
    if (!acc.count) return operation === 'sum' ? 0 : null;
    return round(operation === 'sum' ? acc.sum : operation === 'mean' ? acc.sum/acc.count : acc[operation]);
  }
  records.forEach((record,i) => {
    object(record,`records[${i}]`);
    const dimensions = groupBy.map(field=>{ if (!own(record,field)) fail(`records[${i}] missing group field ${field}`); return scalar(record[field],`group field ${field}`); });
    const key = JSON.stringify(dimensions);
    const n = operation === 'count' ? 0 : finite(record[valueField],`records[${i}].${valueField}`);
    if (!groups.has(key)) groups.set(key,{key:Object.fromEntries(groupBy.map((field,j)=>[field,dimensions[j]])),acc:fresh()});
    accumulate(groups.get(key).acc,n); accumulate(total,n);
  });
  return {operation,groupBy,groups:[...groups.values()].map(g=>({key:g.key,count:g.acc.count,value:value(g.acc)})),totals:{count:total.count,value:value(total)}};
}
