# Sourced by woow-addon-upgrade-check.yml (pipeline #89); needs GH_TOKEN and REPO.
# fetch <path> <ref>: the raw file at a ref through the API; prints nothing for 404, fails on any other error.
fetch() {
  local err; err="$(mktemp)"
  if gh api -H 'Accept: application/vnd.github.raw' "repos/${REPO}/contents/$1?ref=$2" 2>"$err"; then return 0; fi
  if grep -q 'HTTP 404' "$err"; then return 0; fi
  cat "$err" >&2; return 1
}
# fetch_config <path> <previous> <ref>: an add-on's config at a ref; when <path> is not there and the Store registry
# names the path the config was moved from (previous_config, "" when none), the file at <previous>.
fetch_config() {
  local out; out="$(fetch "$1" "$3")" || return 1
  if [ -z "${out}" ] && [ -n "$2" ]; then out="$(fetch "$2" "$3")" || return 1; fi
  [ -z "${out}" ] || printf '%s\n' "${out}"
}
