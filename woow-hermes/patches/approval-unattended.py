#!/usr/bin/env python3
# Approval gate: runs with nobody to approve must follow their deny settings.
#
# start_gateway() sets HERMES_EXEC_ASK=1 for the whole gateway process, and
# check_all_command_guards() then skips its non-interactive branch for
# everything that process runs. A dangerous command from a cron job, the
# OpenAI-compatible API or a webhook reaches smart approval and is approved
# there, instead of being refused by approvals.cron_mode /
# approvals.unattended_mode (both deny by default). Clear the interactive
# flags for those contexts, as upstream already does for single-query runs.
#
# Exits 1 when the anchor is missing, so a base-image bump fails the build.
import sys

path = "/opt/hermes/tools/approval.py"
with open(path, encoding="utf-8") as f:
    src = f.read()

marker = "woow: unattended runs ignore HERMES_EXEC_ASK"
if marker in src:
    print(f"  [skip] {path} (already patched)")
    sys.exit(0)

anchor = (
    "    # Preserve the existing non-interactive behavior: outside CLI/gateway/ask\n"
    "    # flows, we do not block on approvals and we skip external guard work.\n"
    "    if not is_cli and not is_gateway and not is_ask:\n"
)
if src.count(anchor) != 1:
    print(f"  [FAIL] {path}: anchor found {src.count(anchor)} times, expected 1")
    sys.exit(1)

patch = (
    f"    # {marker}: cron jobs and unattended platforms have no\n"
    "    # user to answer, so cron_mode / unattended_mode must decide.\n"
    "    if _is_cron_approval_context() or _is_unattended_platform_approval_context():\n"
    "        is_cli = False\n"
    "        is_gateway = False\n"
    "        is_ask = False\n"
    "\n"
)
with open(path, "w", encoding="utf-8") as f:
    f.write(src.replace(anchor, patch + anchor, 1))
print(f"  [ok] {path}")
