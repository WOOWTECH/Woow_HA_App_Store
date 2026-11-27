import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { assertSafePath, RuntimeError } from './state.mjs';

// A guarded recipe for @getpaseo/server 0.17.5.
// Root may use normal Claude permissions, but must not request the optional
// bypass-permission launch capability that Claude rejects under root/sudo.
export const ORIGINAL_CLAUDE_SHA256 = '6f56bf2aee54221707b40ea35bcc201525190d6e88a20c0414f465c1ba088569';
export const PATCHED_CLAUDE_SHA256 = 'd44fcc2ec7030493b5cce892b554243dbf47aca9ef728cc7f9e575501de888f2';
export const CLAUDE_ROOT_PATH = 'node_modules/@getpaseo/server/dist/server/server/agent/providers/claude/agent.js';
const sha = value => createHash('sha256').update(value).digest('hex');
export const CLAUDE_ROOT_PATCH_ID = sha(ORIGINAL_CLAUDE_SHA256 + ':' + PATCHED_CLAUDE_SHA256);

export function patchClaudeRootSource(source) {
  if (sha(source) === PATCHED_CLAUDE_SHA256) return source;
  if (sha(source) !== ORIGINAL_CLAUDE_SHA256) throw new RuntimeError('CLAUDE_ROOT_SOURCE_MISMATCH');
  const patched = source.replace('allowDangerouslySkipPermissions: true,', 'allowDangerouslySkipPermissions: process.getuid?.() !== 0,')
    .replace('            env: sdkEnv,\n        };\n        if (this.config.mcpServers) {',
      '            env: sdkEnv,\n            ...(process.getuid?.() === 0 ? { allowDangerouslySkipPermissions: false } : {}),\n        };\n        if (this.config.mcpServers) {');
  if (sha(patched) !== PATCHED_CLAUDE_SHA256) throw new RuntimeError('CLAUDE_ROOT_PATCH_MISMATCH');
  return patched;
}

export function applyClaudeRootPatch(root) {
  const file = path.join(root, CLAUDE_ROOT_PATH); assertSafePath(file);
  const source = fs.readFileSync(file, 'utf8');
  const patched = patchClaudeRootSource(source);
  if (patched !== source) fs.writeFileSync(file, patched);
}

export function claudeRootPatchReady(root) {
  try {
    const file = path.join(root, CLAUDE_ROOT_PATH); assertSafePath(file);
    return sha(fs.readFileSync(file)) === PATCHED_CLAUDE_SHA256;
  } catch { return false; }
}
