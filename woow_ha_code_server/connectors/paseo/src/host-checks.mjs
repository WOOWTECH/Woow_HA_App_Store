import {execFile} from 'node:child_process';
// Paseo 0.17.4 finds and closes terminal worker processes by reading the process table with `ps`, in the process
// that stops or starts the daemon (the supervisor's own cleanup and the stopper's, see lifecycle-timeouts.mjs).
// On Linux it runs, both with LC_ALL=C and from the PATH of that process:
//   ps -A -ww -o pid= -o ppid= -o sid= -o lstart=      dist/server/terminal/terminal-worker-processes.js (listPosixProcesses)
//   ps -ww -p <pid> -o lstart= -o command=              dist/server/server/managed-processes/managed-processes.js (inspectPosix)
// Birth times are compared as the strings `ps` prints, cut to 24 characters. A `ps` that is not there or cannot run
// leaves a terminal program recorded without a birth time, which is never signaled, so a stop cannot confirm it
// and reports TERMINAL_CLEANUP_NOT_CONFIRMED (runtime.mjs treats that as a warning). A `ps` that runs but exits
// non-zero for these arguments (busybox, some slim images) is read by upstream as "no such process": the terminal is
// not recorded at all (terminal-worker-process.js, recordTerminalProgram), so a stop confirms nothing and fails at
// nothing. That silence is why this check exists: it is the only sign of that host.
// This check runs the same two commands on this process once, at a bounded time. It never blocks a start.
export const PS_UNAVAILABLE = 'PS_UNAVAILABLE';
export const PS_INCOMPATIBLE = 'PS_INCOMPATIBLE';
export const PS_TABLE_ARGS = Object.freeze(['-A', '-ww', '-o', 'pid=', '-o', 'ppid=', '-o', 'sid=', '-o', 'lstart=']);
export const psInspectArgs = pid => ['-ww', '-p', String(pid), '-o', 'lstart=', '-o', 'command='];
const LSTART_WIDTH = 24;
// LC_ALL=C lstart, as ctime prints it: "Wed Nov 25 19:52:11 2026", the day padded with a space below 10.
const LSTART = /^[A-Z][a-z]{2} [A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d \d{4}$/;
// listPosixProcesses' line pattern for the Linux layout (pid ppid sid lstart).
const TABLE_LINE = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.+?)\s*$/;
function exec(command, args, { env, timeoutMs }) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { env, timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024, encoding: 'utf8', shell: false, windowsHide: true },
      (error, stdout) => error ? reject(error) : resolve(String(stdout)));
  });
}
// A numeric code is the exit status of a `ps` that ran and refused; anything else (ENOENT, EACCES, a timeout, a
// signal) means it could not be used at all.
const failure = error => typeof error?.code === 'number' ? PS_INCOMPATIBLE : PS_UNAVAILABLE;
/** @returns {Promise<{checked: boolean, ok?: boolean, code?: string}>} not checked off Linux; otherwise whether
 * this host's `ps` serves Paseo's terminal cleanup, and if not why. Never throws, never signals anything. */
export async function checkProcessTable({ platform = process.platform, env = process.env, pid = process.pid, ppid = process.ppid, run = exec, timeoutMs = 5000 } = {}) {
  if (platform !== 'linux') return { checked: false };
  const options = { env: { ...env, LC_ALL: 'C' }, timeoutMs };
  let table, inspected;
  try { table = await run('ps', [...PS_TABLE_ARGS], options); } catch (error) { return { checked: true, ok: false, code: failure(error) }; }
  const self = String(table).split('\n').map(line => TABLE_LINE.exec(line)).find(match => match && Number(match[1]) === pid);
  // No process at all is upstream's "ps returned no processes"; this process missing or mismatched is as unusable.
  if (!self || Number(self[2]) !== ppid) return { checked: true, ok: false, code: PS_INCOMPATIBLE };
  const startedAt = self[4].slice(0, LSTART_WIDTH).trim();
  if (!LSTART.test(startedAt)) return { checked: true, ok: false, code: PS_INCOMPATIBLE };
  try { inspected = await run('ps', psInspectArgs(pid), options); } catch (error) { return { checked: true, ok: false, code: failure(error) }; }
  // The two forms must print the same birth time for the same process, or no terminal program would ever match its record.
  const line = String(inspected).trimEnd();
  if (line.slice(0, LSTART_WIDTH).trim() !== startedAt || !line.slice(LSTART_WIDTH).trim()) return { checked: true, ok: false, code: PS_INCOMPATIBLE };
  return { checked: true, ok: true };
}
