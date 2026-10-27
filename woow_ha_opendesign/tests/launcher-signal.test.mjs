import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const launcher = await readFile(new URL('../rootfs/usr/local/bin/ha-opendesign', import.meta.url), 'utf8');
const helpersStart = launcher.indexOf('terminate_children() {');
const helpersEnd = launcher.indexOf('\nprepare_owned_dir() {', helpersStart);
const superviseStart = launcher.indexOf("exited_pid=''");
assert.ok(helpersStart >= 0 && helpersEnd > helpersStart && superviseStart > helpersEnd);

async function runSupervision({ signal, childStatus } = {}) {
  // Exercise the actual launcher trap, helpers, wait and exit decision. Only
  // startup/data preparation is replaced with disposable required processes.
  const harness = `set -Eeuo pipefail
readonly SHUTDOWN_GRACE_SECONDS=2
child_pids=()
child_names=()
stopping=0
${launcher.slice(helpersStart, helpersEnd)}
start_child first sleep 30
${childStatus === undefined ? 'start_child second sleep 30' : `start_child second sh -c 'sleep 0.2; exit ${childStatus}'`}
printf 'READY %s %s\\n' "\${child_pids[0]}" "\${child_pids[1]}"
${launcher.slice(superviseStart)}
`;
  const child = spawn('bash', ['-c', harness], { detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '';
  let stderr = '';
  let sent = false;
  const result = await new Promise((resolve, reject) => {
    const deadline = setTimeout(() => {
      try { process.kill(-child.pid, 'SIGKILL'); } catch {}
      reject(new Error('launcher supervision did not finish within 6 seconds'));
    }, 6000);
    child.on('error', (error) => { clearTimeout(deadline); reject(error); });
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
      if (signal && !sent && /READY \d+ \d+\n/.test(stdout)) {
        sent = true;
        child.kill(signal);
      }
    });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('close', (code, exitSignal) => {
      clearTimeout(deadline);
      resolve({ code, exitSignal, stdout, stderr });
    });
  });
  const pids = result.stdout.match(/READY (\d+) (\d+)/)?.slice(1).map(Number);
  assert.equal(pids?.length, 2, result.stderr);
  for (const pid of pids) {
    assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' }, `required child ${pid} was not reaped`);
  }
  assert.equal(result.exitSignal, null, result.stderr);
  return result;
}

for (const signal of ['SIGTERM', 'SIGINT']) {
  test(`requested ${signal} drains every child and exits successfully for Supervisor`, async () => {
    const result = await runSupervision({ signal });
    assert.match(result.stderr, /stop requested .*all processes stopped/);
    assert.doesNotMatch(result.stderr, /required process|sending KILL/);
    assert.equal(result.code, 0, result.stderr);
  });
}

test('unexpected required-child success still stops peers and reports failure', async () => {
  const result = await runSupervision({ childStatus: 0 });
  assert.match(result.stderr, /required process second exited \(status=0\); stopping its peers/);
  assert.equal(result.code, 1, result.stderr);
});

test('unexpected required-child failure retains its status after draining peers', async () => {
  const result = await runSupervision({ childStatus: 3 });
  assert.match(result.stderr, /required process second exited \(status=3\); stopping its peers/);
  assert.equal(result.code, 3, result.stderr);
});
