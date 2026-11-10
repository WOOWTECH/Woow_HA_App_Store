// Explicit Pi 0.99.1 cold resume. Never used by ordinary ensure or MCP refresh.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';

const fail = code => { throw new Error(code); };
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

export function ownerPath(filename, directory = false) {
  if (!path.isAbsolute(filename)) fail('PI_RESUME_UNSAFE_PATH');
  let current = path.parse(filename).root;
  for (const part of filename.slice(current.length).split(path.sep)) {
    current = path.join(current, part);
    const st = fs.lstatSync(current);
    if (st.isSymbolicLink()) fail('PI_RESUME_UNSAFE_PATH');
  }
  const st = fs.lstatSync(filename);
  if ((directory ? !st.isDirectory() : !st.isFile()) || st.uid !== process.getuid() || (st.mode & 0o022))
    fail('PI_RESUME_UNSAFE_PATH');
  return st;
}

export function verifyHistory(ticket) {
  const st = ownerPath(ticket.nativeFile);
  const bytes = fs.readFileSync(ticket.nativeFile);
  if (st.size !== ticket.nativeBytes || sha(bytes) !== ticket.nativeSHA256) fail('PI_RESUME_HISTORY_CHANGED');
  if (!bytes.length || bytes.at(-1) !== 10) fail('PI_RESUME_INVALID_HISTORY');
  let rows;
  try { rows = bytes.toString('utf8').trimEnd().split('\n').map(line => JSON.parse(line)); }
  catch { fail('PI_RESUME_INVALID_HISTORY'); }
  const h = rows[0];
  if (h.type !== 'session' || h.version !== 3 || h.id !== ticket.nativeSessionId || h.cwd !== ticket.cwd ||
      rows.length !== ticket.entryCount || rows.slice(1).some(r => !r.id || r.type === 'session'))
    fail('PI_RESUME_INVALID_HISTORY');
  return rows;
}

export function installStrictOpen(api, ticket) {
  if (api.VERSION !== '0.99.1' || api.CURRENT_SESSION_VERSION !== 3) fail('PI_RESUME_VERSION_UNSUPPORTED');
  const Manager = api.SessionManager;
  const original = Manager.open;
  let opened = false;
  Manager.open = function(filename, sessionDir) {
    if (opened || path.resolve(filename) !== ticket.nativeFile || path.resolve(sessionDir) !== path.dirname(ticket.nativeFile))
      fail('PI_RESUME_UNEXPECTED_OPEN');
    verifyHistory(ticket);
    const newSession = Manager.prototype.newSession, rewrite = Manager.prototype._rewriteFile;
    // Pinned synchronous open calls these for missing/empty/migrating sessions.
    // Fail before either can create an ID or rewrite any existing history.
    Manager.prototype.newSession = () => fail('PI_RESUME_FRESH_FORBIDDEN');
    Manager.prototype._rewriteFile = () => fail('PI_RESUME_REWRITE_FORBIDDEN');
    let manager;
    try {
      manager = original.call(this, filename, sessionDir);
      if (manager.getSessionId() !== ticket.nativeSessionId || manager.getSessionFile() !== ticket.nativeFile ||
          manager.getEntries().length !== ticket.entryCount - 1) fail('PI_RESUME_IDENTITY_CHANGED');
      verifyHistory(ticket);
      opened = true;
      if (ticket.bridgeDir) fs.writeFileSync(path.join(ticket.bridgeDir, 'woow-pi-cold-opened.json'),
        JSON.stringify({ requestId: ticket.requestId, sessionId: ticket.sessionId, nativeSessionId: ticket.nativeSessionId,
          pid: process.pid, originalBytes: ticket.nativeBytes, originalSHA256: ticket.nativeSHA256 }), { mode: 0o600 });
    } finally {
      Manager.prototype.newSession = newSession;
      Manager.prototype._rewriteFile = rewrite;
    }
    // Ordinary later /resume remains native behavior after this explicit open.
    Manager.open = original;
    return manager;
  };
  return { opened: () => opened, restore: () => { Manager.open = original; } };
}

export async function launch(ticketFile) {
  ownerPath(ticketFile);
  const ticket = JSON.parse(fs.readFileSync(ticketFile, 'utf8'));
  if (ticket.version !== 1 || ticket.expiresAt < Date.now()) fail('PI_RESUME_TICKET_EXPIRED');
  ownerPath(ticket.bridgeDir, true);
  const configFile = path.join(ticket.bridgeDir, 'config.json');
  ownerPath(configFile);
  const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  if (config.sessionId !== ticket.sessionId || sha(fs.readFileSync(configFile)) !== ticket.configSHA256)
    fail('PI_RESUME_CONFIG_CHANGED');
  if (path.dirname(ticket.nativeFile) !== path.join(ticket.bridgeDir, 'sessions')) fail('PI_RESUME_UNSAFE_PATH');
  if (fs.readdirSync(path.join(ticket.bridgeDir, 'inbox')).length) fail('SESSION_BUSY');
  verifyHistory(ticket);
  const claim = path.join(ticket.bridgeDir, 'woow-pi-cold-active');
  try { fs.mkdirSync(claim, { mode: 0o700 }); } catch { fail('SESSION_BUSY'); }
  process.once('exit', () => { try { fs.rmdirSync(claim); } catch {} });
  const api = await import(pathToFileURL(path.join(ticket.packageDir, 'dist/bundle/index.js')));
  // Resolve native trust without changing its store or accepting a prompt.
  if (api.hasTrustRequiringProjectResources(ticket.cwd) &&
      new api.ProjectTrustStore(api.getAgentDir()).get(ticket.cwd) !== true) fail('PI_RESUME_TRUST_REQUIRED');
  const guard = installStrictOpen(api, ticket);
  process.chdir(ticket.cwd);
  const args = ['--session', ticket.nativeFile, '--session-dir', path.dirname(ticket.nativeFile),
    '--extension', path.join(ticket.bridgeDir, 'omnigent_pi_native_extension.js')];
  // No trust, tool-policy, provider or model overrides. Restore native choices.
  await api.main(args);
  if (!guard.opened()) fail('PI_RESUME_NOT_OPENED');
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { await launch(process.argv[2]); }
  catch (error) {
    const code = /^(?:PI_RESUME_[A-Z_]+|SESSION_BUSY)$/.test(error?.message) ? error.message : 'PI_RESUME_FAILED';
    process.stderr.write(code + '\n');
    process.exitCode = 1;
  }
}
