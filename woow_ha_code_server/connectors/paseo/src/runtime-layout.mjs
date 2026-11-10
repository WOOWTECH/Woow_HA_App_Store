import {mcpRefreshPatchReady} from './mcp-refresh-patch.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { assertSafePath } from './state.mjs';
import { pidLockPatchReady } from './pid-lock-patch.mjs';
import { claudeRootPatchReady } from './claude-root-patch.mjs';

const lock = fs.readFileSync(new URL('../runtime/package-lock.json', import.meta.url));
export const lockSha256 = createHash('sha256').update(lock).digest('hex');
export const RUNTIME_REVISION = 'woow-code-server-0.11.2-r3-' + lockSha256.slice(0, 12);
export const runtimeDirectory = loc => loc.runtimeDir;

// Read-only validation: neither importing nor starting the adapter installs anything.
export function runtimeReady(loc) {
  try {
    const root = runtimeDirectory(loc);
    for (const pkg of ['cli', 'server']) {
      const file = path.join(root, 'node_modules/@getpaseo', pkg, 'package.json');
      assertSafePath(file);
      if (JSON.parse(fs.readFileSync(file)).version !== '0.11.2') return false;
    }
    if (createHash('sha256').update(fs.readFileSync(path.join(root, 'package-lock.json'))).digest('hex') !== lockSha256) return false;
    return mcpRefreshPatchReady(root) && pidLockPatchReady(root) && claudeRootPatchReady(root) && fs.existsSync(path.join(root, 'node_modules/@getpaseo/cli/bin/paseo'));
  } catch { return false; }
}
