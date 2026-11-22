def _process_alive(pid: int) -> bool:
    """
    Return whether a process with *pid* currently exists.

    Used by the orphan sweep as the owner-death check. The check is
    conservative in the dangerous direction: ``ProcessLookupError`` is a
    definitive "gone", while a reused pid (or one owned by another user,
    which raises ``PermissionError``) reads as alive and merely defers
    the reap to a later sweep — it can never kill a live owner's
    terminal.

    :param pid: Process id recorded at instance creation,
        e.g. ``48213``.
    :returns: ``True`` when a process with that pid exists.
    """
    # POSIX uses ``os.kill(pid, 0)`` so a killed-but-not-yet-reaped zombie
    # still counts as present (matches ``process_manager._pid_alive``). The
    # ``_proc.process_alive`` psutil probe treats a zombie as gone and can
    # transiently miss a live process, which raced the orphan sweep against a
    # just-exited owner. ``os.kill(pid, 0)`` can't be used on Windows (maps to
    # TerminateProcess and would kill the target), so fall back to psutil there.
    if IS_WINDOWS:
        return _proc.process_alive(pid)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
