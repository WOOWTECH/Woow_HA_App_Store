import path from 'node:path';
import { spawn } from 'node:child_process';

const record = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const word = value => typeof value === 'string' && /^[a-z][a-z0-9-]{0,63}$/.test(value) ? value : null;
const code = value => typeof value === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(value) ? value : null;
const logCode = error => [error?.code, error?.name].find(value => typeof value === 'string' && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(value)) || 'unknown';

/** One add-on log line from `bin/cli.mjs boot`, which prints the receipt it saves
 * as boot.json. Only fixed vocabulary is copied: statuses, phases, reasons and
 * error codes. Server URLs, host ids, messages, details and paths stay in the receipt. */
export function bootSummary(output) {
  let result;
  try { result = JSON.parse(output); } catch { return null; }
  if (!result || typeof result !== 'object' || Array.isArray(result)) return null;
  const startup = record(result.startup), resumption = record(result.resumption);
  const fields = [['startup', word(startup.status)], ['reason', word(startup.reason)],
    ['initialization', word(record(result.initialization).phase)],
    ['resumed', result.resumption ? (resumption.resumed === true ? 'yes' : 'no') : null],
    ['resume-reason', word(resumption.reason)], ['resume-error', code(record(resumption.error).code)],
    // `boot` on a disabled plugin, or the CLI's error envelope: "Operation failed (CODE)."
    ['phase', word(result.phase)], ['error', code(/^Operation failed \(([^)]*)\)\.$/.exec(typeof result.error === 'string' ? result.error : '')?.[1])]];
  const summary = fields.filter(([, value]) => value).map(([key, value]) => `${key}=${value}`).join(' ');
  return summary || null;
}

// Defense in depth for stderr lines: the worker never receives a password, and the
// plugin already keeps adapter output out of its stdout/stderr.
const secrets = [
  [/\b(Bearer|Basic)\s+[\w.~+/=-]{8,}/gi, '$1 [redacted]'],
  [/\beyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]*/g, '[redacted]'],
  [/\b([a-z][a-z0-9+.-]*:\/\/)[^\s/@]+@/gi, '$1[redacted]@'],
  [/\b([\w-]*(?:token|secret|password|passwd|cookie|api[_-]?key|authorization)[\w-]*)(["']?\s*[:=]\s*["']?)[^\s"',;&]+/gi, '$1$2[redacted]'],
  [/[A-Za-z0-9+_-]{40,}={0,2}/g, '[redacted]'],
];
/** A single printable, bounded log line with secret-looking values redacted. */
export function logSafe(line, limit = 300) {
  let value = String(line).replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '').replace(/[\x00-\x1f\x7f]/g, ' ').trim();
  for (const [pattern, replacement] of secrets) value = value.replace(pattern, replacement);
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

/** Run the plugin's offline boot (dependency check and authorized-host resume) in
 * its own process group, so stopping Pi Web also stops unfinished work. Its result
 * reaches the add-on log only as bootSummary(); stderr only through logSafe(). */
export function startBootWorker(root, { env = process.env, spawnImpl = spawn, log = console.log, warn = console.error, maxLines = 20 } = {}) {
  const worker = spawnImpl(process.execPath, [path.join(root, 'bin/cli.mjs'), 'boot'], { env, stdio: ['ignore', 'pipe', 'pipe'], detached: true });
  let output = '', pending = '', shown = 0, hidden = 0, failed = false;
  const line = text => {
    const value = logSafe(text);
    if (!value) return;
    if (shown < maxLines) { shown++; warn(`[omnigent] ${value}`); } else hidden++;
  };
  worker.stdout?.setEncoding('utf8');
  worker.stdout?.on('data', chunk => { if (output.length < 65_536) output += chunk.slice(0, 65_536 - output.length); });
  worker.stderr?.setEncoding('utf8');
  worker.stderr?.on('data', chunk => {
    pending += chunk;
    for (let index = pending.indexOf('\n'); index >= 0; index = pending.indexOf('\n')) { line(pending.slice(0, index)); pending = pending.slice(index + 1); }
    if (pending.length > 8192) { line(pending); pending = ''; }
  });
  worker.once('error', error => { failed = true; warn(`Omnigent host worker could not start (${logCode(error)}).`); });
  worker.once('close', (exitCode, signal) => {
    line(pending); pending = '';
    if (hidden) warn(`[omnigent] ${hidden} more worker log lines not shown.`);
    if (failed) return;
    const summary = bootSummary(output);
    if (signal && !summary) return log(`Omnigent host worker stopped (${signal}).`);
    const status = signal ? `signal ${signal}` : `exit ${exitCode}`;
    (exitCode === 0 ? log : warn)(`Omnigent host worker finished (${status})${summary ? `: ${summary}` : ' without a result.'}`);
  });
  return worker;
}
