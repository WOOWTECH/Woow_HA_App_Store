# shellcheck shell=sh
# omnigent-host-profile.sh — interactive-shell hook of the WOOW PaaS omnigent-host kit.
#
# Canonical copy: woow-paas-charts/shared/omnigent-host/omnigent-host-profile.sh.
# Charts mount it where the image's interactive shells source it (code-server
# /etc/woow/bashrc.d/, pi-agent's /etc/bash.bashrc hook, open-design
# /etc/bash/*.sh for the /console/ `kubectl exec` shell). Shells started by the
# product already inherit both from omnigent-host-launch; shells entered with
# `kubectl exec` do not, hence this hook:
#   * puts $OG_KIT_DIR/bin first on PATH (the `omnigent` guard and
#     omnigent-host-status);
#   * prints omnigent-host-status --motd (only when the tenant must act).
# POSIX sh; never exits, never fails the shell.
if [ -n "${OG_KIT_DIR:-}" ] && [ -d "$OG_KIT_DIR/bin" ]; then
  case ":${PATH:-}:" in
    *":$OG_KIT_DIR/bin:"*) ;;
    *) PATH="$OG_KIT_DIR/bin${PATH:+:$PATH}"; export PATH ;;
  esac
fi
case $- in
  *i*) command -v omnigent-host-status >/dev/null 2>&1 && omnigent-host-status --motd ;;
esac
:
