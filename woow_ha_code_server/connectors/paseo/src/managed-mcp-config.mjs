import fs from 'node:fs';
import path from 'node:path';

// Runs inside the daemon's locked idle lifecycle, before closing the old engine.
// Read synchronized native definitions; never reuse old managed executables from
// the persisted conversation or its provider metadata. Native Pi loads its own
// MCP extension from disk, rather than accepting external ACP MCP definitions.
export function refreshedManagedConfig(config, env = process.env) {
  const data = env.PI_AGENT_DATA_DIR || '/data/pi-agent';
  const managed = JSON.parse(fs.readFileSync(path.join(data, 'shared/managed.json'), 'utf8'));
  const names = managed.managedServers || managed.servers;
  if (!Array.isArray(names) || names.some(name => typeof name !== 'string')) throw new Error('MCP_CONFIG_INVALID');
  const native = JSON.parse(fs.readFileSync(path.join(env.CLAUDE_CONFIG_DIR || path.join(data, 'claude'), '.claude.json'), 'utf8'));
  const servers = {...config.mcpServers};
  for (const name of names) {
    delete servers[name];
    if (config.provider !== 'pi' && Object.hasOwn(native.mcpServers || {}, name)) servers[name] = native.mcpServers[name];
  }
  return {...config, mcpServers: servers};
}
