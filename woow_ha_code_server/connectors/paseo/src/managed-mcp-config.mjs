import fs from 'node:fs';
import path from 'node:path';

// Runs inside the daemon's locked idle lifecycle, before closing the old engine.
// Read synchronized native definitions; never reuse old managed executables from
// the persisted conversation or its provider metadata. Native Pi loads its own
// MCP extension from disk, rather than accepting external ACP MCP definitions.
export function refreshedManagedConfig(config, env = process.env) {
  try {
    const data = env.PI_AGENT_DATA_DIR || '/data/pi-agent';
    const managed = JSON.parse(fs.readFileSync(path.join(data, 'shared/managed.json'), 'utf8'));
    const names = managed.managedServers || managed.servers;
    if (!Array.isArray(names) || names.some(name => typeof name !== 'string' || !name)) throw new Error();
    const native = JSON.parse(fs.readFileSync(path.join(env.CLAUDE_CONFIG_DIR || path.join(data, 'claude'), '.claude.json'), 'utf8'));
    if (!native || typeof native !== 'object' || Array.isArray(native) || (native.mcpServers !== undefined && (!native.mcpServers || typeof native.mcpServers !== 'object' || Array.isArray(native.mcpServers)))) throw new Error();
    const servers = {...config.mcpServers};
    for (const name of names) {
      delete servers[name];
      if (config.provider !== 'pi' && Object.hasOwn(native.mcpServers || {}, name)) Object.defineProperty(servers, name, {value:native.mcpServers[name],enumerable:true,configurable:true,writable:true});
    }
    return {...config, mcpServers: servers};
  } catch {
    // Registry/parser errors must not expose native configuration or credentials.
    throw new Error('MCP_CONFIG_INVALID');
  }
}
