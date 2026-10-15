if [[ $- == *i* ]]; then
  cat <<'HELP'
OpenDesign CLI terminal (credentials and CLI settings persist in /data/opendesign/home)
  Claude Code login: claude                 then run /login if prompted
  Codex login:       codex login --device-auth
  Pi setup/login:    pi                     then use /login in the TUI
  OpenCode providers: use OpenDesign Settings > API providers, or run opencode auth login
  Omnigent host:     OpenDesign Plugins > Omnigent (native dialog), or omnigent login <server-url>
                     status: omnigent-host-status
HELP
fi
