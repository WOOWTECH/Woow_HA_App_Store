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
