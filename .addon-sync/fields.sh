# Sourced by woow-addon-upgrade-check.yml (pipeline #89) to read one JSON line of provider.json, changed.jsonl or plan.jsonl.
# fields <json> <var>=<key>...: sets each shell variable to that key's value, @sh-quoted before eval. Returns 1 with the
# check's ::error line (log.sh fail) when a <var> is not a plain lower-case name or is one of this function's locals, or
# when jq fails, so under set -e a bad line stops the step instead of leaving the previous line's values in place.
source "$(dirname "${BASH_SOURCE[0]}")/log.sh"
fields() {
  local json="$1" spec="" pair code; shift
  for pair in "$@"; do
    case "${pair%%=*}" in
      json|spec|pair|code) fail "fields: ${pair%%=*} is a local of fields; choose another name"; return 1;;
    esac
    if [[ ! "${pair%%=*}" =~ ^[a-z_][a-z0-9_]*$ ]]; then fail "fields: ${pair%%=*} is not a variable name"; return 1; fi
    spec+="${pair%%=*}=\\(.${pair#*=}) "
  done
  code="$(jq -r "@sh \"${spec}\"" <<<"${json}")" || { fail "fields: jq cannot read ${json}"; return 1; }
  eval "${code}"
}
