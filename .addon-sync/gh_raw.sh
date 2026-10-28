# Sourced by woow-addon-upgrade-check.yml (pipeline #89); fetch needs GH_TOKEN and REPO.
# fetch <path> <ref>: the raw file at a ref through the API; prints nothing for 404, fails on any other error.
fetch() {
  local err; err="$(mktemp)"
  if gh api -H 'Accept: application/vnd.github.raw' "repos/${REPO}/contents/$1?ref=$2" 2>"$err"; then return 0; fi
  if grep -q 'HTTP 404' "$err"; then return 0; fi
  cat "$err" >&2; return 1
}
# esc <text>: text from the PR or its Releases, escaped like addon_sync.annotation, before it is echoed: with no
# newline left, it can never start a log line that GitHub reads as a workflow command.
esc() {
  local s="$1"; s="${s//'%'/%25}"; s="${s//$'\r'/%0D}"; s="${s//$'\n'/%0A}"; printf '%s' "${s}"
}
