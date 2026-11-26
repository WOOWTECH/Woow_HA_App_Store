import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

/** The runtime the image carries: installed, patched and verified when the image was built. */
export const BUNDLED_RUNTIME = '/opt/woow/paseo-runtime';

/**
 * The directory the Paseo plugin gets as PI_PASEO_RUNTIME_DIR.
 *
 * A runtime the user keeps in their home (the plugin's own default place, which survives image updates) has always
 * been preferred over the bundled one, and still is, but only while it can serve the plugin: the plugin itself,
 * through its own runtimeReady, accepts the release it needs there. An update that brings a newer Paseo leaves that
 * directory with the older releases only. Used as it is, the plugin would download the new one (about 0.7 GB, with a
 * 5-minute limit) at the first start although the image already carries it, installed and verified. So when the
 * saved directory cannot serve the plugin and the bundled one can, the bundled one is used.
 *
 * Nothing in the saved directory is changed, moved or removed, and no runtime is used that the plugin does not
 * accept itself. When the plugin cannot be asked (it is not found, or it has no such check) or neither directory
 * can serve it, the saved directory is kept, as this launcher always did. `pluginRoot` gives the root of the plugin
 * that will run: that plugin, not this image, decides which release it needs.
 */
export async function chooseRuntimeDir({ home, pluginRoot, bundled = BUNDLED_RUNTIME }) {
  const saved = path.join(home, '.local/share/pi-paseo/runtime');
  if (!fs.existsSync(saved)) return bundled;
  try {
    const layout = await import(pathToFileURL(path.join(await pluginRoot(), 'src/runtime-layout.mjs')).href);
    if (layout.runtimeReady({ runtimeDir: saved })) return saved;
    if (layout.runtimeReady({ runtimeDir: bundled })) return bundled;
  } catch { /* the plugin cannot say: keep what the launcher always did */ }
  return saved;
}
