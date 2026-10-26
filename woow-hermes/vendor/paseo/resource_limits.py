"""Constrain automatic local inference threads to this container's CPU quota."""
from __future__ import annotations

import math
import os
from pathlib import Path


def cpu_quota(root=Path('/sys/fs/cgroup')):
    try:
        quota, period = (root / 'cpu.max').read_text().split()
        if quota == 'max':
            return None
        quota, period = int(quota), int(period)
    except (OSError, ValueError):
        try:
            base = root / 'cpu'
            quota = int((base / 'cpu.cfs_quota_us').read_text())
            period = int((base / 'cpu.cfs_period_us').read_text())
        except (OSError, ValueError):
            return None
    return max(1, math.ceil(quota / period)) if quota > 0 and period > 0 else None


def configure_cpu_environment(env=None, root=Path('/sys/fs/cgroup'), affinity=None):
    env = os.environ if env is None else env
    quota = cpu_quota(root)
    if quota is None:
        return
    if affinity is None:
        try:
            affinity = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            affinity = os.cpu_count() or quota
    limit = max(1, min(quota, affinity))
    for name in ('LLAMA_ARG_THREADS', 'LLAMA_ARG_THREADS_BATCH', 'OMP_NUM_THREADS'):
        env.setdefault(name, str(limit))
    env.setdefault('LLAMA_ARG_THREADS_HTTP', str(max(2, min(limit + 1, 8))))
