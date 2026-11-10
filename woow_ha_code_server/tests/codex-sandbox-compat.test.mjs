import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const shimSource = fs.readFileSync(path.join(root, 'rootfs/opt/woow-agent-tools/sandbox-bin/bwrap'), 'utf8');
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'woow-bwrap-'));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  const backend = path.join(dir, 'real-bwrap'), shim = path.join(dir, 'bwrap');
  fs.writeFileSync(backend, `#!/bin/bash
printf '%s\\0' "$@" > "$ARGV_FILE"
printf '%s' "$FIXTURE_STDOUT"
printf '%s' "$FIXTURE_STDERR" >&2
if [ "\${CHECK_FD:-}" = 1 ]; then cat <&3; cat; fi
exit "\${FIXTURE_STATUS:-0}"
`, {mode: 0o755});
  // Redirect the fixed executable only in the test copy, never via a runtime override.
  assert.equal(shimSource.split('/usr/bin/bwrap').length - 1, 2);
  fs.writeFileSync(shim, shimSource.replaceAll('/usr/bin/bwrap', backend), {mode: 0o755});
  const run = (args, env = {}) => spawnSync(shim, args, {encoding: 'utf8',
    env: {...process.env, ARGV_FILE: path.join(dir, 'args'), ...env}});
  return {dir, shim, run};
}

for (const reason of ['Operation not permitted', 'Permission denied', 'Invalid argument']) {
  test(`only the recognized proc-mount preflight diagnostic is normalized: ${reason}`, t => {
    const {run} = fixture(t);
    for (const command of ['/bin/true', '/usr/bin/true']) {
      const r = run(['--proc', '/proc', '--', command], {
        FIXTURE_STDERR: `before\nbwrap: Can't mount proc on /proc: ${reason}\nafter\n`,
        FIXTURE_STDOUT: 'separate stdout', FIXTURE_STATUS: '1',
      });
      assert.equal(r.status, 1);
      assert.equal(r.stdout, 'separate stdout');
      assert.equal(r.stderr, `before\nbwrap: Can't mount proc on /newroot/proc: ${reason}\nafter\n`);
    }
  });
}
test('real commands and unrecognized preflight failures pass through byte-for-byte', t => {
  const {run} = fixture(t);
  for (const [command, error] of [
    ['/bin/sh', "bwrap: Can't mount proc on /proc: Operation not permitted\n"],
    ['/bin/true', "bwrap: Can't mount proc on /proc: No such file or directory\n"],
    ['/bin/true', "bwrap: Can't mount proc on /newroot/proc: Operation not permitted\n"],
    ['/bin/true', 'bwrap: Creating new namespace failed: Operation not permitted\n'],
    ['/bin/true', "prefix bwrap: Can't mount proc on /proc: Permission denied\n"],
  ]) {
    const r = run(['--', command], {FIXTURE_STDERR: error, FIXTURE_STDOUT: 'output', FIXTURE_STATUS: '23'});
    assert.equal(r.status, 23); assert.equal(r.stderr, error); assert.equal(r.stdout, 'output');
  }
});
test('namespace flags, empty arguments, stdin and inherited descriptors remain intact', t => {
  const {dir, shim} = fixture(t);
  const args = ['--unshare-user', '--unshare-pid', '--unshare-net', '--proc', '/proc', '', 'a b', '--', '/bin/true'];
  const fd = path.join(dir, 'fd'); fs.writeFileSync(fd, 'descriptor\n');
  const r = spawnSync('/bin/bash', ['-c', 'exec 3< "$1"; shift; exec "$@"', 'test', fd, shim, ...args], {
    encoding: 'utf8', input: 'stdin\n',
    env: {...process.env, ARGV_FILE: path.join(dir, 'args'), CHECK_FD: '1', FIXTURE_STATUS: '7'},
  });
  assert.equal(r.status, 7); assert.equal(r.stdout, 'descriptor\nstdin\n');
  assert.equal(fs.readFileSync(path.join(dir, 'args'), 'utf8'), args.join('\0') + '\0');
});
test('native and ACP launchers use the same shim without modifying auth or sandbox policy', t => {
  const {dir} = fixture(t), launcher = path.join(dir, 'codex'), cli = path.join(dir, 'cli'), acp = path.join(dir, 'acp');
  fs.writeFileSync(cli, '#!/bin/sh\nprintf "%s\\n" "$PATH" "$CODEX_HOME" "$@"\n', {mode: 0o755});
  fs.writeFileSync(launcher, fs.readFileSync(path.join(root, 'rootfs/usr/local/bin/woow-codex'), 'utf8')
    .replace('/opt/woow-agent-tools/node_modules/.bin/codex', cli), {mode: 0o755});
  fs.writeFileSync(acp, '#!/bin/sh\nexec "$CODEX_PATH" "$@"\n', {mode: 0o755});
  const adapter = path.join(dir, 'codex-code');
  fs.writeFileSync(adapter, fs.readFileSync(path.join(root, 'rootfs/usr/local/bin/codex-code'), 'utf8')
    .replace('/usr/local/bin/codex', launcher)
    .replace('/opt/woow-agent-tools/node_modules/.bin/codex-acp', acp), {mode: 0o755});
  const args = ['exec', '--sandbox', 'workspace-write', 'a prompt'];
  for (const command of [launcher, adapter]) {
    const r = spawnSync(command, args, {encoding: 'utf8', env: {...process.env, PATH: '/usr/bin:/bin', CODEX_HOME: '/private/auth'}});
    assert.equal(r.status, 0);
    assert.equal(r.stdout, ['/opt/woow-agent-tools/sandbox-bin:/usr/bin:/bin', '/private/auth', ...args, ''].join('\n'));
  }
});
