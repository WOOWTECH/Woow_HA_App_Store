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
  id:'p08',title:'Record Schema Validator',category:'Data quality',version:'1.1.0',
  description:'Validate required fields, primitive types, ranges, lengths, enums and email/date formats with per-record diagnostics.',
  example:{schema:{name:{type:'string',required:true,minLength:1},age:{type:'integer',min:0,max:120}},records:[{name:'Ava',age:30},{name:'',age:-2}],allowUnknown:false},
  fields:[{key:'schema',label:'Field rules',type:'json'},{key:'records',label:'Records',type:'json'}]
};
const typeMatches = (value,type) => type==='integer' ? Number.isInteger(value) : typeof value===type;
function validDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const ms = Date.parse(value+'T00:00:00Z');
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0,10)===value;
}
export function run(input) {
  validateInput(input);
  const schema = object(input.schema,'schema');
  const fields = Object.keys(schema).sort();
  if (!fields.length || fields.length>50) fail('schema must declare 1–50 fields');
  const records = list(input.records,'records',5000);
  const allowUnknown = boolean(input.allowUnknown ?? false,'allowUnknown');
  const allowedRules = ['type','required','nullable','min','max','minLength','maxLength','enum','format'];
  const rules = fields.map(field=>{
    string(field,'schema field',100,1);
    const rule = object(schema[field],`schema.${field}`);
    for (const key of Object.keys(rule)) if (!allowedRules.includes(key)) fail(`schema.${field} has unknown rule ${key}`);
    choice(rule.type,`schema.${field}.type`,['string','number','integer','boolean']);
    const required = boolean(rule.required ?? false,`schema.${field}.required`);
    const nullable = boolean(rule.nullable ?? false,`schema.${field}.nullable`);
    for (const bound of ['min','max']) if (own(rule,bound)) {
      if (!['number','integer'].includes(rule.type)) fail(`${bound} requires a numeric type`);
      finite(rule[bound],`schema.${field}.${bound}`);
    }
    if (own(rule,'min') && own(rule,'max') && rule.min>rule.max) fail(`schema.${field}: min cannot exceed max`);
    for (const bound of ['minLength','maxLength']) if (own(rule,bound)) {
      if (rule.type!=='string') fail(`${bound} requires a string type`);
      integer(rule[bound],`schema.${field}.${bound}`,0,200000);
    }
    if (own(rule,'minLength') && own(rule,'maxLength') && rule.minLength>rule.maxLength) fail(`schema.${field}: minLength cannot exceed maxLength`);
    if (own(rule,'format')) { if (rule.type!=='string') fail('format requires a string type'); choice(rule.format,'format',['email','date']); }
    if (own(rule,'enum')) {
      list(rule.enum,`schema.${field}.enum`,50,1);
      for (const value of rule.enum) if (!(value===null && nullable) && !typeMatches(value,rule.type)) fail(`schema.${field}.enum values must match the declared type`);
      if (new Set(rule.enum.map(canonical)).size !== rule.enum.length) fail(`schema.${field}.enum must contain unique values`);
    }
    return {field,...rule,required,nullable};
  });
  const results = records.map((record,index)=>{
    const errors = [], error = (field,code,message)=>errors.push({field,code,message});
    if (record===null || typeof record!=='object' || Array.isArray(record)) error('$','type','must be an object');
    else {
      for (const rule of rules) {
        const {field} = rule;
        if (!own(record,field)) { if (rule.required) error(field,'required','is required'); continue; }
        const value = record[field];
        if (value===null && rule.nullable) {
          if (own(rule,'enum') && !rule.enum.includes(null)) error(field,'enum','must be one of the allowed values');
          continue;
        }
        if (!typeMatches(value,rule.type)) { error(field,'type',`must be ${rule.type}`); continue; }
        if (own(rule,'enum') && !rule.enum.includes(value)) error(field,'enum','must be one of the allowed values');
        if (own(rule,'min') && value<rule.min) error(field,'min',`must be at least ${rule.min}`);
        if (own(rule,'max') && value>rule.max) error(field,'max',`must be at most ${rule.max}`);
        if (typeof value==='string') {
          const length = [...value].length;
          if (own(rule,'minLength') && length<rule.minLength) error(field,'minLength',`must contain at least ${rule.minLength} characters`);
          if (own(rule,'maxLength') && length>rule.maxLength) error(field,'maxLength',`must contain at most ${rule.maxLength} characters`);
          if (rule.format==='email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) error(field,'format','must be an email address');
          if (rule.format==='date' && !validDate(value)) error(field,'format','must be a valid YYYY-MM-DD date');
        }
      }
      if (!allowUnknown) for (const field of Object.keys(record).sort()) if (!own(schema,field)) error(field,'unknown','is not declared in schema');
    }
    return {index,valid:errors.length===0,errors};
  });
  const validCount = results.filter(r=>r.valid).length;
  return {valid:validCount===records.length,total:records.length,validCount,invalidCount:records.length-validCount,results};
}
