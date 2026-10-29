# Sourced by woow-addon-upgrade-check.yml (pipeline #89); needs GH_TOKEN and REPO.
source "$(dirname "${BASH_SOURCE[0]}")/log.sh"
# fetch <path> <ref>: the raw file at a ref through the API; prints nothing for 404, fails on any other error.
fetch() {
  local err; err="$(mktemp)"
  if gh api -H 'Accept: application/vnd.github.raw' "repos/${REPO}/contents/$1?ref=$2" 2>"$err"; then return 0; fi
  if grep -q 'HTTP 404' "$err"; then return 0; fi
  cat "$err" >&2; return 1
}
# config_at <ref> <path> <previous> <out>: writes an add-on's config at <ref> ("" = the PR checkout in source/) to <out>
# and prints the path it was read from: <path>, or, when that is missing or empty, <previous> (previous_config of a config
# move in progress, "" when none; addon_sync.locate is the same rule). Prints nothing and leaves <out> empty when neither
# has it; the caller's error names both paths.
config_at() {
  local p
  : > "$4"
  for p in "$2" "$3"; do
    [ -n "${p}" ] || continue
    if [ -z "$1" ]; then
      [ -s "source/${p}" ] || continue
      cp "source/${p}" "$4"
    else
      fetch "${p}" "$1" > "$4" || return 1
      [ -s "$4" ] || continue
    fi
    printf '%s\n' "${p}"; return 0
  done
}
# version_since <ref> <path> <previous> <name>: the commit in <ref>'s history where the add-on's version at <ref> first
# appeared (ref_policy main, #129). Of the commits that changed <path> or <previous> (newest first, by committer date), the
# oldest one reached before a commit with another version or no config; versions are read as Supervisor reads them
# (upgrade_check.py version). Prints <ref> itself when <ref> has no config (a new add-on) or no version (check-target says so).
# Never falls back to <ref> on an error: prints the check's ::error line and returns 1.
version_since() {
  local ref="$1" path="$2" previous="$3" name="$4" tool cfg found current v p list sha since="" commits=""
  tool="$(dirname "${BASH_SOURCE[0]}")/upgrade_check.py"; cfg="$(mktemp)"
  found="$(config_at "${ref}" "${path}" "${previous}" "${cfg}")"     || { fail "${name}: cannot read ${path} at the PR base ${ref} (GitHub API); re-run this check"; return 1; }
  current=""; [ -z "${found}" ] || current="$(python3 "${tool}" version --file "${cfg}" --path "${found}" --name "${name}")"     || { printf '%s
' "${current}"; return 1; }
  if [ -z "${current}" ]; then printf '%s
' "${ref}"; return 0; fi
  for p in "${path}" "${previous}"; do
    [ -n "${p}" ] || continue
    list="$(gh api --paginate "repos/${REPO}/commits?sha=${ref}&path=${p}&per_page=100" --jq '.[] | [.commit.committer.date, .sha] | @tsv')"       || { fail "${name}: cannot list the commits that changed ${p} on the PR base (GitHub API), so the commit where version ${current} first appeared is unknown; re-run this check"; return 1; }
    commits+="${list}"$'
'
  done
  # A config move lists its commit under both paths: once, in the API's order where dates tie.
  while IFS=$'	' read -r _ sha; do
    found="$(config_at "${sha}" "${path}" "${previous}" "${cfg}")"       || { fail "${name}: cannot read ${path}${previous:+ or ${previous}} at ${sha} (GitHub API), so the commit where version ${current} first appeared is unknown; re-run this check"; return 1; }
    [ -n "${found}" ] || break
    v="$(python3 "${tool}" version --file "${cfg}" --path "${found}" --name "${name}")" || { printf '%s
' "${v}"; return 1; }
    [ "${v}" = "${current}" ] || break
    since="${sha}"
  done < <(sort -s -t$'	' -k1,1r <<<"${commits}" | awk -F'	' 'NF == 2 && !seen[$2]++')
  if [ -z "${since}" ]; then
    fail "${name}: none of the commits that changed ${path}${previous:+ or ${previous}} on the PR base has version ${current}, the version at ${ref}, so the commit where it first appeared is unknown; re-run this check"; return 1
  fi
  printf '%s
' "${since}"
}
