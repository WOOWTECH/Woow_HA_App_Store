async def _delete_native_bridge_dirs(
    *,
    server_client: httpx.AsyncClient | None,
    session_id: str,
) -> None:
    """
    Remove native-harness bridge directories and attachment caches for a session.

    Each native harness keeps a per-conversation bridge dir under
    ``/tmp/omnigent-<uid>/<harness>-native/<digest>`` (some use ``~/.omnigent``)
    holding a bridge token / auth secret + MCP config — secret material. Closing
    the pane does not remove it, so without this they accumulate even on a clean
    session delete (issue #1350). We don't know which harness this session used,
    so delete every candidate dir for all 11 native families
    (antigravity/claude/codex/cursor/goose/hermes/kimi/kiro/opencode/pi/qwen);
    the per-target ``FileNotFoundError`` swallow makes wrong-harness / already-gone
    cases a no-op, while other ``OSError``s are logged at debug rather than hidden.
    Antigravity/claude/codex/opencode bridge ids can be rotated via a session
    label, so resolve those too (falling back to *session_id*, the un-rotated key);
    the remaining families key purely on *session_id*.

    :param server_client: Omnigent server client used to resolve rotated bridge
        id labels. ``None`` skips label resolution (session_id keys only).
    :param session_id: Omnigent session/conversation id, e.g. ``"conv_abc123"``.
    """
    from omnigent.harnesses.antigravity_native.bridge import (
        ANTIGRAVITY_NATIVE_BRIDGE_ID_LABEL_KEY,
    )
    from omnigent.harnesses.antigravity_native.bridge import (
        bridge_dir_for_bridge_id as antigravity_bridge_dir,
    )
    from omnigent.harnesses.claude_native.bridge import (
        BRIDGE_ID_LABEL_KEY,
    )
    from omnigent.harnesses.claude_native.bridge import (
        bridge_dir_for_bridge_id as claude_bridge_dir,
    )
    from omnigent.harnesses.codex_native.bridge import (
        CODEX_NATIVE_BRIDGE_ID_LABEL_KEY,
    )
    from omnigent.harnesses.codex_native.bridge import (
        bridge_dir_for_bridge_id as codex_bridge_dir,
    )
    from omnigent.harnesses.cursor_native.bridge import (
        bridge_dir_for_session_id as cursor_bridge_dir,
    )
    from omnigent.harnesses.goose_native.bridge import (
        bridge_dir_for_session_id as goose_bridge_dir,
    )
    from omnigent.harnesses.hermes_native.bridge import (
        bridge_dir_for_session_id as hermes_bridge_dir,
    )
    from omnigent.harnesses.kimi_native.bridge import (
        bridge_dir_for_session_id as kimi_bridge_dir,
    )
    from omnigent.harnesses.kiro_native.bridge import (
        bridge_dir_for_session_id as kiro_bridge_dir,
    )
    from omnigent.harnesses.opencode_native.bridge import (
        OPENCODE_NATIVE_BRIDGE_ID_LABEL_KEY,
    )
    from omnigent.harnesses.opencode_native.bridge import (
        bridge_dir_for_bridge_id as opencode_bridge_dir,
    )
    from omnigent.harnesses.pi_native.bridge import (
        bridge_dir_for_session_id as pi_bridge_dir,
    )
    from omnigent.harnesses.qwen_native.bridge import (
        bridge_dir_for_session_id as qwen_bridge_dir,
    )
    from omnigent.inner.native_attachments import attachment_cache_dir

    labels: dict[str, str] = {}
    if server_client is not None:
        labels = await _session_labels_for_runner_spawn(
            server_client=server_client,
            session_id=session_id,
        )

    targets = {
        antigravity_bridge_dir(labels.get(ANTIGRAVITY_NATIVE_BRIDGE_ID_LABEL_KEY) or session_id),
        antigravity_bridge_dir(session_id),
        claude_bridge_dir(labels.get(BRIDGE_ID_LABEL_KEY) or session_id),
        claude_bridge_dir(session_id),
        codex_bridge_dir(labels.get(CODEX_NATIVE_BRIDGE_ID_LABEL_KEY) or session_id),
        codex_bridge_dir(session_id),
        cursor_bridge_dir(session_id),
        goose_bridge_dir(session_id),
        hermes_bridge_dir(session_id),
        kimi_bridge_dir(session_id),
        kiro_bridge_dir(session_id),
        opencode_bridge_dir(labels.get(OPENCODE_NATIVE_BRIDGE_ID_LABEL_KEY) or session_id),
        opencode_bridge_dir(session_id),
        pi_bridge_dir(session_id),
        qwen_bridge_dir(session_id),
    }
    # A cache can survive a missing bridge directory, including after a reboot.
    targets.update(attachment_cache_dir(target) for target in tuple(targets))
    for target in targets:
        try:
            shutil.rmtree(target, ignore_errors=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            _logger.debug(
                "Failed to remove native session directory %s for session %s: %s",
                target,
                session_id,
                exc,
            )
