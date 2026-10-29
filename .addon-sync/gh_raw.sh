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
# appeared (ref_policy main, #129): walking back the commits that changed <path> or <previous>, the last one before a
# commit with another version (as Supervisor reads it, upgrade_check.py version) or with no config. Prints <ref> itself
# when <ref> has no config (a new add-on) or no version (check-target says so). Never falls back to <ref> on an error:
# prints the check's ::error line and returns 1.
version_since() {
  local ref="$1" path="$2" previous="$3" name="$4" tool cfg found current version file listed sha first="" commits=""
  local unknown="so the commit where the version first appeared is unknown; re-run this check"
  tool="$(dirname "${BASH_SOURCE[0]}")/upgrade_check.py"
  cfg="$(mktemp)" || { fail "${name}: mktemp failed; ${unknown}"; return 1; }
  found="$(config_at "${ref}" "${path}" "${previous}" "${cfg}")" \
    || { fail "${name}: cannot read ${path} at the PR base ${ref} (GitHub API); ${unknown}"; return 1; }
  current=""; [ -z "${found}" ] || current="$(python3 "${tool}" version --file "${cfg}" --path "${found}" --name "${name}")" \
    || { printf '%s\n' "${current}"; return 1; }
  if [ -z "${current}" ]; then printf '%s\n' "${ref}"; return 0; fi
  for file in "${path}" "${previous}"; do
    [ -n "${file}" ] || continue
    listed="$(gh api --paginate "repos/${REPO}/commits?sha=${ref}&path=$(jq -rn --arg p "${file}" '$p | @uri')&per_page=100" \
      --jq '.[] | [.commit.committer.date, .sha] | @tsv')" \
      || { fail "${name}: cannot list the commits that changed ${file} on the PR base (GitHub API); ${unknown}"; return 1; }
    commits+="${listed}"$'\n'
  done
  # Newest first by committer date, which follows the history while it is linear (squash or rebase merges; #129).
  # A config move lists its commit under both paths: once, in the API's order where dates tie.
  commits="$(sort -s -t$'\t' -k1,1r <<<"${commits}" | awk -F'\t' 'NF == 2 && !seen[$2]++')" \
    || { fail "${name}: cannot order the commits that changed ${path}; ${unknown}"; return 1; }
  while IFS=$'\t' read -r _ sha; do
    [ -n "${sha}" ] || continue
    found="$(config_at "${sha}" "${path}" "${previous}" "${cfg}")" \
      || { fail "${name}: cannot read ${path}${previous:+ or ${previous}} at ${sha} (GitHub API); ${unknown}"; return 1; }
    [ -n "${found}" ] || break
    version="$(python3 "${tool}" version --file "${cfg}" --path "${found}" --name "${name}")" || { printf '%s\n' "${version}"; return 1; }
    [ "${version}" = "${current}" ] || break
    first="${sha}"
  done <<<"${commits}"
  rm -f "${cfg}"
  if [ -z "${first}" ]; then
    fail "${name}: none of the commits that changed ${path}${previous:+ or ${previous}} on the PR base has version ${current}, the version at ${ref}; ${unknown}"; return 1
  fi
  printf '%s\n' "${first}"
}
