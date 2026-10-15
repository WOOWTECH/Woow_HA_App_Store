import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { lstat, mkdtemp, mkdir, readdir, readFile, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const launcher = await readFile(new URL('../rootfs/usr/local/bin/ha-opendesign', import.meta.url), 'utf8');

test('launcher bounds TERM shutdown before KILL and reap', () => {
  assert.match(launcher, /readonly SHUTDOWN_GRACE_SECONDS=5/);
  const term = launcher.indexOf('kill -TERM');
  const deadline = launcher.indexOf('deadline=$((SECONDS + SHUTDOWN_GRACE_SECONDS))');
  const kill = launcher.indexOf('kill -KILL');
  const reap = launcher.lastIndexOf('wait "$pid"');
  assert.ok(term >= 0 && deadline > term && kill > deadline && reap > kill, 'shutdown order must be TERM, bounded poll, KILL, reap');
  assert.match(launcher, /while \(\( SECONDS < deadline \)\)/);
  assert.doesNotMatch(launcher.slice(term, kill), /wait "\$pid"/, 'must not block in wait during the grace period');
});

test('privileged directory preparation rejects symlinks without touching their target', async () => {
  const start = launcher.indexOf('prepare_owned_dir() {');
  const end = launcher.indexOf('\n}\n\nremove_obsolete_credentials', start) + 2;
  assert.ok(start >= 0 && end > start);
  const prepareOwnedDir = launcher.slice(start, end);
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-launcher-'));
  const outside = path.join(root, 'outside');
  const link = path.join(root, 'runtime-link');
  await mkdir(outside, { mode: 0o711 });
  await symlink(outside, link);
  const before = await stat(outside);
  try {
    const harness = `set -Eeuo pipefail\n${prepareOwnedDir}\nprepare_owned_dir "$1"`;
    const result = spawnSync('bash', ['-c', harness, 'launcher-test', link], { encoding: 'utf8' });
    assert.equal(result.status, 78, result.stderr);
    assert.match(result.stderr, /refusing symbolic-link runtime directory/);
    const after = await stat(outside);
    assert.equal(after.uid, before.uid);
    assert.equal(after.gid, before.gid);
    assert.equal(after.mode, before.mode);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('launcher shutdown actually kills and reaps a TERM-resistant child after grace', () => {
  const start = launcher.indexOf('terminate_children() {');
  const end = launcher.indexOf('\n}\n\ntrap terminate_children', start) + 2;
  assert.ok(start >= 0 && end > start);
  const terminateChildren = launcher.slice(start, end);
  const harness = `
set -Eeuo pipefail
readonly SHUTDOWN_GRACE_SECONDS=1
child_pids=()
stopping=0
${terminateChildren}
bash -c 'trap "" TERM; while :; do sleep 1; done' &
stubborn=$!
child_pids+=("$stubborn")
sleep 0.2
terminate_children
if kill -0 "$stubborn" 2>/dev/null; then exit 70; fi
echo reaped
`;
  const result = spawnSync('bash', ['-c', harness], { encoding: 'utf8', timeout: 4000 });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.match(result.stdout, /reaped/);
  assert.match(result.stderr, /exceeded 1s grace; sending KILL/);
});

test('launcher supervises OpenDesign, nginx, the login TTY and the built-in MCP server as one unit', () => {
  assert.doesNotMatch(launcher, /byok_pid|ha-byok-store|ha-byok-profiles/);
  for (const name of ['opendesign', 'nginx', 'ttyd', 'mcp']) assert.match(launcher, new RegExp(`^start_child ${name} \\\\$`, 'm'));
  assert.match(launcher, /wait -n -p exited_pid "\$\{child_pids\[@\]\}"/);
  const shutdown = launcher.slice(launcher.indexOf('terminate_children() {'), launcher.indexOf('\n}\n\ntrap terminate_children') + 2);
  assert.match(shutdown, /for pid in "\$\{child_pids\[@\]\}"/);
  assert.match(launcher, /terminate_children/);
  assert.match(launcher, /if \(\( status == 0 \)\)/);
});

test('any supervised child exit stops every peer and names the exited process', () => {
  // Run the real launcher supervision section against stub children: the
  // second child exits with 3, so the launcher must stop the long-running
  // peers, report the exited child by name and propagate its status.
  const helpersStart = launcher.indexOf('terminate_children() {');
  const helpersEnd = launcher.indexOf('\nprepare_owned_dir() {', helpersStart);
  const superviseStart = launcher.indexOf("exited_pid=''");
  assert.ok(helpersStart >= 0 && helpersEnd > helpersStart && superviseStart > helpersEnd);
  const harness = `
set -Eeuo pipefail
readonly SHUTDOWN_GRACE_SECONDS=2
child_pids=()
child_names=()
stopping=0
${launcher.slice(helpersStart, helpersEnd)}
start_child first sleep 30
start_child second sh -c 'sleep 0.3; exit 3'
start_child third sleep 30
${launcher.slice(superviseStart)}
`;
  const result = spawnSync('bash', ['-c', harness], { encoding: 'utf8', timeout: 10_000 });
  assert.equal(result.status, 3, result.stderr || result.error?.message);
  assert.match(result.stderr, /required process second exited \(status=3\); stopping its peers/);
});

test('OpenDesign starts directly: no Omnigent host (removed in 0.2.1)', () => {
  assert.match(launcher, /start_child opendesign \\\n  "\$\{no_supervisor_env\[@\]\}" su-exec open-design:open-design \/usr\/local\/bin\/node \/opt\/ha-opendesign\/headless-entry\.mjs\n/);
  assert.doesNotMatch(launcher, /omnigent-host-launch|OMNIGENT_KIT|\/etc\/omnigent-host|export OG_|export OMNIGENT_/);
  assert.doesNotMatch(launcher, /"\$DATA_DIR\/home\/(\.omnigent|studio)"\n/, 'the launcher must not (re)create Omnigent directories');
  for (const setting of ['DO_NOT_TRACK=1', 'DISABLE_TELEMETRY=1']) assert.ok(launcher.includes(`export ${setting}`), `missing export ${setting}`);
});

test('0.2.0 Omnigent state is moved once into a 0700 backup, never deleted or followed', async () => {
  const start = launcher.indexOf('retire_omnigent_state() {');
  const end = launcher.indexOf('\n}\n', start) + 3;
  assert.ok(start >= 0 && end > start);
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-omnigent-'));
  // prepare_owned_dir (tested above) chowns to open-design; here it only creates the directory.
  const harness = (dataDir) => `set -Eeuo pipefail
DATA_DIR=${JSON.stringify(dataDir)}
prepare_owned_dir() { [[ ! -L "$1" ]] && mkdir -p -- "$1"; }
${launcher.slice(start, end)}
retire_omnigent_state`;
  try {
    const data = path.join(root, 'data');
    await mkdir(path.join(data, 'home', '.omnigent', 'omnigent-host'), { recursive: true, mode: 0o755 });
    await writeFile(path.join(data, 'home', '.omnigent', 'auth_tokens.json'), '{"fake": "login"}');
    let result = spawnSync('bash', ['-c', harness(data)], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stderr, /Omnigent was removed in 0\.2\.1: moved its state \(with the stored Omnigent login\) to .*\/\.backup\/omnigent-\d{8}T\d{6}Z; delete it when no longer needed/);
    const backups = await readdir(path.join(data, '.backup'));
    assert.equal(backups.length, 1);
    assert.match(backups[0], /^omnigent-\d{8}T\d{6}Z$/);
    const moved = path.join(data, '.backup', backups[0]);
    assert.equal(await readFile(path.join(moved, 'auth_tokens.json'), 'utf8'), '{"fake": "login"}');
    assert.equal((await stat(moved)).mode & 0o777, 0o700);
    assert.equal((await stat(path.join(data, '.backup'))).mode & 0o777, 0o700);
    await assert.rejects(stat(path.join(data, 'home', '.omnigent')));
    // Idempotent: nothing left to move, nothing logged.
    result = spawnSync('bash', ['-c', harness(data)], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stderr, '');
    assert.equal((await readdir(path.join(data, '.backup'))).length, 1);
    // A symlinked .omnigent is moved as the link itself; its target is never touched.
    const outside = path.join(root, 'outside');
    await mkdir(outside, { mode: 0o755 });
    await writeFile(path.join(outside, 'keep.txt'), 'keep');
    await symlink(outside, path.join(data, 'home', '.omnigent'));
    result = spawnSync('bash', ['-c', harness(data)], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const links = (await readdir(path.join(data, '.backup'))).filter((name) => name !== backups[0]);
    assert.equal(links.length, 1);
    assert.ok((await lstat(path.join(data, '.backup', links[0]))).isSymbolicLink());
    assert.equal((await stat(outside)).mode & 0o777, 0o755);
    assert.equal(await readFile(path.join(outside, 'keep.txt'), 'utf8'), 'keep');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('restored /data is handed back to open-design before any child starts', () => {
  const fn = launcher.indexOf('repair_data_ownership() {');
  assert.ok(fn > 0, 'repair_data_ownership is defined');
  const body = launcher.slice(fn, launcher.indexOf('\n}\n', fn));
  assert.ok(body.includes('find "$DATA_DIR" -xdev \\( ! -user open-design -o ! -group open-design \\) -exec chown -h open-design:open-design {} +'));
  const call = launcher.indexOf('\nrepair_data_ownership\n');
  assert.ok(call > launcher.indexOf('prepare_owned_dir "$dir"\ndone'), 'runs after the owned directories exist');
  assert.ok(call < launcher.indexOf('start_child opendesign'), 'runs before OpenDesign starts');
});

test('launcher runs a loopback-only writable login TTY under the OpenDesign UID', () => {
  assert.match(launcher, /\/usr\/bin\/ttyd[\s\S]*--interface 127\.0\.0\.1[\s\S]*--base-path \/terminal[\s\S]*--writable[\s\S]*--cwd "\$HOME" \/bin\/bash --login/);
  assert.match(launcher, /start_child ttyd \\\n  "\$\{no_supervisor_env\[@\]\}" su-exec open-design:open-design \/usr\/bin\/ttyd/);
  assert.doesNotMatch(launcher, /shared-agents\.mjs/);
});

test('launcher removes obsolete credential symlinks without following them or deleting data', async () => {
  const start = launcher.indexOf('remove_obsolete_credentials() {');
  const end = launcher.indexOf('\n}\n\nif [[ $(id -u)', start) + 2;
  assert.ok(start >= 0 && end > start);
  const removeCredentials = launcher.slice(start, end);
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-credentials-'));
  const data = path.join(root, 'opendesign');
  const target = path.join(data, 'outside-credentials');
  const credentials = path.join(data, 'credentials');
  try {
    await mkdir(target, { recursive: true });
    await (await import('node:fs/promises')).writeFile(path.join(target, 'sentinel'), 'retained');
    await symlink(target, credentials);
    const harness = `set -Eeuo pipefail\nDATA_DIR="$1"\n${removeCredentials}\nremove_obsolete_credentials`;
    const result = spawnSync('bash', ['-c', harness, 'launcher-test', data], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    await assert.rejects(stat(credentials));
    assert.equal(await readFile(path.join(target, 'sentinel'), 'utf8'), 'retained');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('agent CLI homes are created when absent but never replaced or followed', async () => {
  const start = launcher.indexOf('for dir in "$DATA_DIR/home/.claude"');
  const end = launcher.indexOf('\ndone\n', start) + 6;
  assert.ok(start >= 0 && end > start);
  const block = launcher.slice(start, end).replace(/chown -h open-design:open-design "\$dir"/, 'true');
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-agent-homes-'));
  const data = path.join(root, 'opendesign');
  const outside = path.join(root, 'outside');
  try {
    await mkdir(path.join(data, 'home'), { recursive: true });
    await mkdir(outside);
    await symlink(outside, path.join(data, 'home', '.claude'));
    const result = spawnSync('bash', ['-c', `set -Eeuo pipefail\nDATA_DIR="$1"\n${block}`, 'launcher-test', data], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    for (const dir of ['.codex', '.config', '.pi', '.pi/agent']) assert.ok((await stat(path.join(data, 'home', dir))).isDirectory(), dir);
    assert.ok((await (await import('node:fs/promises')).lstat(path.join(data, 'home', '.claude'))).isSymbolicLink(), 'existing .claude symlink must be left alone');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('no supervised child inherits the Supervisor token; nginx and MCP run under their own UIDs', () => {
  const env = spawnSync('bash', ['-c', `${launcher.match(/^no_supervisor_env=.*$/m)[0]}\n"\${no_supervisor_env[@]}" sh -c 'echo "\${SUPERVISOR_TOKEN-unset} \${HASSIO_TOKEN-unset} \${KEEP-unset}"'`], {
    encoding: 'utf8',
    env: { ...process.env, SUPERVISOR_TOKEN: 'fake-supervisor', HASSIO_TOKEN: 'fake-hassio', KEEP: 'kept' },
  });
  assert.equal(env.status, 0, env.stderr);
  assert.equal(env.stdout.trim(), 'unset unset kept');
  const starts = launcher.match(/^start_child \w+ \\\n  .*$/gm);
  assert.equal(starts.length, 4);
  for (const start of starts) assert.match(start, /\n  "\$\{no_supervisor_env\[@\]\}" /);
  assert.match(launcher, /start_child nginx \\\n  "\$\{no_supervisor_env\[@\]\}" su-exec ha-ingress:ha-ingress \/usr\/sbin\/nginx/);
  assert.match(launcher, /start_child mcp \\\n  "\$\{no_supervisor_env\[@\]\}" \/opt\/woow\/bin\/ha-opendesign-mcp$/m);
  assert.match(launcher, /prepare_owned_dir "\$dir" ha-ingress:ha-ingress/);
});
