#!/bin/sh
# Build-time installation into the image, with no agent login or daemon startup.
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
UV_VERSION=0.13.7
PYTHON_VERSION=3.12.16
case "$(uname -m)" in
  x86_64) UV_ARCH=x86_64; UV_SHA256=c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83 ;;
  aarch64) UV_ARCH=aarch64; UV_SHA256=71279f8d3c67241e807b9d8db872d1bf541579fb9f08b7d1eb1682196d1e57dc ;;
  *) echo 'Unsupported connector runtime architecture' >&2; exit 1 ;;
esac
mkdir -p "$ROOT/bootstrap"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 -o "$work/uv.tar.gz" \
  "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_ARCH-unknown-linux-gnu.tar.gz"
printf '%s  %s\n' "$UV_SHA256" "$work/uv.tar.gz" | sha256sum -c -
tar xzf "$work/uv.tar.gz" -C "$work"
install -m 0755 "$work/uv-$UV_ARCH-unknown-linux-gnu/uv" "$ROOT/bootstrap/uv"
export PATH="$ROOT/bootstrap:$PATH"
export UV_PYTHON_INSTALL_DIR="$ROOT/python" UV_PYTHON_PREFERENCE=only-managed UV_NO_CACHE=1 UV_HTTP_RETRIES=8 UV_HTTP_TIMEOUT=120
uv python install "$PYTHON_VERSION" >&2
WOOW_OMNIGENT_INSTALL_PYTHON=$(uv python find "$PYTHON_VERSION")
export WOOW_OMNIGENT_INSTALL_PYTHON
"$ROOT/omnigent/install-runtime.sh" "$ROOT/omnigent/runtime"
"$ROOT/paseo/install-runtime.sh" "$ROOT/paseo"
chmod -R a+rX "$ROOT"
printf '%s\n' 'WOOW connector runtimes installed; connections remain unconfigured.'
