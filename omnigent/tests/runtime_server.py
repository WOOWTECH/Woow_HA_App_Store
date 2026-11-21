"""Isolated CLI entry point used only by test-upgrade-runtime.py."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

# Keep all implicit per-user state in this test directory without changing the
# invoking shell's HOME or touching an installed user's Omnigent profile.
with patch.object(Path, "home", return_value=Path(os.environ["UPGRADE_RUNTIME_DIR"])):
    from omnigent.cli import main
    sys.argv = ["omnigent", "server", "--host", "127.0.0.1", "--port", os.environ["UPGRADE_RUNTIME_PORT"],
                "--database-uri", "sqlite:///" + str(Path(os.environ["UPGRADE_RUNTIME_DIR"]) / "test.db"), "--no-open"]
    main()
