#!/usr/bin/env python3
"""Cold backup/restore of the synthetic HA candidate PVCs (deployment must be scaled to 0)."""
import json, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
NS = 'nextcloud-ha-upgrade-rehearsal'
LABELS = {'woowtech.io/task': 'nextcloud-ha-upgrade', 'woowtech.io/gate': '3'}
BASE = 'debian@' + json.loads((ROOT / 'images.json').read_text())['base']['amd64_digest']
META = "find . -mindepth 1 -printf '%y %m %U %G %p\\n' | LC_ALL=C sort"
SHA = "find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum"
BACKUP = f'''set -euo pipefail; id=$1; mkdir -p /bk/$id; cd /bk/$id; test ! -e DONE
for v in data share; do cd /src/$v; {META} > /bk/$id/$v.meta; {SHA} > /bk/$id/$v.sha; tar --numeric-owner --xattrs --acls -cpf /bk/$id/$v.tar .; done
cd /bk/$id; sha256sum data.tar share.tar > tars.sha; du -sh /bk/$id; date -u +%FT%TZ > DONE; cat tars.sha; wc -l data.meta share.meta data.sha share.sha'''
RESTORE = f'''set -euo pipefail; id=$1; cd /bk/$id; test -e DONE; sha256sum -c tars.sha
for v in data share; do cd /src/$v; find . -mindepth 1 -delete; tar --numeric-owner --xattrs --acls -xpf /bk/$id/$v.tar; {META} > /tmp/$v.meta; {SHA} > /tmp/$v.sha
  cmp /tmp/$v.meta /bk/$id/$v.meta; cmp /tmp/$v.sha /bk/$id/$v.sha; echo "$v restored and verified"; done'''

def k(*a, data=None, check=True):
    return subprocess.run(['kubectl', '--context', 'woow-k3s', '-n', NS, *a], input=None if data is None else json.dumps(data), text=True, capture_output=True, check=check).stdout

def scaled_down():
    k('scale', 'deploy/ha-cand', '--replicas=0')
    for _ in range(60):
        if not json.loads(k('get', 'pods', '-l', 'app=ha-cand', '-o', 'json'))['items']: return
        time.sleep(5)
    raise TimeoutError('ha-cand pod still present')

def run(action, ident):
    assert ident.replace('-', '').replace('.', '').isalnum()
    scaled_down()
    name = (f'{action}-{ident}'.replace('.', '')[:45] + '-' + time.strftime('%H%M%S')).lower()  # unique per run
    script = BACKUP if action == 'backup' else RESTORE
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': name, 'namespace': NS, 'labels': LABELS}, 'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 3600, 'template': {'metadata': {'labels': LABELS}, 'spec': {
        'automountServiceAccountToken': False, 'restartPolicy': 'Never', 'securityContext': {'seccompProfile': {'type': 'RuntimeDefault'}},
        'affinity': {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [{'matchExpressions': [{'key': 'kubernetes.io/hostname', 'operator': 'NotIn', 'values': ['ubuntuserver-59mqj']}]}]}}},
        'containers': [{'name': action, 'image': BASE, 'command': ['bash', '-c', script, 'job', ident],
                        'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL'], 'add': ['CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'FSETID']}},
                        'resources': {'requests': {'cpu': '200m', 'memory': '256Mi'}, 'limits': {'cpu': '2', 'memory': '1Gi'}},
                        'volumeMounts': [{'name': 'data', 'mountPath': '/src/data'}, {'name': 'share', 'mountPath': '/src/share'}, {'name': 'bk', 'mountPath': '/bk', 'readOnly': action == 'restore'}]}],
        'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'ha-cand-data'}}, {'name': 'share', 'persistentVolumeClaim': {'claimName': 'ha-cand-share'}},
                    {'name': 'bk', 'persistentVolumeClaim': {'claimName': 'ha-cand-backups'}}]}}}}
    k('create', '-f', '-', data=job)
    for _ in range(360):
        st = json.loads(k('get', 'job', name, '-o', 'json'))['status']
        types = {c['type'] for c in st.get('conditions', []) if c['status'] == 'True'}
        if types & {'Complete', 'Failed'}: break
        time.sleep(5)
    log = k('logs', f'job/{name}', check=False)
    (ROOT / f'{name}.log').write_text(log); print(log)
    if 'Complete' not in types: raise SystemExit(f'{name} failed')

if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2])
