import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, stat, symlink } from 'node:fs/promises';
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
  const end = launcher.indexOf('\n}\n\nif [[ $(id -u)', start) + 2;
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
od_pid=''
nginx_pid=''
stopping=0
${terminateChildren}
bash -c 'trap "" TERM; while :; do sleep 1; done' &
od_pid=$!
sleep 0.2
terminate_children
if kill -0 "$od_pid" 2>/dev/null; then exit 70; fi
echo reaped
`;
  const result = spawnSync('bash', ['-c', harness], { encoding: 'utf8', timeout: 4000 });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.match(result.stdout, /reaped/);
  assert.match(result.stderr, /exceeded 1s grace; sending KILL/);
});

test('launcher still fails the whole container when either peer exits', () => {
  assert.match(launcher, /wait -n "\$od_pid" "\$nginx_pid"/);
  assert.match(launcher, /terminate_children/);
  assert.match(launcher, /if \(\( status == 0 \)\)/);
});
