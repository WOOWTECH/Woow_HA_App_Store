import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { assertSafePath, RuntimeError } from './state.mjs';

// A guarded recipe for @getpaseo/server 0.11.2; no upstream source is vendored.
// Root may use normal Claude permissions, but must not request the optional
// bypass-permission launch capability that Claude rejects under root/sudo.
export const ORIGINAL_CLAUDE_SHA256 = '519318ffe2c3427e9478ebd3e29e2d28835558c9fb40ff3136f3557c1a077060';
export const PATCHED_CLAUDE_SHA256 = '197cab82770baa1f6dfdef0f7765688e3983a45afec82e003750376a2dafc1da';
const relative = 'node_modules/@getpaseo/server/dist/server/server/agent/providers/claude/agent.js';
const sha = value => createHash('sha256').update(value).digest('hex');

export function patchClaudeRootSource(source) {
  if (sha(source) === PATCHED_CLAUDE_SHA256) return source;
  if (sha(source) !== ORIGINAL_CLAUDE_SHA256) throw new RuntimeError('CLAUDE_ROOT_SOURCE_MISMATCH');
  const patched = source.replace('allowDangerouslySkipPermissions: true,', 'allowDangerouslySkipPermissions: process.getuid?.() !== 0,');
  if (sha(patched) !== PATCHED_CLAUDE_SHA256) throw new RuntimeError('CLAUDE_ROOT_PATCH_MISMATCH');
  return patched;
}

export function applyClaudeRootPatch(root) {
  const file = path.join(root, relative); assertSafePath(file);
  const source = fs.readFileSync(file, 'utf8');
  const patched = patchClaudeRootSource(source);
  if (patched !== source) fs.writeFileSync(file, patched);
}

export function claudeRootPatchReady(root) {
  try {
    const file = path.join(root, relative); assertSafePath(file);
    return sha(fs.readFileSync(file)) === PATCHED_CLAUDE_SHA256;
  } catch { return false; }
}
