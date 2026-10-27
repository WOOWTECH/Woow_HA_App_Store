import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const BUNDLE = '/opt/woow/pi-omnigent-plugin';
const NAME = '@woowtech/pi-omnigent-plugin';
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
  if (source === bundle || /(?:^|[/:])pi-omnigent-plugin(?:\.git)?(?:@[^/]*)?\/?$/i.test(source)
    || source === `npm:${NAME}` || source.startsWith(`npm:${NAME}@`)) return true;
  if (!source.includes(':')) return read(path.resolve(agentDir, source, 'package.json'), {})?.name === NAME;
  return false;
}

/** Called before Pi Web starts; settings and tombstone survive image upgrades. */
export function seed({ agentDir = process.env.PI_CODING_AGENT_DIR, home = process.env.HOME, bundle = BUNDLE,
  seedEnabled = process.env.PI_OMNIGENT_AUTO_SETUP !== 'false' } = {}) {
  if (!seedEnabled) return { seeded: false, reason: 'image-setup-disabled' };
  const marker = path.join(agentDir, 'omnigent-plugin/image-seed.json');
  if (fs.existsSync(marker)) return { seeded: false, reason: 'already-considered' };
  const file = path.join(agentDir, 'settings.json');
  const settings = read(file, {});
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)
    || (settings.packages !== undefined && !Array.isArray(settings.packages))) throw new Error('Invalid package settings');
  const project = read(path.join(home, '.pi/settings.json'), {});
  const existing = (settings.packages || []).some(entry => isPlugin(entry, agentDir, bundle))
    || (project.packages || []).some(entry => isPlugin(entry, home, bundle));
  // A pre-existing state with no package can mean the user previously removed it.
  const stateExists = fs.existsSync(path.join(agentDir, 'omnigent-plugin/state.json'));
  const seeded = !existing && !stateExists;
  if (seeded) write(file, { ...settings, packages: [...(settings.packages || []), bundle] });
  write(marker, { schema: 1, bundle, seeded, reason: existing ? 'existing-package' : stateExists ? 'existing-state' : 'image-default' });
  return { seeded };
}

/** Resolve the user's registered package, including git/local overrides. */
export async function loadPlugin({ env = process.env, bundle = BUNDLE } = {}) {
  const bundledWeb = await import(pathToFileURL(path.join(bundle, 'src/web.mjs')).href);
  const sdk = await bundledWeb.loadPiSdk({ env });
  const cwd = env.HOME;
  const agentDir = env.PI_CODING_AGENT_DIR;
  const settings = sdk.SettingsManager.create(cwd, agentDir, { projectTrusted: false });
  const manager = new sdk.DefaultPackageManager({ cwd, agentDir, settingsManager: settings });
  const entries = manager.listConfiguredPackages();
  if (settings.drainErrors?.().length) throw new Error('Invalid package settings');
  for (const entry of [...entries].reverse()) {
    if (!entry.installedPath) continue;
    const root = entry.installedPath;
    const pkg = read(path.join(root, 'package.json'), {});
    if (pkg.name !== NAME) continue;
    const web = await import(pathToFileURL(path.join(root, 'src/web.mjs')).href);
    const runtime = await import(pathToFileURL(path.join(root, 'src/runtime.mjs')).href);
    return { root, web, runtime, version: pkg.version, lifecycle: () => web.packageLifecycle({ env }),
      locations: () => web.webLocations({ env }),
      onboarding: () => web.readOnboarding({ env }), refreshOnboarding: () => web.refreshOnboardingSession({ env }) };
  }
  return null;
}
