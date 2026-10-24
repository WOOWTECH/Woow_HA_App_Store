"""0.1.12: the secret-path credential (/private_<token>/mcp) never reaches a log line.

Claude.ai custom connectors cannot send an Authorization header, so the gateway also accepts the add-on token as a
path segment. A request path is then a secret. Uvicorn runs with access_log=False and Starlette's handlers never echo
a path, but any record that might (an access log someone turns on, an exception message, a warning from a library)
is scrubbed when it is created: install() wraps the process-wide LogRecord factory, so every logger and every handler
(including logging.lastResort) only ever sees /private_[REDACTED]/. RedactSecretPaths is the same scrub as a Filter,
for handlers that build records some other way (logging.makeLogRecord).
"""
from __future__ import annotations

import logging
import re

PRIVATE_SEGMENT = re.compile(r"/private_[^/\s\"'<>\\]*")
REDACTED = "/private_[REDACTED]"
_installed = False


def redact(text: str) -> str:
    return PRIVATE_SEGMENT.sub(REDACTED, text)


def leaks(text: str) -> bool:
    """True when text has a /private_ segment other than the redacted form."""
    return redact(text) != text


def _scrub_value(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value).decode("latin-1")
        return redact(text).encode("latin-1") if leaks(text) else value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    try:
        text = str(value)
    except Exception:
        return value
    return redact(text) if leaks(text) else value


def scrub(record: logging.LogRecord) -> logging.LogRecord:
    """Redact the message template, its arguments, the formatted exception and the stack in place.

    Arguments are redacted one by one (not merged into the message) so formatters that read record.args, such as
    uvicorn's access formatter, keep working. If the final message still matches (msg was an object), the record
    carries the redacted text instead.
    """
    try:
        record.msg = _scrub_value(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_scrub_value(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _scrub_value(v) for k, v in record.args.items()}
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        message = record.getMessage()
        if leaks(message):
            record.msg, record.args = redact(message), ()
    except Exception:
        # Never let logging fail open with the raw text: drop the content instead.
        record.msg, record.args, record.exc_info, record.exc_text = "log record withheld (redaction failed)", (), None, None
    return record


class RedactSecretPaths(logging.Filter):
    def filter(self, record):
        scrub(record)
        return True


def guard_handlers(*names):
    """Also filter the handlers uvicorn.Config just configured (second layer; the record factory is the first)."""
    for name in ("", *names):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactSecretPaths) for f in handler.filters):
                handler.addFilter(RedactSecretPaths())


UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")


def install():
    """Idempotent. Call before any listener starts (make_apps and both launchers do)."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        return scrub(previous(*args, **kwargs))

    logging.setLogRecordFactory(factory)
    _installed = True


# 0.2.0 (owner decision 2026-10-15): backend errors are relayed with their own text, as the PaaS servers do. Every
# credential this add-on holds is replaced in every reply the gateway relays, wherever a backend or child echoes it.
SECRET_MASK = "[REDACTED]"
SECRET_FIELDS = ("password", "api_key", "api_secret", "master_key", "app_password", "gateway_api_key",
                 "dashboard_password")
BASIC_PAIRS = (("username", "password"), ("api_key", "api_secret"), ("username", "app_password"),
               ("dashboard_username", "dashboard_password"))
MIN_SECRET = 4  # shorter values are too common in ordinary text to replace


def secret_values(state):
    """The credentials of a state: the add-on and child tokens, n8n's backend key and MCP access token, every secret connection field, and
    the Basic Authorization forms (base64 of user:secret, also URL-safe and unpadded) built from them. Longest first."""
    import base64
    found = {getattr(state, "token", None), getattr(state, "child_token", None), getattr(state, "backend_key", None),
             getattr(state, "mcp_access_token", None)}  # 0.2.1: n8n's MCP access token
    connection = getattr(state, "connection", None)
    fields = connection.model_dump() if connection is not None else {}
    found.update(fields.get(name) for name in SECRET_FIELDS)
    for user, secret in BASIC_PAIRS:
        if isinstance(fields.get(user), str) and isinstance(fields.get(secret), str):
            raw = f"{fields[user]}:{fields[secret]}".encode()
            for encode in (base64.b64encode, base64.urlsafe_b64encode):
                text = encode(raw).decode()
                found.update((text, text.rstrip("=")))
    return tuple(sorted((v for v in found if isinstance(v, str) and len(v) >= MIN_SECRET), key=len, reverse=True))


def redact_secrets(value, secrets):
    """value with every occurrence of each secret replaced by [REDACTED], in every string (keys too) of a JSON value."""
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            if secret in value:
                value = value.replace(secret, SECRET_MASK)
        return value
    if isinstance(value, list):
        return [redact_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {redact_secrets(key, secrets): redact_secrets(item, secrets) for key, item in value.items()}
    return value
