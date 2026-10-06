#!/usr/bin/env python3
"""Approved LAN publish of one retained Gate 3 tar: temp netpol -> crane via traefik (normal TLS) -> delete netpol -> verify via public path."""
import json, re, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
NS = 'nextcloud-ha-upgrade-rehearsal'
CRANE = 'gcr.io/go-containerregistry/crane@sha256:dfb14543fc9d2b6231e50af38bb6631f60b21e5f93489c18b1f92f1f23e712b1'
REPO = 'jcr-prod.woowtech.io/woow-paas-docker-local/nextcloud-ha-office-rehearsal'
TRAEFIK_IP = '10.43.104.214'
LABELS = {'woowtech.io/task': 'nextcloud-ha-upgrade', 'woowtech.io/gate': '3'}
AVOID = {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [{'matchExpressions': [{'key': 'kubernetes.io/hostname', 'operator': 'NotIn', 'values': ['ubuntuserver-59mqj']}]}]}}}

def k(*args, data=None, check=True):
    return subprocess.run(['kubectl', '--context', 'woow-k3s', '-n', NS, *args], input=None if data is None else json.dumps(data), text=True, capture_output=True, check=check).stdout

def wait(job):
    for _ in range(360):
        conds = json.loads(k('get', 'job', job, '-o', 'json'))['status'].get('conditions', [])
        types = {c['type'] for c in conds if c['status'] == 'True'}
        if 'Complete' in types: return True
        if 'Failed' in types: return False
        time.sleep(10)
    raise TimeoutError(job)

def main(version):
    b = json.loads((ROOT / f'build-{version}.json').read_text())
    tar, tag = b['tar'], 'ha' + version.replace('.', '') + '-php84-' + b['context_sha256'][:12]
    ref = f'{REPO}:{tag}'
    vol = [{'name': 'output', 'persistentVolumeClaim': {'claimName': 'build-artifacts', 'readOnly': True}}, {'name': 'registry', 'secret': {'secretName': 'registry-pull', 'items': [{'key': '.dockerconfigjson', 'path': 'config.json'}]}}]
    sec = {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}}
    netpol = {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'allow-egress-traefik-jcr', 'namespace': NS, 'labels': LABELS},
              'spec': {'podSelector': {'matchLabels': {'woowtech.io/role': 'jcr-lan-publisher'}}, 'policyTypes': ['Egress'],
                       'egress': [{'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}}, 'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'traefik'}}}], 'ports': [{'protocol': 'TCP', 'port': 8443}]}]}}
    name = 'publish-' + tag[:40].rstrip('-')
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': name, 'namespace': NS, 'labels': LABELS}, 'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 3600, 'template': {
        'metadata': {'labels': dict(LABELS, **{'woowtech.io/role': 'jcr-lan-publisher'})}, 'spec': {'automountServiceAccountToken': False, 'restartPolicy': 'Never', 'affinity': AVOID,
        'securityContext': {'seccompProfile': {'type': 'RuntimeDefault'}}, 'hostAliases': [{'ip': TRAEFIK_IP, 'hostnames': ['jcr-prod.woowtech.io']}],
        'initContainers': [{'name': 'inspect', 'image': 'busybox:1.37', 'command': ['sh', '-c', f'set -e; sha256sum {tar}; stat -c %s {tar}; tar -xOf {tar} manifest.json; echo'], 'securityContext': sec,
                            'resources': {'requests': {'cpu': '100m', 'memory': '64Mi'}, 'limits': {'cpu': '1', 'memory': '256Mi'}}, 'volumeMounts': [{'name': 'output', 'mountPath': '/output', 'readOnly': True}]}],
        'containers': [{'name': 'publish', 'image': CRANE, 'args': ['push', tar, ref], 'env': [{'name': 'DOCKER_CONFIG', 'value': '/registry'}], 'securityContext': sec,
                        'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'cpu': '2', 'memory': '2Gi'}},
                        'volumeMounts': [{'name': 'output', 'mountPath': '/output', 'readOnly': True}, {'name': 'registry', 'mountPath': '/registry', 'readOnly': True}]}], 'volumes': vol}}}}
    k('create', '-f', '-', data=netpol)
    try:
        k('create', '-f', '-', data=job)
        ok = wait(name)
    finally:
        k('delete', 'networkpolicy', 'allow-egress-traefik-jcr', check=False)  # always removed, success or not
    inspect = k('logs', f'job/{name}', '-c', 'inspect'); log = k('logs', f'job/{name}', '-c', 'publish', check=False)
    (ROOT / f'publish-{version}.log').write_text(inspect + '\n' + log)
    if not ok: raise SystemExit(f'publish {version} failed; see publish-{version}.log')
    digest = re.search(r'@(sha256:[0-9a-f]{64})', log).group(1)
    vname = 'verify-' + digest[7:19]
    k('create', '-f', '-', data={'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': vname, 'namespace': NS, 'labels': LABELS}, 'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 900, 'template': {'metadata': {'labels': LABELS}, 'spec': {
        'automountServiceAccountToken': False, 'restartPolicy': 'Never', 'affinity': AVOID, 'securityContext': {'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{'name': 'verify', 'image': CRANE, 'args': ['manifest', f'{REPO}@{digest}'], 'env': [{'name': 'DOCKER_CONFIG', 'value': '/registry'}], 'securityContext': sec,
                        'resources': {'requests': {'cpu': '50m', 'memory': '64Mi'}, 'limits': {'cpu': '500m', 'memory': '256Mi'}}, 'volumeMounts': [{'name': 'registry', 'mountPath': '/registry', 'readOnly': True}]}],
        'volumes': [vol[1]]}}}})
    if not wait(vname): raise SystemExit('verify job failed')
    manifest = json.loads(k('logs', f'job/{vname}'))
    tarman = json.loads(re.search(r'\[\{.*\}\]', inspect).group(0))[0]
    cfg_ok = manifest['config']['digest'] == tarman['Config']
    layers_ok = [l['digest'] for l in manifest['layers']] == ['sha256:' + x.split('.')[0] for x in tarman['Layers']]
    tar_sha = inspect.split()[0]
    r = {'version': version, 'tar': tar, 'tar_sha256': tar_sha, 'ref': ref, 'digest': digest, 'config': manifest['config']['digest'], 'config_matches_tar': cfg_ok, 'layers_match_tar': layers_ok,
         'publish_job': name, 'verify_job': vname, 'netpol_deleted': 'allow-egress-traefik-jcr' not in k('get', 'networkpolicy', '-o', 'name')}
    (ROOT / f'publish-{version}.json').write_text(json.dumps(r, indent=2) + '\n'); print(json.dumps(r))
    if not (cfg_ok and layers_ok and r['netpol_deleted']): raise SystemExit('verification failed')

if __name__ == '__main__':
    main(sys.argv[1])
