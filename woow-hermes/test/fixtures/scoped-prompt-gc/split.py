# Unmodified upstream excerpts; see provenance.json and README.md.
from __future__ import annotations
import glob
import sqlite3
from pathlib import Path
from typing import *

def _sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"

def _sql_json_extract(expression: str, path: str) -> str:
    """Build a non-throwing JSON marker lookup for a JSON TEXT column."""

    safe_json = (
        f"(CASE WHEN json_valid({expression}) "
        f"THEN {expression} ELSE json_object() END)"
    )
    return f"json_extract({safe_json}, {_sql_literal(path)})"

_RESET_END_REASONS = ("session_reset", "session_switch", "idle", "daily", "suspended", "resume_pending_expired")

_RESET_END_REASONS_SQL = ", ".join(f"'{reason}'" for reason in _RESET_END_REASONS)

def _legacy_reset_child_sql(alias: str, reasons_sql: str) -> str:
    """Pre-marker reset-continuation heuristic: child rides its parent's exact non-empty routing key and the
    parent ended at a reset boundary.  Shared by ``_RESET_CHILD_SQL`` and ``reopen_session()`` so the two
    cannot drift; ``reasons_sql`` is a literal or placeholder list."""
    return (f"EXISTS (SELECT 1 FROM sessions p            WHERE p.id = {alias}.parent_session_id"
        f"            AND p.end_reason IN ({reasons_sql})            AND {alias}.session_key IS NOT NULL"
        f"            AND {alias}.session_key != ''            AND {alias}.session_key = p.session_key)")

_RESET_CHILD_SQL = (f"{_sql_json_extract('{a}.model_config', '$._reset_from')} IS NOT NULL"
    " OR " + _legacy_reset_child_sql("{a}", _RESET_END_REASONS_SQL))

def _placeholders(items) -> str:
    """``?,?,?`` for one bound parameter per element of *items* (a sequence or an int count)."""
    return ",".join("?" for _ in range(items if isinstance(items, int) else len(items)))

_SQL_IN_CHUNK = 900

def _id_chunks(ids, size: int = _SQL_IN_CHUNK):
    """Yield *ids* (any iterable) as lists of at most *size* elements."""
    ids = list(ids)
    for start in range(0, len(ids), size):
        yield ids[start:start + size]
_session_ids_placeholders = _placeholders
_CHAIN_CAP = 1000

def _delegate_from_json(col: str = "model_config") -> str:
    return _sql_json_extract(col, "$._delegate_from")


def _expand_compression_lineage_ids(conn, frontier: List[str]) -> List[str]:
    """One both-direction compression-edge step from *frontier*: forward through every
    continuation child and backward through the compression parent, using the SAME edge
    definition as ``_CHAIN_STEP_SQL`` / the list-projection CTE (parent ended with
    ``reason='compression'``, child is not a branch / reset / delegate / tool session).
    Branch/reset children are NOT continuations — they are their own conversations."""
    ids = [sid for sid in frontier if sid]
    if not ids:
        return []
    out: List[str] = []
    for chunk in _id_chunks(ids, _SQL_IN_CHUNK // 4):  # each id bound 4x below
        ph = _session_ids_placeholders(chunk)
        child_filter = (
            f"{_sql_json_extract('child.model_config', '$._branched_from')} IS NULL "
            f"AND {_sql_json_extract('child.model_config', '$._delegate_from')} IS NULL "
            f"AND NOT ({_RESET_CHILD_SQL.format(a='child')}) "
            "AND COALESCE(child.source, '') != 'tool'"
        )
        out.extend(row["id"] for row in conn.execute(
            # forward: every continuation of a compression-ended frontier row
            f"SELECT child.id FROM sessions parent "
            f"JOIN sessions child ON child.parent_session_id = parent.id "
            f"WHERE parent.id IN ({ph}) AND parent.end_reason = 'compression' AND {child_filter}",
            chunk,
        ).fetchall())
        out.extend(row["id"] for row in conn.execute(
            # backward: the compression parent of a frontier row
            f"SELECT parent.id FROM sessions child "
            f"JOIN sessions parent ON parent.id = child.parent_session_id "
            f"WHERE child.id IN ({ph}) AND parent.end_reason = 'compression' "
            f"AND {child_filter}",
            chunk,
        ).fetchall())
    return out


def _collect_delegate_child_ids(conn, parent_ids: List[str]) -> List[str]:
    """Delegate-subagent ids (``_delegate_from`` marker, walked recursively) to cascade-delete with
    *parent_ids*; untagged children stay orphaned, not deleted."""
    df = _delegate_from_json()
    seeds = {sid for sid in parent_ids if sid}
    # Seed visited with the parents: a marker chain can loop back onto a parent,
    # which would then be collected as its own descendant. Never return parents.
    # A delegation marker chain can loop back onto a parent — a cycle, or a parent that is also another
    # parent's delegate child when several ids are deleted at once — and without this guard that parent
    # would be collected as one of its own descendants and cascade-deleted along with all of its messages.
    # Callers delete the parents separately, so parents must never appear in the returned child set.
    # (#49148)
    found: set[str] = set(seeds)
    frontier = list(seeds)
    while frontier:
        next_frontier: List[str] = []
        for chunk in _id_chunks(frontier, _SQL_IN_CHUNK // 2):  # each id is bound twice below
            ph = _session_ids_placeholders(chunk)
            cursor = conn.execute(
                f"SELECT id FROM sessions WHERE {df} IN ({ph}) "
                f"OR (parent_session_id IN ({ph}) AND {df} IS NOT NULL)", chunk + chunk,
            )
            for row in cursor.fetchall():
                if row["id"] not in found:
                    found.add(row["id"])
                    next_frontier.append(row["id"])
        frontier = next_frontier
    return [sid for sid in found if sid not in seeds]


def _delete_delegate_children(conn, parent_ids: List[str]) -> List[str]:
    ids = _collect_delegate_child_ids(conn, parent_ids)
    for chunk in _id_chunks(ids):
        ph = _session_ids_placeholders(chunk)
        conn.execute(f"DELETE FROM messages WHERE session_id IN ({ph})", chunk)
        # FK safety: orphan any untagged stragglers pointing at a doomed row.
        conn.execute(f"UPDATE sessions SET parent_session_id = NULL WHERE parent_session_id IN ({ph})", chunk)
        conn.execute(f"DELETE FROM sessions WHERE id IN ({ph})", chunk)
    return ids


class Methods:
    @staticmethod
    def _remove_session_files(sessions_dir: Optional[Path], session_id: str) -> None:
        """Remove ``<id>.json``/``.jsonl``, the legacy ``session_<id>.json`` snapshot, and gateway
        ``request_dump_<id>_*.json``; OSError is swallowed so a filesystem hiccup never blocks a
        DB operation. Every historical writer name is swept because a "deleted" session's snapshot
        can carry plaintext secrets (#20334, #60207)."""
        if sessions_dir is None:
            return
        targets = [sessions_dir / f"{session_id}{suffix}" for suffix in (".json", ".jsonl")]
        targets.append(sessions_dir / f"session_{session_id}.json")
        try:
            # glob.escape: a session id carrying ``[`` / ``?`` / ``*`` is a PATTERN otherwise, so the
            # dump sweep either matches nothing or matches another session's files.
            targets.extend(sessions_dir.glob(f"request_dump_{glob.escape(session_id)}_*.json"))
        except OSError:
            pass
        for p in targets:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


    def _expand_compression_lineage(self, conn, session_ids: List[str]) -> List[str]:
        """Expand *session_ids* to every member of their compression chains.

        The dashboard sessions list surfaces one row per logical conversation: compression
        roots are projected forward to their latest continuation, and the surfaced row
        carries the *tip's* id (see :meth:`list_sessions_rich`). Deleting only that tip row
        leaves the root behind, and the next list re-projects the root onto the previous
        link — the "deleted" conversation reappears (#57543).

        Walks compression-continuation edges in BOTH directions from the given ids:
        backward to the chain root, and forward through every continuation — including
        stale sibling continuations (e.g. ``ws_orphan_reap`` leftovers), which would
        otherwise be orphaned into brand-new visible top-level rows by the delete itself.
        The edge definition matches ``_CHAIN_STEP_SQL`` / ``get_compression_tip`` and the
        list-projection CTE: parent ended with ``reason='compression'``, child is not a
        branch / reset / delegate / tool session. Branch, reset and delegate children are
        deliberately NOT pulled in — a branch/reset is its own conversation, and delegates
        are handled by the existing cascade in the delete paths.

        Runs inside the caller's write transaction (*conn*). The walk is defensively
        bounded like ``get_compression_chain`` — ``seen`` guards cycles.
        """
        seen = set(session_ids)
        frontier = list(session_ids)
        for _ in range(_CHAIN_CAP):
            if not frontier:
                break
            targets = _expand_compression_lineage_ids(conn, frontier)
            frontier = [sid for sid in targets if sid not in seen]
            seen.update(frontier)
        return list(seen)


    def delete_session(
        self, session_id: str, sessions_dir: Optional[Path] = None,
        expected_delete_ids: Optional[List[str]] = None,
        expected_display_messages: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        exclude_active_write_guards: bool = False,
        include_compression_chain: bool = False,
    ) -> bool:
        """Delete a session and its messages; delegate children cascade, branch/compression children
        are orphaned. Optional expected ids fence delegate drift; expected display snapshots fence
        transcript drift. Both checks run inside the same write transaction as deletion.
        With ``exclude_active_write_guards``, raises :class:`SessionActiveWriteGuardError` if the row
        is protected by an active turn lease or compression lock.

        With ``include_compression_chain=True`` the whole compression chain the session belongs to
        is deleted with it (root and every continuation) — the dashboard delete endpoints use this
        variant because their list rows carry chain-*tip* ids; deleting only that physical row
        would leave the rest of the chain to resurface on the next list (#57543). Default False so
        callers that operate on a single physical session keep the historic contract. Routing
        through :meth:`delete_sessions` keeps the chain-aware guard/counting semantics in one
        place; its return value counts the *requested* ids that existed, so ``> 0`` is exactly
        "the session was found"."""
        if include_compression_chain:
            return self.delete_sessions(
                [session_id], sessions_dir=sessions_dir,
                exclude_active_write_guards=exclude_active_write_guards,
                include_compression_chain=True,
            ) > 0
        removed_ids: List[str] = []
        expected_ids = set(expected_delete_ids) if expected_delete_ids is not None else None
        def _do(conn):
            if conn.execute("SELECT 1 FROM sessions WHERE id = ? LIMIT 1", (session_id,)).fetchone() is None:
                return False
            target_ids = (
                [session_id, *_collect_delegate_child_ids(conn, [session_id])]
                if exclude_active_write_guards or expected_ids is not None else None
            )
            if exclude_active_write_guards and self._guarded_ids(conn, target_ids):
                # Delegate children cascade with the root, so a guard on any of them refuses too.
                raise SessionActiveWriteGuardError(
                    f"session '{session_id}' (or a delegate child) has an active turn lease or compression lock"
                )
            if expected_ids is not None and expected_ids != set(target_ids):
                return False
            if expected_display_messages is not None and any(
                self._display_messages_from_conn(conn, covered_id) != expected
                for covered_id, expected in expected_display_messages.items()
            ):
                return False
            removed_ids.extend(_delete_delegate_children(conn, [session_id]))
            conn.execute(  # orphan remaining children (branches) so FK is satisfied
                "UPDATE sessions SET parent_session_id = NULL WHERE parent_session_id = ?", (session_id,),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._delete_unreferenced_system_prompts(conn)
            removed_ids.append(session_id)
            return True
        deleted = self._execute_write(_do)
        for sid in removed_ids:
            self._remove_session_files(sessions_dir, sid)
        return bool(deleted)


    def delete_sessions(
        self, session_ids: List[str], sessions_dir: Optional[Path] = None,
        exclude_active_write_guards: bool = False, skipped_ids: Optional[List[str]] = None,
        include_compression_chain: bool = False,
    ) -> int:
        """Bulk delete with :meth:`delete_session` semantics per row, in ONE transaction. Unknown ids
        are skipped (UI selection can race another tab's delete). With ``exclude_active_write_guards``, rows
        protected by an active turn lease or compression lock are skipped and, when given, appended
        to ``skipped_ids`` so callers can tell the user. Returns the number deleted.

        With ``include_compression_chain=True``, each selected id is expanded to its full
        compression chain (root + every continuation, including stale sibling continuations)
        via :meth:`_expand_compression_lineage` — the dashboard rows carry chain-tip ids, so
        without the expansion a "deleted" conversation resurfaces as the previous chain link on
        the next list reload (#57543). The returned count still reflects the *requested* rows,
        not the expanded chain links, so the caller's toast matches the user's selection."""
        unique_ids = list({sid for sid in session_ids or () if isinstance(sid, str) and sid})
        if not unique_ids:
            return 0
        removed_ids: list[str] = []
        def _do(conn):
            existing = [row["id"] for chunk in _id_chunks(unique_ids) for row in conn.execute(
                f"SELECT id FROM sessions WHERE id IN ({_session_ids_placeholders(chunk)})", chunk,
            ).fetchall()]
            if not existing:
                return 0
            if include_compression_chain:
                # Expand BEFORE the guard pass so a guarded chain member (active turn lease /
                # compression lock anywhere in the lineage) keeps its selected root listed too.
                expanded = self._expand_compression_lineage(conn, existing)
            else:
                expanded = existing
            guard_pool = [*expanded, *_collect_delegate_child_ids(conn, expanded)]
            if exclude_active_write_guards:
                # A root is skipped when it or any delegate child it would cascade is guarded, so the
                # cascade below never deletes a guarded row reported back as kept. When the chain
                # expansion is on, a guard on ANY lineage member keeps its selected root: deleting
                # a torn chain would re-surface it (the root re-projects onto a surviving link).
                # One batched check first; per-root attribution only when something is guarded.
                active_ids: set = set()
                if self._guarded_ids(conn, guard_pool):
                    if include_compression_chain:
                        for sid in existing:
                            member_lineage = set(self._expand_compression_lineage(conn, [sid]))
                            member_lineage.add(sid)
                            if self._guarded_ids(conn, [*member_lineage,
                                    *_collect_delegate_child_ids(conn, list(member_lineage))]):
                                active_ids.add(sid)
                    else:
                        active_ids = {
                            sid for sid in existing
                            if self._guarded_ids(conn, [sid, *_collect_delegate_child_ids(conn, [sid])])
                        }
                existing = [sid for sid in existing if sid not in active_ids]
                if skipped_ids is not None:
                    skipped_ids.extend(sorted(active_ids))
                if not existing:
                    return 0
                if include_compression_chain:
                    expanded = self._expand_compression_lineage(conn, existing)
                else:
                    expanded = existing
            removed_ids.extend(_delete_delegate_children(conn, expanded))
            for chunk in _id_chunks(expanded):
                ph = _session_ids_placeholders(chunk)
                conn.execute(  # orphan children whose parent is in the kill list (FK)
                    f"UPDATE sessions SET parent_session_id = NULL WHERE parent_session_id IN ({ph})", chunk,
                )
                conn.execute(f"DELETE FROM messages WHERE session_id IN ({ph})", chunk)
                conn.execute(f"DELETE FROM sessions WHERE id IN ({ph})", chunk)
            self._delete_unreferenced_system_prompts(conn)
            removed_ids.extend(expanded)
            # Count the ids the CALLER asked for, not the expanded chain links —
            # the dashboard toast should say "3 deleted" when the user selected
            # 3 rows, however many physical links those rows had.
            return len(existing)
        count = self._execute_write(_do)
        for sid in removed_ids:
            self._remove_session_files(sessions_dir, sid)
        return count


    @staticmethod
    def _delete_unreferenced_system_prompts(conn) -> None:
        conn.execute(
            "DELETE FROM system_prompts WHERE NOT EXISTS ("
            "SELECT 1 FROM sessions WHERE sessions.system_prompt_hash = system_prompts.hash) AND NOT EXISTS ("
            "SELECT 1 FROM sessions WHERE sessions.tool_names = system_prompts.hash)"
        )
