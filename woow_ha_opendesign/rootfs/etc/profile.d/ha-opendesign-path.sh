# Alpine's /etc/profile resets PATH for login shells (the CLI Terminal). Restore
# the core image's Python helper venv used by OpenDesign design skills.
case ":${PATH:-}:" in
  *:/opt/venv/bin:*) ;;
  *) PATH="/opt/venv/bin${PATH:+:$PATH}"; export PATH ;;
esac
