# Sourced by woow-addon-upgrade-check.yml (pipeline #89) for text it prints to the Actions log.
# esc <text>: text from the PR or its Releases, escaped like addon_sync.annotation, before it is echoed: with no
# newline left, it can never start a log line that GitHub reads as a workflow command.
esc() {
  local s="$1"; s="${s//'%'/%25}"; s="${s//$'\r'/%0D}"; s="${s//$'\n'/%0A}"; printf '%s' "${s}"
}
# fail <message>: the check's ::error line, the message escaped with esc (addon_sync.workflow_command). With FAIL_LOG
# set, the message is also appended there (the runtime job hands its reasons to compare, #137).
fail() {
  printf '::error title=Upgrade comparison failed::%s\n' "$(esc "$1")"
  if [ -n "${FAIL_LOG:-}" ]; then printf '%s\n' "$1" >> "${FAIL_LOG}"; fi
}
# addon_failed <id> <reason>: add-on <id> cannot be upgrade-tested, for <reason>, before upgrade_runtime.py runs (e.g.
# its new image, built on the device, does not build from the PR; #144). Prints the check's ::error line and writes
# <id>'s upgrade test result (runtime-reports/<id>.json, passed false, as upgrade_runtime.py writes one), so compare
# fails for that add-on with <reason> instead of a reason-less runtime job; FAIL_LOG is left alone so the reason is not
# given twice. The caller then sets the add-on's `test` to false in upgrade.jsonl and goes on with the others; "Run the
# upgrade tests" tests only rows with test true and fails the job for every passed-false result.
addon_failed() {
  printf '::error title=Upgrade comparison failed::%s\n' "$(esc "$1: $2")"
  mkdir -p runtime-reports
  jq -n --arg name "$1" --arg reason "$2" '{name: $name, passed: false, reason: $reason, hooks: [], data_checked: false, phases: []}' > "runtime-reports/$1.json"
}
# target_failed <id> <reason>: addon_failed for a comparison target that cannot be tested (its image cannot be pulled,
# or, for an add-on built on the device, its source cannot be downloaded or rebuilt; #140, #144), the same contract:
# the caller sets test false and goes on. A target that starts badly or whose seed fails is judged by upgrade_runtime.py.
target_failed() {
  addon_failed "$1" "$2"
}
# no_cntrl <value> <message>: fail <message> and returns 1 when <value> has a control character (newline, tab...), so a
# value from the PR or its Releases is refused before use; returns 0 otherwise.
no_cntrl() {
  [[ "$1" == *[[:cntrl:]]* ]] || return 0
  fail "$2"; return 1
}
# fail_output <output>: a failed command's output is its ::error line (already escaped); print it and exit 1.
fail_output() {
  printf '%s\n' "$1"
  if [ -n "${FAIL_LOG:-}" ]; then printf '%s\n' "${1#::error title=*::}" >> "${FAIL_LOG}"; fi
  exit 1
}
