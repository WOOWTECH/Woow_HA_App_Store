#!/usr/bin/env python3
"""Gate 3 candidate builds (one NC version per call) into the retained build-artifacts PVC; no push."""
import base64, hashlib, io, json, subprocess, sys, tarfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
REPO = Path('/data/pi-agent/home/work/nextcloud-ha-php84')
NS = 'nextcloud-ha-upgrade-rehearsal'
SHA = {'33.0.9': 'f331c1041d027e6588526d2a00ce42bc70a9622eab5871c0be9177252cf77423',
       '34.0.4': '00f226e6364f96e0918ab06157158f66601b8cedc25af777f5ee5a3056f42b83',
       '35.0.1': '7ed305e880192d804ba83179a19dd22257679608d63161a611ce3f8a918d2aa6'}
LABELS = {'woowtech.io/task': 'nextcloud-ha-upgrade', 'woowtech.io/gate': '3'}

def kube(args, data=None):
    return subprocess.run(['kubectl', '--context', 'woow-k3s', *args], input=None if data is None else json.dumps(data), text=True, capture_output=True, check=True).stdout

def main(commit, version):
    images = json.loads((ROOT / 'images.json').read_text())
    base = 'debian@' + images['base']['amd64_digest']; builder = 'gcr.io/kaniko-project/executor@' + images['builder']['amd64_digest']; busy = 'busybox@' + images['unpack']['amd64_digest']
    full = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', commit], text=True).strip()
    raw = subprocess.check_output(['git', '-C', str(REPO), 'archive', '--format=tar', full, 'woow-nextcloud-office'])
    src = tarfile.open(fileobj=io.BytesIO(raw)); out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz', format=tarfile.PAX_FORMAT) as t:
        for m in sorted(src.getmembers(), key=lambda m: m.name):
            if not m.isfile() or '/test/' in m.name or '/qa/' in m.name or m.name.endswith(('.png',)):
                continue
            data = src.extractfile(m).read(); name = m.name.split('/', 1)[1]
            if name == 'Dockerfile':
                text = data.decode(); assert text.count('FROM debian:trixie-slim') == 1
                data = text.replace('FROM debian:trixie-slim', 'FROM ' + base).encode()
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = m.mode; info.mtime = 0
            t.addfile(info, io.BytesIO(data))
    content = out.getvalue(); h = hashlib.sha256(content).hexdigest(); assert len(content) < 900000
    tag = version.replace('.', '') ; name = f'ha{tag}-build-{h[:12]}'
    meta = lambda n: {'name': n, 'namespace': NS, 'labels': LABELS}
    kube(['create', '-f', '-'], {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta(name), 'immutable': True, 'binaryData': {'context.tgz': base64.b64encode(content).decode()}})
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': meta(name), 'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 3600, 'template': {'metadata': {'labels': dict(LABELS, app='ha-candidate-build')}, 'spec': {
        'automountServiceAccountToken': False, 'restartPolicy': 'Never', 'securityContext': {'seccompProfile': {'type': 'RuntimeDefault'}},
        'affinity': {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [{'matchExpressions': [{'key': 'kubernetes.io/hostname', 'operator': 'NotIn', 'values': ['ubuntuserver-59mqj']}, {'key': 'kubernetes.io/arch', 'operator': 'In', 'values': ['amd64']}]}]}}},
        'initContainers': [{'name': 'unpack', 'image': busy, 'command': ['sh', '-c', 'tar xzf /source/context.tgz -C /workspace'], 'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '100m', 'memory': '128Mi'}},
                            'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}}, 'volumeMounts': [{'name': 'source', 'mountPath': '/source', 'readOnly': True}, {'name': 'workspace', 'mountPath': '/workspace'}]}],
        'containers': [{'name': 'build', 'image': builder, 'args': ['--context=dir:///workspace', '--dockerfile=/workspace/Dockerfile', '--build-arg=BUILD_ARCH=amd64', '--build-arg=TARGETARCH=amd64',
                        f'--build-arg=NEXTCLOUD_VERSION={version}', f'--build-arg=NEXTCLOUD_SHA256={SHA[version]}', f'--destination=nextcloud-ha-office-rehearsal:{name}', '--no-push', '--cache=false',
                        f'--tarPath=/output/{name}.tar', f'--digest-file=/output/{name}.digest', '--verbosity=info'],
                        'resources': {'requests': {'cpu': '500m', 'memory': '1Gi', 'ephemeral-storage': '4Gi'}, 'limits': {'cpu': '4', 'memory': '6Gi', 'ephemeral-storage': '16Gi'}},
                        'securityContext': {'allowPrivilegeEscalation': False}, 'volumeMounts': [{'name': 'workspace', 'mountPath': '/workspace'}, {'name': 'output', 'mountPath': '/output'}]}],
        'volumes': [{'name': 'workspace', 'emptyDir': {}}, {'name': 'source', 'configMap': {'name': name}}, {'name': 'output', 'persistentVolumeClaim': {'claimName': 'build-artifacts'}}]}}}}
    kube(['create', '-f', '-'], job)
    r = {'job': name, 'version': version, 'nextcloud_sha256': SHA[version], 'commit': full, 'context_sha256': h, 'base': base, 'builder': builder, 'tar': f'/output/{name}.tar'}
    (ROOT / f'build-{version}.json').write_text(json.dumps(r, indent=2) + '\n'); print(json.dumps(r))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
