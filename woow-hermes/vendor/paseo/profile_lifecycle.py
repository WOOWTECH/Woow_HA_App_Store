"""Profile-scoped lifecycle for an explicitly enabled trusted Hermes plugin."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import threading
import logging
import re

logger = logging.getLogger('hermes_paseo.host')


class LifecycleError(Exception):
    pass


def safe_owned(path, directory=False):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise LifecycleError('UNSAFE_PROFILE_PATH')
    info = path.stat()
    if info.st_uid != os.geteuid() or (directory and not stat.S_ISDIR(info.st_mode)):
        raise LifecycleError('PROFILE_OWNER_MISMATCH')
    return info


def prepare_profile_origin(home, public_url):
    # The operator's environment is authoritative. A request cannot set this.
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(public_url)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment or any(c.isspace() for c in public_url)):
            raise ValueError()
        parsed.port
    except (TypeError, ValueError):
        raise LifecycleError('PUBLIC_ORIGIN_REQUIRED') from None
    canonical = public_url.rstrip('/')
    home = Path(home).absolute()
    safe_owned(home, directory=True)
    for path in (home / 'plugin-data', home / 'plugin-data/hermes-paseo'):
        if path.is_symlink():
            raise LifecycleError('UNSAFE_PROFILE_PATH')
        path.mkdir(mode=0o700, exist_ok=True)
        safe_owned(path, directory=True)
    state = home / 'plugin-data/hermes-paseo'
    target = state / 'dashboard-origin.json'
    if target.exists() or target.is_symlink():
        info = safe_owned(target)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
            raise LifecycleError('UNSAFE_ORIGIN_FILE')
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            current = os.fstat(descriptor)
            if (current.st_ino, current.st_dev) != (info.st_ino, info.st_dev):
                raise LifecycleError('ORIGIN_FILE_CHANGED')
            try:
                value = json.loads(os.read(descriptor, 4097))
            except (ValueError, UnicodeError):
                raise LifecycleError('ORIGIN_STATE_CORRUPT') from None
        finally:
            os.close(descriptor)
        if value != {'origin': canonical}:
            raise LifecycleError('ORIGIN_MISMATCH')
        if info.st_mode & 0o777 == 0o600:
            state.chmod(0o700)
            return
    state.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.dashboard-origin-', dir=state)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump({'origin': canonical}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


class ProfileLifecycle:
    def __init__(self, home, enabled, public_url):
        self.home = Path(home).absolute()
        self.enabled, self.public_url = enabled, public_url
        self.bridge = None
        self.error = None
        self.stopped_for_disable = False
        self.resume_after_enable = False
        self.task = None
        self.next_start = 0
        self.lock = threading.RLock()

    def _intent(self):
        path = self.home / 'plugin-data/hermes-paseo/host-lifecycle.json'
        if not path.exists():
            return {}
        info = safe_owned(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
            raise LifecycleError('UNSAFE_LIFECYCLE_FILE')
        value = json.loads(path.read_text())
        if (not isinstance(value, dict) or set(value) != {'disabled', 'resumeOnEnable'}
                or any(type(v) is not bool for v in value.values())):
            raise LifecycleError('LIFECYCLE_STATE_CORRUPT')
        return value

    def _save_intent(self, disabled):
        state = self.home / 'plugin-data/hermes-paseo'
        safe_owned(state, directory=True)
        target = state / 'host-lifecycle.json'
        if target.exists() or target.is_symlink():
            safe_owned(target)
            if target.stat().st_nlink != 1:
                raise LifecycleError('UNSAFE_LIFECYCLE_FILE')
        descriptor, temporary = tempfile.mkstemp(prefix='.lifecycle-', dir=state)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'disabled': disabled, 'resumeOnEnable': self.resume_after_enable}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def mark_disabled(self):
        with self.lock:
            self._save_intent(True)

    def load_bridge(self):
        path = self.home / 'plugins/hermes-paseo/hermes_paseo.py'
        if not path.is_file():
            return None
        safe_owned(path)
        key = '_hermes_paseo_bridge_' + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
        if key not in sys.modules:
            spec = importlib.util.spec_from_file_location(key, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[key] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(key, None)
                raise
        return sys.modules[key].get_bridge()

    def reconcile(self):
        with self.lock:
            self._reconcile()

    def _reconcile(self):
        active = bool(self.enabled())
        if active:
            prepare_profile_origin(self.home, self.public_url())
            self.bridge = self.load_bridge()
            if self.bridge is None:
                return
            snapshot = self.bridge.status()
            # A user's stop is durable. Ordinary host/process restarts should
            # recover enabled intent; a host-initiated disable may resume later.
            state_path = self.home / 'plugin-data/hermes-paseo/onboarding.json'
            paused = json.loads(state_path.read_text()).get('paused', False) if state_path.exists() else False
            intent = self._intent()
            resume_requested = False
            if intent.get('disabled'):
                self.resume_after_enable = intent['resumeOnEnable']
                self.stopped_for_disable = False
                if self.resume_after_enable:
                    self.next_start = 0
                    paused = False
                    resume_requested = True
                self._save_intent(False)
            should_start = not paused and (resume_requested or snapshot.get('phase') in ('not_installed', 'stopped'))
            if should_start and time.monotonic() >= self.next_start:
                self.next_start = time.monotonic() + 30
                self.bridge.start()
        elif self.bridge is not None and not self.stopped_for_disable:
            self.stop_for_disable()

    def stop_for_disable(self, record_intent=True):
        with self.lock:
            return self._stop_for_disable(record_intent)

    def _stop_for_disable(self, record_intent):
        if self.bridge is None:
            self.bridge = self.load_bridge()
        if self.bridge is None:
            return
        snapshot = self.bridge.status()
        intent = self._intent()
        self.resume_after_enable = intent['resumeOnEnable'] if intent.get('disabled') else snapshot.get('enabled') is True
        self.bridge.call('stop', {})
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            snapshot = self.bridge.status(fresh=True)
            if not snapshot.get('daemon', {}).get('running') and snapshot.get('phase') != 'stopping':
                self.stopped_for_disable = True
                if record_intent:
                    self._save_intent(True)
                return
            time.sleep(0.25)
        raise LifecycleError('PLUGIN_STOP_PENDING')

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.reconcile)
                self.error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code = getattr(error, 'code', None) or (str(error) if isinstance(error, LifecycleError) else 'LIFECYCLE_FAILED')
                code = code if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', code) else 'LIFECYCLE_FAILED'
                if self.error != code:
                    logger.warning('Paseo profile lifecycle requires attention: code=%s', code)
                self.error = code
            await asyncio.sleep(5)
