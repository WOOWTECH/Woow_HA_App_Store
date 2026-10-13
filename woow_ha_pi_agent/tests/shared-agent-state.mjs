#!/usr/bin/env node
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const repo = process.cwd();
const temp = mkdtempSync(path.join(os.tmpdir(), "pi-agent-shared-state-"));
const data = path.join(temp, "data");
const home = path.join(data, "home");
const sync = path.join(repo, "rootfs/usr/local/bin/pi-agent-share-state.mjs");
const run = () => {
  const result = spawnSync(process.execPath, [sync], {
    env: { ...process.env, PI_AGENT_DATA_DIR: data, PI_CODING_AGENT_DIR: data, HOME: home },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
};

try {
  mkdirSync(path.join(home, ".claude"), { recursive: true });
  writeFileSync(path.join(home, ".claude.json"), JSON.stringify({ oauthAccount: { id: "keep" }, custom: true }));
  mkdirSync(path.join(data, "plugins/demo/skills/demo-skill"), { recursive: true });
  writeFileSync(path.join(data, "plugins/demo/skills/demo-skill/SKILL.md"), "---\nname: demo-skill\ndescription: shared\n---\n");
  writeFileSync(path.join(data, "plugins/demo/plugin.json"), JSON.stringify({
    skills: ["skills/demo-skill"],
    mcpServers: { portable: { command: "node", args: ["server.js"], env: { TOKEN: "from-plugin" } } },
  }));
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: { docs: { url: "https://example.test/mcp", headers: { Authorization: "Bearer test" } } } }));
  run();

  const canonicalSkills = path.join(data, "skills");
  for (const agentPath of [".pi/agent/skills", ".claude/skills", ".agents/skills"]) {
    assert.equal(realpathSync(path.join(home, agentPath)), realpathSync(canonicalSkills), `${agentPath} shares canonical skills`);
  }
  assert.equal(realpathSync(path.join(home, "workspace")), realpathSync(path.join(data, "workspace")));
  assert.equal(realpathSync(path.join(canonicalSkills, "demo-skill")), realpathSync(path.join(data, "plugins/demo/skills/demo-skill")));
  const claude = JSON.parse(readFileSync(path.join(home, ".claude.json"), "utf8"));
  assert.equal(claude.oauthAccount.id, "keep");
  assert.equal(claude.mcpServers.docs.type, "http");
  assert.equal(claude.mcpServers.portable.command, "node");
  const codexPath = path.join(home, ".codex/config.toml");
  const codex = readFileSync(codexPath, "utf8");
  assert.match(codex, /\[mcp_servers\."docs"\]/);
  assert.match(codex, /\[mcp_servers\."portable"\]/);

  run();
  const codexAgain = readFileSync(codexPath, "utf8");
  assert.equal((codexAgain.match(/BEGIN pi-agent shared MCP/g) || []).length, 1, "Codex managed MCP block is idempotent");
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: {} }));
  rmSync(path.join(data, "plugins/demo"), { recursive: true });
  run();
  assert.equal(readFileSync(codexPath, "utf8").includes('mcp_servers."portable"'), false, "removed plugin MCP is removed from Codex");
  assert.equal(readFileSync(path.join(home, ".claude.json"), "utf8").includes('"portable"'), false, "removed plugin MCP is removed from Claude");
  assert.equal(false, (() => { try { realpathSync(path.join(canonicalSkills, "demo-skill")); return true; } catch { return false; } })(), "removed plugin skill link is removed");
  console.log("Shared Pi/Claude/Codex skills, workspace, portable plugins and MCP sync passed.");
} finally {
  rmSync(temp, { recursive: true, force: true });
}
