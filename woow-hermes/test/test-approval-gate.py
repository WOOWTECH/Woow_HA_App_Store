"""Run inside the add-on image: the upstream v0.22.5 unattended approval gate.

The gateway sets HERMES_EXEC_ASK=1 for its whole process. The native _presence
helper must still route cron, API calls without an approval reader, and
webhooks to approvals.cron_mode / approvals.unattended_mode (both deny).
This is the regression that the former WOOW approval patch addressed.

    podman run --rm -v hermes/test:/t:ro,Z --entrypoint /opt/hermes/.venv/bin/python <image> /t/test-approval-gate.py
"""
import os
import sys
import tempfile

HERMES_SRC = os.environ.get("HERMES_SRC", "/opt/hermes")
sys.path.insert(0, HERMES_SRC)
os.chdir(HERMES_SRC)
os.environ["HERMES_HOME"] = tempfile.mkdtemp()
for var in ("HERMES_GATEWAY_SESSION", "HERMES_INTERACTIVE", "HERMES_CRON_SESSION", "HERMES_SESSION_PLATFORM"):
    os.environ.pop(var, None)
os.environ["HERMES_EXEC_ASK"] = "1"  # what start_gateway() does

import tools.approval as approval  # noqa: E402
from gateway.session_context import _VAR_MAP  # noqa: E402

smart_calls = []
approval._smart_verdict = lambda command, *args: (smart_calls.append(command), "approve")[1]
approval.approval_context._get_approval_mode = lambda: "smart"

COMMAND = "rm -r /opt/data/workspace/approval-gate-test"
assert approval.detect_dangerous_command(COMMAND)[0], "the test command must count as dangerous"


def guard(**session):
    tokens = [(_VAR_MAP[k], _VAR_MAP[k].set(v)) for k, v in session.items()]
    smart_calls.clear()
    try:
        return approval.check_all_command_guards(COMMAND, "local"), len(smart_calls)
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


for label, session in (
    ("cron job", {"HERMES_CRON_SESSION": "1"}),
    ("OpenAI-compatible API", {"HERMES_SESSION_PLATFORM": "api_server"}),
    ("webhook", {"HERMES_SESSION_PLATFORM": "webhook"}),
):
    result, smart = guard(**session)
    assert result.get("approved") is False and "BLOCKED" in (result.get("message") or ""), \
        f"{label}: dangerous command was not refused: {result}"
    assert smart == 0, f"{label}: smart approval was consulted"
    print(f"{label}: refused")

# A person chatting on a messaging platform still gets smart approval, as before.
result, smart = guard(HERMES_SESSION_PLATFORM="telegram")
assert smart == 1 and result.get("approved") is True, f"chat session changed: {result}, smart={smart}"
print("chat session: smart approval as before")
print("approval gate: ok")
