# Sourced (pipeline #131) by wait_artifacts.sh and woow-addon-upgrade-check.yml: which run attempt's artifact the upgrade
# comparison reads. This attempt's own; after "Re-run failed jobs", an earlier attempt's when the job that uploaded it
# did not run again (the rule: upgrade_check.py attempt_artifact()). Env: GH_TOKEN, REPO, RUN_ID, RUN_ATTEMPT. Needs log.sh.
attempt_tooling="$(dirname "${BASH_SOURCE[0]}")"
# run_state: this run's state as `upgrade_check.py attempt-artifact` reads it, {run, jobs, artifacts}. On attempt 1 only
# the artifacts: there is no earlier attempt. When a gh call fails it prints the ::error line and fails, so call it as
# state="$(run_state)" || fail_output "${state}": set -e does not stop a function in a command substitution, and a list
# that lost a page could leave out a job that ran again, so that an earlier attempt's artifact would be read.
run_state() {
  local run='{}' jobs='[]' arts
  arts="$(gh api --paginate "repos/${REPO}/actions/runs/${RUN_ID}/artifacts?per_page=100" \
    --jq '.artifacts[]? | {name, id, created_at, expired, workflow_run}' | jq -sc .)" || { run_state_failed artifacts; return 1; }
  if [ "${RUN_ATTEMPT}" -gt 1 ]; then
    run="$(gh api "repos/${REPO}/actions/runs/${RUN_ID}/attempts/${RUN_ATTEMPT}" --jq '{run_started_at, head_sha}')" \
      || { run_state_failed "attempt ${RUN_ATTEMPT}"; return 1; }
    # filter=all: every attempt's jobs; a job that did not run again is listed in this attempt with its old started_at.
    jobs="$(gh api --paginate "repos/${REPO}/actions/runs/${RUN_ID}/jobs?filter=all&per_page=100" \
      --jq '.jobs[]? | {name, run_attempt, status, started_at, completed_at}' | jq -sc .)" || { run_state_failed jobs; return 1; }
  fi
  jq -nc --argjson run "${run}" --argjson jobs "${jobs}" --argjson artifacts "${arts}" '$ARGS.named'
}
# run_state_failed <what>: run_state's ::error line when the gh call for <what> fails. FAIL_LOG is left to the caller's
# fail_output, so the reason is not logged twice.
run_state_failed() {
  FAIL_LOG='' fail "cannot read the state of run ${RUN_ID} attempt ${RUN_ATTEMPT} (the GitHub API call for its $1 failed), so no artifact is read; re-run the check"
}
# pick_artifact <state> <name in this attempt> [runtime]: {id, attempt, note} (id null: none to read yet). runtime: the
# upgrade comparison's runtime job uploads it; without it, the caller's build does. On a tool error it prints the ::error
# line and fails, so call it as pick="$(pick_artifact ...)" || fail_output "${pick}".
pick_artifact() {
  python3 "${attempt_tooling}/upgrade_check.py" attempt-artifact --name "$2" --attempt "${RUN_ATTEMPT}" ${3:+--producer "$3"} <<<"$1"
}
