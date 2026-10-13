#!/usr/bin/env node
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
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
  mkdirSync(path.join(home, ".codex"), { recursive: true });
  writeFileSync(path.join(home, ".claude.json"), JSON.stringify({ oauthAccount: { id: "keep" }, custom: true, mcpServers: { user_owned: { command: "keep" } } }));
  mkdirSync(path.join(data, "skills/gui-skill"), { recursive: true });
  writeFileSync(path.join(data, "skills/gui-skill/SKILL.md"), "---\nname: gui-skill\ndescription: shared\n---\nFIRST\n");
  mkdirSync(path.join(data, "plugins/demo/skills/plugin-skill"), { recursive: true });
  writeFileSync(path.join(data, "plugins/demo/skills/plugin-skill/SKILL.md"), "---\nname: plugin-skill\ndescription: excluded\n---\n");
  writeFileSync(path.join(data, "plugins/demo/plugin.json"), JSON.stringify({
    skills: ["skills/plugin-skill"],
    mcpServers: { portable: { command: "node", args: ["server.js"], env: { TOKEN: "from-plugin" } } },
  }));
  mkdirSync(path.join(data, "skills"), { recursive: true });
  symlinkSync(path.join(data, "plugins/demo/skills/plugin-skill"), path.join(data, "skills/legacy-plugin-skill"), "dir");
  writeFileSync(path.join(data, ".shared-plugin-skills.json"), JSON.stringify({ "legacy-plugin-skill": path.join(data, "plugins/demo/skills/plugin-skill") }));
  writeFileSync(path.join(data, ".shared-mcp-managed.json"), JSON.stringify(["portable"]));
  writeFileSync(path.join(home, ".codex/config.toml"), '# user config\n[mcp_servers.user_owned]\ncommand = "keep"\n\n# BEGIN pi-agent shared MCP (managed)\n[mcp_servers."portable"]\ncommand = "node"\n# END pi-agent shared MCP (managed)\n');
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: { docs: { url: "https://example.test/mcp", headers: { Authorization: "Bearer test" } } } }));
  run();

  const canonicalSkills = path.join(data, "skills");
  for (const agentPath of [".pi/agent/skills", ".claude/skills", ".agents/skills"]) {
    assert.equal(realpathSync(path.join(home, agentPath)), realpathSync(canonicalSkills), `${agentPath} shares canonical skills`);
  }
  assert.equal(realpathSync(path.join(home, "workspace")), realpathSync(path.join(data, "workspace")));
  assert.equal(readFileSync(path.join(home, ".claude/skills/gui-skill/SKILL.md"), "utf8").includes("FIRST"), true);
  assert.equal(existsSync(path.join(canonicalSkills, "plugin-skill")), false, "native plugin skills are not imported");
  assert.equal(existsSync(path.join(canonicalSkills, "legacy-plugin-skill")), false, "old plugin-owned skill links are cleaned");
  assert.equal(existsSync(path.join(data, ".shared-plugin-skills.json")), false, "old plugin ownership record is retired");
  const claude = JSON.parse(readFileSync(path.join(home, ".claude.json"), "utf8"));
  assert.equal(claude.oauthAccount.id, "keep");
  assert.equal(claude.mcpServers.user_owned.command, "keep");
  assert.equal(claude.mcpServers.docs.type, "http");
  assert.equal("portable" in claude.mcpServers, false, "native plugin MCP is not imported");
  const codexPath = path.join(home, ".codex/config.toml");
  const codex = readFileSync(codexPath, "utf8");
  assert.match(codex, /\[mcp_servers\."docs"\]/);
  assert.equal(codex.includes('mcp_servers."portable"'), false, "native plugin MCP is not imported");
  assert.match(codex, /mcp_servers\.user_owned/, "Codex user MCP remains untouched");

  run();
  const codexAgain = readFileSync(codexPath, "utf8");
  assert.equal((codexAgain.match(/BEGIN pi-agent shared MCP/g) || []).length, 1, "Codex managed MCP block is idempotent");
  writeFileSync(path.join(data, "skills/gui-skill/SKILL.md"), "---\nname: gui-skill\ndescription: shared\n---\nUPDATED\n");
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: { docs: { url: "https://updated.test/mcp" } } }));
  run();
  assert.equal(readFileSync(path.join(home, ".agents/skills/gui-skill/SKILL.md"), "utf8").includes("UPDATED"), true, "skill updates are immediately visible through shared links");
  assert.match(readFileSync(codexPath, "utf8"), /https:\/\/updated\.test\/mcp/, "global MCP updates propagate");
  writeFileSync(path.join(data, "skills/gui-skill/SKILL.md"), "---\nname: gui-skill\ndescription: shared\n---\nREMOVED\n");
  rmSync(path.join(data, "skills/gui-skill"), { recursive: true });
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: {} }));
  run();
  assert.equal(existsSync(path.join(home, ".claude/skills/gui-skill")), false, "skill removal is visible through shared links");
  assert.equal(readFileSync(codexPath, "utf8").includes('mcp_servers."docs"'), false, "removed global MCP is removed from Codex");
  const finalClaude = JSON.parse(readFileSync(path.join(home, ".claude.json"), "utf8"));
  assert.equal("docs" in finalClaude.mcpServers, false, "removed global MCP is removed from Claude");
  assert.equal(finalClaude.mcpServers.user_owned.command, "keep", "user MCP remains untouched");
  console.log("Pi Web skill and global MCP add/update/remove sync passed; native plugin items excluded; user settings preserved.");
} finally {
  rmSync(temp, { recursive: true, force: true });
}
