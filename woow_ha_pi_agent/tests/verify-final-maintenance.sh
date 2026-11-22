#!/usr/bin/env bash
# CI runner only: execute the final loaded image by immutable local image ID.
set -euo pipefail
test "$#" -eq 6
context=$1 arch=$2 image_tag=$3 action_image_id=$4 action_digest=$5 source_commit=$6
case "$arch" in amd64) docker_arch=amd64;; aarch64) docker_arch=arm64;; *) exit 2;; esac
test -n "${RUNNER_TEMP:?}"
receipt="${RUNNER_TEMP}/ha-final-image-maintenance-${arch}.json"
log="${RUNNER_TEMP}/ha-final-image-maintenance-${arch}.log"
raw="${RUNNER_TEMP}/ha-final-image-maintenance-${arch}.runtime.json"
image_id=''
preflight_receipt() {
  code=$?
  if [ ! -s "$receipt" ]; then
    python3 - "$receipt" "$code" "$arch" "$image_id" "$source_commit" <<'PY'
import json,sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'schema':'ha-final-image-installed-maintenance/v1',
    'success':False,'hostExitCode':int(sys.argv[2]),'matrixArchitecture':sys.argv[3],
    'loadedImageId':sys.argv[4],'sourceCommit':sys.argv[5],
    'error':'host_preflight_or_container_result_unavailable'},indent=2)+'\n')
PY
  fi
  return "$code"
}
trap preflight_receipt EXIT
# The action imageid is the built config ID. Its manifest digest is a separate
# identity, recorded below; it cannot substitute for this exact local binding.
[[ "$action_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
image_id="$(docker image inspect --format '{{.Id}}' "$image_tag")"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$action_image_id" == "$image_id" ]]
test "$(docker image inspect --format '{{.Architecture}}' "$image_id")" = "$docker_arch"
test "$(docker image inspect --format '{{.Os}}' "$image_id")" = linux
image_bytes="$(docker image inspect --format '{{.Size}}' "$image_id")"
free_bytes="$(df -B1 --output=avail / | awk 'NR == 2 {print $1}')"
[[ "$image_bytes" =~ ^[0-9]+$ && "$free_bytes" =~ ^[0-9]+$ ]]
# amd64 subsequently saves the image for SBOM/Store; arm64 only needs room
# for receipts and the small owned payload after its final image is loaded.
required_bytes=$((2 * 1024 * 1024 * 1024))
if [ "$arch" = amd64 ]; then required_bytes=$((required_bytes + image_bytes)); fi
if (( free_bytes < required_bytes )); then
  echo "Insufficient free disk after final image load: ${free_bytes} < ${required_bytes}" >&2
  exit 1
fi
payload="$(mktemp -d "${RUNNER_TEMP}/ha-final-maintenance-${arch}.XXXXXX")"
chmod 755 "$payload"
cp -a "$context/patches/omnigent-native-maintenance-patch" "$payload/maintenance"
install -m 644 "$context/cli-runtime/versions.json" "$payload/versions.json"
install -m 644 "$context/tests/verify-final-maintenance.py" "$payload/verify-final-maintenance.py"
status=0
timeout 300s docker run --rm --network none --read-only --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 --memory 512m \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777 \
  --mount "type=bind,source=${payload},target=/ha-final-verification,readonly" \
  --entrypoint /opt/omnigent/venv/bin/python "$image_id" -I -B \
  /ha-final-verification/verify-final-maintenance.py --arch "$arch" \
  --image-id "$image_id" --source-commit "$source_commit" \
  --build-action-image-id "$action_image_id" --build-action-digest "$action_digest" \
  > "$raw" 2> "$log" || status=$?
cat "$log" >&2
python3 - "$raw" "$receipt" "$status" "$image_id" "$image_bytes" "$free_bytes" "$required_bytes" <<'PY'
import hashlib,json,sys
from pathlib import Path
raw,receipt=map(Path,sys.argv[1:3]);status=int(sys.argv[3])
try:
    result=json.loads(raw.read_bytes())
except (ValueError,OSError):
    result={'schema':'ha-final-image-installed-maintenance/v1','success':False,'error':'container_result_missing_or_invalid'}
result.update(containerExitCode=status,loadedImageId=sys.argv[4],loadedImageBytes=int(sys.argv[5]),
              hostFreeBytesBeforeReadback=int(sys.argv[6]),hostRequiredFreeBytes=int(sys.argv[7]),
              runtimeStdoutSha256=hashlib.sha256(raw.read_bytes()).hexdigest())
receipt.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,sort_keys=True))
if status!=0 or result.get('success') is not True:
    raise SystemExit(1)
PY
