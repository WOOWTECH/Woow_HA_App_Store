#!/usr/bin/env node
// The browser terminal is a login shell: /etc/profile rebuilds PATH, so a
// refresh launcher that lived only in ~/.local/bin never ran there and Pi Web
// global MCP servers did not reach Claude Code or Codex until a restart.
// Every caller must go through /usr/local/bin/{claude,codex}, which refresh
// the shared state first, whatever PATH they have.

import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

const repo = process.cwd();
const dockerfile = readFileSync(path.join(repo, "Dockerfile"), "utf8");
const sync = path.join(repo, "rootfs/usr/local/bin/pi-agent-share-state.mjs");
const temp = mkdtempSync(path.join(os.tmpdir(), "pi-agent-cli-wrappers-"));
const data = path.join(temp, "data");
const home = path.join(data, "home");
const stubDir = path.join(temp, "stubs");
const env = { PATH: "/usr/local/bin:/usr/bin:/bin", PI_AGENT_DATA_DIR: data, PI_CODING_AGENT_DIR: data, HOME: home };

assert.doesNotMatch(dockerfile, /ln -s \/opt\/pi-clis\/\w+\/node_modules\/\.bin\/\w+ \/usr\/local\/bin\//, "CLIs must not bypass the refresh wrappers");
// Codex 0.162 invokes `ps` for its pid-managed app-server; the Debian base
// ships without it, so a plain `codex` failed before the sign-in screen.
assert.match(dockerfile, /apt-get install[^&]*\bprocps\b/, "runtime image installs procps for Codex");

try {
  mkdirSync(stubDir, { recursive: true });
  mkdirSync(home, { recursive: true });
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: { "gui-added": { url: "https://mcp.example.test/mcp" } } }));
  for (const name of ["claude", "codex"]) {
    const source = readFileSync(path.join(repo, "rootfs/usr/local/bin", name), "utf8");
    assert.match(source, /^#!\/bin\/sh\n/, `${name} wrapper is POSIX sh`);
    assert.match(source, /node \/usr\/local\/bin\/pi-agent-share-state\.mjs >\/dev\/null/, `${name} wrapper refreshes quietly`);
    assert.match(source, new RegExp(`exec /opt/pi-clis/${name}/node_modules/\\.bin/${name} "\\$@"`), `${name} wrapper execs the pinned binary`);
    // Run the shipped wrapper with only its two absolute paths redirected.
    const stub = path.join(stubDir, `${name}-real`);
    writeFileSync(stub, `#!/bin/sh\necho "${name}-real $*"\n`);
    chmodSync(stub, 0o755);
    const wrapper = path.join(stubDir, name);
    writeFileSync(wrapper, source
      .replace("/usr/local/bin/pi-agent-share-state.mjs", sync)
      .replace(`/opt/pi-clis/${name}/node_modules/.bin/${name}`, stub));
    chmodSync(wrapper, 0o755);
    const result = spawnSync(wrapper, ["--print", "two words"], { env, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, `${name}-real --print two words\n`, `${name} output stays machine-readable`);
  }
  assert.equal(JSON.parse(readFileSync(path.join(home, ".claude.json"), "utf8")).mcpServers["gui-added"].url, "https://mcp.example.test/mcp", "Claude sees the Pi Web MCP server without ~/.local/bin on PATH");
  assert.match(readFileSync(path.join(home, ".codex/config.toml"), "utf8"), /\[mcp_servers\."gui-added"\]/, "Codex sees the Pi Web MCP server without ~/.local/bin on PATH");

  writeFileSync(path.join(data, "mcp.json"), "{ not json");
  const broken = spawnSync(path.join(stubDir, "claude"), ["--version"], { env, encoding: "utf8" });
  assert.equal(broken.status, 0, "a failed refresh must not block the CLI");
  assert.equal(broken.stdout, "claude-real --version\n");
  assert.match(broken.stderr, /shared MCP\/skills sync failed/);
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: {} }));

  // Launchers written by 0.14.8 and earlier are retired; a user's own binary stays.
  const binDir = path.join(home, ".local/bin");
  mkdirSync(binDir, { recursive: true });
  writeFileSync(path.join(binDir, "claude"), "#!/bin/sh\n# pi-agent shared MCP launcher\nexec /usr/local/bin/claude \"$@\"\n");
  writeFileSync(path.join(binDir, "codex"), "#!/bin/sh\nexec /home/user/my-codex \"$@\"\n");
  const rerun = spawnSync(process.execPath, [sync], { env, encoding: "utf8" });
  assert.equal(rerun.status, 0, rerun.stderr);
  assert.equal(existsSync(path.join(binDir, "claude")), false, "managed ~/.local/bin launcher is retired");
  assert.equal(existsSync(path.join(binDir, "codex")), true, "user-owned ~/.local/bin binary is kept");

  // The terminal's login shell gets ~/.local/bin back in front, once.
  const profile = path.join(repo, "rootfs/etc/profile.d/pi-agent.sh");
  const shell = spawnSync("sh", ["-c", `. "${profile}"; . "${profile}"; printf %s "$PATH"`], { env: { HOME: home, PATH: "/usr/local/bin:/usr/bin:/bin" }, encoding: "utf8" });
  assert.equal(shell.status, 0, shell.stderr);
  const entries = shell.stdout.split(":");
  assert.ok(entries.includes(`${home}/.local/bin`) && entries.indexOf(`${home}/.local/bin`) < entries.indexOf("/usr/local/bin"), "login shell puts ~/.local/bin before /usr/local/bin like the pi-web service");
  assert.equal(entries.filter((entry) => entry === `${home}/.local/bin`).length, 1, "profile is idempotent");
  // Claude Code, Codex and Pi use one Pi Web MCP server at the same time: each starts its own
  // copy from its own configuration (no shared process), so three concurrent calls all answer.
  const probe = path.join(temp, "probe-mcp.mjs");
  writeFileSync(probe, `import readline from "node:readline";
const send = m => process.stdout.write(JSON.stringify(m) + "\\n");
readline.createInterface({ input: process.stdin }).on("line", line => {
  let m; try { m = JSON.parse(line); } catch { return; }
  if (m.method === "initialize") send({ jsonrpc: "2.0", id: m.id, result: { protocolVersion: "2025-06-18", capabilities: { tools: {} }, serverInfo: { name: "probe", version: "1" } } });
  else if (m.method === "tools/call") send({ jsonrpc: "2.0", id: m.id, result: { content: [{ type: "text", text: "PROBE_OK " + process.pid }] } });
  else if (m.id !== undefined) send({ jsonrpc: "2.0", id: m.id, result: {} });
});\n`);
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: { probe: { command: process.execPath, args: [probe] } } }));
  assert.equal(spawnSync(process.execPath, [sync], { env, encoding: "utf8" }).status, 0);
  const fromPi = JSON.parse(readFileSync(path.join(data, "mcp.json"), "utf8")).mcpServers.probe;
  const fromClaude = JSON.parse(readFileSync(path.join(home, ".claude.json"), "utf8")).mcpServers.probe;
  const codexTable = readFileSync(path.join(home, ".codex/config.toml"), "utf8").split(/\n(?=\[)/).find(part => part.startsWith('[mcp_servers."probe"]')) || "";
  const fromCodex = { command: JSON.parse(codexTable.match(/^command = (.+)$/m)?.[1] ?? "null"), args: JSON.parse(codexTable.match(/^args = (.+)$/m)?.[1] ?? "null") };
  const callOnce = server => new Promise((resolve, reject) => {
    const child = spawn(server.command, server.args || [], { stdio: ["pipe", "pipe", "ignore"] });
    let buffer = "";
    const timer = setTimeout(() => { child.kill(); reject(new Error("probe call timed out")); }, 20000);
    child.stdout.on("data", chunk => {
      buffer += chunk;
      for (const line of buffer.split("\n").slice(0, -1)) {
        const message = JSON.parse(line);
        if (message.id === 2) { clearTimeout(timer); child.kill(); resolve(message.result.content[0].text); }
      }
      buffer = buffer.slice(buffer.lastIndexOf("\n") + 1);
    });
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } } }) + "\n");
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "probe", arguments: {} } }) + "\n");
  });
  const answers = await Promise.all([fromClaude, fromCodex, fromPi].map(callOnce));
  assert.ok(answers.every(answer => answer.startsWith("PROBE_OK ")), "Claude, Codex and Pi each reach the shared MCP server");
  assert.equal(new Set(answers).size, 3, "the three callers run independently at the same time");
  writeFileSync(path.join(data, "mcp.json"), JSON.stringify({ mcpServers: {} }));

  console.log("Claude/Codex wrappers refresh Pi Web MCP for every caller; old launchers retired; terminal PATH matches pi-web.");
} finally {
  rmSync(temp, { recursive: true, force: true });
}
