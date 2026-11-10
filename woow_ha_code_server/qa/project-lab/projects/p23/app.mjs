export const meta = {
  id: 'p23', title: 'Synthetic Environment Template Validator', category: 'Configuration', version: '1.1.0',
  description: 'Check supplied synthetic variables against a .env-style template without reading the host environment.',
  example: { template: '# Blank defaults are required\nAPP_HOST=\nAPP_PORT=8080\nMODE=demo', values: { APP_HOST: 'demo.local', MODE: 'test' } },
  fields: [{ key: 'template', label: 'Synthetic template', type: 'textarea' }, { key: 'values', label: 'Synthetic values', type: 'json' }]
};
const namePattern = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const unsafe = name => ['__proto__', 'constructor', 'prototype'].includes(name);
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['template', 'values'].includes(k))) throw new Error('Input must contain template and values');
  const { template, values } = input;
  if (typeof template !== 'string' || !template.trim() || template.length > 30000 || template.includes('\0')) throw new Error('template must contain 1–30000 characters without NUL');
  if (!values || typeof values !== 'object' || Array.isArray(values) || Object.keys(values).length > 200) throw new Error('values must be an object of at most 200 synthetic strings');
  let valueLength = 0;
  for (const [name, value] of Object.entries(values)) {
    if (!namePattern.test(name) || unsafe(name) || typeof value !== 'string' || value.length > 4096 || value.includes('\0')) throw new Error('Each synthetic value needs a safe variable name and a string up to 4096 characters');
    valueLength += value.length;
  }
  if (valueLength > 100000) throw new Error('Combined synthetic values exceed 100000 characters');
  const lines = template.split(/\r?\n/), definitions = new Map();
  if (lines.length > 300) throw new Error('template exceeds 300 lines');
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index].trim();
    if (!line || line.startsWith('#')) continue;
    const match = /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]{0,63})\s*=\s*(.*)$/.exec(line);
    if (!match || unsafe(match[1])) throw new Error(`Invalid template assignment on line ${index + 1}`);
    const name = match[1];
    if (definitions.has(name)) throw new Error(`Duplicate template variable ${name}`);
    let value = match[2];
    if (value.startsWith('"')) {
      const quoted = /^("(?:[^"\\]|\\.)*")\s*(?:#.*)?$/.exec(value);
      if (!quoted) throw new Error(`Invalid quoted default on line ${index + 1}`);
      try { value = JSON.parse(quoted[1]); } catch { throw new Error(`Invalid quoted default on line ${index + 1}`); }
    } else if (value.startsWith("'")) {
      const quoted = /^'([^']*)'\s*(?:#.*)?$/.exec(value);
      if (!quoted) throw new Error(`Invalid quoted default on line ${index + 1}`);
      value = quoted[1];
    } else value = value.replace(/(?:^|\s+)#.*$/, '').trim();
    if (value.length > 4096 || value.includes('\0')) throw new Error('Default values must be at most 4096 characters without NUL');
    definitions.set(name, value);
    if (definitions.size > 200) throw new Error('template exceeds 200 variables');
  }
  if (!definitions.size) throw new Error('template needs at least one variable');
  const required = [], missing = [], empty = [], resolved = {};
  for (const [name, fallback] of definitions) {
    const mandatory = fallback.trim() === '';
    if (mandatory) required.push(name);
    if (Object.hasOwn(values, name)) {
      if (mandatory && values[name].trim() === '') empty.push(name);
      else resolved[name] = values[name];
    } else if (mandatory) missing.push(name);
    else resolved[name] = fallback;
  }
  const unexpected = Object.keys(values).filter(name => !definitions.has(name)).sort();
  return { valid: !missing.length && !empty.length && !unexpected.length, required, missing, empty, unexpected, resolved };
}
