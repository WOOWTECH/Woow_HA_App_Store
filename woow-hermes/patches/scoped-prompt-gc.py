#!/usr/bin/env python3
"""Scope session-delete prompt GC to the deleted rows and their delegate cascade.

Applied in the addon build, not to a running store. Exact input/output hashes
fail closed on drift, partial application and tampering. The split source pin
is the current v0.22.5 image target; older excerpts are regression fixtures.
"""
import argparse
import ast
import hashlib
import stat
from pathlib import Path

SPECS = {
    "hermes_state.py": (
        "696fd2d37d66a599228f5b1be5d5b76423b744149c83a2fbd59bf3f45a5f3891",
        "8a17f82d934ddc454c1e8251a3bd862b2ffa11f21bf916f57da803ae43932d48",
    ),
    "hermes_state_sessions.py": (
        "1eddb7aadd63ca88d366cfe10d9ba3a709f044eb7d6dcb60dbdd699167f7300e",
        "5cc672ecc77bfed764544efaf4320ec2457c5298f49701d675814ade319a6db3",
    ),
}


def rewrite_methods(source):
    """Transform only the two deletion methods; also used on test excerpts."""
    lines = source.splitlines(keepends=True)
    edits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef) or node.name not in ("delete_session", "delete_sessions"):
            continue
        body = "".join(lines[node.lineno - 1:node.end_lineno])
        anchors = [line for line in body.splitlines() if ".extend(_delete_delegate_children(conn," in line]
        old = "            self._delete_unreferenced_system_prompts(conn)"
        if len(anchors) != 1 or body.count(old) != 1:
            raise ValueError("session deletion anchors changed")
        anchor = anchors[0]
        if node.name == "delete_session":
            roots = "scope" if "_delete_delegate_children(conn, scope)" in anchor else "[session_id]"
        else:
            roots = "expanded" if "_delete_delegate_children(conn, expanded)" in anchor else "existing"
        split = any(arg.arg == "include_compression_chain" for arg in node.args.args + node.args.kwonlyargs)
        columns = "system_prompt_hash, tool_names" if split else "system_prompt_hash"
        value = "prompt_hash" if split else "row[0]"
        tail = "for prompt_hash in row if prompt_hash is not None" if split else "if row[0] is not None"
        capture = f'''            gc_roots = {roots}
            gc_ids = [*gc_roots, *_collect_delegate_child_ids(conn, gc_roots)]
            gc_hashes = {{
                {value} for target in gc_ids
                for row in conn.execute(
                    "SELECT {columns} FROM sessions WHERE id = ?", (target,)
                ) {tail}
            }}
'''
        reclaim = '''            for prompt_hash in gc_hashes:
                conn.execute(
                    "DELETE FROM system_prompts WHERE hash = ? AND NOT EXISTS ("
                    "SELECT 1 FROM sessions WHERE sessions.system_prompt_hash = system_prompts.hash)",
                    (prompt_hash,),
                )'''
        if split:
            # Newer upstream interns tool names in the same table. Keep either
            # kind of surviving reference, including cross-column sharing.
            reclaim = reclaim.replace(
                'system_prompts.hash)",',
                'system_prompts.hash) AND NOT EXISTS ("\n'
                '                    "SELECT 1 FROM sessions WHERE sessions.tool_names = system_prompts.hash)",',
            )
        edits.append((node.lineno - 1, node.end_lineno, body.replace(anchor, capture + anchor, 1).replace(old, reclaim, 1)))
    if len(edits) != 2:
        raise ValueError("expected both session deletion methods")
    for start, end, body in sorted(edits, reverse=True):
        lines[start:end] = [body]
    result = "".join(lines)
    compile(result, "<scoped-prompt-gc>", "exec")
    return result


def patched_source(name, source):
    original_hash, patched_hash = SPECS[name]
    digest = hashlib.sha256(source.encode()).hexdigest()
    if digest == patched_hash:
        return source
    if digest != original_hash:
        raise ValueError(f"{name}: source differs from reviewed pin")
    result = rewrite_methods(source)
    if hashlib.sha256(result.encode()).hexdigest() != patched_hash:
        raise ValueError(f"{name}: transformed output differs from reviewed pin")
    return result


def patch_directory(directory, check=False):
    # Newer upstream moves these methods to the mixin; do not also patch its
    # facade. lexists semantics ensure a dangling link is rejected, not ignored.
    split = directory / "hermes_state_sessions.py"
    path = split if split.exists() or split.is_symlink() else directory / "hermes_state.py"
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("expected regular session source file")
    source = path.read_bytes().decode("utf-8")
    result = patched_source(path.name, source)
    if check:
        if result != source:
            raise ValueError("scoped prompt GC patch missing")
    elif result != source:
        path.write_bytes(result.encode("utf-8"))
    return path.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/opt/hermes"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    name = patch_directory(args.directory, args.check)
    print(f"Scoped prompt GC: {name} " + ("verified" if args.check else "patched/verified"))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(f"[FAIL] {type(error).__name__}: scoped prompt GC source check failed")
