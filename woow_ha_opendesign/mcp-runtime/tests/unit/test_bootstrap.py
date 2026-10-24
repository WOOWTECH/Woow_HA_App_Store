"""0.2.4: the add-on version reaches the capability contract (management venv).

The root bootstrap (bin/ha-opendesign-mcp) starts the management process with a fixed environment. #15 reports the
add-on build version as product.version from WOOW_ADDON_VERSION (Dockerfile ENV), which that fixed environment dropped:
every installed add-on would have reported "unknown". The bootstrap now passes that one value on, and only when it has
a version's shape; nothing else from its own environment (SUPERVISOR_TOKEN above all) is passed.

HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as in test_surface.py.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor'))
sys.path[:0] = [str(Path(VENDOR) / 'packaging'), str(Path(VENDOR) / 'packages' / 'mcp-admin-core'), CODE]

loader = importlib.machinery.SourceFileLoader('ha_opendesign_mcp_bootstrap', str(Path(CODE) / 'bin' / 'ha-opendesign-mcp'))
bootstrap = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(bootstrap)

from ha_opendesign_mcp import runtime  # noqa: E402

FIXED = {'PATH', 'HOME', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED'}


class Bootstrap(unittest.TestCase):
    def test_the_add_on_version_and_nothing_else_is_passed_on(self):
        env = bootstrap.management_env({'WOOW_ADDON_VERSION': '0.2.4', 'SUPERVISOR_TOKEN': 'not-a-secret',
                                        'HASSIO_TOKEN': 'not-a-secret', 'HOME': '/root', 'OTHER': 'x'})
        self.assertEqual(set(env), FIXED | {'WOOW_ADDON_VERSION'})
        self.assertEqual(env['WOOW_ADDON_VERSION'], '0.2.4')
        self.assertEqual(env['HOME'], '/data/mcp')

    def test_a_missing_or_odd_version_is_not_passed_on(self):
        for value in (None, '', '0.2.4\n', 'x' * 65, '1 2', '../x', '-1', 'vé', '0.2.4;id'):
            environ = {} if value is None else {'WOOW_ADDON_VERSION': value}
            self.assertEqual(set(bootstrap.management_env(environ)), FIXED, value)
        self.assertEqual(bootstrap.management_env({'WOOW_ADDON_VERSION': '0.1.0-smoke'})['WOOW_ADDON_VERSION'],
                         '0.1.0-smoke')

    def test_the_management_process_reports_what_the_bootstrap_passes(self):
        with mock.patch.dict(os.environ, bootstrap.management_env({'WOOW_ADDON_VERSION': '0.2.4'}), clear=True):
            self.assertEqual(runtime.management_options().product_version, '0.2.4')
        with mock.patch.dict(os.environ, bootstrap.management_env({}), clear=True):
            self.assertEqual(runtime.management_options().product_version, 'unknown')


if __name__ == '__main__':
    unittest.main()
