#!/usr/bin/env bash
# Wait for the artifacts of the caller's build (pipeline #89 SBOMs, #137 new images).
#
#   wait_artifacts.sh <wanted.tsv> <found.tsv> <what> <action>
#
# wanted.tsv: one "<add-on id>\t<artifact name>" per line, the name in this attempt (-attempt-<N>). Writes found.tsv,
# "<add-on id>\t<artifact id>\t<attempt>" per line, once every artifact is there: this attempt's, or after "Re-run failed
# jobs" the earlier attempt's whose build did not run again (#131, attempt_artifacts.sh); the step summary says which
# attempt each is from. <what> names them in messages ("SBOM of the new image"), <action> is the Store action that
# uploads them ("addon-sbom"). Env: GH_TOKEN, REPO, RUN_ID, RUN_ATTEMPT, WAIT_MINUTES. Fails (with the reason) after
# WAIT_MINUTES, or once every job of the attempt besides the upgrade comparison's own (caller job "<name> / compare" and
# "<name> / runtime") has finished, twice in a row: the build ended without uploading, so waiting longer cannot help.
set -euo pipefail
source "$(dirname "$0")/log.sh"
source "$(dirname "$0")/attempt_artifacts.sh"
wanted="$1"; found="$2"; what="$3"; action="$4"
deadline=$(( $(date -u +%s) + WAIT_MINUTES * 60 )); idle=0; : > "${found}"
while :; do
  state="$(run_state)"
  missing=""; why=""; : > "${found}"
  while IFS=$'\t' read -r id n; do
    pick="$(pick_artifact "${state}" "${n}")" || fail_output "${pick}"
    art="$(jq -r '.id // ""' <<<"${pick}")"; from="$(jq -r '.attempt' <<<"${pick}")"
    if [ -n "${art}" ]; then printf '%s\t%s\t%s\n' "${id}" "${art}" "${from}" >> "${found}"
    else missing="${missing} ${id}"; why="${why}; ${id}: $(jq -r '.note' <<<"${pick}")"; fi
  done < "${wanted}"
  if [ -z "${missing}" ]; then
    echo "All of the ${what} artifacts are there."
    while IFS=$'\t' read -r id art from; do
      if [ "${from}" = "${RUN_ATTEMPT}" ]; then line="${id}: ${what} from this attempt (${from})"
      else line="${id}: ${what} from attempt ${from}: its build did not run again in attempt ${RUN_ATTEMPT} (Re-run failed jobs)"; fi
      echo "${line}"; echo "- ${line}" >> "$GITHUB_STEP_SUMMARY"
    done < "${found}"
    break
  fi
  open="$(gh api --paginate "repos/${REPO}/actions/runs/${RUN_ID}/attempts/${RUN_ATTEMPT}/jobs?per_page=100" \
    --jq '.jobs[] | select(.status != "completed") | select(.name | test(" / (compare|runtime)$") | not) | .name' | wc -l)"
  if [ "${open}" -eq 0 ]; then idle=$(( idle + 1 )); else idle=0; fi
  if [ "${idle}" -ge 2 ]; then
    fail "no ${what} for${missing}: every other job of attempt ${RUN_ATTEMPT} finished without uploading it; check that the amd64 build passed and ran the ${action} action. An earlier attempt's artifact is read only when its build did not run again in this attempt (Store README, re-runs)${why}"; exit 1
  fi
  if [ "$(date -u +%s)" -ge "${deadline}" ]; then
    fail "no ${what} for${missing} after ${WAIT_MINUTES} minutes; the amd64 build with the ${action} action did not finish in time, re-run the check"; exit 1
  fi
  echo "Waiting for the ${what} of${missing} (${open} other jobs still open)..."; sleep 20
done
