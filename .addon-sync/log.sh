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
# no_cntrl <value> <message>: fail <message> and returns 1 when <value> has a control character (newline, tab...), so a
# value from the PR or its Releases is refused before use; returns 0 otherwise.
no_cntrl() {
  [[ "$1" == *[[:cntrl:]]* ]] || return 0
  fail "$2"; return 1
}
# fail_output <output>: a failed command's output is its ::error line (already escaped); print it and exit 1.
fail_output() {
  printf '%s\n' "$1"; exit 1
}
