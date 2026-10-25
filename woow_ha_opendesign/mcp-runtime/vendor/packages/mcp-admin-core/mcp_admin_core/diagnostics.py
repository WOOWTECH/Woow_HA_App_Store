"""Memory-only bounded child output; secrets are removed before retention."""
from collections import deque
from datetime import datetime, timezone
import base64
import json
import re
from urllib.parse import quote

from . import redact

MAX_LINE = 8192
MAX_BYTES = 128 * 1024
MAX_ENTRIES = 200
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|$))")
AUTH = re.compile(r"(?i)\b(Bearer|Basic)\s+[^\s\"'<>]+")
ASSIGNMENT = re.compile(r'''(?ix)(\b[\w-]{0,64}(?:token|password|passwd|secret|api[_-]?key|authorization|cookie)[\w-]{0,64}["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;&]+)''')
USERINFO = re.compile(r"(?i)(https?://)[^/\s@]+@")


def scrub_line(text, secrets=()):
    # Scrub before bounding the display: truncating first can expose half a secret.
    text = ANSI.sub("", text)
    variants = set()
    for value in secrets:
        if not isinstance(value, str) or not value:
            continue
        variants.update((value, quote(value, safe=""), json.dumps(value)[1:-1],
                         base64.b64encode(value.encode()).decode()))
    if variants:
        # One substitution pass: short credentials must not recursively replace
        # letters in the mask emitted for a previous credential.
        pattern = "|".join(re.escape(value) for value in sorted(variants, key=len, reverse=True))
        text = re.sub(pattern, lambda _: redact.SECRET_MASK, text)
    text = redact.redact(text)
    text = AUTH.sub(r"\1 [REDACTED]", text)
    text = ASSIGNMENT.sub(r"\1[REDACTED]", text)
    text = USERINFO.sub(r"\1[REDACTED]@", text)
    return "".join(c for c in text if c == "\t" or c.isprintable())[:MAX_LINE]


class ChildLogs:
    def __init__(self):
        self.entries = deque()
        self.bytes = 0
        self.dropped = 0

    def append(self, stream, text, generation, secrets=()):
        entry = {"at": datetime.now(timezone.utc).isoformat(), "stream": stream,
                 "generation": generation, "text": scrub_line(text, secrets)}
        size = len(json.dumps(entry).encode())
        if size > MAX_BYTES:
            self.dropped += 1
            return
        while self.entries and (len(self.entries) >= MAX_ENTRIES or self.bytes + size > MAX_BYTES):
            _, old_size = self.entries.popleft()
            self.bytes -= old_size
            self.dropped += 1
        self.entries.append((entry, size))
        self.bytes += size

    async def collect(self, reader, stream, generation, secrets=()):
        pending = b""
        oversized = False
        while chunk := await reader.read(4096):
            parts = chunk.split(b"\n")
            for i, part in enumerate(parts):
                if not oversized:
                    pending += part
                    if len(pending) > MAX_LINE:
                        pending, oversized = b"", True
                if i < len(parts) - 1:
                    if oversized:
                        self.dropped += 1
                    else:
                        self.append(stream, pending.decode("utf-8", "replace"), generation, secrets)
                    pending, oversized = b"", False
        if oversized:
            self.dropped += 1
        elif pending:
            self.append(stream, pending.decode("utf-8", "replace"), generation, secrets)

    def snapshot(self):
        return {"entries": [dict(entry) for entry, _ in self.entries], "dropped": self.dropped,
                "bytes": self.bytes, "max_bytes": MAX_BYTES, "max_entries": MAX_ENTRIES,
                "redacted": True, "retention": "memory"}
