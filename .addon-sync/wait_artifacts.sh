#!/usr/bin/env bash
# Wait for artifacts of this run attempt (pipeline #89 SBOMs, #137 new images).
#
#   wait_artifacts.sh <wanted.tsv> <found.tsv> <what> <action>
#
# wanted.tsv: one "<add-on id>\t<artifact name>" per line. Writes found.tsv,
# "<add-on id>\t<artifact id>" per line, once every artifact is uploaded.
# <what> names them in messages ("SBOM of the new image"), <action> is the Store
# action that uploads them ("addon-sbom"). Env: GH_TOKEN, REPO, RUN_ID,
# RUN_ATTEMPT, WAIT_MINUTES. Fails (with the reason) after WAIT_MINUTES, or
# once every job of the attempt besides the upgrade comparison's own (caller job
# "<name> / compare" and "<name> / runtime") has finished, twice in a row: the
# build ended without uploading, so waiting longer cannot help.
set -euo pipefail
source "$(dirname "$0")/log.sh"
wanted="$1"; found="$2"; what="$3"; action="$4"
deadline=$(( $(date -u +%s) + WAIT_MINUTES * 60 )); idle=0; : > "${found}"
while :; do
  # Only this attempt's artifact (the names end in -attempt-<N>): a re-run judges its own build.
  arts="$(gh api --paginate "repos/${REPO}/actions/runs/${RUN_ID}/artifacts?per_page=100" \
    --jq '.artifacts[] | select(.expired | not) | [.name, .created_at, (.id | tostring)] | @tsv' | sort -t$'\t' -k2,2)"
  missing=""; : > "${found}"
  while IFS=$'\t' read -r id n; do
    row="$(awk -F'\t' -v n="${n}" '$1 == n' <<<"${arts}" | tail -n1)"
    if [ -n "${row}" ]; then printf '%s\t%s\n' "${id}" "$(cut -f3 <<<"${row}")" >> "${found}"; else missing="${missing} ${id}"; fi
  done < "${wanted}"
  if [ -z "${missing}" ]; then echo "All of the ${what} artifacts are uploaded."; break; fi
  open="$(gh api --paginate "repos/${REPO}/actions/runs/${RUN_ID}/attempts/${RUN_ATTEMPT}/jobs?per_page=100" \
    --jq '.jobs[] | select(.status != "completed") | select(.name | test(" / (compare|runtime)$") | not) | .name' | wc -l)"
  if [ "${open}" -eq 0 ]; then idle=$(( idle + 1 )); else idle=0; fi
  if [ "${idle}" -ge 2 ]; then
    fail "no ${what} for${missing}: every other job of attempt ${RUN_ATTEMPT} finished without uploading it; check that the amd64 build passed and ran the ${action} action. On a re-run, use Re-run all jobs: an earlier attempt's artifact is not used"; exit 1
  fi
  if [ "$(date -u +%s)" -ge "${deadline}" ]; then
    fail "no ${what} for${missing} after ${WAIT_MINUTES} minutes; the amd64 build with the ${action} action did not finish in time, re-run the check"; exit 1
  fi
  echo "Waiting for the ${what} of${missing} (${open} other jobs still open)..."; sleep 20
done
