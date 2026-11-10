'use strict';
const { spawn } = require('node:child_process');
const path = require('node:path');
const { StringDecoder } = require('node:string_decoder');
const DEFAULT_RUNTIME = '/usr/local/bin/woow-connectors';
const ACTIONS = new Set(['status', 'configure', 'start', 'stop', 'restore', 'models', 'verify', 'pair', 'connect', 'disconnect']);
const MAX_OUTPUT = 2 * 1024 * 1024;

function failure(code, message) { return { ok: false, error: { code, message } }; }
function publicCode(value) { return typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(value) ? value : 'RUNTIME_ERROR'; }
function safeText(value, max = 240) {
  if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') return '';
  return String(value).replace(/\bBearer\s+\S+/gi, '[redacted]')
    .replace(/\b(?:sk-|sk-or-v1-|ghp_|github_pat_)[\w-]{8,}/g, '[redacted]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[redacted]')
    .replace(/((?:password|token|secret|authorization|credential)\s*[=:]\s*)[^\s,;]+/gi, '$1[redacted]')
    .replace(/(https?:\/\/[^\s?#]+)[?#][^\s]*/gi, '$1?[redacted]')
    .replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, max);
}
function webUrl(value, { server = false } = {}) {
  if (typeof value !== 'string' || value.length > 8192 || /[\x00-\x1f\x7f]/.test(value)) return undefined;
  try {
    const u = new URL(value);
    if (!['https:', 'http:'].includes(u.protocol) || u.username || u.password) return undefined;
    if (server && (u.search || u.hash || value.includes('?') || value.includes('#'))) return undefined;
    return u.toString();
  } catch { return undefined; }
}
function settingsFrom(configuration) {
  // Ignore workspace/repository settings even when called by a mock or old host.
  const result = {};
  for (const key of ['runtimePath', 'workspace', 'hostName', 'server', 'webUrl']) {
    const entry = configuration.inspect(key);
    result[key] = entry?.globalValue ?? entry?.defaultValue ?? '';
  }
  result.runtimePath ||= DEFAULT_RUNTIME;
  return result;
}
function configureFields(connector, input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid configuration.');
  const allowed = ['workspace', 'hostName', 'webUrl', ...(connector === 'omnigent' ? ['server'] : [])];
  if (Object.keys(input).some(key => !allowed.includes(key))) throw new Error('Unknown configuration field.');
  const result = {};
  for (const key of ['workspace', 'hostName']) {
    const value = input[key];
    if (typeof value !== 'string' || !value.trim() || value.length > (key === 'workspace' ? 4096 : 120) || /[\x00-\x1f\x7f]/.test(value)) throw new Error(`Invalid ${key}.`);
    result[key] = value.trim();
  }
  if (!path.posix.isAbsolute(result.workspace)) throw new Error('Workspace must be an absolute container path.');
  if (connector === 'omnigent') {
    result.server = webUrl(input.server, { server: true });
    if (!result.server) throw new Error('Server must be an HTTP(S) URL without credentials, query, or fragment.');
  }
  if (input.webUrl !== undefined && input.webUrl !== '') {
    result.webUrl = webUrl(input.webUrl, { server: true });
    if (!result.webUrl) throw new Error('Web URL must be an HTTP(S) URL without credentials, query, or fragment.');
  }
  return result;
}
function validMessage(message) {
  if (!message || typeof message !== 'object' || Array.isArray(message) || Object.keys(message).some(k => !['action', 'fields'].includes(k))) return false;
  if (!['status', 'configure', 'start', 'stop', 'restore', 'models', 'verify', 'pair', 'connect', 'disconnect', 'openWeb', 'settings'].includes(message.action)) return false;
  if (message.action === 'configure') return !!message.fields && typeof message.fields === 'object' && !Array.isArray(message.fields);
  return message.fields === undefined;
}
function createRuntime({ executable = DEFAULT_RUNTIME, spawnProcess = spawn, timeoutMs, onEvent = () => {} } = {}) {
  return async function invoke(request) {
    if (!request || !['paseo', 'omnigent'].includes(request.connector) || !ACTIONS.has(request.action)) return failure('INVALID_REQUEST', 'Unsupported connector action.');
    if (typeof executable !== 'string' || !path.isAbsolute(executable) || /[\x00\r\n]/.test(executable)) return failure('INVALID_RUNTIME_PATH', 'Use an absolute runtime executable path.');
    const limit = timeoutMs ?? ({ verify: 420000, connect: 180000, models: 180000, start: 130000, restore: 130000 }[request.action] ?? 45000);
    return new Promise(resolve => {
      let child, timer, killTimer, done = false, out = '', size = 0;
      const decoder = new StringDecoder('utf8');
      const finish = result => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        // Diagnostics contain operation identifiers only, never stdin/stdout/stderr.
        try { onEvent({ connector: request.connector, action: request.action, ok: result.ok, ...(result.ok ? {} : { code: publicCode(result.error?.code) }) }); } catch {}
        resolve(result);
      };
      const terminate = () => {
        child?.kill('SIGTERM');
        killTimer = setTimeout(() => child?.kill('SIGKILL'), 1000);
        killTimer.unref?.();
      };
      try {
        child = spawnProcess(executable, [], { shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
        child.once('error', () => finish(failure('RUNTIME_UNAVAILABLE', 'Connector runtime unavailable. Install the matching WOOW connector runtime in this container.')));
        child.stdout.on('data', data => {
          if (done) return;
          size += data.length;
          if (size > MAX_OUTPUT) { terminate(); finish(failure('OUTPUT_LIMIT', 'Runtime response exceeded the size limit.')); }
          else out += decoder.write(data);
        });
        // Consume but never expose diagnostics: a third-party CLI can include secrets.
        child.stderr.on('data', () => {});
        child.stdin.on('error', () => {});
        child.once('close', code => {
          clearTimeout(killTimer);
          if (done) return;
          try {
            const result = JSON.parse((out + decoder.end()).trim());
            if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.ok !== 'boolean') throw new Error();
            if (code !== 0 && result.ok) return finish(failure('RUNTIME_EXIT', 'Runtime exited before completing the operation.'));
            if (!result.ok) return finish(failure(publicCode(result.error?.code), 'Connector operation failed. Check the deployment runtime and authentication status.'));
            finish(result);
          } catch { finish(failure('INVALID_RESPONSE', 'Runtime returned an invalid JSON response.')); }
          out = '';
        });
        timer = setTimeout(() => { terminate(); finish(failure('TIMEOUT', 'Connector operation timed out. Refresh status before retrying.')); }, Math.max(10, limit));
        child.stdin.end(JSON.stringify(request) + '\n');
      } catch { finish(failure('RUNTIME_UNAVAILABLE', 'Connector runtime could not be started.')); }
    });
  };
}
function entries(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') return Object.entries(value).map(([id, item]) => typeof item === 'object' && item !== null ? { id, ...item } : { id, name: item });
  return [];
}
function modelItems(result) {
  const source = result?.data ?? result ?? {};
  const models = [];
  for (const model of entries(source.models)) {
    if (typeof model === 'string') models.push({ id: model, name: model });
    else if (model && typeof model === 'object') models.push({ id: String(model.id ?? model.model ?? model.name ?? ''), name: String(model.name ?? model.label ?? model.id ?? model.model ?? ''), agent: String(model.agent ?? model.engine ?? model.provider ?? '') });
  }
  for (const engine of entries(source.engines ?? source.providers ?? source.agents)) {
    for (const item of entries(engine.models)) {
      const model = typeof item === 'string' ? { id: item, name: item } : item;
      if (model) models.push({ id: String(model.id ?? model.model ?? model.name ?? ''), name: String(model.name ?? model.label ?? model.id ?? model.model ?? ''), agent: String(engine.id ?? engine.engine ?? engine.provider ?? engine.name ?? '') });
    }
  }
  return models.filter(m => m.id && m.id.length <= 512 && !/[\x00-\x1f]/.test(m.id)).slice(0, 500);
}
function publicStatus(result, connector, configuration = {}) {
  const data = result?.data ?? result ?? {};
  const verification = data.verification ?? data.lastVerification ?? data.acceptance;
  // Omnigent validates all engine receipts against the current host, CLI and
  // shared tools. Its explicit false must override otherwise successful stale
  // receipts; a connected host alone never establishes a verified reply.
  const verified = typeof data.verified === 'boolean' ? data.verified : verification?.ok === true || verification?.requestedPassed === true || verification?.passed === true || verification?.status === 'passed';
  const host = data.host;
  const phase = data.phase ?? data.status ?? data.state ?? (data.online === true ? 'online' : data.daemon?.running === true ? 'daemon running; connection unverified' : data.online === false ? 'offline' : undefined);
  return {
    connector,
    ok: result?.ok === true,
    phase: safeText(typeof phase === 'string' ? phase : 'unknown'),
    error: result?.ok === false ? publicCode(result.error?.code) : '',
    host: safeText(typeof host === 'object' && host ? host.name ?? host.id : host ?? data.hostName),
    mode: safeText(data.mode ?? data.managementMode),
    server: safeText(webUrl(data.server ?? data.serverUrl ?? configuration.server, { server: true }) ?? ''),
    workspace: safeText(data.workspace ?? configuration.workspace),
    verification: result?.ok === true && verified ? 'passed' : verification || typeof data.verified === 'boolean' ? 'incomplete' : 'unverified',
    verifiedAt: safeText(verification?.at ?? verification?.timestamp ?? verification?.completedAt),
    engines: entries(data.engines ?? data.providers ?? data.agents).map(item => typeof item === 'string' ? { id: safeText(item), installed: 'unknown', authenticated: 'unknown' } : {
      id: safeText(item.id ?? item.engine ?? item.name ?? item.provider),
      installed: typeof item.installed === 'boolean' ? String(item.installed) : safeText(item.status ?? 'unknown'),
      authenticated: typeof item.authenticated === 'boolean' ? String(item.authenticated) : safeText(item.authStatus ?? 'unknown'),
      version: safeText(item.version),
    }).slice(0, 20),
    models: modelItems(data).map(m => ({ id: safeText(m.id), name: safeText(m.name), agent: safeText(m.agent) })),
    settings: Object.fromEntries(['workspace', 'hostName', 'webUrl', ...(connector === 'omnigent' ? ['server'] : [])].map(key => [key, safeText(['server', 'webUrl'].includes(key) ? webUrl(configuration[key], { server: true }) ?? '' : configuration[key], key === 'workspace' ? 4096 : 512)])),
  };
}
module.exports = { DEFAULT_RUNTIME, createRuntime, failure, publicCode, safeText, settingsFrom, configureFields, validMessage, webUrl, modelItems, publicStatus };
