"""Bounded child supervision; backend failures never drive this restart loop."""
import asyncio
import ctypes
from dataclasses import dataclass, field
import os
from pathlib import Path
import random
import signal

import anyio


async def _join_transition(operation):
    """Finish owned lifecycle work before propagating caller cancellation."""
    with anyio.CancelScope(shield=True):
        task = asyncio.create_task(operation)
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError


@dataclass(frozen=True)
class ChildSpec:
    argv: tuple[str, ...]
    env: dict[str, str] = field(repr=False)
    cwd: Path


class Supervisor:
    def __init__(self, spec: ChildSpec | None, *, retries=3, backoff=1.0, grace=3.0):
        # Linux/HA runtime: adopt orphan grandchildren, then reap only OUR group.
        # This is unprivileged and does not replace the container's init process.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise RuntimeError("child subreaper unavailable")
        self.spec = spec
        self.retries, self.backoff, self.grace = retries, backoff, grace
        self.process = None
        self.task = None
        self.status = "stopped"
        self.starts = 0
        self.last_exit = None
        self.ready = False
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()

    def _start_child(self):
        if self.task is None and self.process is not None:
            raise RuntimeError("child cleanup required before start")
        if self.spec is None:
            self.status = 'unconfigured'
            return
        if self.task is None:
            self.status = "starting"
            self._stop.clear()
            self.task = asyncio.create_task(self._run())

    async def start(self):
        async with self._lock:
            self._start_child()

    @staticmethod
    def _signal(pid, sig):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass

    async def _terminate(self, process):
        # Always clean the group, even if its leader already exited.
        self._signal(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=self.grace)
        except TimeoutError:
            pass
        # Remaining descendants may outlive an already reaped leader.
        self._signal(process.pid, signal.SIGKILL)
        # Bound both the leader's post-KILL wait and group-scoped reaping.
        # Never use waitpid(-1), which could race unrelated subprocesses.
        async with asyncio.timeout(self.grace + 1):
            await process.wait()
            while True:
                try:
                    pid, _ = os.waitpid(-process.pid, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid == 0:
                    await asyncio.sleep(0.01)

    async def _run(self):
        try:
            for attempt in range(self.retries + 1):
                self.starts += 1
                self.status = "starting"
                try:
                    self.process = await asyncio.create_subprocess_exec(
                        *self.spec.argv, env=self.spec.env, cwd=self.spec.cwd,
                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                    )
                    self.status = "running"
                    exited = asyncio.create_task(self.process.wait())
                    stopped = asyncio.create_task(self._stop.wait())
                    try:
                        await asyncio.wait((exited, stopped), return_when=asyncio.FIRST_COMPLETED)
                        if exited.done():
                            self.last_exit = exited.result()
                    finally:
                        for waiter in (exited, stopped):
                            waiter.cancel()
                        await asyncio.gather(exited, stopped, return_exceptions=True)
                except OSError:
                    self.last_exit = None
                finally:
                    self.ready = False
                    if self.process is not None:
                        await self._terminate(self.process)
                        self.process = None
                if self._stop.is_set():
                    return
                if attempt < self.retries:
                    self.status = "backoff"
                    delay = min(30, self.backoff * 2 ** attempt) * random.uniform(1, 1.2)
                    try:
                        await asyncio.wait_for(self._stop.wait(), delay)
                        return
                    except TimeoutError:
                        pass
            self.status = "failed"
        except asyncio.CancelledError:
            raise

    async def _stop_child(self):
        try:
            if self.task is not None:
                # Cooperative stop cannot interrupt natural-exit group cleanup.
                self._stop.set()
                try:
                    await self.task
                finally:
                    self.task = None
            if self.process is not None:
                # A previous bounded cleanup failed. Retain the process handle
                # and retry cleanup before any replacement is allowed to start.
                await self._terminate(self.process)
                self.process = None
        except BaseException:
            self.ready = False
            self.status = "failed"
            raise
        self.ready = False
        self.status = "stopped"

    async def stop(self):
        async with self._lock:
            # Keep the lock and join cleanup even on repeated caller cancellation.
            await _join_transition(self._stop_child())

    async def restart(self, spec: ChildSpec | None):
        async def replace():
            await self._stop_child()
            self.spec = spec
            self._start_child()

        async with self._lock:
            # Stop + spec replacement + supervised start are one owned transition.
            await _join_transition(replace())

    def health(self):
        return {"state": self.status, "transport_ready": self.ready,
                "starts": self.starts, "last_exit": self.last_exit}
