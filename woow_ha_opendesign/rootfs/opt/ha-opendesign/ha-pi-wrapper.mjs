#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { chmod, lstat, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const REAL_PI_BIN = '/opt/ha-opendesign/pi/node_modules/.bin/pi';
const DEFAULT_PROFILES_FILE = '/data/opendesign/credentials/byok-profiles.json';
const PI_PROVIDER_ID = 'ha-profile';
const OFFICIAL_BASE_URLS = Object.freeze({
  anthropic: 'https://api.anthropic.com',
  openai: 'https://api.openai.com/v1',
  google: 'https://generativelanguage.googleapis.com/v1beta',
});
const PI_APIS = Object.freeze({
  anthropic: 'anthropic-messages',
  openai: 'openai-responses',
  google: 'google-generative-ai',
});

function fail(message) {
  throw new Error(message);
}

function nonEmptyString(value, maximum, message) {
  if (typeof value !== 'string' || value.trim().length === 0 || value.length > maximum) fail(message);
  return value.trim();
}

function isHttpsUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && !url.hash;
  } catch {
    return false;
  }
}

export function validateActiveProfile(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail('Pi profile is unavailable. Configure an active HA Persistent BYOK Profile in Settings.');
  const profile = raw;
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(nonEmptyString(profile.id, 128, 'Pi profile is invalid.'))) fail('Pi profile is invalid.');
  nonEmptyString(profile.label, 120, 'Pi profile is invalid.');
  nonEmptyString(profile.model, 256, 'Pi profile is invalid.');
  nonEmptyString(profile.apiKey, 4096, 'Pi profile is missing an API key.');

  if (!Object.hasOwn(OFFICIAL_BASE_URLS, profile.protocol) && profile.protocol !== 'openai-compatible') {
    fail('Pi profile uses an unsupported profile protocol.');
  }
  if (profile.protocol === 'openai-compatible') {
    if (!isHttpsUrl(profile.baseUrl)) fail('Pi compatible profile requires an HTTPS base URL.');
    if (profile.authStyle !== 'bearer' && profile.authStyle !== 'api-key') fail('Pi compatible profile has an invalid authentication style.');
    if (profile.apiFlavor !== 'openai-completions' && profile.apiFlavor !== 'openai-responses') fail('Pi compatible profile has an invalid API flavour.');
  }
  return profile;
}

export function profileToPiConfig(raw) {
  const profile = validateActiveProfile(raw);
  const compatible = profile.protocol === 'openai-compatible';
  const config = {
    baseUrl: compatible ? profile.baseUrl.trim() : OFFICIAL_BASE_URLS[profile.protocol],
    api: compatible ? profile.apiFlavor : PI_APIS[profile.protocol],
    apiKey: '$OD_PI_PROFILE_KEY',
    models: [{ id: profile.model.trim(), name: profile.model.trim() }],
  };
  if (compatible && profile.authStyle === 'api-key') {
    config.authHeader = false;
    config.headers = { 'api-key': '$OD_PI_PROFILE_KEY' };
  } else {
    config.authHeader = true;
  }
  return { providers: { [PI_PROVIDER_ID]: config } };
}

export function buildPiArgs(argv, raw) {
  const profile = validateActiveProfile(raw);
  const next = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--model' || arg === '--session-dir') {
      index += 1;
      continue;
    }
    if (arg.startsWith('--model=') || arg.startsWith('--session-dir=')) continue;
    if (arg === '--no-session') continue;
    next.push(arg);
  }
  next.push('--model', `${PI_PROVIDER_ID}/${profile.model.trim()}`, '--no-session');
  return next;
}

export async function createTransientPiConfig(raw, parentDirectory = '/tmp') {
  const profile = validateActiveProfile(raw);
  await mkdir(parentDirectory, { recursive: true, mode: 0o700 });
  const directory = await mkdtemp(path.join(parentDirectory, 'pi-agent-'));
  await chmod(directory, 0o700);
  const modelsPath = path.join(directory, 'models.json');
  await writeFile(modelsPath, `${JSON.stringify(profileToPiConfig(profile))}\n`, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
  await chmod(modelsPath, 0o600);
  return { dir: directory, modelsPath };
}

async function readActiveProfile(profilesPath) {
  let status;
  try {
    status = await lstat(profilesPath);
  } catch {
    fail('Pi profile is unavailable. Configure an active HA Persistent BYOK Profile in Settings.');
  }
  if (!status.isFile() || status.isSymbolicLink()) fail('Pi profile storage is unsafe. Contact the add-on administrator.');

  let state;
  try {
    state = JSON.parse(await readFile(profilesPath, 'utf8'));
  } catch {
    fail('Pi profile storage is invalid. Re-save the active profile in Settings.');
  }
  if (!state || typeof state !== 'object' || Array.isArray(state) || typeof state.activeProfileId !== 'string' || !state.profiles || typeof state.profiles !== 'object' || Array.isArray(state.profiles)) {
    fail('Pi profile is unavailable. Configure an active HA Persistent BYOK Profile in Settings.');
  }
  return validateActiveProfile(state.profiles[state.activeProfileId]);
}

function invoke(command, args, environment) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', env: environment });
    child.once('error', reject);
    child.once('exit', (code, signal) => resolve({ code: code ?? 1, signal }));
  });
}

function isVersionProbe(argv) {
  return argv.length === 1 && argv[0] === '--version';
}

async function main() {
  const argv = process.argv.slice(2);
  if (isVersionProbe(argv)) {
    const result = await invoke(REAL_PI_BIN, argv, process.env);
    process.exitCode = result.code;
    return;
  }

  let runtime;
  try {
    const profile = await readActiveProfile(process.env.OD_BYOK_PROFILES_FILE || DEFAULT_PROFILES_FILE);
    runtime = await createTransientPiConfig(profile);
    const environment = {
      ...process.env,
      OD_PI_PROFILE_KEY: profile.apiKey,
      PI_CODING_AGENT_DIR: runtime.dir,
      PI_CODING_AGENT_SESSION_DIR: path.join(runtime.dir, 'sessions'),
      PI_OFFLINE: '1',
      PI_SKIP_VERSION_CHECK: '1',
      PI_TELEMETRY: '0',
    };
    const result = await invoke(REAL_PI_BIN, buildPiArgs(argv, profile), environment);
    process.exitCode = result.code;
  } finally {
    if (runtime) await rm(runtime.dir, { recursive: true, force: true });
  }
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
if (invokedPath === fileURLToPath(import.meta.url)) {
  main().catch(() => {
    // Deliberately avoid echoing profile, file, or provider details: an add-on
    // log may be readable by an HA administrator and must never become a key sink.
    process.stderr.write('Pi Local CLI could not start. Configure a valid active HA Persistent BYOK Profile in Settings.\n');
    process.exitCode = 78;
  });
}
