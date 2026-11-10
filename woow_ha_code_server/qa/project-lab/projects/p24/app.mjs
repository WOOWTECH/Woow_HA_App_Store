export const meta = {
  id: 'p24', title: 'Allowlisted URL Query Workshop', category: 'Web tools', version: '1.1.0',
  description: 'Parse or build HTTP URLs with exact hostname and query-key allowlists, preserving repeated values.',
  example: { mode: 'build', url: 'https://example.test/search?lang=en', allowedHosts: ['example.test'], allowedKeys: ['lang', 'q', 'tag'], params: { q: 'blue sky', tag: ['demo', 'tools'] } }
};
const safeKey = key => typeof key === 'string' && /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(key) && !['constructor', 'prototype'].includes(key);
function validateEncoding(query) {
  for (const part of query.split(/[&=]/)) {
    try { decodeURIComponent(part.replace(/\+/g, ' ')); } catch { throw new Error('Query contains malformed percent encoding or UTF-8'); }
  }
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['mode', 'url', 'allowedHosts', 'allowedKeys', 'params'].includes(k))) throw new Error('Input must be an object with supported URL fields');
  const { mode, allowedHosts, allowedKeys } = input;
  if (!['build', 'parse'].includes(mode)) throw new Error('mode must be build or parse');
  if (typeof input.url !== 'string' || input.url.length > 4096 || !/^https?:\/\//i.test(input.url) || /[\s\\\u0000-\u001f\u007f]/.test(input.url)) throw new Error('url must be an absolute HTTP(S) URL up to 4096 characters without whitespace or backslashes');
  if (!Array.isArray(allowedHosts) || allowedHosts.length < 1 || allowedHosts.length > 50 || allowedHosts.some(h => typeof h !== 'string' || h.length > 253 || !/^[a-z0-9]+(?:[.-][a-z0-9]+)*$/.test(h))) throw new Error('allowedHosts needs 1–50 lowercase ASCII hostnames without ports');
  if (!Array.isArray(allowedKeys) || allowedKeys.length > 50 || allowedKeys.some(k => !safeKey(k))) throw new Error('allowedKeys must contain at most 50 safe query names');
  let url;
  try { url = new URL(input.url); } catch { throw new Error('Invalid URL'); }
  if (url.username || url.password) throw new Error('URL credentials are not supported');
  if (!allowedHosts.includes(url.hostname)) throw new Error(`Hostname is not allowed: ${url.hostname}`);
  validateEncoding(url.search.slice(1));
  const keys = new Set(allowedKeys);
  if ([...url.searchParams].length > 200) throw new Error('Query exceeds 200 pairs');
  for (const [key, value] of url.searchParams) {
    if (!keys.has(key)) throw new Error(`Query key is not allowed: ${key}`);
    if (value.length > 1024 || /[\u0000-\u001f\u007f]/.test(value)) throw new Error('Query values must be up to 1024 characters without control characters');
  }
  if (mode === 'parse' && input.params !== undefined) throw new Error('params is only supported in build mode');
  if (mode === 'build') {
    const params = input.params;
    if (!params || typeof params !== 'object' || Array.isArray(params) || Object.keys(params).length > 50) throw new Error('params must be an object with at most 50 keys');
    for (const [key, raw] of Object.entries(params)) {
      if (!keys.has(key)) throw new Error(`Query key is not allowed: ${key}`);
      const values = raw === null ? [] : Array.isArray(raw) ? raw : [raw];
      if (values.length > 20) throw new Error('A query key may have at most 20 supplied values');
      url.searchParams.delete(key);
      for (const value of values) {
        if (!['string', 'number', 'boolean'].includes(typeof value) || (typeof value === 'number' && !Number.isFinite(value))) throw new Error('Query values must be strings, finite numbers, or booleans; null deletes a key');
        const string = String(value);
        if (string.length > 1024 || /[\u0000-\u001f\u007f]/.test(string) || !string.isWellFormed()) throw new Error('Query values must be valid Unicode up to 1024 characters without control characters');
        url.searchParams.append(key, string);
      }
    }
    url.searchParams.sort();
  }
  if (url.href.length > 8192 || [...url.searchParams].length > 200) throw new Error('Result exceeds 8192 URL characters or 200 query pairs');
  const query = new Map();
  for (const [key, value] of url.searchParams) {
    if (!query.has(key)) query.set(key, []);
    query.get(key).push(value);
  }
  return { url: url.href, origin: url.origin, pathname: url.pathname, query: Object.fromEntries(query), fragment: url.hash.slice(1) };
}
