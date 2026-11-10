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

function timestamp(value, label = 'timestamp') {
  string(value,label,24,20);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(value)) fail(`${label} must be an ISO UTC timestamp ending in Z`);
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds) || new Date(milliseconds).toISOString().slice(0,19) !== value.slice(0,19)) fail(`${label} is not a valid UTC calendar timestamp`);
  return milliseconds;
}

export const meta = {
  id:'p06',title:'Log Severity and Timeline Analyzer',category:'Observability',version:'1.1.0',
  description:'Parse UTC log lines, normalize severity aliases, build time buckets, rank messages and report malformed lines.',
  example:{log:'2026-01-01T10:00:00Z INFO Started\n2026-01-01T10:05:00Z ERROR Timeout\n2026-01-01T11:00:00Z WARN Retrying',bucketMinutes:60},
  fields:[{key:'log',label:'UTC timestamp LEVEL message, one per line',type:'textarea'},{key:'bucketMinutes',label:'Bucket size in minutes',type:'number'}]
};
const levels = ['TRACE','DEBUG','INFO','WARN','ERROR','FATAL'];
const emptyCounts = () => Object.fromEntries(levels.map(level=>[level,0]));
export function run(input) {
  validateInput(input);
  const log = string(input.log,'log',200000);
  const bucketMinutes = integer(input.bucketMinutes ?? 60,'bucketMinutes',1,1440);
  const strict = boolean(input.strict ?? false,'strict');
  const rawLines = log.split(/\r?\n/);
  if (rawLines.length > 5000) fail('log exceeds 5000 lines');
  const severityCounts = emptyCounts(), rejected = [], buckets = new Map(), messages = new Map();
  let totalLines = 0, accepted = 0, first = Infinity, last = -Infinity;
  rawLines.forEach((raw,index)=>{
    if (!raw.trim()) return;
    totalLines++;
    try {
      const match = /^(\S+)\s+([A-Za-z]+)\s+(.+)$/.exec(raw.trim());
      if (!match) fail('expected timestamp LEVEL message');
      const time = timestamp(match[1]);
      let level = match[2].toUpperCase();
      if (level === 'WARNING') level = 'WARN';
      if (level === 'CRITICAL') level = 'FATAL';
      if (!levels.includes(level)) fail(`unsupported severity ${level}`);
      const message = match[3].trim();
      if (!message) fail('message must not be blank');
      accepted++; severityCounts[level]++;
      first = Math.min(first,time); last = Math.max(last,time);
      const bucket = Math.floor(time/(bucketMinutes*60000))*(bucketMinutes*60000);
      if (!buckets.has(bucket)) buckets.set(bucket,{start:new Date(bucket).toISOString(),total:0,counts:emptyCounts()});
      buckets.get(bucket).total++; buckets.get(bucket).counts[level]++;
      messages.set(message,(messages.get(message) ?? 0)+1);
    } catch (error) {
      if (strict) fail(`Line ${index+1}: ${error.message}`);
      rejected.push({line:index+1,reason:error.message});
    }
  });
  return {totalLines,accepted,rejected,severityCounts,first:accepted?new Date(first).toISOString():null,last:accepted?new Date(last).toISOString():null,
    buckets:[...buckets].sort((a,b)=>a[0]-b[0]).map(([,value])=>value),
    topMessages:[...messages].map(([message,count])=>({message,count})).sort((a,b)=>b.count-a.count || (a.message<b.message?-1:a.message>b.message?1:0)).slice(0,10)};
}
