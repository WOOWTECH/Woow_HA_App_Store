def _codex_orphan_retention_expired(bridge_dir: Path) -> bool:
    """Return whether a dead-owner Codex bridge has been inactive for 7 days."""
    activity_cutoff = time.time() - _ORPHAN_RETENTION_SECONDS
    owner_marker = bridge_dir / native_bridge_common.OWNER_PID_FILENAME
    try:
        if owner_marker.stat().st_mtime > activity_cutoff:
            return False
    except OSError:
        return False

    sessions_dir = bridge_dir / "codex-home" / "sessions"
    try:
        sessions_mode = sessions_dir.stat().st_mode
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISDIR(sessions_mode):
        return False

    scan_failed = False

    def _record_scan_failure(_error: OSError) -> None:
        nonlocal scan_failed
        scan_failed = True

    try:
        for directory, _subdirs, filenames in os.walk(
            sessions_dir,
            onerror=_record_scan_failure,
        ):
            for filename in filenames:
                if not filename.startswith("rollout-") or not filename.endswith(".jsonl"):
                    continue
                rollout = Path(directory) / filename
                try:
                    if rollout.stat().st_mtime > activity_cutoff:
                        return False
                except FileNotFoundError:
                    continue
                except OSError:
                    return False
    except OSError:
        return False
    return not scan_failed
