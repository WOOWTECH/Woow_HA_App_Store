"""Trusted management-only boundary, after final exec and before core imports.

Do NOT replace runpy with exec: exec resets dumpability. MCP children stay
same-UID but cannot read this process's procfs environment or memory. This is
not a sandbox against a compromised management process or CAP_SYS_PTRACE.
"""
import ctypes
import os
from pathlib import Path
import resource
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ('odoo', 'odoo-manage', 'n8n', 'hermes', 'opendesign', 'emqx', 'litellm', 'nextcloud')


def guard():
    libc = ctypes.CDLL(None, use_errno=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if (libc.prctl(38, 1, 0, 0, 0) != 0 or libc.prctl(39, 0, 0, 0, 0) != 1
            or libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0
            or resource.getrlimit(resource.RLIMIT_CORE) != (0, 0)):
        raise RuntimeError('management credential guard unavailable')


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in PRODUCTS or os.geteuid() == 0:
        raise RuntimeError('fixed nonroot management required')
    product = sys.argv[1]
    guard()
    if product == 'n8n':
        sys.argv = [str(ROOT / 'apps/n8n/run.py')]
        runpy.run_path(sys.argv[0], run_name='__main__')
    else:
        sys.argv = ['mcp_admin_core.run_product', product]
        runpy.run_module('mcp_admin_core.run_product', run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError):
        raise SystemExit('management unavailable; credential guard or runtime failed') from None
