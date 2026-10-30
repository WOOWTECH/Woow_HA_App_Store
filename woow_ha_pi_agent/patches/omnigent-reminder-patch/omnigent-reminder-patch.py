#!/usr/bin/env python3
"""Hide Claude Code <system-reminder> blocks from Omnigent chat bubbles and titles.

Symptoms this fixes (omnigent 0.16.0, claude-native harness):

  * the first web-UI message shows a 19 KB "<system-reminder> Codebase and user
    instructions ..." bubble (CLAUDE.md, auto-memory index, attribution rules);
  * the auto-generated session title describes that boilerplate
    ("記憶索引與專案狀態") instead of the request, because the title prompt is the
    first 4000 chars of the mirrored message;
  * background-task notifications, which Claude Code now wraps in a reminder,
    miss the existing "<task-notification>" meta path and render as user bubbles;
  * every typed message and tool result appears TWICE: Claude Code >= 2.1.300 writes
    "api-request-blob" records (a copy of each API message, no uuid) and omnigent mirrors
    any record that has a message role, under a byte-offset source id the server cannot
    dedupe against the real record's uuid.

Root cause: Claude Code stores its reminders in the SAME role=user transcript
record as the person's text; the forwarder mirrors every text block verbatim.

What it changes (all under <site-packages>/omnigent):

  * adds _reminder_filter.py;
  * harnesses/claude_native/bridge.py: api-request-* records are skipped; user
    records are stripped of reminder blocks before parsing; task notifications found inside a reminder become
    meta items; queued prompts are stripped too;
  * runner/app.py and server/background_session_titles.py: the title prompt is
    cleaned (reminders and "[Attached: ...]" markers removed) BEFORE the 4000
    character cut.

Same safety model as the other omnigent patches in this fleet: version gate,
idempotent marker, pristine copy kept as <file>.orig, result must compile or the
original is restored, and it never raises (exit 0 on every abnormal path unless
--strict). Needs write access to site-packages, so run it at image build time.
"""

from __future__ import annotations

import argparse
import py_compile
import shutil
import sys
from pathlib import Path

EXPECTED_VERSION = "0.16.0"
MARKER = "omnigent-reminder-patch v2"

BRIDGE = "harnesses/claude_native/bridge.py"
APP = "runner/app.py"
SERVER_TITLES = "server/background_session_titles.py"

BRIDGE_WRAPPER = '''\
def _user_transcript_items_from_entry(
    entry: _JsonObject,
    *,
    line_number: int,
    record_offset: int | None,
    agent_name: str,
    current_response_id: str | None,
) -> tuple[str | None, list[ClaudeTranscriptItem]]:
    """
    Parse a Claude ``role=user`` record after removing injected reminders.

    # omnigent-reminder-patch v2
    Claude Code writes ``<system-reminder>`` context into the same record as the
    person's text. Strip it first so it never becomes a user bubble (or a title
    prompt); task notifications wrapped in a reminder are re-surfaced as the
    ``is_meta`` items the UI already renders compactly.
    """
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if (
        entry.get("isMeta") is True
        or entry.get("isCompactSummary") is True
        or not isinstance(message, dict)
    ):
        return _user_transcript_items_from_clean_entry(
            entry,
            line_number=line_number,
            record_offset=record_offset,
            agent_name=agent_name,
            current_response_id=current_response_id,
        )
    notices: list[str] = []
    changed = False
    new_content: object = content
    if isinstance(content, str):
        cleaned, bodies = _reminder_filter.split_system_reminders(content)
        if bodies:
            changed = True
            notices.extend(_reminder_filter.task_notifications_in(bodies))
            new_content = cleaned
    elif isinstance(content, list):
        kept: list[object] = []
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                cleaned, bodies = _reminder_filter.split_system_reminders(block["text"])
                if bodies:
                    changed = True
                    notices.extend(_reminder_filter.task_notifications_in(bodies))
                    if not cleaned:
                        continue
                    block = {**block, "text": cleaned}
            kept.append(block)
        new_content = kept
    if changed:
        entry = {**entry, "message": {**message, "content": new_content}}
    response_id, items = _user_transcript_items_from_clean_entry(
        entry,
        line_number=line_number,
        record_offset=record_offset,
        agent_name=agent_name,
        current_response_id=current_response_id,
    )
    if not notices:
        return response_id, items
    source_key = _transcript_source_key(entry, line_number, record_offset)
    notice_items = [
        ClaudeTranscriptItem(
            source_id=_source_id(source_key, 1000 + index, "message"),
            item_type="message",
            data={
                "role": "user",
                "is_meta": True,
                "content": [{"type": "input_text", "text": notice}],
            },
            response_id=_response_id_from_source(source_key),
        )
        for index, notice in enumerate(notices)
    ]
    return (None if not items else response_id), notice_items + items


'''

# (relative path, old, new) — each ``old`` must occur exactly once.
EDITS: list[tuple[str, str, str]] = [
    (
        BRIDGE,
        "from omnigent._platform import IS_WINDOWS, is_wsl, stable_user_id\n",
        "from omnigent import _reminder_filter\n"
        "from omnigent._platform import IS_WINDOWS, is_wsl, stable_user_id\n",
    ),
    (
        BRIDGE,
        '    if not include_sidechains and entry.get("isSidechain") is True:\n'
        "        return current_response_id, []\n"
        '    if entry.get("type") == "attachment":\n',
        '    if not include_sidechains and entry.get("isSidechain") is True:\n'
        "        return current_response_id, []\n"
        "    if _reminder_filter.is_non_conversation_record(entry):\n"
        "        return current_response_id, []\n"
        '    if entry.get("type") == "attachment":\n',
    ),
    (
        BRIDGE,
        "def _user_transcript_items_from_entry(\n",
        BRIDGE_WRAPPER + "def _user_transcript_items_from_clean_entry(\n",
    ),
    (
        BRIDGE,
        '    prompt = attachment.get("prompt")\n'
        "    if not isinstance(prompt, str) or not prompt:\n"
        "        return current_response_id, []\n",
        '    prompt = attachment.get("prompt")\n'
        "    if isinstance(prompt, str):\n"
        "        prompt = _reminder_filter.split_system_reminders(prompt)[0]\n"
        "    if not isinstance(prompt, str) or not prompt:\n"
        "        return current_response_id, []\n",
    ),
    (
        APP,
        "            prompt=body.prompt[:BACKGROUND_TITLE_MAX_PROMPT_CHARS],\n",
        "            prompt=_reminder_filter.title_source_text(body.prompt)"
        "[:BACKGROUND_TITLE_MAX_PROMPT_CHARS],\n",
    ),
    (
        APP,
        "from omnigent.runner.background_titles.service import BACKGROUND_TITLE_MAX_PROMPT_CHARS\n",
        "from omnigent import _reminder_filter\n"
        "from omnigent.runner.background_titles.service import BACKGROUND_TITLE_MAX_PROMPT_CHARS\n",
    ),
    (
        SERVER_TITLES,
        "from omnigent.entities.conversation import (\n",
        "from omnigent import _reminder_filter\nfrom omnigent.entities.conversation import (\n",
    ),
    (
        SERVER_TITLES,
        "            if isinstance(text, str):\n                parts.append(text)\n"
        '    return " ".join(parts)[:4000]\n',
        "            if isinstance(text, str):\n"
        "                text = _reminder_filter.title_source_text(text)\n"
        "                if text:\n"
        "                    parts.append(text)\n"
        '    return " ".join(parts)[:4000]\n',
    ),
]


def log(msg: str) -> None:
    print(f"[omnigent-reminder-patch] {msg}", flush=True)


def installed_version(pkg: Path) -> str | None:
    vfile = pkg / "version.py"
    if not vfile.is_file():
        return None
    for line in vfile.read_text(encoding="utf-8").splitlines():
        if line.startswith("VERSION"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None


def apply(pkg: Path, payload_dir: Path) -> int:
    """Return 0 on success/no-op, 1 on refusal or failure."""
    version = installed_version(pkg)
    if version != EXPECTED_VERSION:
        log(f"omnigent {version!r} != validated {EXPECTED_VERSION!r}; leaving it alone")
        return 1
    bridge = pkg / BRIDGE
    if MARKER in bridge.read_text(encoding="utf-8"):
        log("already patched")
        return 0

    texts: dict[str, str] = {}
    for rel, old, new in EDITS:
        path = pkg / rel
        if not path.is_file():
            # server/ may be absent in a host-only image; only bridge + app are mandatory.
            if rel == SERVER_TITLES:
                continue
            log(f"missing {rel}; nothing changed")
            return 1
        text = texts.setdefault(rel, path.read_text(encoding="utf-8"))
        if text.count(old) != 1:
            log(f"anchor not found exactly once in {rel}: {old[:60]!r}; nothing changed")
            return 1
        texts[rel] = text.replace(old, new, 1)

    written: list[Path] = []
    filter_dst = pkg / "_reminder_filter.py"
    try:
        shutil.copyfile(payload_dir / "_reminder_filter.py", filter_dst)
        written.append(filter_dst)
        for rel, text in texts.items():
            path = pkg / rel
            orig = path.with_name(path.name + ".orig")
            if not orig.exists():
                shutil.copyfile(path, orig)
            path.write_text(text, encoding="utf-8")
            written.append(path)
        for path in written:
            py_compile.compile(str(path), doraise=True)
    except Exception as exc:  # noqa: BLE001 - restore on any failure
        log(f"failed ({exc!r}); restoring originals")
        for rel in texts:
            path = pkg / rel
            orig = path.with_name(path.name + ".orig")
            if orig.exists():
                shutil.copyfile(orig, path)
        filter_dst.unlink(missing_ok=True)
        return 1
    log(f"patched {len(texts)} files + _reminder_filter.py")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--site-packages", required=True, type=Path)
    ap.add_argument("--strict", action="store_true", help="exit non-zero when not applied")
    args = ap.parse_args()
    pkg = args.site_packages / "omnigent"
    if not pkg.is_dir():
        log(f"no omnigent package under {args.site_packages}")
        return 1 if args.strict else 0
    rc = apply(pkg, Path(__file__).resolve().parent)
    return rc if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
