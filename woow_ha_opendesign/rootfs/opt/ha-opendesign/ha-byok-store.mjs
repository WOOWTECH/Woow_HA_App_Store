#!/usr/bin/env node
import { createServer } from 'node:http';
import { lstat, open, readFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

export const BYOK_ENDPOINT = '/api/ha-opendesign/byok/profiles';
export const PRIVATE_MARKER_HEADER = 'x-ha-opendesign-byok-marker';
export const DEFAULT_PRIVATE_MARKER = 'ha-opendesign-byok-private';
export const DEFAULT_PROFILES_FILE = '/data/opendesign/credentials/byok-profiles.json';

const MAX_BODY_BYTES = 128 * 1024;
const MAX_PROFILES = 20;
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const OFFICIAL_PROTOCOLS = new Set(['anthropic', 'openai', 'google']);
const COMPATIBLE_FLAVORS = new Set(['openai-completions', 'openai-responses']);
const COMPATIBLE_AUTH_STYLES = new Set(['bearer', 'api-key']);

class ValidationError extends Error {}
class StorageError extends Error {}
class BodyError extends Error {}

function invalid() {
  throw new ValidationError('invalid profile state');
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasOnlyKeys(object, keys) {
  const actual = Object.keys(object);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}

function boundedString(value, maximum) {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= maximum;
}

function isHttpsUrl(value) {
  if (!boundedString(value, 2048)) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && !url.hash;
  } catch {
    return false;
  }
}

function isTimestamp(value) {
  if (!boundedString(value, 64)) return false;
  const milliseconds = Date.parse(value);
  return Number.isFinite(milliseconds) && new Date(milliseconds).toISOString() === value;
}

function validateProfile(profile, profileId) {
  if (!isPlainObject(profile) || !ID_PATTERN.test(profileId) || profile.id !== profileId
    || !boundedString(profile.label, 120) || !boundedString(profile.model, 256)
    || !boundedString(profile.apiKey, 4096) || !isTimestamp(profile.updatedAt)) invalid();

  if (OFFICIAL_PROTOCOLS.has(profile.protocol)) {
    if (!hasOnlyKeys(profile, ['id', 'label', 'protocol', 'apiKey', 'model', 'updatedAt'])) invalid();
    return;
  }
  if (profile.protocol !== 'openai-compatible'
    || !hasOnlyKeys(profile, ['id', 'label', 'protocol', 'baseUrl', 'authStyle', 'apiFlavor', 'apiKey', 'model', 'updatedAt'])
    || !isHttpsUrl(profile.baseUrl)
    || !COMPATIBLE_AUTH_STYLES.has(profile.authStyle)
    || !COMPATIBLE_FLAVORS.has(profile.apiFlavor)) invalid();
}

/** Validate a complete persisted state without changing supplied profile values. */
export function validateState(state) {
  if (!isPlainObject(state) || !hasOnlyKeys(state, ['version', 'revision', 'activeProfileId', 'profiles'])
    || state.version !== 1 || !Number.isSafeInteger(state.revision) || state.revision < 0
    || !isPlainObject(state.profiles)) invalid();

  const profileIds = Object.keys(state.profiles);
  if (profileIds.length > MAX_PROFILES) invalid();
  for (const profileId of profileIds) validateProfile(state.profiles[profileId], profileId);
  if (state.activeProfileId !== null
    && (typeof state.activeProfileId !== 'string' || !Object.hasOwn(state.profiles, state.activeProfileId))) invalid();
  return state;
}

export function emptyState() {
  return { version: 1, revision: 0, activeProfileId: null, profiles: {} };
}

async function assertSafeDirectory(directory) {
  const resolved = path.resolve(directory);
  const parsed = path.parse(resolved);
  let current = parsed.root;
  for (const segment of resolved.slice(parsed.root.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, segment);
    let status;
    try {
      status = await lstat(current);
    } catch {
      throw new StorageError('credential directory unavailable');
    }
    if (status.isSymbolicLink() || !status.isDirectory()) throw new StorageError('unsafe credential directory');
  }
}

async function assertSafeStorage(profilesFile) {
  const directory = path.dirname(profilesFile);
  await assertSafeDirectory(directory);
  let directoryStatus;
  try {
    directoryStatus = await lstat(directory);
  } catch {
    throw new StorageError('credential directory unavailable');
  }
  if (directoryStatus.uid !== process.getuid() || (directoryStatus.mode & 0o777) !== 0o700) {
    throw new StorageError('unsafe credential directory permissions');
  }
  try {
    const status = await lstat(profilesFile);
    if (status.isSymbolicLink() || !status.isFile()) throw new StorageError('unsafe credential file');
    if ((status.mode & 0o777) !== 0o600) throw new StorageError('unsafe credential file mode');
    return true;
  } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error instanceof StorageError ? error : new StorageError('credential file unavailable');
  }
}

async function readState(profilesFile) {
  const exists = await assertSafeStorage(profilesFile);
  if (!exists) return emptyState();
  let raw;
  try {
    raw = await readFile(profilesFile, 'utf8');
  } catch {
    throw new StorageError('credential file unavailable');
  }
  // Recheck after reading so a static symlink swap cannot be accepted.
  await assertSafeStorage(profilesFile);
  try {
    return validateState(JSON.parse(raw));
  } catch {
    throw new StorageError('credential file invalid');
  }
}

async function syncDirectory(directory) {
  let handle;
  try {
    handle = await open(directory, 'r');
    await handle.sync();
  } finally {
    if (handle) await handle.close();
  }
}

async function writeState(profilesFile, state) {
  const directory = path.dirname(profilesFile);
  await assertSafeStorage(profilesFile);
  const temporary = path.join(directory, `.${path.basename(profilesFile)}.${process.pid}.${randomUUID()}.tmp`);
  let handle;
  try {
    handle = await open(temporary, 'wx', 0o600);
    await handle.writeFile(`${JSON.stringify(state)}\n`, 'utf8');
    await handle.chmod(0o600);
    await handle.sync();
    await handle.close();
    handle = undefined;
    // Do not replace a file or directory that became unsafe while writing.
    await assertSafeStorage(profilesFile);
    await rename(temporary, profilesFile);
    await syncDirectory(directory);
  } catch (error) {
    throw error instanceof StorageError ? error : new StorageError('credential write failed');
  } finally {
    if (handle) await handle.close().catch(() => {});
    await rm(temporary, { force: true }).catch(() => {});
  }
}

function send(response, status, body, headers = {}) {
  response.writeHead(status, {
    'Cache-Control': 'no-store',
    'Content-Type': 'application/json; charset=utf-8',
    ...headers,
  });
  response.end(JSON.stringify(body));
}

async function readJsonBody(request) {
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    total += chunk.length;
    if (total > MAX_BODY_BYTES) throw new BodyError('request too large');
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new BodyError('invalid json');
  }
}

export function createByokStore({
  profilesFile = process.env.OD_BYOK_PROFILES_FILE || DEFAULT_PROFILES_FILE,
  marker = process.env.HA_BYOK_PRIVATE_MARKER || DEFAULT_PRIVATE_MARKER,
} = {}) {
  // HTTP handlers interleave at filesystem awaits. Serialize compare-and-swap
  // writes so two callers using the same revision cannot both succeed.
  let writeTail = Promise.resolve();
  const withWriteLock = (work) => {
    const result = writeTail.then(work, work);
    writeTail = result.catch(() => {});
    return result;
  };
  return createServer(async (request, response) => {
    const pathname = new URL(request.url || '/', 'http://127.0.0.1').pathname;
    if (pathname !== BYOK_ENDPOINT) return send(response, 404, { error: 'not found' });
    if (request.headers[PRIVATE_MARKER_HEADER] !== marker) return send(response, 403, { error: 'forbidden' });
    if (request.method === 'GET') {
      try {
        return send(response, 200, await readState(profilesFile));
      } catch {
        return send(response, 500, { error: 'profile storage unavailable' });
      }
    }
    if (request.method !== 'PUT') {
      return send(response, 405, { error: 'method not allowed' }, { Allow: 'GET, PUT' });
    }

    try {
      const candidate = validateState(await readJsonBody(request));
      const outcome = await withWriteLock(async () => {
        const current = await readState(profilesFile);
        if (candidate.revision !== current.revision) return { status: 409, body: { error: 'profile revision conflict' } };
        if (current.revision === Number.MAX_SAFE_INTEGER) throw new StorageError('revision exhausted');
        const next = { ...candidate, revision: current.revision + 1 };
        await writeState(profilesFile, next);
        return { status: 200, body: next };
      });
      return send(response, outcome.status, outcome.body);
    } catch (error) {
      if (error instanceof ValidationError || error instanceof BodyError) return send(response, 400, { error: 'invalid profile state' });
      return send(response, 500, { error: 'profile storage unavailable' });
    }
  });
}

export async function startByokStore(options = {}) {
  const server = createByokStore(options);
  const host = options.host || '127.0.0.1';
  const port = options.port ?? 7457;
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.off('error', reject);
      resolve();
    });
  });
  return server;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
if (invokedPath === fileURLToPath(import.meta.url)) {
  startByokStore().catch(() => {
    process.stderr.write('[ha-opendesign] profile sidecar could not start\n');
    process.exitCode = 78;
  });
}
