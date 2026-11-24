// Stop handling shared by the two node launchers in front of Pi Web
// (s6 pi-web → Paseo launcher → Omnigent launcher → pi-web).
//
// Supervisor gives the whole container `timeout` seconds (10 by default) after
// `docker stop`, then sends SIGKILL (exit 137). s6-overlay waits for the pi-web
// service without a time limit, so each launcher must end on its own within
// that budget: forward the signal, wait for its child, give its own cleanup a
// bounded time, and then end the process explicitly instead of waiting for the
// event loop to drain (plugin timers and watchers can keep it alive).

const SIGNALS = ['SIGINT', 'SIGTERM', 'SIGHUP'];

/** Exit code for a child that ended, given whether we asked it to stop. A child
 * that ends from the signal we forwarded (or 143/130/129 from a shell) is a
 * normal stop, not a failure. */
export function exitCodeFor(code, signal, stopSignal) {
  if (stopSignal) {
    if (signal === stopSignal || code === 0) return 0;
    if (code === 128 + ({ SIGHUP: 1, SIGINT: 2, SIGTERM: 15 }[stopSignal] ?? 0)) return 0;
  }
  return code ?? (signal ? 1 : 0);
}

/**
 * Supervise one child process until it ends, then run `cleanup` and exit.
 *
 * - On SIGINT/SIGTERM/SIGHUP: forward the signal to the child and start cleanup
 *   at once (it runs in parallel with the child's own shutdown).
 * - If the child is still running `killAfterMs` after the signal, SIGKILL it.
 * - Cleanup gets at most `cleanupTimeoutMs`; whatever it has not finished by
 *   then is abandoned.
 * - At most `deadlineMs` after the signal the process exits, whatever is left.
 * - If the child ends by itself, cleanup runs and the launcher exits with the
 *   child's code.
 */
export function superviseChild(child, {
  cleanup = async () => {},
  killAfterMs = 4000,
  cleanupTimeoutMs = 5000,
  deadlineMs = 6000,
  exit = code => process.exit(code),
  log = message => console.error(message),
  name = 'child',
  proc = process,
} = {}) {
  let stopSignal = null, cleaning = null, exited = false, finished = false;
  let childDone = false, childCode = 0;
  const timers = [];
  const kill = signal => { try { child.kill(signal); } catch {} };
  const runCleanup = () => {
    cleaning ??= (async () => {
      let timer;
      const limit = new Promise(resolve => { timer = setTimeout(() => resolve('timeout'), cleanupTimeoutMs); });
      const work = Promise.resolve().then(cleanup).then(() => 'done', () => 'failed');
      const result = await Promise.race([work, limit]);
      clearTimeout(timer);
      if (result === 'timeout') log(`${name} launcher: cleanup did not finish within ${cleanupTimeoutMs} ms; exiting anyway.`);
      return result;
    })();
    return cleaning;
  };
  const finish = code => {
    if (finished) return;
    finished = true;
    for (const timer of timers) clearTimeout(timer);
    exit(code);
  };
  const onExit = async (code, signal) => {
    if (exited) return;
    exited = true; childDone = true;
    childCode = exitCodeFor(code, signal, stopSignal);
    await runCleanup();
    finish(childCode);
  };
  const onSignal = signal => {
    if (stopSignal) return;
    stopSignal = signal;
    if (!childDone) kill(signal);
    void runCleanup();
    const killTimer = setTimeout(() => {
      if (childDone) return;
      log(`${name} launcher: ${name} still running ${killAfterMs} ms after ${signal}; sending SIGKILL.`);
      kill('SIGKILL');
    }, killAfterMs);
    const deadline = setTimeout(() => {
      log(`${name} launcher: stop deadline of ${deadlineMs} ms reached; exiting.`);
      finish(childDone ? childCode : 0);
    }, deadlineMs);
    timers.push(killTimer, deadline);
  };
  for (const signal of SIGNALS) proc.on(signal, onSignal);
  child.on('exit', onExit);
  child.on('error', async () => {
    if (exited) return;
    exited = true; childDone = true; childCode = 1;
    await runCleanup();
    finish(1);
  });
  return { stop: onSignal };
}
