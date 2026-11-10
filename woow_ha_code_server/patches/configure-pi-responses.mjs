#!/usr/bin/env node
// Explicit migration for GPT-6 tool calls through a Responses-capable gateway.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

function main() {
  const args = process.argv.slice(2);
  let provider, apply = false;
  let file = path.join(process.env.PI_AGENT_DATA_DIR || '/data/pi-agent', 'models.json');
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--apply') apply = true;
    else if (args[i] === '--provider' && args[i + 1]) provider = args[++i];
    else if (args[i] === '--models' && args[i + 1]) file = args[++i];
    else throw Error('Usage: --provider NAME [--models PATH] [--apply]');
  }
  if (!provider) throw Error('--provider is required');
  if (!fs.lstatSync(file).isFile()) throw Error('models.json must be a regular file');
  const before = fs.readFileSync(file, 'utf8');
  let config;
  try { config = JSON.parse(before); } catch { throw Error('models.json is not valid JSON'); }
  const p = config.providers?.[provider];
  if (!p || !Array.isArray(p.models)) throw Error('Provider must have an explicit models array');
  const changed = [];
  for (const model of p.models) {
    if (typeof model.id !== 'string' || !/(^|\/)gpt-6(?:[.-]|$)/.test(model.id)) continue;
    const api = model.api || p.api;
    if (api === 'openai-responses') continue;
    if (api !== 'openai-completions') throw Error('A GPT-6 model uses an unsupported API; no changes written');
    model.api = 'openai-responses';
    changed.push(model.id);
  }
  if (!changed.length) { console.log(JSON.stringify({changed: [], applied: false})); return; }
  if (!apply) {
    console.log(JSON.stringify({changed, applied: false, next: 'Verify gateway /responses support, then run with --apply'}));
    return;
  }
  if (fs.readFileSync(file, 'utf8') !== before || !fs.lstatSync(file).isFile()) {
    throw Error('Configuration changed while preparing migration; retry after other writers finish');
  }
  const suffix = crypto.randomUUID();
  const backup = `${file}.before-responses-${suffix}`;
  const temporary = `${file}.responses-${suffix}.tmp`;
  fs.writeFileSync(backup, before, {flag: 'wx', mode: 0o600});
  try {
    fs.writeFileSync(temporary, JSON.stringify(config, null, 2) + '\n', {flag: 'wx', mode: 0o600});
    // A concurrent writer must not be silently replaced.
    if (fs.readFileSync(file, 'utf8') !== before) throw Error('Concurrent configuration change; backup retained');
    fs.renameSync(temporary, file);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
  console.log(JSON.stringify({changed, applied: true, backup}));
}

try { main(); } catch (error) {
  // Never print configuration contents, credentials, or a failed HTTP request.
  console.error(error.code ? `Configuration operation failed (${error.code})` : error.message);
  process.exitCode = 1;
}
