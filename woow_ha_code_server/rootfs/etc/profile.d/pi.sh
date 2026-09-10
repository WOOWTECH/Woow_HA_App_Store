# Scope any pi CLI process started from an interactive shell (code-server
# terminal → user types `pi`) at the persistent /data/pi-agent volume, so
# provider auth and session history are the same view the ACP chat panel
# already sees.
#
# Only PI_CODING_AGENT_DIR is set — NOT HOME. Overriding HOME here would
# break code-server itself (extensions, config, .bashrc lookup) since
# /etc/profile.d/*.sh runs for every interactive login shell inside this
# container. PI_CODING_AGENT_DIR is the env pi CLI checks first for its
# state directory, and it takes precedence over ~/.pi when set.
#
# There is a companion `~/.pi -> /data/pi-agent/home/.pi` symlink for the
# login user. It is a SKILLS BRIDGE, not a fallback safety net: the only
# thing under that tree is `agent/skills -> /data/pi-agent/skills`. Auth,
# settings, models-store and sessions all live one level up, directly in
# /data/pi-agent, and are reachable ONLY through PI_CODING_AGENT_DIR. A pi
# started without this env finds its skills and then fails with "No API key
# found" — verified, not assumed.
#
# That is acceptable because no shipped path drops the env: it is an image
# ENV, it is re-exported by pi-code, and on the HA add-on it is also written
# into /run/s6/container_environment. Do NOT "fix" it by symlinking
# auth.json into the .pi tree — pi rewrites that file write-temp-then-rename
# on OAuth refresh, which replaces the symlink with a real file and splits
# the credential store in two.
#
# This file is byte-identical across the podman package, the k3s chart and
# the HA add-on, and hash-pinned in rootfs/opt/SHA256SUMS. Keep every
# comment here true on all three — the login user is `coder` on podman/k3s
# and `root` on HA, so do not name it, and the symlink is created by the
# image build on podman/k3s but at runtime by init-woow on HA.
export PI_CODING_AGENT_DIR=/data/pi-agent
export PI_TELEMETRY=0
export PI_SKIP_VERSION_CHECK=1
