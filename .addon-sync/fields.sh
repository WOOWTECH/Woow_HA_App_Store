# Sourced by woow-addon-upgrade-check.yml (pipeline #89) to read one JSON line of provider.json, changed.jsonl or plan.jsonl.
# fields <json> <var>=<key>...: sets each shell variable to that key's value, @sh-quoted before eval. Returns 1 when jq
# fails, so under set -e a bad line stops the step instead of leaving the previous line's values in place.
fields() {
  local json="$1" spec="" pair code; shift
  for pair in "$@"; do spec+="${pair%%=*}=\\(.${pair#*=}) "; done
  code="$(jq -r "@sh \"${spec}\"" <<<"${json}")" || return 1
  eval "${code}"
}
