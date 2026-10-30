"""Unit tests for omnigent-reminder-patch (run in the image build after the patch is applied).

    /opt/omnigent/venv/bin/python -m unittest /opt/patches/tests/omnigent-reminder-patch.test.py
"""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from omnigent import _reminder_filter as rf
from omnigent.harnesses.claude_native import bridge as b

REM = "<system-reminder>\nCodebase and user instructions are shown below.\n- [x](x.md) memory\n</system-reminder>"
NOTE = (
    "<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nautomated.\n\n"
    "<task-notification>\n<task-id>abc</task-id>\n<status>completed</status>\n</task-notification>\n"
    "</system-reminder>"
)


def parse(entry, rid=None):
    return b._transcript_items_from_entry(
        entry, line_number=1, record_offset=None, agent_name="Claude", current_response_id=rid
    )


def user(content, **extra):
    return {"type": "user", "message": {"role": "user", "content": content}, **extra}


def texts(items):
    return [(i.data.get("is_meta", False), "".join(c["text"] for c in i.data["content"])) for i in items]


class SplitTests(unittest.TestCase):
    def test_no_marker_untouched(self):
        self.assertEqual(rf.split_system_reminders("hi"), ("hi", []))

    def test_unterminated_untouched(self):
        t = "<system-reminder>\nnever closed, user text"
        self.assertEqual(rf.split_system_reminders(t), (t, []))

    def test_prefix_and_tail(self):
        clean, bodies = rf.split_system_reminders(REM + "\n先去分析")
        self.assertEqual(clean, "先去分析")
        self.assertEqual(len(bodies), 1)

    def test_title_source(self):
        t = "[Attached: /data/x/shot.png]\n" + REM + "\n[Attached: /y.png]\n檢查標題\n"
        self.assertEqual(rf.title_source_text(t), "檢查標題")


class ParserTests(unittest.TestCase):
    def test_list_blocks(self):
        e = user([
            {"type": "text", "text": "[Attached: /a.png]"},
            {"type": "text", "text": REM},
            {"type": "text", "text": "真正的問題"},
        ])
        _, items = parse(e)
        out = texts(items)
        self.assertEqual(len(out), 1)
        self.assertIn("真正的問題", out[0][1])
        self.assertNotIn("system-reminder", out[0][1])
        self.assertNotIn("Codebase", out[0][1])

    def test_string_prefix(self):
        _, items = parse(user(REM + "\n換帳號了繼續吧"))
        self.assertEqual(texts(items), [(False, "換帳號了繼續吧")])

    def test_only_reminders_emit_nothing(self):
        rid, items = parse(user([{"type": "text", "text": REM}]), rid="r1")
        self.assertEqual(items, [])
        self.assertEqual(rid, "r1")

    def test_task_notification_becomes_meta(self):
        _, items = parse(user([{"type": "text", "text": NOTE}]))
        out = texts(items)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0][0])
        self.assertTrue(out[0][1].startswith("<task-notification>"))
        self.assertNotIn("SYSTEM NOTIFICATION", out[0][1])

    def test_notification_plus_user_text(self):
        _, items = parse(user([{"type": "text", "text": NOTE}, {"type": "text", "text": "好"}]))
        self.assertEqual([m for m, _ in texts(items)], [True, False])

    def test_tool_result_untouched(self):
        e = user([{"type": "tool_result", "tool_use_id": "t1", "content": REM}])
        _, items = parse(e)
        self.assertEqual([i.item_type for i in items], ["function_call_output"])

    def test_compact_summary_untouched(self):
        e = user(REM + " summary", isCompactSummary=True)
        _, items = parse(e)
        self.assertTrue(items[0].is_compact_summary)

    def test_queued_command(self):
        e = {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": REM + "\nSTOP"}}
        _, items = parse(e)
        self.assertEqual(texts(items), [(False, "STOP")])

    def test_plain_message_unchanged(self):
        _, items = parse(user("<pasted_content id=\"1\">\nhello\n</pasted_content id=\"1\">"))
        self.assertEqual(texts(items), [(False, "hello")])


class BlobDuplicateTests(unittest.TestCase):
    """Claude Code >= 2.1.300 writes api-request-blob copies of every API message (no uuid)."""

    def blob(self, message):
        return {"type": "api-request-blob", "sessionId": "s", "hash": "h", "message": message}

    def test_blob_user_message_ignored(self):
        rid, items = parse(self.blob({"role": "user", "content": "合併了"}), rid="r1")
        self.assertEqual(items, [])
        self.assertEqual(rid, "r1")

    def test_blob_assistant_and_tool_result_ignored(self):
        self.assertEqual(parse(self.blob({"role": "assistant", "content": [{"type": "text", "text": "hi"}]}))[1], [])
        tool = self.blob({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]})
        self.assertEqual(parse(tool)[1], [])

    def test_real_records_still_parsed(self):
        _, items = parse(user("合併了", uuid="u-1"))
        self.assertEqual(texts(items), [(False, "合併了")])
        self.assertTrue(rf.is_non_conversation_record({"type": "api-request"}))
        self.assertFalse(rf.is_non_conversation_record({"type": "user"}))
        self.assertFalse(rf.is_non_conversation_record({}))


class PatcherTests(unittest.TestCase):
    def load_patcher(self):
        spec = importlib.util.spec_from_file_location(
            "p", Path(__file__).resolve().parent.parent / "omnigent-reminder-patch" / "omnigent-reminder-patch.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def stock_copy(self, tmp):
        stock = Path(rf.__file__).parent  # the installed (patched) package; .orig holds the pristine files
        dst = Path(tmp) / "omnigent"
        for rel in ("version.py", "harnesses/claude_native/bridge.py", "runner/app.py", "server/background_session_titles.py"):
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            orig = stock / (rel + ".orig")  # pristine copy once the patch has run
            shutil.copyfile(orig if orig.exists() else stock / rel, dst / rel)
        return dst

    def test_apply_idempotent_and_revertible(self):
        p = self.load_patcher()
        with tempfile.TemporaryDirectory() as tmp:
            pkg = self.stock_copy(tmp)
            payload = Path(p.__file__).parent
            self.assertEqual(p.apply(pkg, payload), 0)
            self.assertTrue((pkg / "_reminder_filter.py").exists())
            before = (pkg / p.BRIDGE).read_text()
            self.assertEqual(p.apply(pkg, payload), 0)  # already patched
            self.assertEqual((pkg / p.BRIDGE).read_text(), before)

    def test_refuses_other_version(self):
        p = self.load_patcher()
        with tempfile.TemporaryDirectory() as tmp:
            pkg = self.stock_copy(tmp)
            (pkg / "version.py").write_text('VERSION = "9.9.9"\n')
            self.assertEqual(p.apply(pkg, Path(p.__file__).parent), 1)
            self.assertFalse((pkg / "_reminder_filter.py").exists())

    def test_anchor_drift_changes_nothing(self):
        p = self.load_patcher()
        with tempfile.TemporaryDirectory() as tmp:
            pkg = self.stock_copy(tmp)
            app = pkg / p.APP
            app.write_text(app.read_text().replace("body.prompt[:BACKGROUND", "body.prompt [:BACKGROUND"))
            snap = (pkg / p.BRIDGE).read_text()
            self.assertEqual(p.apply(pkg, Path(p.__file__).parent), 1)
            self.assertEqual((pkg / p.BRIDGE).read_text(), snap)


if __name__ == "__main__":
    unittest.main()
