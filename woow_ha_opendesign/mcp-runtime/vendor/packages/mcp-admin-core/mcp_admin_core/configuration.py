"""Opaque edit revisions and generation-bound child application status.

All metadata is runtime-only. Public tokens/endpoints do not change the child
launch identity. Backend reachability is deliberately separate from application.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets


class ConfigurationState:
    def __init__(self, store, process=None, health=None):
        self.store, self.process, self.health = store, process, health
        self._key = secrets.token_bytes(32)
        self._attempted = None
        self._minimum_generation = None
        self._applied = None
        self._applied_generation = None
        self._error = None

    def _revision(self, value, domain):
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        return 'c1-' + hmac.new(self._key, domain.encode() + b'\0' + raw, hashlib.sha256).hexdigest()

    def revision(self, state):
        return self._revision(state.model_dump(mode='json'), 'edit')

    def etag(self, state):
        return '"' + self.revision(state) + '"'

    def launch_revision(self, state):
        raw = state.model_dump(mode='json')
        # These are the inputs read by the fixed product/n8n child launchers.
        fields = ('product', 'child_token', 'connection', 'backend_url', 'backend_key', 'mcp_access_token')
        value = {key: raw.get(key) for key in fields}
        if raw.get('product') in ('emqx', 'litellm', 'nextcloud'):
            # Native child policy is also rebuilt for these products.
            value.update({key: raw.get(key) for key in
                          ('writes_enabled', 'disabled', 'enabled_write_tools', 'denied_operations')})
        return self._revision(value, 'launch')

    def begin(self, state):
        """Before stop/start, freeze the attempted config and reject old readiness."""
        self._attempted = self.launch_revision(state)
        self._minimum_generation = getattr(self.process, 'starts', 0) + 1
        self._error = None

    def failed(self, code='child_start_failed'):
        if code not in ('child_start_failed', 'child_restart_failed'):
            raise ValueError('invalid configuration error code')
        self._error = code

    def snapshot(self, state):
        saved = self.launch_revision(state)
        product = getattr(state, 'product', 'n8n')
        configured = getattr(state, 'configured', bool(state.backend_url and state.backend_key))
        phase = getattr(self.process, 'status', 'unknown')
        generation = getattr(self.process, 'starts', None)
        settled = getattr(self.health, 'settled', None)
        attempted_current = self._attempted == saved
        generation_current = (self._minimum_generation is not None and generation is not None
                              and generation >= self._minimum_generation)
        ready = (phase == 'running' and generation_current and settled is not None
                 and settled[0] == generation and settled[1] is True)
        if ready:
            # Health proves the child generation, not whichever config was saved later.
            self._applied, self._applied_generation = self._attempted, generation
            self._error = None
        applied = self._applied if phase == 'running' and self._applied_generation == generation else None
        error = self._error if attempted_current else None
        if product != 'n8n' and not configured:
            status, applied, error = 'unconfigured', None, None
        elif applied == saved and generation_current and not error:
            status = 'applied'
        elif error:
            status = 'failed'
        elif attempted_current and phase in ('failed', 'stopped'):
            status, error = 'failed', 'child_start_failed'
        elif (attempted_current and generation_current and settled is not None
              and settled[0] == generation and settled[1] is False and phase == 'running'):
            status, error = 'failed', 'child_not_ready'
        elif self._attempted is None:
            status = 'unknown'
        else:
            status = 'pending'
        return {'revision': self.revision(state), 'saved_revision': saved,
                'applied_revision': applied, 'apply_state': status, 'last_error_code': error}
