import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const BUNDLE = '/opt/woow/pi-paseo-plugin';
const NAME = '@woowtech/pi-paseo';
function read(file, fallback) {
  try {
    if (fs.lstatSync(file).isSymbolicLink()) throw new Error('Symlink metadata preserved');
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  }
  catch (error) { if (error.code === 'ENOENT') return fallback; throw error; }
}
function write(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  if (fs.existsSync(file) && fs.lstatSync(file).isSymbolicLink()) throw new Error('Symlink metadata preserved');
  const temporary = `${file}.${process.pid}.tmp`;
  try {
    fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    fs.renameSync(temporary, file);
  } finally { fs.rmSync(temporary, { force: true }); }
}
function isPlugin(entry, agentDir, bundle) {
  const source = typeof entry === 'string' ? entry : entry?.source;
  if (typeof source !== 'string') return false;
  if (source === bundle || /(?:^|[/:])pi-paseo-plugin(?:\.git)?(?:@[^/]*)?\/?$/i.test(source)
    || source === `npm:${NAME}` || source.startsWith(`npm:${NAME}@`)) return true;
  if (!source.includes(':')) return read(path.resolve(agentDir, source, 'package.json'), {})?.name === NAME;
  return false;
}

/** Called before Pi Web starts; settings and tombstone survive image upgrades. */
export function seed({ agentDir = process.env.PI_CODING_AGENT_DIR, home = process.env.HOME, bundle = BUNDLE,
  seedEnabled = process.env.PI_PASEO_AUTO_SETUP !== 'false' } = {}) {
  if (!seedEnabled) return { seeded: false, reason: 'image-setup-disabled' };
  const marker = path.join(agentDir, 'pi-paseo/image-seed.json');
  if (fs.existsSync(marker)) return { seeded: false, reason: 'already-considered' };
  const file = path.join(agentDir, 'settings.json');
  const settings = read(file, {});
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)
    || (settings.packages !== undefined && !Array.isArray(settings.packages))) throw new Error('Invalid package settings');
  const project = read(path.join(home, '.pi/settings.json'), {});
  const existing = (settings.packages || []).some(entry => isPlugin(entry, agentDir, bundle))
    || (project.packages || []).some(entry => isPlugin(entry, home, bundle));
  // A pre-existing state with no package can mean the user previously removed it.
  const stateExists = fs.existsSync(path.join(agentDir, 'pi-paseo/state.json'));
  const seeded = !existing && !stateExists;
  if (seeded) write(file, { ...settings, packages: [...(settings.packages || []), bundle] });
  write(marker, { schema: 1, bundle, seeded, reason: existing ? 'existing-package' : stateExists ? 'existing-state' : 'image-default' });
  return { seeded };
}

/** Use the host SDK 1.1 from Pi Web 0.12, never the plugin's 0.10 overlay. */
export async function loadPlugin({ env = process.env, bundle = BUNDLE } = {}) {
  const sdk = await import(pathToFileURL(path.join(bundle, 'node_modules/@earendil-works/pi-coding-agent/dist/index.js')).href);
  const settings = sdk.SettingsManager.create(env.HOME, env.PI_CODING_AGENT_DIR, { projectTrusted: false });
  const manager = new sdk.DefaultPackageManager({ cwd: env.HOME, agentDir: env.PI_CODING_AGENT_DIR, settingsManager: settings });
  const entries = manager.listConfiguredPackages();
  if (settings.drainErrors?.().length) throw new Error('Invalid package settings');
  for (const entry of [...entries].reverse()) {
    if (!entry.installedPath) continue;
    const root = entry.installedPath;
    const pkg = read(path.join(root, 'package.json'), {});
    if (pkg.name !== NAME) continue;
    const scopes = { user: settings.getGlobalSettings(), project: settings.getProjectSettings() };
    const binding = (scopes[entry.scope]?.packages || []).find(item => (typeof item === 'string' ? item : item.source) === entry.source);
    const enabled = typeof binding === 'string' || !!binding && (!Array.isArray(binding.extensions) || binding.extensions.length > 0);
    const api = await import(pathToFileURL(path.join(root, 'src/host-api.mjs')).href);
    return { root, api, enabled, version: pkg.version, hooks: {
      createOnboarding: async (prompt, remember) => {
        const cwd = path.resolve(env.HOME);
        const safePath = `--${cwd.replace(/^[/\\]/, '').replace(/[/\\:]/g, '-')}--`;
        const session = sdk.SessionManager.create(cwd, path.join(env.PI_CODING_AGENT_DIR, 'sessions', safePath));
        session.appendSessionInfo('Paseo 連線初始化');
        session.appendCustomEntry('paseo-onboarding', { version: 1 });
        // Persist without requiring a model account or spending tokens. The
        // plugin supervisor already performs installation/startup independently.
        session.appendMessage({ role: 'user', content: prompt, timestamp: Date.now() });
        remember(session.getSessionId());
        return session.getSessionId();
      },
    } };
  }
  return null;
}

/** Seed the verified static release into persistent plugin state without
 * replacing credentials, sessions, configuration, or user-installed runtimes. */
export async function prepareImage({ bundle = BUNDLE, image = '/opt/woow/paseo-web' } = {}) {
  const { locations, assertSafePath } = await import(pathToFileURL(path.join(bundle, 'src/state.mjs')).href);
  const { webClientManifest, webClientStatus } = await import(pathToFileURL(path.join(bundle, 'src/web-client.mjs')).href);
  const loc = locations(), manifest = webClientManifest();
  if (webClientStatus(loc).ready) return;
  const destination = path.join(loc.stateDir, 'web-client', manifest.sha256);
  assertSafePath(destination);
  // The plugin owns repair of an incomplete cache under its runtime lock.
  // Do not prevent registration or its normal retry supervisor from starting.
  if (fs.existsSync(destination)) return;
  fs.mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
  const temporary = destination + '.image-' + process.pid;
  assertSafePath(temporary);
  try {
    fs.cpSync(path.join(image, 'web-client', manifest.sha256), temporary, { recursive: true, errorOnExist: true, force: false });
    fs.renameSync(temporary, destination);
  } finally { fs.rmSync(temporary, { recursive: true, force: true }); }
  if (!webClientStatus(loc).ready) throw new Error('Invalid prebuilt client');
}

/** Watch registration independently of a running model turn. Disabled/removal
 * tombstones win on boot; explicit service pauses stay paused across restarts. */
export async function startLifecycle({ load = loadPlugin, intervalMs = 3000, stop = async plugin => {
  const supervisor = await import(pathToFileURL(path.join(plugin.root, 'src/supervisor.mjs')).href);
  await supervisor.stopSupervisor();
} } = {}) {
  let previous, signature, busy = false, closing = false;
  async function sync() {
    if (busy || closing) return;
    busy = true;
    try {
      const current = await load();
      const next = current ? JSON.stringify([current.root, current.enabled]) : 'missing';
      if (next === signature) return;
      if (previous && (previous.root !== current?.root || !current?.enabled)) await previous.api.lifecycle({ action: 'disable' });
      if (current?.enabled) await current.api.lifecycle({ action: signature === undefined ? 'restore' : 'enable', cwd: process.env.HOME }, current.hooks);
      else if (current && !previous) await current.api.lifecycle({ action: 'disable' });
      previous = current; signature = next;
    } catch { console.error('Paseo setup needs attention; Pi Web remains available.'); }
    finally { busy = false; }
  }
  await sync();
  const timer = setInterval(() => { void sync(); }, intervalMs); timer.unref();
  return async () => {
    closing = true; clearInterval(timer);
    while (busy) await new Promise(resolve => setTimeout(resolve, 20));
    // A process shutdown is not a user pause: leave host-registration intact.
    if (previous) await stop(previous);
  };
}
