# Unmodified upstream excerpts; see provenance.json and README.md.
from __future__ import annotations
import glob
import sqlite3
from pathlib import Path
from typing import *

def _delegate_from_json(col: str = "model_config") -> str:
    return f"json_extract(COALESCE({col}, '{{}}'), '$._delegate_from')"


def _collect_delegate_child_ids(conn, parent_ids: List[str]) -> List[str]:
    """Delegate-subagent ids to cascade-delete with *parent_ids*.

    Only rows carrying the ``_delegate_from`` marker (set at creation, and
    backfilled by the v16 migration) — generic untagged children keep the
    orphan-don't-delete contract. Walks marker chains recursively so an
    orchestrator subagent's own delegate children go too (FK safety).
    """
    df = _delegate_from_json()
    seeds = {sid for sid in parent_ids if sid}
    # Seed the visited set with the parents themselves. A delegation marker
    # chain can loop back onto a parent — a cycle, or a parent that is also
    # another parent's delegate child when several ids are deleted at once —
    # and without this guard that parent would be collected as one of its own
    # descendants and cascade-deleted along with all of its messages. Callers
    # delete the parents separately, so parents must never appear in the
    # returned child set. (#49148)
    found: set[str] = set(seeds)
    frontier = list(seeds)
    while frontier:
        ph = ",".join("?" * len(frontier))
        cursor = conn.execute(
            f"SELECT id FROM sessions WHERE {df} IN ({ph}) "
            f"OR (parent_session_id IN ({ph}) AND {df} IS NOT NULL)",
            frontier + frontier,
        )
        frontier = [row["id"] for row in cursor.fetchall() if row["id"] not in found]
        found.update(frontier)
    # Return only the discovered children — never the parents themselves.
    return [sid for sid in found if sid not in seeds]


def _delete_delegate_children(conn, parent_ids: List[str]) -> List[str]:
    ids = _collect_delegate_child_ids(conn, parent_ids)
    if ids:
        ph = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM messages WHERE session_id IN ({ph})", ids)
        # FK safety: orphan any untagged stragglers pointing at a doomed row.
        conn.execute(
            f"UPDATE sessions SET parent_session_id = NULL "
            f"WHERE parent_session_id IN ({ph})",
            ids,
        )
        conn.execute(f"DELETE FROM sessions WHERE id IN ({ph})", ids)
    return ids


class Methods:
    @staticmethod
    def _remove_session_files(sessions_dir: Optional[Path], session_id: str) -> None:
        """Remove on-disk transcript files for a session.

        Cleans up ``{session_id}.json``, ``{session_id}.jsonl``, and any
        ``request_dump_{session_id}_*.json`` files left by the gateway.
        Silently skips files that don't exist and swallows OSError so a
        filesystem hiccup never blocks a DB operation.
        """
        if sessions_dir is None:
            return
        for suffix in (".json", ".jsonl"):
            p = sessions_dir / f"{session_id}{suffix}"
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        # request_dump files use session_id as a prefix component
        try:
            for p in sessions_dir.glob(f"request_dump_{session_id}_*.json"):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass


    def delete_session(
        self,
        session_id: str,
        sessions_dir: Optional[Path] = None,
        expected_delete_ids: Optional[List[str]] = None,
    ) -> bool:
        """Delete a session and all its messages.

        Delegate subagent children (``model_config._delegate_from``) are
        cascade-deleted with the parent so they never resurface in session
        pickers as orphaned rows. Branch / compression children are orphaned
        (``parent_session_id → NULL``) so they remain accessible independently.
        When *sessions_dir* is provided, also removes on-disk transcript
        files (``.json`` / ``.jsonl`` / ``request_dump_*``) for every deleted
        session. When *expected_delete_ids* is provided, deletion proceeds only
        if the parent plus delegate cascade still matches that exact set. This
        lets export-before-delete callers fail closed if a new delegate appears
        after they materialize their archive. The delegate tree is re-walked
        inside the write transaction on purpose (TOCTOU guard); the cost is
        accepted for correctness. Returns True if the session was found and
        deleted.
        """
        removed_delegate_ids: List[str] = []
        expected_ids = (
            set(expected_delete_ids) if expected_delete_ids is not None else None
        )

        def _do(conn):
            cursor = conn.execute(
                "SELECT 1 FROM sessions WHERE id = ? LIMIT 1", (session_id,)
            )
            if cursor.fetchone() is None:
                return False
            if expected_ids is not None:
                actual_ids = {
                    session_id,
                    *_collect_delegate_child_ids(conn, [session_id]),
                }
                if actual_ids != expected_ids:
                    return False
            removed_delegate_ids.extend(_delete_delegate_children(conn, [session_id]))
            # Orphan remaining child sessions (branches, etc.) so FK is satisfied.
            conn.execute(
                "UPDATE sessions SET parent_session_id = NULL "
                "WHERE parent_session_id = ?",
                (session_id,),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._delete_unreferenced_system_prompts(conn)
            return True

        deleted = self._execute_write(_do)
        if deleted:
            for delegate_id in removed_delegate_ids:
                self._remove_session_files(sessions_dir, delegate_id)
            self._remove_session_files(sessions_dir, session_id)
        return bool(deleted)


    def delete_sessions(
        self,
        session_ids: List[str],
        sessions_dir: Optional[Path] = None,
    ) -> int:
        """Delete every session in *session_ids* in a single transaction.

        Backs the dashboard's bulk-select-then-delete flow on the
        sessions page (``POST /api/sessions/bulk-delete``). Mirrors the
        single-session :meth:`delete_session` contract per row:

        * Unknown IDs are silently skipped (no 404) — selection state
          in the UI can race against another tab's delete, and we'd
          rather succeed-on-the-rest than fail-the-whole-batch.
        * Delegate subagent children (``model_config._delegate_from``) are
          cascade-deleted with their parent; branch children are orphaned
          (``parent_session_id → NULL``) so they stay accessible.
        * Messages and the session row both go in one
          ``_execute_write`` call so a partial failure can't leave the
          DB in a "messages gone but session row still there" state.
        * On-disk transcript / ``request_dump_*`` files are cleaned up
          outside the DB transaction when *sessions_dir* is provided,
          matching :meth:`prune_sessions` and
          :meth:`delete_empty_sessions`.

        Returns the count of sessions that actually existed and were
        deleted (may be less than ``len(session_ids)`` if some IDs were
        already gone).
        """
        if not session_ids:
            return 0
        # Dedup + drop any non-string entries up-front. Avoids
        # double-counting in the WHERE-IN list and protects against
        # callers that pass a list with stray ``None`` values.
        unique_ids = list({sid for sid in session_ids if isinstance(sid, str) and sid})
        if not unique_ids:
            return 0

        removed_ids: list[str] = []
        removed_delegate_ids: list[str] = []

        def _do(conn):
            placeholders = ",".join("?" * len(unique_ids))
            # First, filter to IDs that actually exist — we want to
            # return the real deleted count, not the input length.
            cursor = conn.execute(
                f"SELECT id FROM sessions WHERE id IN ({placeholders})",
                unique_ids,
            )
            existing = [row["id"] for row in cursor.fetchall()]
            if not existing:
                return 0

            existing_placeholders = ",".join("?" * len(existing))
            removed_delegate_ids.extend(_delete_delegate_children(conn, existing))
            # Orphan remaining children whose parent is in the kill list so the
            # FK constraint stays satisfied. Pin children whose parent
            # is itself in the kill list rather than NULL-ing parents
            # of survivors — the IN list on ``parent_session_id`` does
            # exactly this.
            conn.execute(
                f"UPDATE sessions SET parent_session_id = NULL "
                f"WHERE parent_session_id IN ({existing_placeholders})",
                existing,
            )
            conn.execute(
                f"DELETE FROM messages WHERE session_id IN ({existing_placeholders})",
                existing,
            )
            conn.execute(
                f"DELETE FROM sessions WHERE id IN ({existing_placeholders})",
                existing,
            )
            self._delete_unreferenced_system_prompts(conn)
            removed_ids.extend(existing)
            return len(existing)

        count = self._execute_write(_do)
        for sid in removed_delegate_ids:
            self._remove_session_files(sessions_dir, sid)
        for sid in removed_ids:
            self._remove_session_files(sessions_dir, sid)
        return count


    @staticmethod
    def _delete_unreferenced_system_prompts(conn) -> None:
        conn.execute(
            "DELETE FROM system_prompts "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM sessions "
            "WHERE sessions.system_prompt_hash = system_prompts.hash"
            ")"
        )
