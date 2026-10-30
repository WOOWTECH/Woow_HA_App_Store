// One add-on start, offline: the image seed, the launcher's package activation
// (launch.mjs activate(), without the boot worker that contacts a server or
// installs dependencies), then a Settings → Omnigent read through the HA bridge.
// omnigent-contract.test.mjs runs this file in a new process for every start,
// so each restart loads the registered plugin from disk again. Reads the add-on
// environment (HOME, PI_CODING_AGENT_DIR, PI_OMNIGENT_SDK_ROOT) and
// HA_OMNIGENT_BUNDLE, the image plugin path; prints one JSON line.
import fs from 'node:fs';
import path from 'node:path';
import { seed, loadPlugin } from '../rootfs/usr/local/lib/pi-omnigent-ha/lifecycle.mjs';
import { createOmnigentBridge } from '../rootfs/usr/local/lib/pi-omnigent-ha/bridge.mjs';

const bundle = process.env.HA_OMNIGENT_BUNDLE;
if (!bundle) throw new Error('HA_OMNIGENT_BUNDLE must name the image plugin directory');
const seeded = seed({ bundle });
const load = () => loadPlugin({ bundle });
const plugin = await load();
const lifecycle = plugin ? await plugin.lifecycle() : { active: false, registered: false, reason: 'package-removed-or-unregistered' };
const observed = await plugin?.runtime.observeLifecycle?.(lifecycle);
const view = await createOmnigentBridge(load).read();
// Every plugin entry point the HA launcher, bridge and image smoke call.
const surface = plugin && {
  runtime: Object.fromEntries(['status', 'catalog', 'initialize', 'verify', 'disconnect', 'observeLifecycle', 'enabled', 'resumeAuthorizedHost']
    .map(name => [name, typeof plugin.runtime[name]])),
  web: Object.fromEntries(['loadPiSdk', 'packageLifecycle', 'watchPackageLifecycle', 'webLocations'].map(name => [name, typeof plugin.web[name]])),
  bootCommand: fs.existsSync(path.join(plugin.root, 'bin/cli.mjs')),
};
let extensions = null;
if (plugin && process.env.HA_CONTRACT_LOAD_EXTENSIONS === '1') {
  // The real Pi SDK loads the registered package's extension, as Pi Web does.
  const sdk = await plugin.web.loadPiSdk();
  const loader = new sdk.DefaultResourceLoader({ cwd: process.env.HOME, agentDir: process.env.PI_CODING_AGENT_DIR,
    noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true });
  await loader.reload();
  const found = loader.getExtensions();
  extensions = { errors: found.errors.map(error => String(error?.message ?? error)), paths: found.extensions.map(extension => extension.path) };
}
console.log(JSON.stringify({ seeded, root: plugin?.root ?? null, version: plugin?.version ?? null, lifecycle,
  observed: observed ?? null, enabled: plugin ? plugin.runtime.enabled() : null, view, surface, extensions }));
