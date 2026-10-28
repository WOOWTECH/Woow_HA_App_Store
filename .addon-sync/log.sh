# Sourced by woow-addon-upgrade-check.yml (pipeline #89) for text it prints to the Actions log.
# esc <text>: text from the PR or its Releases, escaped like addon_sync.annotation, before it is echoed: with no
# newline left, it can never start a log line that GitHub reads as a workflow command.
esc() {
  local s="$1"; s="${s//'%'/%25}"; s="${s//$'\r'/%0D}"; s="${s//$'\n'/%0A}"; printf '%s' "${s}"
}
# fail <message>: the check's ::error line, the message escaped with esc (addon_sync.workflow_command).
fail() {
  printf '::error title=Upgrade comparison failed::%s\n' "$(esc "$1")"
}
