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
  id:'p09',title:'Text Keyword Frequencies',category:'Text analysis',version:'1.1.0',
  description:'Count Unicode words or contiguous phrases with stop words, minimum lengths, deterministic rankings and percentages.',
  example:{text:'Blue sky, blue sea. Sky!',stopWords:[],ngramSize:1,top:10},
  fields:[{key:'text',label:'Text to analyze',type:'textarea'},{key:'stopWords',label:'Stop words',type:'json'},{key:'ngramSize',label:'Words per phrase (1–3)',type:'number'},{key:'top',label:'Maximum results',type:'number'}]
};
const wordPattern = /[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu;
export function run(input) {
  validateInput(input);
  const text = string(input.text,'text',200000);
  const caseSensitive = boolean(input.caseSensitive ?? false,'caseSensitive');
  const minLength = integer(input.minLength ?? 1,'minLength',1,50);
  const ngramSize = integer(input.ngramSize ?? 1,'ngramSize',1,3);
  const top = integer(input.top ?? 10,'top',1,100);
  const normalize = value => { const normalized = value.normalize('NFKC').replace(/’/g,"'"); return caseSensitive?normalized:normalized.toLowerCase(); };
  const stopWords = new Set(list(input.stopWords ?? [],'stopWords',2000).map((word,i)=>{
    const normalized = normalize(string(word,`stopWords[${i}]`,100,1));
    if (!/^[\p{L}\p{N}]+(?:'[\p{L}\p{N}]+)*$/u.test(normalized)) fail(`stopWords[${i}] must be a single word`);
    return normalized;
  }));
  const tokens = normalize(text).match(wordPattern) ?? [];
  if (tokens.length>30000) fail('text exceeds 30000 tokens');
  const counts = new Map(); let matchedTerms = 0;
  for (let i=0;i<=tokens.length-ngramSize;i++) {
    const words = tokens.slice(i,i+ngramSize);
    if (words.some(word=>stopWords.has(word) || [...word].length<minLength)) continue;
    const term = words.join(' '); counts.set(term,(counts.get(term)??0)+1); matchedTerms++;
  }
  const frequencies = [...counts].map(([term,count])=>({term,count,percent:round(count/matchedTerms*100)}))
    .sort((a,b)=>b.count-a.count || (a.term<b.term?-1:a.term>b.term?1:0)).slice(0,top);
  return {totalTokens:tokens.length,matchedTerms,uniqueTerms:counts.size,frequencies};
}
