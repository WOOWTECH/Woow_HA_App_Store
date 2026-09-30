# Scope any Claude Code process started from an interactive shell (code-server
# terminal -> user types `claude`) at the persistent pi volume, so the login
# and settings are the same view the ACP chat panel's claude-agent-acp and
# the Claude Code extension already see. The image also sets both variables
# as container ENV; this file is for login shells, where /etc/profile resets
# the environment first.
#
# CLAUDE_CONFIG_DIR moves ~/.claude and ~/.claude.json into one directory.
# It sits on the pi state volume (seeded as /data/pi-agent/claude, mode 0700)
# because that is the only per-deployment persistent directory all three
# platforms share; the login user's own HOME does not survive a recreate on
# podman/k3s. Like pi's auth.json, the credential file in there is rewritten
# on token refresh, so it must stay a real RW directory, never a Secret mount.
#
# DISABLE_AUTOUPDATER: the CLI is installed root-owned in /usr and pinned by
# PARITY_CONTRACT.md; a self-update cannot write there and must not drift.
#
# This file is byte-identical across the podman package, the k3s chart and
# the HA add-on, and hash-pinned in rootfs/opt/SHA256SUMS.
export CLAUDE_CONFIG_DIR=/data/pi-agent/claude
export DISABLE_AUTOUPDATER=1
