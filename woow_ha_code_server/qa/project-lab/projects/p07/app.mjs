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
  id:'p07',title:'Time-Series Moving Averages and Anomalies',category:'Time series',version:'1.1.0',
  description:'Compute trailing averages and detect deviations against the preceding full window, including constant-baseline changes.',
  example:{points:[{time:'2026-01-01T00:00:00Z',value:10},{time:'2026-01-01T01:00:00Z',value:10},{time:'2026-01-01T02:00:00Z',value:10},{time:'2026-01-01T03:00:00Z',value:30}],window:3,threshold:3},
  fields:[{key:'points',label:'Chronological UTC points',type:'json'},{key:'window',label:'Window size',type:'number'},{key:'threshold',label:'Anomaly z-score threshold',type:'number'}]
};
function stats(values) {
  const origin = values[0];
  const mean = origin + values.reduce((sum,n)=>sum+(n-origin),0)/values.length;
  const std = Math.sqrt(values.reduce((sum,n)=>sum+(n-mean)**2,0)/values.length);
  return {mean,std};
}
export function run(input) {
  validateInput(input);
  const points = list(input.points,'points',5000,1);
  const window = integer(input.window ?? 3,'window',1,1000);
  const threshold = finite(input.threshold ?? 3,'threshold',0.01,1000);
  let previous = -Infinity, anomalyCount = 0;
  const values = [], output = [];
  points.forEach((point,i)=>{
    object(point,`points[${i}]`);
    const time = timestamp(point.time,`points[${i}].time`);
    if (time <= previous) fail(`points[${i}].time must be later than the previous timestamp`);
    previous = time;
    const value = finite(point.value,`points[${i}].value`,-1e12,1e12);
    let baselineMean = null, baselineStdDev = null, zScore = null, anomaly = false;
    if (values.length >= window) {
      const baseline = stats(values.slice(-window));
      baselineMean = round(baseline.mean); baselineStdDev = round(baseline.std);
      if (baseline.std === 0) { anomaly = value !== baseline.mean; zScore = anomaly ? null : 0; }
      else { const z = Math.abs(value-baseline.mean)/baseline.std; anomaly = z > threshold; zScore = round(z); }
    }
    values.push(value);
    if (anomaly) anomalyCount++;
    output.push({time:new Date(time).toISOString(),value,movingAverage:round(stats(values.slice(-window)).mean),baselineMean,baselineStdDev,zScore,anomaly});
  });
  return {window,threshold,anomalyCount,points:output};
}
