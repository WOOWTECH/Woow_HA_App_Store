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
  id: 'p01', title: 'CSV Profile and Anomaly Report', category: 'Data quality', version:'1.1.0',
  description: 'Parse quoted CSV, profile columns, detect blanks, mixed numeric values, duplicate rows and numeric outliers.',
  example: {csv: 'name,amount\nAva,10\nBo,20\nAva,10\nCy,', zScoreThreshold: 3, delimiter: ','},
  fields: [{key:'csv',label:'CSV including headers',type:'textarea'},{key:'delimiter',label:'Delimiter (default comma)',type:'text'},{key:'zScoreThreshold',label:'Outlier z-score threshold',type:'number'}]
};
function parseCSV(text, delimiter) {
  const rows = []; let row = [], cell = '', state = 'start';
  function field() { row.push(cell); cell = ''; state = 'start'; if (row.length > 100) fail('CSV exceeds 100 columns'); }
  function line() { field(); rows.push(row); row = []; if (rows.length > 5001) fail('CSV exceeds 5000 data rows'); }
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (state === 'quoted') {
      if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else state = 'closed'; }
      else cell += c;
    } else if (c === delimiter) field();
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; line(); }
    else if (state === 'closed') fail(`Unexpected character after closing quote at position ${i}`);
    else if (c === '"') { if (state !== 'start') fail(`Unexpected quote at position ${i}`); state = 'quoted'; }
    else { cell += c; state = 'plain'; }
  }
  if (state === 'quoted') fail('Unterminated quoted CSV field');
  if (text.length && (row.length || cell.length || state !== 'start')) line();
  return rows;
}
const numeric = text => /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text) && Number.isFinite(Number(text));
export function run(input) {
  validateInput(input);
  let csv = string(input.csv, 'csv', 200000, 1).replace(/^\uFEFF/, '');
  const delimiter = string(input.delimiter ?? ',', 'delimiter', 1, 1);
  if ('"\r\n'.includes(delimiter)) fail('delimiter cannot be a quote or newline');
  const threshold = finite(input.zScoreThreshold ?? 3, 'zScoreThreshold', 0.1, 20);
  const parsed = parseCSV(csv, delimiter);
  if (!parsed.length) fail('CSV requires a header');
  const headers = parsed.shift().map(v => v.trim());
  if (headers.some(v => !v) || new Set(headers).size !== headers.length) fail('CSV headers must be nonempty and unique');
  parsed.forEach((row, i) => { if (row.length !== headers.length) fail(`Data row ${i + 1} has ${row.length} cells; expected ${headers.length}`); });
  const columns = headers.map((name, column) => {
    const values = parsed.map(row => row[column].trim());
    const present = values.filter(v => v !== '');
    const numbers = present.filter(numeric).map(Number);
    const result = {name, present: present.length, missing: values.length - present.length, distinct: new Set(present).size,
      type: !present.length ? 'empty' : numbers.length === present.length ? 'number' : numbers.length ? 'mixed' : 'text', anomalies: []};
    let mean = 0, std = 0;
    if (numbers.length) {
      const scale = Math.max(...numbers.map(Math.abs));
      const scaledMean = scale ? numbers.reduce((s, n) => s + n / scale, 0) / numbers.length : 0;
      mean = scaledMean * scale;
      std = scale ? Math.sqrt(numbers.reduce((s,n) => s + (n / scale - scaledMean) ** 2, 0) / numbers.length) * scale : 0;
      finite(std, 'numeric standard deviation');
      result.numeric = {count: numbers.length, min: Math.min(...numbers), max: Math.max(...numbers), mean: round(mean)};
    }
    values.forEach((value, i) => {
      let kind;
      if (!value) kind = 'missing';
      else if (numbers.length && !numeric(value)) kind = 'nonNumeric';
      else if (numeric(value) && std > 0 && Math.abs(Number(value) / std - mean / std) > threshold) kind = 'outlier';
      if (kind) result.anomalies.push({row: i + 1, kind, value});
    });
    return result;
  });
  const seen = new Map(), duplicateRows = [];
  parsed.forEach((row, i) => { const key = JSON.stringify(row); if (seen.has(key)) duplicateRows.push({row: i + 1, firstRow: seen.get(key)}); else seen.set(key, i + 1); });
  return {rowCount: parsed.length, columnCount: headers.length, columns, duplicateRows};
}
