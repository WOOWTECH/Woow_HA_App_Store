#!/usr/bin/env node

import { chmodSync, cpSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, readlinkSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import path from "node:path";

const data = process.env.PI_AGENT_DATA_DIR || process.env.PI_CODING_AGENT_DIR || "/data/pi-agent";
const home = process.env.HOME || path.join(data, "home");
const skills = path.join(data, "skills");
const workspace = path.join(data, "workspace");
const piExtensions = path.join(data, "plugins/pi");
const manifest = path.join(data, "mcp.json");
const marker = "# BEGIN pi-agent shared MCP (managed)";
const endMarker = "# END pi-agent shared MCP (managed)";
const managedList = path.join(data, ".shared-mcp-managed.json");
const pluginSkillLinks = path.join(data, ".shared-plugin-skills.json");

function ensureDir(dir) { mkdirSync(dir, { recursive: true, mode: 0o700 }); }
function atomicWrite(file, contents) {
  ensureDir(path.dirname(file));
  const tmp = `${file}.${process.pid}.tmp`;
  writeFileSync(tmp, contents, { mode: 0o600 });
  renameSync(tmp, file);
}
function linkDir(target, link) {
  ensureDir(path.dirname(link));
  try {
    const stat = lstatSync(link);
    if (stat.isSymbolicLink() && path.resolve(path.dirname(link), readlinkSync(link)) === path.resolve(target)) return;
    if (stat.isDirectory() && !stat.isSymbolicLink()) cpSync(link, target, { recursive: true, force: false, errorOnExist: false });
    rmSync(link, { recursive: true, force: true });
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  symlinkSync(target, link, "dir");
}
function tomlString(value) { return JSON.stringify(String(value)); }
function tomlValue(value) {
  if (typeof value === "string") return tomlString(value);
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return `[${value.map(tomlValue).join(", ")}]`;
  if (value && typeof value === "object") return `{ ${Object.entries(value).map(([key, item]) => `${tomlString(key)} = ${tomlValue(item)}`).join(", ")} }`;
  throw new Error(`Unsupported MCP TOML value: ${typeof value}`);
}
function codexMcpBlock(servers) {
  const lines = [marker];
  for (const [name, server] of Object.entries(servers)) {
    if (!/^[A-Za-z0-9_.-]+$/.test(name)) throw new Error(`Invalid MCP server name: ${name}`);
    lines.push(`\n[mcp_servers.${tomlString(name)}]`);
    if (server.url) {
      lines.push(`url = ${tomlString(server.url)}`);
      if (server.headers && Object.keys(server.headers).length) lines.push(`http_headers = ${tomlValue(server.headers)}`);
    } else {
      if (!server.command) throw new Error(`MCP server ${name} needs command or url`);
      lines.push(`command = ${tomlString(server.command)}`);
      if (server.args) lines.push(`args = ${tomlValue(server.args)}`);
      if (server.cwd) lines.push(`cwd = ${tomlString(server.cwd)}`);
      if (server.env && Object.keys(server.env).length) lines.push(`env = ${tomlValue(server.env)}`);
    }
  }
  lines.push(endMarker);
  return lines.join("\n");
}

ensureDir(data); ensureDir(home); ensureDir(skills); ensureDir(workspace); ensureDir(piExtensions);
if (!existsSync(manifest)) atomicWrite(manifest, `${JSON.stringify({ mcpServers: {} }, null, 2)}\n`);
const parsed = JSON.parse(readFileSync(manifest, "utf8"));
if (!parsed.mcpServers || typeof parsed.mcpServers !== "object" || Array.isArray(parsed.mcpServers)) throw new Error(`${manifest} must contain an mcpServers object`);
const servers = {};
const activeSkillLinks = {};
const pluginRoot = path.join(data, "plugins");
ensureDir(pluginRoot);
for (const pluginId of readdirSync(pluginRoot).sort()) {
  if (pluginId === "pi") continue;
  const pluginDir = path.join(pluginRoot, pluginId);
  if (!lstatSync(pluginDir).isDirectory()) continue;
  const pluginManifest = path.join(pluginDir, "plugin.json");
  if (!existsSync(pluginManifest)) continue;
  const plugin = JSON.parse(readFileSync(pluginManifest, "utf8"));
  for (const relative of plugin.skills || []) {
    const source = path.resolve(pluginDir, relative);
    if (!source.startsWith(`${pluginDir}${path.sep}`) || !existsSync(path.join(source, "SKILL.md"))) throw new Error(`Invalid plugin skill path: ${pluginId}/${relative}`);
    const skillName = path.basename(source);
    const destination = path.join(skills, skillName);
    if (existsSync(destination) && !lstatSync(destination).isSymbolicLink()) throw new Error(`Portable plugin skill collides with existing skill: ${skillName}`);
    if (existsSync(destination) && path.resolve(path.dirname(destination), readlinkSync(destination)) !== source) throw new Error(`Portable plugin skill name collision: ${skillName}`);
    if (!existsSync(destination)) symlinkSync(source, destination, "dir");
    activeSkillLinks[skillName] = source;
  }
  for (const [name, server] of Object.entries(plugin.mcpServers || {})) {
    if (servers[name]) throw new Error(`Portable plugins define duplicate MCP server: ${name}`);
    servers[name] = server;
  }
}
const oldSkillLinks = existsSync(pluginSkillLinks) ? JSON.parse(readFileSync(pluginSkillLinks, "utf8")) : [];
for (const [skillName, oldTarget] of Object.entries(Array.isArray(oldSkillLinks) ? Object.fromEntries(oldSkillLinks.map((name) => [name, ""])) : oldSkillLinks)) {
  if (activeSkillLinks[skillName]) continue;
  const destination = path.join(skills, skillName);
  try {
    if (lstatSync(destination).isSymbolicLink() && (!oldTarget || path.resolve(path.dirname(destination), readlinkSync(destination)) === oldTarget)) rmSync(destination);
  } catch (error) { if (error.code !== "ENOENT") throw error; }
}
atomicWrite(pluginSkillLinks, `${JSON.stringify(activeSkillLinks)}\n`);
Object.assign(servers, parsed.mcpServers);

for (const target of [path.join(home, ".pi/agent/skills"), path.join(home, ".claude/skills"), path.join(home, ".agents/skills")]) linkDir(skills, target);
linkDir(piExtensions, path.join(home, ".pi/agent/extensions"));
linkDir(workspace, path.join(home, "workspace"));

// CLI launchers refresh translated MCP settings immediately before the agent
// starts. This makes edits to the Pi-native mcp.json visible on the next launch
// while leaving each CLI's credential and unrelated settings files in place.
const binDir = path.join(home, ".local/bin");
ensureDir(binDir);
for (const name of ["claude", "codex"]) {
  const launcher = path.join(binDir, name);
  const body = `#!/bin/sh\n# pi-agent shared MCP launcher\nnode /usr/local/bin/pi-agent-share-state.mjs || exit $?\nexec /usr/local/bin/${name} "$@"\n`;
  if (existsSync(launcher) && !readFileSync(launcher, "utf8").includes("# pi-agent shared MCP launcher")) continue;
  writeFileSync(launcher, body, { mode: 0o700 });
  chmodSync(launcher, 0o700);
}

// Claude stores user MCP servers beside its auth state. Preserve all unrelated
// settings and merge only the shared server map.
const claudeConfig = path.join(home, ".claude.json");
let claude = {};
if (existsSync(claudeConfig)) claude = JSON.parse(readFileSync(claudeConfig, "utf8"));
const previous = existsSync(managedList) ? JSON.parse(readFileSync(managedList, "utf8")) : [];
claude.mcpServers ||= {};
for (const name of previous) if (!(name in servers)) delete claude.mcpServers[name];
for (const [name, server] of Object.entries(servers)) {
  claude.mcpServers[name] = server.url
    ? { type: "http", url: server.url, ...(server.headers ? { headers: server.headers } : {}) }
    : server;
}
atomicWrite(claudeConfig, `${JSON.stringify(claude, null, 2)}\n`);

// Codex uses TOML. Replace only our marked block and retain the user's other
// settings and MCP entries. The same mcp.json remains Pi's native source.
const codexConfig = path.join(home, ".codex/config.toml");
ensureDir(path.dirname(codexConfig));
let codexText = existsSync(codexConfig) ? readFileSync(codexConfig, "utf8") : "";
const managedBlock = codexMcpBlock(servers);
const escapedMarker = marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const escapedEnd = endMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const managedPattern = new RegExp(`${escapedMarker}[\\s\\S]*?${escapedEnd}\\n?`, "g");
codexText = codexText.replace(managedPattern, "").trimEnd();
// A server with the same name may already have been added directly with the
// Codex CLI. The shared manifest owns that name, so remove its old table block
// before writing the updated managed definition (including any subtables).
const sharedNames = new Set(Object.keys(servers));
const lines = codexText.split("\n");
const retained = [];
let skipTable = false;
for (const line of lines) {
  const table = line.match(/^\s*\[\[?mcp_servers\.(?:"([^"]+)"|([A-Za-z0-9_.-]+))(?:\.|\])/)?.slice(1).find(Boolean);
  if (/^\s*\[/.test(line)) skipTable = Boolean(table && sharedNames.has(table));
  if (!skipTable) retained.push(line);
}
codexText = retained.join("\n").trimEnd();
if (Object.keys(servers).length) codexText = `${codexText}${codexText ? "\n\n" : ""}${managedBlock}\n`;
atomicWrite(codexConfig, codexText);
atomicWrite(managedList, `${JSON.stringify(Object.keys(servers))}\n`);
console.log(`Shared agent state ready: ${Object.keys(servers).length} MCP server(s), ${skills}, ${workspace}`);
