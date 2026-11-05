"""The real startup script must keep credential values out of DEBUG/TRACE logs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


RUN_SCRIPT = Path(__file__).resolve().parents[1] / "rootfs" / "run.sh"
TOKEN = "SYNTHETIC_TUNNEL_TOKEN_PRIVATE_123"
TAG = "SYNTHETIC_TAG_PRIVATE_456"


class TestSecretLogging(unittest.TestCase):
    def _run(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stub = root / "bashio.sh"
            stub.write_text('''
cloudflared-credential-guard() { return 0; }
bashio::log.log() { printf '[%s] %s\\n' "$1" "$2"; }
bashio::log.trace() { bashio::log.log TRACE "$*"; }
bashio::log.debug() { bashio::log.log DEBUG "$*"; }
bashio::log.info() { bashio::log.log INFO "$*"; }
bashio::config.true() { return 1; }
bashio::config.has_value() {
    case "$1" in
        tunnel_token) [ "$MODE" = remote ] ;;
        run_parameters) [ "$MODE" = local ] ;;
        *) return 1 ;;
    esac
}
bashio::config() {
    case "$1" in
        tunnel_token) printf '%s\\n' "$TEST_TOKEN" ;;
        run_parameters) printf '%s\\n' "--tag=$TEST_TAG --protocol=quic" ;;
        tunnel_name) printf '%s\\n' safe-tunnel-name ;;
    esac
}
''')
            cloudflared = root / "cloudflared"
            cloudflared.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARG_CAPTURE"\n')
            cloudflared.chmod(0o700)
            env = dict(os.environ, MODE=mode, TEST_TOKEN=TOKEN, TEST_TAG=TAG,
                       ARG_CAPTURE=str(root / "args"),
                       CLOUDFLARED_TOKEN_FILE=str(root / "tunnel-token"),
                       __BASHIO_LOG_LEVEL_TRACE="TRACE",
                       PATH=f"{root}:{os.environ['PATH']}")
            result = subprocess.run(
                ["bash", "-c", 'source "$BASHIO_STUB"; source "$RUN_SCRIPT"'],
                env=dict(env, BASHIO_STUB=str(stub), RUN_SCRIPT=str(RUN_SCRIPT)),
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            token_file = root / "tunnel-token"
            token = None
            if token_file.exists():
                token = (token_file.read_text(), token_file.stat().st_mode & 0o777)
            return result.stdout + result.stderr, (root / "args").read_text(), token

    def test_remote_token_is_passed_by_private_file_without_logging(self):
        log, args, token = self._run("remote")
        self.assertIn("--token-file=", args)
        self.assertNotIn(TOKEN, args)
        self.assertEqual(token, (TOKEN, 0o600))
        self.assertNotIn(TOKEN, log)
        self.assertIn("arguments omitted", log)

    def test_user_parameter_is_passed_without_logging(self):
        log, args, _ = self._run("local")
        self.assertIn(f"--tag={TAG}", args)
        self.assertIn("--protocol=quic", args)
        self.assertNotIn(TAG, log)
        self.assertIn("arguments omitted", log)


if __name__ == "__main__":
    unittest.main()
