#!/bin/sh
# Build-time installer. Usage: install-runtime.sh /opt/woow-connectors/omnigent/runtime
# Requires Python >=3.12 and uv (or pip in the newly created venv). No global install.
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PREFIX=${1:-$ROOT/runtime}
case "$PREFIX" in /*) ;; *) echo 'runtime prefix must be absolute' >&2; exit 64 ;; esac
PY=${WOOW_OMNIGENT_INSTALL_PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3,12), "Python >=3.12 required"'
if [ -e "$PREFIX" ]; then
  [ -x "$PREFIX/bin/python" ] || { echo 'runtime prefix exists but is not a venv' >&2; exit 1; }
else
  if command -v uv >/dev/null 2>&1; then uv venv --python "$PY" "$PREFIX" >&2
  else "$PY" -m venv "$PREFIX"; fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PREFIX/bin/python" --require-hashes --no-deps -r "$ROOT/requirements.lock" >&2
  uv pip check --python "$PREFIX/bin/python" >&2
else
  "$PREFIX/bin/python" -m pip install --require-hashes --no-deps -r "$ROOT/requirements.lock" >&2
  "$PREFIX/bin/python" -m pip check >&2
fi
"$PREFIX/bin/python" -c 'import importlib.metadata; assert importlib.metadata.version("omnigent") == "0.16.0"'
"$PREFIX/bin/python" "$ROOT/patch-runtime.py"
WOOW_RUNTIME_SITE=$("$PREFIX/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
"$PREFIX/bin/python" "$ROOT/patch-native-resume.py" --site-packages "$WOOW_RUNTIME_SITE"
"$PREFIX/bin/python" "$ROOT/patch-claude-strict-resume.py" --site-packages "$WOOW_RUNTIME_SITE"
# Claude is supplied by the image. Do not ship a second SDK bundled binary.
"$PREFIX/bin/python" -c 'import claude_agent_sdk,pathlib; (pathlib.Path(claude_agent_sdk.__file__).parent/"_bundled"/"claude").unlink(missing_ok=True)'
"$PREFIX/bin/python" -m compileall -q "$PREFIX/lib"
printf '%s\n' 'Omnigent 0.16.0 runtime installed with code-server shared-tools compatibility patch.'
