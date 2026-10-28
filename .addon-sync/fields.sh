# Sourced by woow-addon-upgrade-check.yml (pipeline #89) to read one JSON line of provider.json, changed.jsonl or plan.jsonl.
# fields <json> <var>=<key>...: sets each shell variable to that key's value, @sh-quoted before eval. Returns 1 with the
# check's ::error line (log.sh fail) when a <var> is not a plain lower-case name or starts with _f_ (this function's
# locals), or when jq fails, so under set -e a bad line stops the step instead of leaving the previous line's values in place.
source "$(dirname "${BASH_SOURCE[0]}")/log.sh"
fields() {
  local _f_json="$1" _f_spec="" _f_pair _f_code; shift
  for _f_pair in "$@"; do
    case "${_f_pair%%=*}" in
      _f_*) fail "fields: ${_f_pair%%=*} starts with _f_, which fields keeps for its locals; choose another name"; return 1;;
    esac
    if [[ ! "${_f_pair%%=*}" =~ ^[a-z_][a-z0-9_]*$ ]]; then fail "fields: ${_f_pair%%=*} is not a variable name"; return 1; fi
    _f_spec+="${_f_pair%%=*}=\\(.${_f_pair#*=}) "
  done
  _f_code="$(jq -r "@sh \"${_f_spec}\"" <<<"${_f_json}")" || { fail "fields: jq cannot read ${_f_json}"; return 1; }
  eval "${_f_code}"
}
