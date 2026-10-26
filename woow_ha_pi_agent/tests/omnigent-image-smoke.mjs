// Runs inside each final image during CI; no network/login/model turn.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { seed, loadPlugin, BUNDLE } from '/usr/local/lib/pi-omnigent-ha/lifecycle.mjs';

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'omnigent-image-smoke-'));
Object.assign(process.env, { HOME: path.join(temporary, 'home'), PI_CODING_AGENT_DIR: temporary,
  PI_OMNIGENT_STATE_DIR: path.join(temporary, 'omnigent-plugin'), OMNIGENT_CONFIG_HOME: path.join(temporary, 'omni'),
  OMNIGENT_DATA_DIR: path.join(temporary, 'omni'), PI_OMNIGENT_SDK_ROOT: '/usr/local/lib/node_modules/@agegr/pi-web' });
fs.mkdirSync(process.env.HOME);
// A first-run extension must not quietly add/update engines. Discovery's
// --version probes are allowed; package-manager mutations are recorded/fail.
const guardDir = path.join(temporary, 'guard'); fs.mkdirSync(guardDir);
const installAttempts = path.join(temporary, 'install-attempts');
for (const command of ['npm', 'npx', 'uv', 'pip', 'pip3', 'curl', 'wget']) {
  const real = process.env.PATH.split(path.delimiter).map(directory => path.join(directory, command)).find(file => fs.existsSync(file));
  fs.writeFileSync(path.join(guardDir, command), `#!/usr/bin/env node\nimport{spawnSync}from'node:child_process';import{appendFileSync}from'node:fs';const args=process.argv.slice(2);if(args.length===1&&args[0]==='--version'){if(!${JSON.stringify(real || '')})process.exit(127);const r=spawnSync(${JSON.stringify(real || '')},args,{stdio:'inherit'});process.exit(r.status??1)}appendFileSync(${JSON.stringify(installAttempts)},${JSON.stringify(command + '\n')});process.exit(77);\n`, { mode: 0o755 });
}
process.env.PATH = `${guardDir}:${process.env.PATH}`;
let child;
try {
  const pkg = JSON.parse(fs.readFileSync(`${BUNDLE}/package.json`, 'utf8'));
  assert.equal(pkg.version, '0.3.16');
  assert.equal(JSON.parse(fs.readFileSync('/usr/local/lib/node_modules/@agegr/pi-web/package.json', 'utf8')).version, '0.12.0');
  console.log('SMOKE: loading registered image plugin');
  seed(); const plugin = await loadPlugin(); assert.equal(typeof plugin.runtime.resumeAuthorizedHost, 'function'); assert.equal((await plugin.lifecycle()).active, true);
  const first = await plugin.web.ensureOnboarding(); const second = await plugin.web.ensureOnboarding();
  assert.equal(first.status, 'created'); assert.equal(second.sessionId, first.sessionId);
  const sdk = await plugin.web.loadPiSdk();
  const loader = new sdk.DefaultResourceLoader({ cwd: process.env.HOME, agentDir: temporary, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true });
  console.log('SMOKE: loading real SDK extensions');
  await loader.reload();
  const extensions = loader.getExtensions(); assert.deepEqual(extensions.errors, []);
  assert.ok(extensions.extensions.some(extension => extension.path.includes('pi-omnigent-plugin')));
  console.log('SMOKE: discovering preinstalled dependencies without installers');
  const installer = await import(`${BUNDLE}/src/installer.mjs`);
  const dependencies = await installer.installDependencies({ env: process.env, run: async () => { throw new Error('Unexpected runtime download'); } });
  assert.equal(dependencies.ok, true, JSON.stringify(dependencies.issues));
  assert.deepEqual(dependencies.installedEngines.sort(), ['claude', 'codex', 'pi']);
  assert.equal(dependencies.claude.path, '/usr/local/bin/claude');
  assert.equal(dependencies.claude.version, '2.1.296');
  assert.equal(dependencies.codex.version, '0.162.1');
  const fallback = spawnSync('/opt/omnigent/venv/bin/python', ['-c',
    'from pathlib import Path; import claude_agent_sdk; from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport; assert not (Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude").exists(); transport=SubprocessCLITransport("", claude_agent_sdk.ClaudeAgentOptions()); assert transport._find_cli() == "/usr/local/bin/claude"; print("SDK uses pinned official Claude wrapper")'],
    { env: process.env, encoding: 'utf8', timeout: 15000 });
  assert.equal(fallback.status, 0, fallback.stderr);
  console.log('SMOKE: Claude SDK uses official CLI 2.1.296; duplicate SDK binary absent');
  assert.equal(dependencies.omnigent.version, '0.16.0'); assert.equal(dependencies.changed, false);
  const current = await plugin.runtime.status(); assert.equal(current.loginConfirmed, false); assert.notEqual(current.phase, 'ready');
  assert.equal(fs.existsSync(path.join(process.env.OMNIGENT_CONFIG_HOME, 'auth.json')), false);
  // Exercise the actual launcher and Pi Web 0.12 RPC contract. No model prompt
  // is submitted: the setup session must expose the plugin command by itself.
  console.log('SMOKE: starting real Pi Web and onboarding RPC');
  child = spawn(process.execPath, ['/usr/local/lib/pi-omnigent-ha/launch.mjs'], {
    detached: true, stdio: 'ignore', cwd: process.env.HOME,
    env: { ...process.env, PI_WEB_HOSTNAME: '127.0.0.1', PI_WEB_NO_OPEN: '1', PORT: '30141',
      PI_OMNIGENT_PI_WEB_URL: 'http://127.0.0.1:30141' },
  });
  let commandsReady = false;
  for (let attempt = 0; attempt < 90; attempt++) {
    try {
      const response = await fetch(`http://127.0.0.1:30141/api/agent/${first.sessionId}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'get_commands' }), signal: AbortSignal.timeout(2000),
      });
      if (response.ok && (await response.json()).data?.commands?.some(command => command.name === 'omnigent')) { commandsReady = true; break; }
    } catch {}
    if (child.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  assert.equal(commandsReady, true, 'real Pi Web startup exposes Omnigent command in the setup session');
  const saved = plugin.web.readOnboarding(); assert.equal(saved.sessionId, first.sessionId);
  console.log('SMOKE: RPC ready; waiting for offline activation receipt');
  const bootPath = path.join(temporary, 'omnigent-plugin/boot.json');
  for (let attempt = 0; attempt < 45 && !fs.existsSync(bootPath); attempt++) await new Promise(resolve => setTimeout(resolve, 1000));
  assert.equal(fs.existsSync(bootPath), true, 'background activation completes offline');
  const boot = JSON.parse(fs.readFileSync(bootPath, 'utf8'));
  assert.equal(boot.initialization.phase, 'needs-login');
  assert.equal(boot.startup.status, 'started');
  assert.equal(fs.existsSync(installAttempts), false, 'no package manager or engine download during fresh activation');
  fs.writeFileSync(path.join(temporary, 'settings.json'), JSON.stringify({ packages: [{ source: BUNDLE, extensions: [] }] }));
  assert.equal((await plugin.lifecycle()).active, false);
  fs.writeFileSync(path.join(temporary, 'settings.json'), JSON.stringify({ packages: [] }));
  assert.equal(seed().seeded, false); assert.equal(await loadPlugin(), null);
  console.log('Omnigent image smoke passed: Pi Web 0.12 starts, real RPC command loads, one setup conversation, no runtime install/login, opt-out retained.');
} finally {
  if (child?.pid) {
    try { process.kill(-child.pid, 'SIGTERM'); } catch {}
    await new Promise(resolve => setTimeout(resolve, 500));
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
  }
  fs.rmSync(temporary, { recursive: true, force: true });
}
