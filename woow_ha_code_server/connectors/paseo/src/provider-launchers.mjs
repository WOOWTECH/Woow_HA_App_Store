import path from 'node:path';
import { findExecutable, runProcess } from './process.mjs';

export const PROVIDERS = Object.freeze(['claude', 'codex', 'pi']);

export function providerEnvironment(loc, env = process.env) {
  return {
    ...env,
    HOME: loc.home,
    PI_AGENT_DATA_DIR: env.PI_AGENT_DATA_DIR || loc.dataDir,
    PI_CODING_AGENT_DIR: env.PI_CODING_AGENT_DIR || loc.agentDir,
    CLAUDE_CONFIG_DIR: env.CLAUDE_CONFIG_DIR || path.join(loc.dataDir, 'claude'),
    CODEX_HOME: env.CODEX_HOME || path.join(loc.dataDir, 'codex'),
    // Engines are image-pinned. A client or SDK child must never self-update the
    // shared executable, even if a caller's ambient environment says otherwise.
    DISABLE_AUTOUPDATER: '1',
  };
}

// Only discover existing agents; never npm-install an engine or copy credentials.
export async function resolveProviderLaunchers(loc, { env = process.env, discover = findExecutable, run = runProcess } = {}) {
  const result = {};
  const inherited = providerEnvironment(loc, env);
  await Promise.all(PROVIDERS.map(async provider => {
    const command = discover(provider, inherited);
    const row = result[provider] = { command, version: null, startup: command ? 'invalid' : 'missing' };
    if (!command) return;
    try {
      const output = await run(command, ['--version'], { env: inherited, timeoutMs: 10000, maxBytes: 4096 });
      row.version = output.trim().match(/\d+\.\d+\.\d+/)?.[0] || null;
      row.startup = row.version ? 'ready' : 'invalid';
    } catch { row.startup = 'PROVIDER_LAUNCH_FAILED'; }
  }));
  return result;
}

export function configureProviders(previous, launchers, loc, env = process.env) {
  const inherited = providerEnvironment(loc, env);
  const providerEnv = Object.fromEntries(['HOME', 'PI_AGENT_DATA_DIR', 'PI_CODING_AGENT_DIR', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME'].map(key => [key, inherited[key]]));
  // This is a connector-private config: never enable other engines implicitly.
  return Object.fromEntries(PROVIDERS.map(provider => [provider, {
    enabled: launchers[provider].startup === 'ready',
    ...(launchers[provider].command ? { command: [path.resolve(launchers[provider].command)] } : {}),
    env: provider === 'claude' ? { ...providerEnv, DISABLE_AUTOUPDATER: '1' } : { ...providerEnv },
  }]));
}
