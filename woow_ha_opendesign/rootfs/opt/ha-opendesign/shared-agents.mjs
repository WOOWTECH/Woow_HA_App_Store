import { copyFile, cp, lstat, mkdir, readdir, readFile, rename, rm, symlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

const RUNTIME_NAMES = ['claude', 'codex', 'pi', 'opencode'];

function runtimePaths(home, env = process.env) {
  const insideHome = (value, fallback, name) => {
    const result = path.resolve(value || fallback);
    const relative = path.relative(home, result);
    if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
      throw new Error(`${name} must stay inside the add-on HOME`);
    }
    return result;
  };
  const claudeHome = insideHome(env.CLAUDE_CONFIG_DIR, path.join(home, '.claude'), 'CLAUDE_CONFIG_DIR');
  const codexHome = insideHome(env.CODEX_HOME, path.join(home, '.codex'), 'CODEX_HOME');
  const piHome = insideHome(env.PI_CODING_AGENT_DIR, path.join(home, '.pi/agent'), 'PI_CODING_AGENT_DIR');
  const xdgHome = insideHome(env.XDG_CONFIG_HOME, path.join(home, '.config'), 'XDG_CONFIG_HOME');
  return {
    claude: { skills: path.join(claudeHome, 'skills'), mcp: path.join(home, '.claude.json') },
    codex: { skills: path.join(home, '.agents/skills'), mcp: path.join(codexHome, 'config.toml') },
    pi: { skills: path.join(piHome, 'skills'), mcp: path.join(piHome, 'mcp.json') },
    opencode: { skills: path.join(xdgHome, 'opencode/skills'), mcp: path.join(xdgHome, 'opencode/opencode.json') },
  };
}

const MANAGED_START = '# BEGIN ha-opendesign shared MCP';
const MANAGED_END = '# END ha-opendesign shared MCP';
const MANAGED_PREFIX = 'ha-shared-';

async function exists(target) {
  try { return await lstat(target); } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

async function ensureRealDirectory(target) {
  const stat = await exists(target);
  if (!stat) await mkdir(target, { recursive: true, mode: 0o750 });
  else if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`refusing non-directory or symbolic-link path: ${target}`);
  }
}

async function ensureSafeParents(home, relative) {
  const parts = relative.split(path.sep).slice(0, -1);
  let current = home;
  await ensureRealDirectory(home);
  for (const part of parts) {
    current = path.join(current, part);
    await ensureRealDirectory(current);
  }
}

async function migrateSkills(source, canonical, runtime) {
  const stat = await exists(source);
  if (!stat) {
    await mkdir(path.dirname(source), { recursive: true, mode: 0o750 });
    await symlink(canonical, source, 'dir');
    return { linked: true, migrated: 0, conflicts: [] };
  }
  if (stat.isSymbolicLink()) {
    const resolved = path.resolve(path.dirname(source), await (await import('node:fs/promises')).readlink(source));
    if (resolved !== canonical) throw new Error(`refusing unexpected skills symlink: ${source}`);
    return { linked: true, migrated: 0, conflicts: [] };
  }
  if (!stat.isDirectory()) throw new Error(`refusing non-directory skills path: ${source}`);

  const conflicts = [];
  let migrated = 0;
  for (const entry of await readdir(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name);
    const to = path.join(canonical, entry.name);
    if (await exists(to)) {
      conflicts.push(entry.name);
      const preserved = path.join(canonical, '.migration-conflicts', runtime, entry.name);
      await mkdir(path.dirname(preserved), { recursive: true, mode: 0o750 });
      if (!(await exists(preserved))) {
        if (entry.isDirectory() && !entry.isSymbolicLink()) {
          const { cp } = await import('node:fs/promises');
          await cp(from, preserved, { recursive: true, errorOnExist: true, force: false, dereference: false });
        } else if (entry.isFile()) await copyFile(from, preserved);
      }
      continue;
    }
    if (entry.isSymbolicLink()) {
      conflicts.push(`${entry.name} (symbolic link retained in backup)`);
      continue;
    }
    if (entry.isDirectory()) {
      const { cp } = await import('node:fs/promises');
      await cp(from, to, { recursive: true, errorOnExist: true, force: false, dereference: false });
    } else if (entry.isFile()) await copyFile(from, to);
    migrated += 1;
  }

  const backup = `${source}.pre-shared`;
  if (await exists(backup)) throw new Error(`skills migration backup already exists: ${backup}`);
  await rename(source, backup);
  await symlink(canonical, source, 'dir');
  return { linked: true, migrated, conflicts, backup };
}

function validateMcpCatalog(catalog) {
  if (!catalog || catalog.version !== 1 || !Array.isArray(catalog.servers)) {
    throw new Error('shared MCP catalog must have version 1 and a servers array');
  }
  const names = new Set();
  for (const server of catalog.servers) {
    if (!server || typeof server.name !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(server.name) || names.has(server.name)) {
      throw new Error('MCP server names must be unique alphanumeric, underscore, or hyphen identifiers');
    }
    names.add(server.name);
    if (server.enabled === false) continue;
    const stdio = typeof server.command === 'string' && Array.isArray(server.args ?? []);
    const http = typeof server.url === 'string' && /^https?:\/\//.test(server.url);
    if (stdio === http) throw new Error(`MCP server ${server.name} must define exactly one of command or http url`);
    if (stdio && !(server.args ?? []).every((arg) => typeof arg === 'string')) throw new Error(`MCP server ${server.name} args must be strings`);
  }
}

function activeServers(catalog) {
  return catalog.servers.filter((server) => server.enabled !== false);
}

function jsonFor(server) {
  if (server.url) return { type: 'http', url: server.url, ...(server.headers ? { headers: server.headers } : {}) };
  return { command: server.command, args: server.args ?? [], ...(server.cwd ? { cwd: server.cwd } : {}) };
}

function tomlString(value) { return JSON.stringify(value); }
function tomlInlineStringTable(value) {
  return `{ ${Object.entries(value).map(([key, item]) => `${tomlString(key)} = ${tomlString(item)}`).join(', ')} }`;
}

function removeManagedBlock(text) {
  const start = text.indexOf(MANAGED_START);
  if (start < 0) return text.trimEnd();
  const end = text.indexOf(MANAGED_END, start);
  if (end < 0) throw new Error('found incomplete shared MCP block in Codex config');
  return `${text.slice(0, start)}${text.slice(end + MANAGED_END.length)}`.trimEnd();
}

function codexTomlBlock(servers) {
  const lines = [MANAGED_START];
  for (const server of servers) {
    lines.push(`[mcp_servers.${MANAGED_PREFIX}${server.name}]`, `enabled = ${server.enabled !== false}`);
    if (server.url) lines.push(`url = ${tomlString(server.url)}`);
    else {
      lines.push(`command = ${tomlString(server.command)}`);
      if ((server.args ?? []).length) lines.push(`args = [${server.args.map(tomlString).join(', ')}]`);
      if (server.cwd) lines.push(`cwd = ${tomlString(server.cwd)}`);
    }
    if (server.headers) lines.push(`http_headers = ${tomlInlineStringTable(server.headers)}`);
    lines.push('');
  }
  lines.push(MANAGED_END);
  return lines.join('\n');
}

async function mergeJsonConfig(file, key, servers, mapServer) {
  let config = {};
  const current = await exists(file);
  if (current) {
    if (!current.isFile() || current.isSymbolicLink()) throw new Error(`refusing unsafe config file: ${file}`);
    config = JSON.parse(await readFile(file, 'utf8'));
  }
  if (config[key] === undefined) config[key] = {};
  else if (!config[key] || typeof config[key] !== 'object' || Array.isArray(config[key])) {
    throw new Error(`refusing invalid ${key} value in config file: ${file}`);
  }
  for (const name of Object.keys(config[key])) {
    if (name.startsWith(MANAGED_PREFIX)) delete config[key][name];
  }
  for (const server of servers) {
    const name = `${MANAGED_PREFIX}${server.name}`;
    if (Object.hasOwn(config[key], name)) throw new Error(`MCP server name is reserved for shared configuration: ${name}`);
    config[key][name] = mapServer(server);
  }
  await atomicWrite(file, `${JSON.stringify(config, null, 2)}\n`);
}

async function atomicWrite(file, content) {
  await mkdir(path.dirname(file), { recursive: true, mode: 0o750 });
  const tmp = `${file}.ha-opendesign-${process.pid}.tmp`;
  await writeFile(tmp, content, { mode: 0o600 });
  await rename(tmp, file);
}

async function syncMcp(home, sharedRoot, paths) {
  const catalogFile = path.join(sharedRoot, 'mcp', 'servers.json');
  const catalog = JSON.parse(await readFile(catalogFile, 'utf8'));
  validateMcpCatalog(catalog);
  const servers = activeServers(catalog);
  const status = {};

  const claudeFile = paths.claude.mcp;
  await mergeJsonConfig(claudeFile, 'mcpServers', servers, jsonFor);
  status.claude = claudeFile;

  const piFile = paths.pi.mcp;
  await mergeJsonConfig(piFile, 'mcpServers', servers, (server) => server.url
    ? { url: server.url, ...(server.headers ? { headers: server.headers } : {}) }
    : { command: server.command, args: server.args ?? [], ...(server.cwd ? { cwd: server.cwd } : {}) });
  status.pi = piFile;

  const opencodeFile = paths.opencode.mcp;
  await mergeJsonConfig(opencodeFile, 'mcp', servers, (server) => server.url
    ? { type: 'remote', url: server.url, ...(server.headers ? { headers: server.headers } : {}) }
    : { type: 'local', command: [server.command, ...(server.args ?? [])], ...(server.cwd ? { cwd: server.cwd } : {}) });
  status.opencode = opencodeFile;

  const codexFile = paths.codex.mcp;
  let codexText = '';
  const codexStat = await exists(codexFile);
  if (codexStat) {
    if (!codexStat.isFile() || codexStat.isSymbolicLink()) throw new Error(`refusing unsafe config file: ${codexFile}`);
    codexText = await readFile(codexFile, 'utf8');
  }
  codexText = removeManagedBlock(codexText);
  const namesInUse = [...codexText.matchAll(/^\s*\[mcp_servers\.([^\]]+)\]\s*$/gm)].map((match) => match[1]);
  const collisions = servers.map((server) => `${MANAGED_PREFIX}${server.name}`).filter((name) => namesInUse.includes(name));
  if (collisions.length) throw new Error(`Codex MCP names already configured outside the managed block: ${collisions.join(', ')}`);
  const combined = `${codexText}${codexText ? '\n\n' : ''}${codexTomlBlock(servers)}\n`;
  await atomicWrite(codexFile, combined);
  status.codex = codexFile;
  return status;
}

async function discoverSharedPlugins(sharedRoot, catalog) {
  const root = path.join(sharedRoot, 'plugins');
  const mcpNames = new Set(catalog.servers.map((server) => server.name));
  const plugins = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
    const directory = path.join(root, entry.name);
    const manifestPath = path.join(directory, 'manifest.json');
    const stat = await exists(manifestPath);
    if (!stat) continue;
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`refusing unsafe plugin manifest: ${manifestPath}`);
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    if (manifest.schemaVersion !== 1 || manifest.name !== entry.name || !manifest.components || typeof manifest.components !== 'object') {
      throw new Error(`invalid shared plugin manifest: ${manifestPath}`);
    }
    const skills = manifest.components.skills ?? [];
    const mcpServers = manifest.components.mcpServers ?? [];
    if (!Array.isArray(skills) || !Array.isArray(mcpServers)) throw new Error(`invalid plugin component lists: ${manifestPath}`);
    const missingSkills = [];
    for (const name of skills) {
      if (typeof name !== 'string' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)
        || !(await exists(path.join(sharedRoot, 'skills', name, 'SKILL.md')))) missingSkills.push(name);
    }
    const missingServers = mcpServers.filter((name) => !mcpNames.has(name));
    const nativeAdapters = {};
    for (const [runtime, relative] of Object.entries(manifest.nativeAdapters ?? {})) {
      if (!RUNTIME_NAMES.includes(runtime) || typeof relative !== 'string') throw new Error(`invalid native adapter declaration: ${manifestPath}`);
      const adapterPath = path.resolve(directory, relative);
      if (!adapterPath.startsWith(`${directory}${path.sep}`)) throw new Error(`plugin adapter path escapes bundle: ${manifestPath}`);
      const adapterStat = await exists(adapterPath);
      if (adapterStat?.isSymbolicLink()) throw new Error(`plugin adapter cannot be a symbolic link: ${manifestPath}`);
      nativeAdapters[runtime] = Boolean(adapterStat?.isFile());
    }
    plugins.push({ name: manifest.name, skills, mcpServers, missingSkills, missingServers, nativeAdapters });
  }
  return plugins;
}

// Bundle layout: manifest.json, skills/<skill-name>/..., and optional mcp/servers.json.
// Native adapters remain runtime-specific; this command installs only portable components.
export async function installSharedPlugin({ dataDir = '/data/opendesign', name, home, runtimeEnv = process.env } = {}) {
  if (!name || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) throw new Error('plugin name must be a lowercase hyphenated identifier');
  const root = path.join(dataDir, 'shared');
  const bundle = path.join(root, 'plugins', name);
  const manifest = JSON.parse(await readFile(path.join(bundle, 'manifest.json'), 'utf8'));
  if (manifest.schemaVersion !== 1 || manifest.name !== name || !manifest.components) throw new Error('invalid shared plugin manifest');
  const skills = manifest.components.skills ?? [];
  const mcpNames = manifest.components.mcpServers ?? [];
  if (!Array.isArray(skills) || !Array.isArray(mcpNames)) throw new Error('invalid plugin component lists');
  const stateFile = path.join(root, 'plugins', 'installed.json');
  let state = { version: 1, plugins: {} };
  if (await exists(stateFile)) state = JSON.parse(await readFile(stateFile, 'utf8'));
  if (state.version !== 1 || !state.plugins || state.plugins[name]) throw new Error(`plugin already installed or invalid install state: ${name}`);
  const catalogFile = path.join(root, 'mcp', 'servers.json');
  const catalog = JSON.parse(await readFile(catalogFile, 'utf8'));
  validateMcpCatalog(catalog);
  let selected = [];
  if (mcpNames.length) {
    const pluginCatalog = JSON.parse(await readFile(path.join(bundle, 'mcp', 'servers.json'), 'utf8'));
    validateMcpCatalog(pluginCatalog);
    selected = pluginCatalog.servers.filter((item) => mcpNames.includes(item.name));
    if (selected.length !== mcpNames.length) throw new Error('plugin MCP definitions do not match manifest');
    const collisions = selected.filter((item) => catalog.servers.some((existing) => existing.name === item.name));
    if (collisions.length) throw new Error(`MCP server already exists: ${collisions.map((item) => item.name).join(', ')}`);
  }
  const installedSkills = [];
  for (const skill of skills) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(skill)) throw new Error(`invalid skill name: ${skill}`);
    const source = path.join(bundle, 'skills', skill);
    const target = path.join(root, 'skills', skill);
    if (!(await exists(path.join(source, 'SKILL.md')))) throw new Error(`plugin skill is missing: ${skill}`);
    if (await exists(target)) throw new Error(`skill already exists; refusing to overwrite: ${skill}`);
    await cp(source, target, { recursive: true, errorOnExist: true, force: false, dereference: false });
    installedSkills.push(skill);
  }
  const installedServers = selected.map((item) => item.name);
  if (mcpNames.length) {
    catalog.servers.push(...selected);
    await atomicWrite(catalogFile, `${JSON.stringify(catalog, null, 2)}\n`);
  }
  state.plugins[name] = { skills: installedSkills, mcpServers: installedServers };
  await atomicWrite(stateFile, `${JSON.stringify(state, null, 2)}\n`);
  await initializeSharedAgents({ dataDir, home, runtimeEnv });
  return { name, skills: installedSkills, mcpServers: installedServers };
}

export async function removeSharedPlugin({ dataDir = '/data/opendesign', name, home, runtimeEnv = process.env } = {}) {
  if (!name || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) throw new Error('plugin name must be a lowercase hyphenated identifier');
  const root = path.join(dataDir, 'shared');
  const stateFile = path.join(root, 'plugins', 'installed.json');
  const state = JSON.parse(await readFile(stateFile, 'utf8'));
  const owned = state.plugins?.[name];
  if (!owned) throw new Error(`plugin is not installed: ${name}`);
  const catalogFile = path.join(root, 'mcp', 'servers.json');
  const catalog = JSON.parse(await readFile(catalogFile, 'utf8'));
  catalog.servers = catalog.servers.filter((item) => !owned.mcpServers.includes(item.name));
  await atomicWrite(catalogFile, `${JSON.stringify(catalog, null, 2)}\n`);
  for (const skill of owned.skills) await rm(path.join(root, 'skills', skill), { recursive: true, force: true });
  delete state.plugins[name];
  await atomicWrite(stateFile, `${JSON.stringify(state, null, 2)}\n`);
  await initializeSharedAgents({ dataDir, home, runtimeEnv });
  return { name, removedSkills: owned.skills, removedMcpServers: owned.mcpServers };
}

export async function initializeSharedAgents({ home, dataDir = '/data/opendesign', runtimeEnv = process.env } = {}) {
  home ??= runtimeEnv.HA_OPENDESIGN_HOME || runtimeEnv.HOME;
  if (!home) throw new Error('HOME is required');
  const sharedRoot = path.join(dataDir, 'shared');
  await ensureRealDirectory(dataDir);
  await ensureRealDirectory(sharedRoot);
  for (const directory of ['skills', 'mcp', 'plugins', 'workspaces']) {
    await ensureRealDirectory(path.join(sharedRoot, directory));
  }
  const workspaceInstructions = path.join(sharedRoot, 'workspaces', 'AGENTS.md');
  if (!(await exists(workspaceInstructions))) {
    await writeFile(workspaceInstructions,
      '# Shared OpenDesign workspace\n\nFiles saved in this directory are visible to Claude Code, Codex, Pi, and OpenCode when they are launched from this workspace. Shared skills live in `../skills`; shared MCP server definitions live in `../mcp/servers.json`.\n',
      { mode: 0o640 });
  }
  const catalogFile = path.join(sharedRoot, 'mcp', 'servers.json');
  const catalogStat = await exists(catalogFile);
  if (!catalogStat) await writeFile(catalogFile, '{\n  "version": 1,\n  "servers": []\n}\n', { mode: 0o600 });
  else if (!catalogStat.isFile() || catalogStat.isSymbolicLink()) throw new Error(`refusing unsafe MCP catalog: ${catalogFile}`);

  const skillLinks = {};
  const paths = runtimePaths(home, runtimeEnv);
  for (const [runtime, runtimePath] of Object.entries(paths)) {
    await ensureSafeParents(home, path.relative(home, runtimePath.skills));
    await ensureSafeParents(home, path.relative(home, runtimePath.mcp));
    skillLinks[runtime] = await migrateSkills(runtimePath.skills, path.join(sharedRoot, 'skills'), runtime);
  }
  const mcp = await syncMcp(home, sharedRoot, paths);
  const catalog = JSON.parse(await readFile(path.join(sharedRoot, 'mcp/servers.json'), 'utf8'));
  const plugins = await discoverSharedPlugins(sharedRoot, catalog);
  return { sharedRoot, skills: skillLinks, mcp, plugins, workspace: path.join(sharedRoot, 'workspaces') };
}

export async function statusSharedAgents({ home, dataDir = '/data/opendesign', runtimeEnv = process.env } = {}) {
  home ??= runtimeEnv.HA_OPENDESIGN_HOME || runtimeEnv.HOME;
  if (!home) throw new Error('HOME is required');
  const sharedRoot = path.join(dataDir, 'shared');
  const skills = {};
  const paths = runtimePaths(home, runtimeEnv);
  for (const [runtime, runtimePath] of Object.entries(paths)) {
    const target = runtimePath.skills;
    const stat = await exists(target);
    skills[runtime] = stat?.isSymbolicLink()
      ? path.resolve(path.dirname(target), await (await import('node:fs/promises')).readlink(target)) === path.join(sharedRoot, 'skills')
      : false;
  }
  const catalog = JSON.parse(await readFile(path.join(sharedRoot, 'mcp/servers.json'), 'utf8'));
  validateMcpCatalog(catalog);
  const plugins = await discoverSharedPlugins(sharedRoot, catalog);
  return { sharedRoot, workspace: path.join(sharedRoot, 'workspaces'), skills, mcpServerCount: activeServers(catalog).length, plugins };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    const args = process.argv.slice(2);
    let result;
    if (args[0] === '--status') result = await statusSharedAgents();
    else if (args[0] === '--plugin-install') result = await installSharedPlugin({ name: args[1] });
    else if (args[0] === '--plugin-remove') result = await removeSharedPlugin({ name: args[1] });
    else result = await initializeSharedAgents();
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } catch (error) {
    process.stderr.write(`[shared-agents] ${error.message}\n`);
    process.exitCode = 1;
  }
}
