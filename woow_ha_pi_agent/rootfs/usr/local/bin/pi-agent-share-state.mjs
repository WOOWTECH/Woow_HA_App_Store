#!/usr/bin/env node

import { cpSync, existsSync, lstatSync, mkdirSync, readFileSync, readlinkSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
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
const previousSkillLinks = path.join(data, ".shared-plugin-skills.json");

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
  try {
    symlinkSync(target, link, "dir");
  } catch (error) {
    // Two CLI launches can refresh at once; keep the other run's identical link.
    if (error.code !== "EEXIST" || path.resolve(path.dirname(link), readlinkSync(link)) !== path.resolve(target)) throw error;
  }
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
// Remove only skill links previously owned by the old portable-plugin sync.
// Current shared skills must be installed through Pi Web's skills directory.
const oldSkillLinks = existsSync(previousSkillLinks) ? JSON.parse(readFileSync(previousSkillLinks, "utf8")) : [];
for (const [skillName, oldTarget] of Object.entries(Array.isArray(oldSkillLinks) ? Object.fromEntries(oldSkillLinks.map((name) => [name, ""])) : oldSkillLinks)) {
  const destination = path.join(skills, skillName);
  try {
    if (lstatSync(destination).isSymbolicLink() && (!oldTarget || path.resolve(path.dirname(destination), readlinkSync(destination)) === oldTarget)) rmSync(destination);
  } catch (error) { if (error.code !== "ENOENT") throw error; }
}
if (existsSync(previousSkillLinks)) rmSync(previousSkillLinks);
const servers = parsed.mcpServers;

for (const target of [path.join(home, ".pi/agent/skills"), path.join(home, ".claude/skills"), path.join(home, ".agents/skills")]) linkDir(skills, target);
linkDir(piExtensions, path.join(home, ".pi/agent/extensions"));
linkDir(workspace, path.join(home, "workspace"));

// /usr/local/bin/claude and /usr/local/bin/codex run this script before every
// launch. 0.14.8 and earlier wrote refresh launchers into ~/.local/bin instead,
// which the browser terminal's login shell never reached. Retire only the
// launchers this script wrote; a user's own binaries there keep precedence.
for (const name of ["claude", "codex"]) {
  const launcher = path.join(home, ".local/bin", name);
  try {
    if (lstatSync(launcher).isFile() && readFileSync(launcher, "utf8").includes("# pi-agent shared MCP launcher")) rmSync(launcher);
  } catch (error) { if (error.code !== "ENOENT") throw error; }
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
console.log(`Shared agent state ready: ${Object.keys(servers).length} Pi Web global MCP server(s), ${skills}, ${workspace}`);
