#!/usr/bin/env python3
"""WOOW addon outbox + Store consumer. No cross-repository write credential.

Publish uses only its own repository GITHUB_TOKEN. Consumers use their own
GITHUB_TOKEN and poll immutable source snapshots advertised in public outboxes.
"""
from __future__ import annotations
import argparse, base64, hashlib, io, json, os, pathlib, re, shutil, subprocess, tarfile, tempfile, urllib.error, urllib.parse, urllib.request
import yaml
from packaging.version import Version, InvalidVersion

BRANCH = 'woow-addon-sync'
EVENT_FILE = 'notification.json'
SHA = re.compile(r'^[0-9a-f]{40}$')
SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,95}$')
IGNORED = {'.git', '.github', '.gitignore', '.claude', '.agents', 'CLAUDE.md', 'AGENTS.md', 'repository.yaml', 'repository.yml', 'repository.json'}
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXTRACTED = 512 * 1024 * 1024
ACCEPT = ','.join(['application/vnd.oci.image.index.v1+json','application/vnd.oci.image.manifest.v1+json','application/vnd.docker.distribution.manifest.list.v2+json','application/vnd.docker.distribution.manifest.v2+json'])

class Blocked(RuntimeError): pass
class Deferred(Blocked): pass

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def digest(data): return 'sha256:' + hashlib.sha256(data).hexdigest()

def safe_repo(repo):
    if not re.fullmatch(r'WOOWTECH/[A-Za-z0-9_.-]+', repo): raise Blocked('Unregistered repository namespace')
    return repo

def safe_path(path):
    p = pathlib.PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or '\\' in path or not p.parts: raise Blocked('Unsafe relative path')
    return p

def version_not_older(candidate, installed):
    if candidate == installed: return True
    try: return Version(candidate) >= Version(installed)
    except InvalidVersion:
        a = re.match(r'^(\d+(?:\.\d+)+)', candidate)
        b = re.match(r'^(\d+(?:\.\d+)+)', installed)
        if not a or not b: raise Blocked('Uncomparable version')
        aa, bb = tuple(map(int, a[0].split('.'))), tuple(map(int, b[0].split('.')))
        if aa == bb: raise Blocked('Ambiguous nonstandard version suffix: review required')
        return aa > bb

class GitHub:
    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get('GITHUB_TOKEN', '')
        self.cache = {}
    def api(self, repo, path, data=None, method=None):
        safe_repo(repo)
        key = (repo, path)
        if data is None and method is None and key in self.cache: return self.cache[key]
        headers = {'Accept':'application/vnd.github+json','User-Agent':'woow-addon-sync/1'}
        if self.token: headers['Authorization'] = 'Bearer ' + self.token
        req = urllib.request.Request('https://api.github.com/repos/'+repo+('/'+path if path else ''), headers=headers,
            data=json.dumps(data).encode() if data is not None else None, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r: result = json.load(r)
        except urllib.error.HTTPError as e:
            raise Blocked(f'GitHub {repo}/{path.split("?")[0]} HTTP {e.code}') from None
        if data is None and method is None: self.cache[key] = result
        return result
    def content(self, repo, path, ref):
        d = self.api(repo, 'contents/'+urllib.parse.quote(path, safe='/')+'?ref='+urllib.parse.quote(ref, safe=''))
        if not isinstance(d, dict) or d.get('encoding') != 'base64': raise Blocked('Expected a small ordinary file')
        return base64.b64decode(d['content'])
    def head(self, repo):
        m = self.api(repo, '')
        if m.get('archived'): raise Blocked('Archived source repository')
        if m.get('private'): raise Blocked('Private source cannot be exported to public Store')
        return m['default_branch'], self.api(repo, 'commits/'+m['default_branch'])['sha']
    def tree(self, repo, sha, subdir='.'):
        if not SHA.fullmatch(sha): raise Blocked('Source must be an immutable commit SHA')
        node = sha
        if subdir != '.':
            for part in safe_path(subdir).parts:
                rows = self.api(repo, 'git/trees/'+node)['tree']
                found = next((x for x in rows if x['path']==part and x['type']=='tree'), None)
                if not found: raise Blocked('Source context not found')
                node = found['sha']
        t = self.api(repo, 'git/trees/'+node+'?recursive=1')
        if t.get('truncated'): raise Blocked('Truncated tree is not a complete validation')
        return t['tree']
    def fingerprint(self, repo, sha, subdir, material=False):
        rows = []
        for x in self.tree(repo, sha, subdir):
            p = safe_path(x['path'])
            if p.parts[0] in IGNORED or x['type'] != 'blob': continue
            if material and (p.parts[0] in ['docs','tests'] or p.suffix.lower() in ['.md','.rst','.png','.jpg','.svg']): continue
            rows.append([str(p), x['sha'], x.get('mode')])
        return digest(canonical(sorted(rows)))
    def outbox(self, repo):
        try:
            d = json.loads(self.content(repo, EVENT_FILE, BRANCH))
        except Blocked as e:
            if 'HTTP 404' in str(e): return {'schema':1,'repository':repo,'components':{}}
            raise
        if d.get('schema') != 1 or d.get('repository') != repo or not isinstance(d.get('components'),dict): raise Blocked('Invalid outbox identity/schema')
        return d
    def put_outbox(self, repo, outbox):
        # Never writes the producer's main branch. GITHUB_TOKEN's own-repo write
        # does not recursively trigger push workflows in the notification branch.
        try:
            old = self.api(repo, 'git/ref/heads/'+BRANCH)
            parent = old['object']['sha']
            base = self.api(repo, 'git/commits/'+parent)['tree']['sha']
        except Blocked as e:
            if 'HTTP 404' not in str(e): raise
            parent = None; base = None
        body = {'tree':[{'path':EVENT_FILE,'mode':'100644','type':'blob','content':json.dumps(outbox,ensure_ascii=False,indent=2)+'\n'}]}
        if base: body['base_tree'] = base
        tree = self.api(repo, 'git/trees', body)
        commit = self.api(repo, 'git/commits', {'message':'chore(sync): publish validated addon notification','tree':tree['sha'],'parents':[parent] if parent else []})
        if parent:
            self.api(repo, 'git/refs/heads/'+BRANCH, {'sha':commit['sha'],'force':False}, 'PATCH')
        else:
            self.api(repo, 'git/refs', {'ref':'refs/heads/'+BRANCH,'sha':commit['sha']})
        return commit['sha']

_ARCHIVE_CACHE = {}
def source_archive(repo, sha):
    safe_repo(repo)
    if not SHA.fullmatch(sha): raise Blocked('Archive must use a commit SHA')
    key = (repo, sha)
    if key not in _ARCHIVE_CACHE:
        # All registered producer repos are public. Never send GitHub credentials
        # to codeload, registries, redirects, or URLs supplied by a notification.
        req = urllib.request.Request(f'https://codeload.github.com/{repo}/tar.gz/{sha}', headers={'User-Agent':'woow-addon-sync/1'})
        with urllib.request.urlopen(req, timeout=120) as r: raw = r.read(MAX_ARCHIVE+1)
        if len(raw)>MAX_ARCHIVE: raise Blocked('Archive exceeds size limit')
        _ARCHIVE_CACHE[key] = raw
    return _ARCHIVE_CACHE[key]

def context_files(raw, subdir):
    """Return a constrained context, rejecting links and special files entirely."""
    result = {}; total = 0; roots = set()
    subparts = () if subdir=='.' else safe_path(subdir).parts
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for m in archive:
            p = safe_path(m.name); roots.add(p.parts[0])
            if len(roots)>1: raise Blocked('Archive has multiple roots')
            relative = p.parts[1:]
            if relative[:len(subparts)] != subparts: continue
            relative = relative[len(subparts):]
            if not relative or relative[0] in IGNORED: continue
            if m.isdir(): continue
            if not m.isfile(): raise Blocked('Context contains a link or special file: '+m.name)
            total += m.size
            if total>MAX_EXTRACTED: raise Blocked('Expanded context exceeds limit')
            name = '/'.join(relative)
            if name in result: raise Blocked('Duplicate archive member')
            result[name] = (archive.extractfile(m).read(), m.mode & 0o777)
    if not result: raise Blocked('Empty source context')
    return result

def config_from_files(files, filename):
    if filename not in files: raise Blocked('Missing addon manifest')
    raw = files[filename][0]
    d = json.loads(raw) if filename.endswith('.json') else yaml.safe_load(raw)
    if not isinstance(d,dict) or not all(k in d for k in ['slug','name','version','arch']): raise Blocked('Invalid addon manifest')
    if not SLUG.fullmatch(d['slug']) or not isinstance(d['arch'],list) or not d['arch']: raise Blocked('Invalid addon slug/architectures')
    if str(d['version']) in ['dev','latest','']: raise Blocked('Unversioned addon must publish a version first')
    if not d.get('image') and 'Dockerfile' not in files: raise Blocked('Neither published image nor source Dockerfile')
    return d

def source_build_supported(files):
    """Check local COPY/ADD inputs, not compilation or runtime health."""
    import fnmatch,shlex
    if 'Dockerfile' not in files:return False
    text=files['Dockerfile'][0].decode().replace('\\\n','')
    for line in text.splitlines():
        m=re.match(r'^\s*(COPY|ADD)\s+(.*)',line,re.I)
        if not m:continue
        args=m[2]
        if re.search(r'(^|\s)--from(?:=|\s)',args):continue
        args=re.sub(r'^(?:--[\w-]+(?:=\S+)?\s+)+','',args)
        try:words=json.loads(args) if args.startswith('[') else shlex.split(args)
        except (ValueError,json.JSONDecodeError):return False
        for source in words[:-1]:
            if source.startswith(('https://','http://')):continue
            if '$' in source:return False
            source=source.lstrip('/')
            p=pathlib.PurePosixPath(source)
            if '..' in p.parts:return False
            source=str(p).rstrip('/')
            if source=='.':continue
            if not any(name==source or name.startswith(source+'/') or fnmatch.fnmatch(name,source) for name in files):return False
    return True

def image_ready(reference, arch):
    """Resolve and validate public OCI/Docker manifest + architecture, no layers."""
    if reference.startswith('ghcr.io/'):
        registry = 'https://ghcr.io'; repo_tag = reference[8:]
        repo, tag = repo_tag.rsplit(':',1)
        token_url = registry+'/token?scope=repository:'+repo+':pull'
    else:
        registry = 'https://registry-1.docker.io';repo_tag = reference.removeprefix('docker.io/')
        repo, tag = repo_tag.rsplit(':',1)
        if '/' not in repo: repo = 'library/'+repo
        token_url = 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:'+repo+':pull'
    if not re.fullmatch(r'[a-z0-9._/-]+',repo) or not re.fullmatch(r'[A-Za-z0-9_.-]+',tag): raise Blocked('Invalid image reference')
    with urllib.request.urlopen(token_url, timeout=45) as r: token = json.load(r)['token']
    def read(path):
        req = urllib.request.Request(registry+'/v2/'+repo+'/'+path,headers={'Authorization':'Bearer '+token,'Accept':ACCEPT})
        with urllib.request.urlopen(req,timeout=60) as r: return r.read()
    raw = read('manifests/'+tag); index_digest = digest(raw);m = json.loads(raw)
    architecture = {'aarch64':'arm64','armv7':'arm','armhf':'arm','i386':'386'}.get(arch,arch)
    if 'manifests' in m:
        desc = next((x for x in m['manifests'] if x.get('platform',{}).get('os')=='linux' and x['platform'].get('architecture')==architecture and (arch!='armv7' or x['platform'].get('variant')=='v7')),None)
        if not desc: raise Blocked('Published image missing architecture '+arch)
        raw = read('manifests/'+desc['digest'])
        if digest(raw)!=desc['digest']: raise Blocked('Image manifest digest mismatch')
        m = json.loads(raw)
    platform_digest = digest(raw)
    config = read('blobs/'+m['config']['digest'])
    if digest(config)!=m['config']['digest']: raise Blocked('Image config digest mismatch')
    cfg = json.loads(config)
    if cfg.get('os')!='linux' or cfg.get('architecture')!=architecture: raise Blocked('Image platform does not match advertised addon architecture')
    return {'reference':reference,'index_digest':index_digest,'digest':platform_digest,'source_revision':((cfg.get('config') or {}).get('Labels') or {}).get('org.opencontainers.image.revision')}

def pi_image_reuse(gh,sha,arch,version):
    """Never overwrite a Pi Agent version tag, even for CI-only changes."""
    if arch not in ['amd64','aarch64'] or not re.fullmatch(r'[0-9][A-Za-z0-9_.-]*',version):raise Blocked('Invalid image metadata')
    repo='WOOWTECH/Woow_ha_pi_agent_add_on'
    try:image=image_ready('ghcr.io/woowtech/woow-ha-pi-agent-'+arch+':'+version,arch)
    except urllib.error.HTTPError as e:
        if e.code==404:return False
        raise
    revision=image.get('source_revision')
    if not revision or not SHA.fullmatch(revision):raise Blocked('Existing image lacks immutable source revision; refusing overwrite')
    if gh.fingerprint(repo,revision,'.',material=True)!=gh.fingerprint(repo,sha,'.',material=True):raise Blocked('Existing version has a different runtime; bump config.yaml version before publishing')
    return True

def ci_gate(gh, repo, sha, component, required):
    """Require successful relevant CI, or an unchanged runtime since that CI.
    Mirrors with no runtime build CI rely on the published-image architecture gate.
    """
    fingerprint = gh.fingerprint(repo,sha,component['source_path'],material=True)
    for workflow in required:
        endpoint='actions/workflows/'+urllib.parse.quote(workflow.rsplit('/',1)[-1],safe='')+'/runs'
        exact = [r for r in gh.api(repo,endpoint+'?head_sha='+sha+'&per_page=20')['workflow_runs'] if r['head_sha']==sha and r['event']!='pull_request']
        if exact:
            latest = max(exact,key=lambda r:r['id'])
            if latest['status']!='completed': raise Deferred('CI still running: '+workflow)
            if latest['conclusion']!='success': raise Blocked('CI failed: '+workflow)
            continue
        ok = False
        runs=gh.api(repo,endpoint+'?per_page=40')['workflow_runs']
        for r in runs:
            if r.get('conclusion')!='success' or r['event']=='pull_request': continue
            try:previous_fingerprint=gh.fingerprint(repo,r['head_sha'],component['source_path'],material=True)
            except Blocked as e:
                if 'context not found' in str(e):continue
                raise
            if previous_fingerprint==fingerprint:
                comparison = gh.api(repo,'compare/'+r['head_sha']+'...'+sha)
                if comparison['status'] in ['ahead','identical']: ok=True;break
        if not ok: raise Blocked('No successful CI for current runtime: '+workflow)
    return fingerprint

def publish(gh, registry, repo, apply=False, only=None):
    provider = registry['providers'][repo]
    _,sha = gh.head(repo)
    if provider.get('ref_policy')=='release':
        release = gh.api(repo,'releases/latest')
        if release.get('draft') or release.get('prerelease'): raise Blocked('No stable release')
        sha = gh.api(repo,'commits/'+urllib.parse.quote(release['tag_name'],safe=''))['sha']
    old = gh.outbox(repo); new = json.loads(json.dumps(old)); report=[]
    for comp in provider['components']:
        cid=comp['id']
        if only and cid not in only: continue
        if not comp.get('enabled',True): report.append({'id':cid,'state':'excluded','reason':comp['reason']});continue
        try:
            fp=gh.fingerprint(repo,sha,comp['source_path'])
            previous=old['components'].get(cid)
            if previous and previous.get('context_fingerprint')==fp:
                report.append({'id':cid,'state':'unchanged'});continue
            material=ci_gate(gh,repo,sha,comp,provider.get('required_workflows',[]))
            raw=source_archive(repo,sha);files=context_files(raw,comp['source_path']);cfg=config_from_files(files,comp['config_file'])
            if cfg['slug']!=cid: raise Blocked('Unexpected addon slug')
            version=str(cfg['version'])
            if previous and previous['version']==version and previous.get('material_fingerprint')!=material:
                raise Blocked('Runtime changed without an addon version bump')
            if previous and not version_not_older(version,previous['version']): raise Blocked('Producer version downgrade')
            images={};build_supported=source_build_supported(files)
            if not cfg.get('image') and not build_supported:raise Blocked('Source context is missing Docker COPY inputs or uses unresolved source paths')
            if cfg.get('image'):
                for arch in cfg['arch']:
                    try:images[arch]=image_ready(cfg['image'].replace('{arch}',arch)+':'+version,arch)
                    except urllib.error.HTTPError as e:raise Blocked(f'Published image unavailable for {arch}: HTTP {e.code}') from None
            entry={'id':cid,'name':cfg['name'],'version':version,'repository':repo,'source_sha':sha,
                'source_path':comp['source_path'],'config_file':comp['config_file'],'config_sha256':digest(files[comp['config_file']][0]),
                'archive_sha256':digest(raw),'context_fingerprint':fp,'material_fingerprint':material,
                'architectures':cfg['arch'],'config':cfg,'source_build_supported':build_supported,'images':images,'delivery':'published-image' if images else 'local-source-build',
                'validation':'manifest+architecture-images+configured-CI' if images else 'manifest+source-context+configured-CI (runtime build not certified)',
                'publisher_run_id':os.environ.get('GITHUB_RUN_ID'),'channel':comp.get('channel','stable')}
            new['components'][cid]=entry;report.append({'id':cid,'state':'ready','version':version})
        except Exception as e:
            # Never expose response bodies/headers/environment or credential values.
            report.append({'id':cid,'state':'waiting' if isinstance(e,Deferred) else 'blocked','reason':str(e) if isinstance(e,Blocked) else type(e).__name__})
    if apply and canonical(old)!=canonical(new):gh.put_outbox(repo,new)
    return report,new

def validate_entry(gh, repo, component, entry):
    if entry.get('repository')!=repo or entry.get('id')!=component['id']:raise Blocked('Notification identity mismatch')
    if entry.get('source_path')!=component['source_path'] or entry.get('config_file')!=component['config_file']:raise Blocked('Notification context mismatch')
    if not SHA.fullmatch(entry.get('source_sha','')):raise Blocked('Missing immutable source SHA')
    run_id=entry.get('publisher_run_id')
    if not run_id or not str(run_id).isdigit():raise Blocked('Missing successful producer workflow receipt')
    run=gh.api(repo,'actions/runs/'+str(run_id))
    if run.get('conclusion')!='success' or run.get('status')!='completed':raise Blocked('Producer publication is not yet successful')
    if run.get('path','').split('@')[0]!='.github/workflows/woow-addon-sync.yml' or run.get('event') not in ['push','workflow_dispatch','workflow_run','schedule']:raise Blocked('Unexpected publisher workflow')
    if run.get('head_repository',{}).get('full_name')!=repo:raise Blocked('Foreign workflow source')
    if gh.fingerprint(repo,entry['source_sha'],component['source_path'])!=entry['context_fingerprint']:raise Blocked('Context fingerprint mismatch')

def write_context(destination,files):
    # Caller chooses a registry-controlled package directory, never arbitrary payload paths.
    destination=pathlib.Path(destination)
    if destination.is_symlink():raise Blocked('Destination is a symlink')
    if destination.exists():shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for name,(data,mode) in files.items():
        p=destination.joinpath(*safe_path(name).parts);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(mode)

def consume(gh, registry, workspace, only=None):
    workspace=pathlib.Path(workspace);catpath=workspace/'.addon-sync/catalog.json'
    catalog=json.loads(catpath.read_text()) if catpath.exists() else {'schema':1,'components':{}}
    report=[];outboxes={}
    for repo,provider in registry['providers'].items():
        active=[c for c in provider['components'] if c.get('enabled',True) and c.get('channel','stable')=='stable' and (not only or c['id'] in only)]
        if not active:continue
        try:outboxes[repo]=gh.outbox(repo)
        except Blocked as e:
            report.append({'repository':repo,'state':'blocked','reason':str(e)});continue
        for comp in active:
            cid=comp['id'];entry=outboxes[repo]['components'].get(cid);previous=catalog['components'].get(cid)
            if not entry:report.append({'id':cid,'state':'waiting-for-source-notification'});continue
            if previous and previous.get('context_fingerprint')==entry.get('context_fingerprint'):
                report.append({'id':cid,'state':'unchanged'});continue
            try:
                if not SLUG.fullmatch(comp['store_path']):raise Blocked('Unsafe registered destination')
                validate_entry(gh,repo,comp,entry)
                if previous and previous['source_sha']!=entry['source_sha']:
                    comparison=gh.api(repo,'compare/'+previous['source_sha']+'...'+entry['source_sha'])
                    if comparison['status'] not in ['ahead','identical']:raise Blocked('Out-of-order or divergent source notification')
                dest=workspace/comp['store_path'];existing=dest/comp['config_file']
                current=json.loads(existing.read_text()) if existing.exists() and existing.suffix=='.json' else yaml.safe_load(existing.read_text()) if existing.exists() else None
                if current and current.get('slug')!=cid:raise Blocked('Destination belongs to another addon')
                baseline=str(current['version']) if current else previous['version'] if previous else None
                if baseline and not version_not_older(entry['version'],baseline):raise Blocked('Store ahead of source; downgrade refused')
                raw=source_archive(repo,entry['source_sha'])
                if digest(raw)!=entry['archive_sha256']:raise Blocked('Source archive checksum mismatch')
                files=context_files(raw,entry['source_path']);cfg=config_from_files(files,entry['config_file'])
                if cfg['slug']!=cid or str(cfg['version'])!=entry['version'] or digest(files[entry['config_file']][0])!=entry['config_sha256']:raise Blocked('Manifest identity/version mismatch')
                if canonical(cfg)!=canonical(entry.get('config')) or cfg['arch']!=entry['architectures']:raise Blocked('Notification altered the source configuration')
                if cfg.get('image'):
                    if set(entry['images'])!=set(cfg['arch']):raise Blocked('Incomplete architecture image receipts')
                    for arch in cfg['arch']:
                        ref=cfg['image'].replace('{arch}',arch)+':'+str(cfg['version'])
                        if image_ready(ref,arch)!=entry['images'][arch]:raise Blocked('Published image changed after producer validation')
                elif entry.get('images'):raise Blocked('Unexpected image receipts on a source-only addon')
                with tempfile.TemporaryDirectory(prefix='.addon-sync-stage-',dir=workspace) as tmp:
                    staged=pathlib.Path(tmp)/'new';write_context(staged,files)
                    # Apply trusted Store metadata policy before replacing the old context.
                    policy=workspace/'.github/scripts/sidebar_titles.py'
                    if policy.exists():
                        import importlib.util
                        spec=importlib.util.spec_from_file_location('sidebar_policy',policy);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
                        if comp['store_path'] in mod.TITLES:
                            f=staged/'config.yaml';f.write_text(mod.normalize(f.read_text(),mod.TITLES[comp['store_path']]))
                    previous_dir=pathlib.Path(tmp)/'old'
                    if dest.is_symlink():raise Blocked('Destination is a symlink')
                    if dest.exists():dest.rename(previous_dir)
                    try:staged.rename(dest)
                    except Exception:
                        if previous_dir.exists():previous_dir.rename(dest)
                        raise
                catalog['components'][cid]={**entry,'store_path':comp['store_path']}
                report.append({'id':cid,'state':'synced','version':entry['version']})
            except Exception as e:report.append({'id':cid,'state':'blocked','reason':str(e) if isinstance(e,Blocked) else type(e).__name__})
    catalog['catalog_id']=digest(canonical(catalog['components']))
    catpath.parent.mkdir(exist_ok=True);catpath.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    return report,catalog

def summary(report):
    text='## WOOW addon synchronization\n\n'+ '\n'.join('- '+json.dumps(r,ensure_ascii=False) for r in report)+'\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['publish','consume']);p.add_argument('--registry',default='.addon-sync/registry.json');p.add_argument('--repo',default=os.environ.get('GITHUB_REPOSITORY'));p.add_argument('--workspace',default='.');p.add_argument('--apply',action='store_true');p.add_argument('--only',action='append');p.add_argument('--result')
    a=p.parse_args();registry=json.loads(pathlib.Path(a.registry).read_text());gh=GitHub()
    if a.command=='publish':report,data=publish(gh,registry,a.repo,a.apply,a.only)
    else:report,data=consume(gh,registry,a.workspace,a.only)
    summary(report)
    if a.result:pathlib.Path(a.result).write_text(json.dumps({'report':report,'data':data},ensure_ascii=False,indent=2))
    if report and all(r['state'] in ['blocked','excluded','waiting-for-source-notification'] for r in report) and any(r['state']=='blocked' for r in report):raise SystemExit(1)

if __name__=='__main__':main()
