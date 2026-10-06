#!/bin/bash
# usage: up.sh <image-ref> <bootlog>; scale 1 and wait until the pod running THIS image finished s6 (success or init failure)
export PATH=$HOME/.local/bin:$PATH
K="kubectl --context woow-k3s -n nextcloud-ha-upgrade-rehearsal"
$K set image deploy/ha-cand addon="$1" >/dev/null
$K scale deploy/ha-cand --replicas=1 >/dev/null
pod=""
for i in $(seq 1 120); do
  pod=$($K get pods -l app=ha-cand -o json | python3 -c "
import sys,json
for p in json.load(sys.stdin)['items']:
    c=[x for x in p['spec']['containers'] if x['name']=='addon'][0]
    st=(p['status'].get('containerStatuses') or [{}])[0]
    if c['image']==sys.argv[1] and not p['metadata'].get('deletionTimestamp') and 'running' in st.get('state',{}): print(p['metadata']['name'])" "$1")
  [ -n "$pod" ] && break; sleep 5
done
[ -n "$pod" ] || { echo "no running pod for $1"; exit 1; }
for i in $(seq 1 120); do
  $K logs "$pod" -c addon > "$2" 2>/dev/null && grep -q -E "legacy-services successfully started|unable to start service" "$2" && break
  sleep 10
done
sleep 5; $K logs "$pod" -c addon > "$2" 2>&1
echo "pod $pod"
grep -E "^s6-rc: warning|upgrade|Upgrade|Updating|Update successful|Installing|disabled|incompatible|Repair|error" "$2" | grep -v -E "^wsd-|^kit-|^frk-|websocket|^Connection" | grep -v -i pass | tail -30 | cut -c1-220
grep -q "legacy-services successfully started" "$2" && echo BOOT_OK || echo BOOT_NOT_COMPLETE
