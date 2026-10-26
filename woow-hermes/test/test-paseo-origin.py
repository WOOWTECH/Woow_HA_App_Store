"""HA option validation prevents widening the plugin's trusted browser origins."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

FILE = Path(__file__).resolve().parents[1] / 'rootfs/opt/woow/paseo_origin.py'
spec = importlib.util.spec_from_file_location('paseo_origin', FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OriginTests(unittest.TestCase):
    def test_accepts_exact_http_https_and_ipv6_origins(self):
        for value in ('https://ha.example', 'http://homeassistant.local:8123', 'http://[::1]:8123'):
            self.assertEqual(module.canonical_origin(value), value)
            self.assertEqual(module.canonical_origin(value + '/'), value)

    def test_rejects_credentials_paths_wildcards_and_ambiguous_urls(self):
        for value in ('', '*', 'https://*.example', 'https://user:secret@ha.example',
                      'https://ha.example/api/hassio_ingress/token', 'https://ha.example/?a=b',
                      'https://ha.example/#x', 'javascript:alert(1)', '//ha.example',
                      ' https://ha.example', 'https://ha.example\n', 'https://ha.example:bad',
                      'https://ha.example:99999', 'https://ha.example\\evil',
                      'https://ha.example?', 'https://ha.example#', 'https://ha.example:',
                      'https://ha.example:0', 'https://bad..example', 'https://ha%2eexample'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.canonical_origin(value)

    def test_invalid_input_is_not_echoed(self):
        secret = 'https://user:unique-test-secret@ha.example'
        result = subprocess.run([sys.executable, str(FILE)], input=secret, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('unique-test-secret', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
