// Runs inside each final image during CI; no network/login/model turn.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { seed, loadPlugin, BUNDLE } from '/usr/local/lib/pi-omnigent-ha/lifecycle.mjs';

// The image's copy of cli-runtime/versions.json: the pins it was built from.
const pins = JSON.parse(fs.readFileSync('/usr/local/share/woow-ha-pi-agent/versions.json', 'utf8'));
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
  assert.equal(pkg.version, pins.omnigentPlugin.version);
  // Pi Web is not in versions.json: the settings patch pins its compiled artifact hashes.
  assert.equal(JSON.parse(fs.readFileSync('/usr/local/lib/node_modules/@agegr/pi-web/package.json', 'utf8')).version, '0.12.0');
  console.log('SMOKE: loading registered image plugin');
  seed(); const plugin = await loadPlugin(); assert.equal(typeof plugin.runtime.resumeAuthorizedHost, 'function'); assert.equal((await plugin.lifecycle()).active, true);
  // Registration never creates a setup conversation: no onboarding state, no session.
  assert.equal(fs.existsSync(path.join(process.env.PI_OMNIGENT_STATE_DIR, 'onboarding.json')), false);
  assert.equal(fs.existsSync(path.join(temporary, 'sessions')), false);
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
  assert.equal(dependencies.claude.version, pins.claude.version);
  assert.equal(dependencies.codex.version, pins.codex.version);
  const fallback = spawnSync('/opt/omnigent/venv/bin/python', ['-c',
    'from pathlib import Path; import claude_agent_sdk; from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport; assert not (Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude").exists(); transport=SubprocessCLITransport("", claude_agent_sdk.ClaudeAgentOptions()); assert transport._find_cli() == "/usr/local/bin/claude"; print("SDK uses pinned official Claude wrapper")'],
    { env: process.env, encoding: 'utf8', timeout: 15000 });
  assert.equal(fallback.status, 0, fallback.stderr);
  console.log(`SMOKE: Claude SDK uses official CLI ${pins.claude.version}; duplicate SDK binary absent`);
  assert.equal(dependencies.omnigent.version, pins.omnigent.version); assert.equal(dependencies.changed, false);
  assert.equal(installer.DEPENDENCY_VERSIONS.omnigent, pins.omnigent.version, 'the image CLI is the version the plugin installs');
  const current = await plugin.runtime.status(); assert.equal(current.loginConfirmed, false); assert.notEqual(current.phase, 'ready');
  assert.equal(fs.existsSync(path.join(process.env.OMNIGENT_CONFIG_HOME, 'auth.json')), false);
  console.log('SMOKE: pi-omnigent refuses the Pi Web 0.10 setup and still reaches the plugin CLI');
  const refused = spawnSync('/usr/local/bin/pi-omnigent', ['install-ui'], { env: process.env, encoding: 'utf8', timeout: 15000 });
  assert.equal(refused.status, 2, refused.stderr); assert.match(refused.stderr, /Pi Web 0\.10/);
  assert.equal(fs.existsSync(path.join(process.env.HOME, '.local/share/pi-omnigent-web')), false);
  const cliStatus = spawnSync('/usr/local/bin/pi-omnigent', ['status'], { env: process.env, encoding: 'utf8', timeout: 60000 });
  assert.equal(cliStatus.status, 0, cliStatus.stderr); assert.equal(JSON.parse(cliStatus.stdout).loginConfirmed, false);
  // The actual launcher must start Pi Web and leave the session list untouched.
  console.log('SMOKE: starting real Pi Web without a setup conversation');
  child = spawn(process.execPath, ['/usr/local/lib/pi-omnigent-ha/launch.mjs'], {
    detached: true, stdio: ['ignore', 'pipe', 'pipe'], cwd: process.env.HOME,
    env: { ...process.env, PI_WEB_HOSTNAME: '127.0.0.1', PI_WEB_NO_OPEN: '1', PORT: '30141' },
  });
  // What the add-on log would show: keep the worker's lines, drain the rest so Pi Web never blocks.
  const workerLog = [];
  for (const stream of [child.stdout, child.stderr]) {
    let pending = '';
    stream.setEncoding('utf8').on('data', chunk => {
      const lines = (pending + chunk).split('\n'); pending = lines.pop().slice(-4096);
      workerLog.push(...lines.filter(line => line.includes('Omnigent host worker')));
    });
  }
  let webReady = false;
  for (let attempt = 0; attempt < 90; attempt++) {
    try {
      const response = await fetch('http://127.0.0.1:30141/api/home', { signal: AbortSignal.timeout(2000) });
      if (response.ok) { webReady = true; break; }
    } catch {}
    if (child.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  assert.equal(webReady, true, 'real Pi Web starts');
  assert.equal(fs.existsSync(path.join(process.env.PI_OMNIGENT_STATE_DIR, 'onboarding.json')), false);
  assert.equal(fs.existsSync(path.join(temporary, 'sessions')), false);
  console.log('SMOKE: web ready; waiting for offline activation receipt');
  const bootPath = path.join(temporary, 'omnigent-plugin/boot.json');
  for (let attempt = 0; attempt < 45 && !fs.existsSync(bootPath); attempt++) await new Promise(resolve => setTimeout(resolve, 1000));
  assert.equal(fs.existsSync(bootPath), true, 'background activation completes offline');
  const boot = JSON.parse(fs.readFileSync(bootPath, 'utf8'));
  assert.equal(boot.initialization.phase, 'needs-login');
  assert.equal(boot.startup.status, 'settings-required');
  for (let attempt = 0; attempt < 20 && !workerLog.length; attempt++) await new Promise(resolve => setTimeout(resolve, 500));
  assert.match(workerLog.join('\n'), /Omnigent host worker finished \(exit 0\): startup=settings-required initialization=needs-login/, 'the boot result reaches the add-on log');
  console.log(`SMOKE: add-on log: ${workerLog.join(' | ')}`);
  assert.equal(fs.existsSync(installAttempts), false, 'no package manager or engine download during fresh activation');
  fs.writeFileSync(path.join(temporary, 'settings.json'), JSON.stringify({ packages: [{ source: BUNDLE, extensions: [] }] }));
  assert.equal((await plugin.lifecycle()).active, false);
  fs.writeFileSync(path.join(temporary, 'settings.json'), JSON.stringify({ packages: [] }));
  assert.equal(seed().seeded, false); assert.equal(await loadPlugin(), null);
  console.log('Omnigent image smoke passed: Pi Web 0.12 starts, no setup conversation, no runtime install/login, worker result in the add-on log, pi-omnigent refuses install-ui, opt-out retained.');
} finally {
  if (child?.pid) {
    try { process.kill(-child.pid, 'SIGTERM'); } catch {}
    await new Promise(resolve => setTimeout(resolve, 500));
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
  }
  // A process outside the group could still hold the log pipe; never wait on it.
  child?.stdout?.destroy(); child?.stderr?.destroy();
  fs.rmSync(temporary, { recursive: true, force: true });
}
