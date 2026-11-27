// Stop budgets. They bound a wait, never a process: a stop that outlives its budget fails (STOP_NOT_CONFIRMED
// for the daemon, "Plugin supervisor is still stopping" for the plugin supervisor) and nothing is force-killed.
//
// What Paseo 0.17.4's stopDaemonInstance (dist/server/server/daemon-instance.js) does on Linux:
//   1. SIGTERM to the Paseo supervisor, then wait up to `timeoutMs` for it to exit. The supervisor asks the daemon
//      worker to shut down and kills the worker's process tree after WORKER_TERMINATION_GRACE_MS (10 s,
//      dist/scripts/supervisor.js). Once the worker is gone it closes the terminal workers (reapTerminalWorkers,
//      dist/server/terminal/terminal-worker-reaper.js), releases the PID lock and exits.
//   2. After that exit and the PID lock release, the caller's own process runs reapTerminalWorkers once more. It is
//      not covered by `timeoutMs`, and on a clean first pass it finds nothing to do.
// reapTerminalWorkers takes the worker records one after the other. A worker whose socket accepts but that does not
// shut down costs up to 5 s for the shutdown request, 5 s of waiting for its terminals, then SIGKILL and 3 s to
// confirm: 13 s. A daemon runs at most MAX_TERMINAL_WORKERS = 2 workers (dist/server/terminal/worker-terminal-manager.js).
// 0.11.2 has none of this: its stop waits for the supervisor only.
export const WORKER_GRACE_MS = 10000;
export const TERMINAL_WORKER_LIMIT = 2;
export const TERMINAL_RECORD_CLEANUP_MS = 13000;
export const TERMINAL_CLEANUP_BUDGET_MS = TERMINAL_WORKER_LIMIT * TERMINAL_RECORD_CLEANUP_MS;
// Signal delivery, the 100 ms exit poll and the supervisor's log flush after its cleanup.
export const SUPERVISOR_EXIT_MARGIN_MS = 9000;
// Until the supervisor has exited and released the PID lock: 10 s + 2 x 13 s + 9 s = 45 s.
export const DAEMON_STOP_TIMEOUT_MS = WORKER_GRACE_MS + TERMINAL_CLEANUP_BUDGET_MS + SUPERVISOR_EXIT_MARGIN_MS;
// The plugin supervisor awaits the complete daemon stop before it exits: the wait above, then the second terminal
// cleanup, then the final status and record writes. Its parent must cover all of it.
export const SUPERVISOR_STOP_TIMEOUT_MS = DAEMON_STOP_TIMEOUT_MS + TERMINAL_CLEANUP_BUDGET_MS + 10000;
// What an earlier cleanup could not confirm stays as a closing record (<PASEO_HOME>/terminal-worker/closing-<id>.json)
// and every later cleanup walks it again, in each of its two passes: a worker that is gone costs 3 s of confirmation
// per record (terminal-worker-reaper.js, DEFAULT_CONFIRM_MS). On a host without a usable ps every stop leaves one more.
// The budget above is not resized for them. The margin has room for a few (one record's time stays for signal delivery,
// the exit poll and the log flush), and past that the worst case no longer fits DAEMON_STOP_TIMEOUT_MS: that count is
// where the plugin warns (TERMINAL_RECORDS_ACCUMULATING), while 3 records still cost the supervisor no more than 9 s.
export const CLOSING_RECORD_CLEANUP_MS = 3000;
export const CLOSING_RECORDS_IN_BUDGET = Math.floor(SUPERVISOR_EXIT_MARGIN_MS / CLOSING_RECORD_CLEANUP_MS) - 1;
export const CLOSING_RECORDS_WARNING_AT = CLOSING_RECORDS_IN_BUDGET + 1;
