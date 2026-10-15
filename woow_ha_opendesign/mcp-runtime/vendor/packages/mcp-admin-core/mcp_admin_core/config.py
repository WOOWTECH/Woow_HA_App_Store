"""Single-writer, GUI-owned state. No deployment options or executable settings.

New implementation informed by the legacy same-directory atomic replace primitive;
see docs/provenance/n8n-tracer.md. No permissive recovery from missing/corrupt state.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ConfigError(RuntimeError):
    pass


def http_url(value: str) -> str:
    if len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("invalid URL")
    parts = urlsplit(value)
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment or any(c.isspace() for c in value)
            or "\\" in value):
        raise ValueError("expected explicit HTTP URL without credentials/query/fragment")
    _ = parts.port
    return value.rstrip("/")


class State(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: int = 1
    token: str | None = Field(repr=False)
    child_token: str = Field(repr=False)
    backend_url: str | None = None
    backend_key: str | None = Field(default=None, repr=False)
    endpoint: str | None = None
    writes_enabled: bool = False
    disabled: list[str] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def version(cls, value):
        if value != 1:
            raise ValueError("unsupported schema; restore compatible backup, do not downgrade state")
        return value

    @field_validator("token", "child_token")
    @classmethod
    def tokens(cls, value, info):
        if value is None and info.field_name == "token":
            return value
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            raise ValueError("invalid token")
        return value

    @field_validator("backend_url", "endpoint")
    @classmethod
    def urls(cls, value, info):
        if value is None:
            return value
        value = http_url(value)
        if info.field_name == "endpoint" and not value.endswith("/mcp"):
            raise ValueError("endpoint must end in /mcp")
        return value

    @field_validator("backend_key")
    @classmethod
    def key(cls, value):
        if value is not None and (not value or len(value) > 8192 or any(not 32 <= ord(c) <= 126 for c in value)):
            raise ValueError("invalid credential")
        return value

    @field_validator("disabled")
    @classmethod
    def names(cls, value):
        if len(value) > 256 or len(set(value)) != len(value) or any(not re.fullmatch(r"[a-zA-Z0-9_]{1,128}", v) for v in value):
            raise ValueError("invalid disabled tools")
        return value


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite number")

    def number(text):
        value = float(text)
        if value in (float("inf"), float("-inf")):
            raise ValueError("nonfinite number")  # e.g. 1e400 would re-serialize as Infinity
        return value

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


class Store:
    """One process owns the lock until close. State is reread/validated per request.

    Dedicated 0700 subdirectory (normally /data/mcp) is owned by the runtime user.
    No migration exists before v1; missing keys are rejected, not silently seeded.
    """
    def __init__(self, directory: Path):
        self._lock_fd = None
        self._poisoned = False
        self.directory = Path(os.path.abspath(directory))
        self.path = self.directory / "state.json"
        try:
            for parent in [*reversed(self.directory.parents), self.directory]:
                if parent.is_symlink():
                    raise ConfigError("symlink state directory refused")
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.directory, 0o700)
            try:
                self._lock_fd = os.open(self.directory / ".writer.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                first_boot = True
            except FileExistsError:
                self._lock_fd = os.open(self.directory / ".writer.lock", os.O_RDWR | os.O_NOFOLLOW)
                first_boot = False
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if first_boot and not self.path.exists() and not self.path.is_symlink():
                self._write(self._initial_state())
            self.load()
        except Exception:
            self.close()
            raise ConfigError("state unavailable or incompatible; manual recovery required") from None

    def close(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def load(self) -> State:
        if self._lock_fd is None or self._poisoned:
            raise ConfigError("state unavailable")
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
                    raise ValueError("invalid state file")
                os.fchmod(stream.fileno(), 0o600)
                value = strict_json(stream.read(65537))
            return self._decode(value)
        except (OSError, ValueError, RecursionError):
            raise ConfigError("state unavailable or incompatible; manual recovery required") from None

    def _initial_state(self):
        return State(token=secrets.token_urlsafe(32), child_token=secrets.token_urlsafe(32))

    def _decode(self, value):
        if not isinstance(value, dict) or set(value) != set(State.model_fields):
            raise ValueError("incomplete schema")
        return State.model_validate(value)

    def update(self, **changes) -> State:
        try:
            updated = self._decode({**self.load().model_dump(), **changes})
        except ValueError:
            raise ConfigError("invalid state update") from None
        self._write(updated)
        return updated

    def _write(self, value: State):
        temporary = self.directory / (".state-" + secrets.token_hex(16))
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(value.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            self._poisoned = True
            raise ConfigError("durable state write failed; manual recovery required") from None
        finally:
            temporary.unlink(missing_ok=True)
