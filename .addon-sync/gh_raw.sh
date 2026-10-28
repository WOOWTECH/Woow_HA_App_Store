# Sourced by woow-addon-upgrade-check.yml (pipeline #89); needs GH_TOKEN and REPO.
# fetch <path> <ref>: the raw file at a ref through the API; prints nothing for 404, fails on any other error.
fetch() {
  local err; err="$(mktemp)"
  if gh api -H 'Accept: application/vnd.github.raw' "repos/${REPO}/contents/$1?ref=$2" 2>"$err"; then return 0; fi
  if grep -q 'HTTP 404' "$err"; then return 0; fi
  cat "$err" >&2; return 1
}
# config_at <ref> <path> <previous> <out>: writes an add-on's config at <ref> ("" = the PR checkout in source/) to <out>
# and prints the path it was read from: <path>, or, when that is not there, <previous> (previous_config of a config move
# in progress, "" when none; addon_sync.locate is the same rule). Prints nothing and leaves <out> empty when neither is there.
config_at() {
  local p
  : > "$4"
  for p in "$2" "$3"; do
    [ -n "${p}" ] || continue
    if [ -z "$1" ]; then
      [ -f "source/${p}" ] || continue
      cp "source/${p}" "$4"
    else
      fetch "${p}" "$1" > "$4" || return 1
      [ -s "$4" ] || continue
    fi
    printf '%s\n' "${p}"; return 0
  done
}
