#!/bin/sh
# ==============================================================================
# Home Assistant App (Add-on): Cloudflared Web GUI
#
# Container build of the Web GUI backend runtime (Python + FastAPI)
# ==============================================================================

set -eux

# Python runtime for the FastAPI backend
apk add --no-cache python3 py3-pip

# Backend dependencies (pinned; musllinux wheels only, no compiler needed)
pip3 install --no-cache-dir --break-system-packages --only-binary=:all: \
    -r /opt/webgui/backend/requirements.txt

# Trim pip cache remnants
rm -rf /root/.cache
