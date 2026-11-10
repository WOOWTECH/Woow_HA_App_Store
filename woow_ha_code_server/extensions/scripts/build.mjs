import { cp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
export const root = fileURLToPath(new URL('../', import.meta.url));
export async function build() {
  for (const connector of ['paseo', 'omnigent']) {
    const out = path.join(root, connector, 'out');
    await rm(out, { recursive: true, force: true });
    await mkdir(out, { recursive: true });
    for (const name of ['runtime.cjs', 'ui.cjs', 'extension.cjs']) await cp(path.join(root, 'shared', name), path.join(out, name === 'extension.cjs' ? 'controller.cjs' : name));
    await writeFile(path.join(out, 'extension.cjs'), `'use strict';\nmodule.exports = require('./controller.cjs').createExtension('${connector}');\n`);
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await build();
