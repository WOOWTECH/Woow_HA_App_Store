"""Keep Claude Code's non-conversation transcript content out of mirrored chat.

Two sources of noise, both new in the claude-native transcript since Claude Code 2.1.300:

* ``api-request-blob`` records (no ``uuid``) carry a copy of every message sent to the API.
  omnigent parses any record with a ``message`` role, so each user/assistant message and tool
  result is mirrored a second time under a ``byte-<offset>`` source id — the server cannot
  dedupe it, so the web chat shows the typed message (and tool output) twice.
* ``<system-reminder>`` blocks.

Claude Code writes its own context (CLAUDE.md, auto-memory index, attribution
rules, automated task notifications) into the *same* ``role=user`` transcript
record as the person's message, as extra ``<system-reminder>`` text blocks or as
a prefix inside one block. The model needs them; a chat viewer must not see
them, and neither must the session-title generator.
"""

from __future__ import annotations

import re

_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>(?P<body>.*?)</system-reminder>", re.DOTALL)
_TASK_NOTIFICATION_RE = re.compile(r"<task-notification>.*?</task-notification>", re.DOTALL)
# Lines Omnigent itself prepends for attachments; useful in the chat, noise in a title.
_ATTACHED_LINE_RE = re.compile(r"^\[Attached: [^\]\n]*\]\s*$", re.MULTILINE)


def split_system_reminders(text: str) -> tuple[str, list[str]]:
    """Return ``(text without reminder blocks, reminder bodies)``.

    Text with no complete block (including an unterminated opening tag) is
    returned untouched, so a half-written marker never eats user content.
    """
    if "<system-reminder>" not in text:
        return text, []
    bodies: list[str] = []

    def _collect(match: re.Match[str]) -> str:
        bodies.append(match.group("body"))
        return ""

    remainder = _SYSTEM_REMINDER_RE.sub(_collect, text)
    if not bodies:
        return text, []
    return remainder.strip(), bodies


def task_notifications_in(reminder_bodies: list[str]) -> list[str]:
    """Pull ``<task-notification>`` documents out of reminder bodies.

    Claude Code wraps background-task completions in a reminder; the web UI
    already knows how to show a bare ``<task-notification>`` as a compact
    meta item, so surface those and drop the surrounding boilerplate.
    """
    found: list[str] = []
    for body in reminder_bodies:
        found.extend(_TASK_NOTIFICATION_RE.findall(body))
    return found


def title_source_text(text: str) -> str:
    """Prompt text for title generation: no reminders, no attachment markers."""
    cleaned, _ = split_system_reminders(text)
    cleaned = _ATTACHED_LINE_RE.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def is_non_conversation_record(entry: dict) -> bool:
    """True for transcript records that only mirror API traffic (``api-request-blob`` etc.)."""
    record_type = entry.get("type")
    return isinstance(record_type, str) and record_type.startswith("api-request")
