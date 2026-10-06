#!/usr/bin/env python3
"""Download a verified local-addon context. Does NOT install/start/upgrade anything.
Python standard library only. Existing directories are never overwritten.
"""
import argparse,hashlib,io,json,os,pathlib,platform,re,tarfile,tempfile,urllib.request
DEFAULT='https://raw.githubusercontent.com/WOOWTECH/Woow_HA_App_Store/main/.addon-sync/catalog.json'
LIMIT=256*1024*1024
IGNORE={'.git','.github','.gitignore','.claude','.agents','CLAUDE.md','AGENTS.md','repository.yaml','repository.yml','repository.json'}

def digest(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def canonical(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'woow-local-addon-download/1'}),timeout=120) as r:raw=r.read(LIMIT+1)
    if len(raw)>LIMIT:raise ValueError('Download exceeds size limit')
    return raw

def stage(entry,destination,arch,source_build=False,raw=None):
    cid=entry['id'];repo=entry['repository'];sha=entry['source_sha']
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}',cid):raise ValueError('Unsafe addon identifier')
    if not re.fullmatch(r'WOOWTECH/[A-Za-z0-9_.-]+',repo) or not re.fullmatch(r'[0-9a-f]{40}',sha):raise ValueError('Invalid immutable source')
    if arch not in entry['architectures']:raise ValueError('Addon does not support '+arch)
    if entry.get('channel','stable')!='stable':raise ValueError('This downloader only accepts stable catalog entries')
    if entry.get('images') and arch not in entry['images']:raise ValueError('Requested architecture image is not validated')
    destination=pathlib.Path(destination);target=destination/cid
    if target.exists() or target.is_symlink():raise FileExistsError('Refusing to replace existing addon context: '+str(target))
    raw=raw if raw is not None else fetch(f'https://codeload.github.com/{repo}/tar.gz/{sha}')
    if digest(raw)!=entry['archive_sha256']:raise ValueError('Source archive checksum mismatch')
    sub=() if entry['source_path']=='.' else pathlib.PurePosixPath(entry['source_path']).parts
    if '..' in sub or (sub and sub[0]=='/'):raise ValueError('Unsafe source directory')
    destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.local-addon-download-',dir=destination) as tmp:
        out=pathlib.Path(tmp)/cid;out.mkdir();seen=set();roots=set();expanded=0
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
            for member in archive:
                p=pathlib.PurePosixPath(member.name)
                if p.is_absolute() or '..' in p.parts or '\\' in member.name or not p.parts:raise ValueError('Unsafe archive path')
                roots.add(p.parts[0])
                if len(roots)>1:raise ValueError('Multiple archive roots')
                rel=p.parts[1:]
                if rel[:len(sub)]!=sub:continue
                rel=rel[len(sub):]
                if not rel or rel[0] in IGNORE or member.isdir():continue
                if not member.isfile():raise ValueError('Links/special files are not accepted')
                name='/'.join(rel)
                if name in seen:raise ValueError('Duplicate archive path')
                seen.add(name);expanded+=member.size
                if expanded>512*1024*1024:raise ValueError('Expanded context too large')
                f=out.joinpath(*rel);f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(archive.extractfile(member).read());f.chmod(member.mode&0o777)
        config_file=entry['config_file']
        if config_file not in ['config.yaml','config.yml','config.json']:raise ValueError('Invalid config filename')
        config_path=out/config_file
        if digest(config_path.read_bytes())!=entry['config_sha256']:raise ValueError('Manifest checksum mismatch')
        cfg=json.loads(json.dumps(entry['config']))
        if cfg['slug']!=cid or str(cfg['version'])!=entry['version']:raise ValueError('Catalog/manifest identity mismatch')
        cfg['boot']='manual' # Never automatically start DHCP/MQTT or any other new service.
        if source_build:
            if not entry.get('source_build_supported'):raise ValueError('Source build needs additional repository context; use the published-runtime wrapper or review the source build instructions')
            if not (out/'Dockerfile').is_file():raise ValueError('This addon has no source Dockerfile')
            cfg.pop('image',None)
        elif entry.get('images'):
            image=entry['images'][arch]
            if not re.fullmatch(r'sha256:[0-9a-f]{64}',image['digest']):raise ValueError('Invalid runtime image digest')
            base=image['reference'].rsplit(':',1)[0]
            if not re.fullmatch(r'[a-z0-9._/-]+',base):raise ValueError('Invalid runtime image name')
            original=out/'Dockerfile'
            if original.exists():
                saved=out/'Dockerfile.source'
                if saved.exists():raise ValueError('Source already has Dockerfile.source; review wrapper naming')
                original.rename(saved)
            original.write_text('# Local wrapper of an already published runtime; not source compilation.\nFROM '+base+'@'+image['digest']+'\n')
            cfg.pop('image',None)
            cfg['arch']=[arch]
        # JSON is a strict YAML subset; this avoids a PyYAML dependency on HAOS.
        # Keep the original filename so Docker COPY instructions remain valid.
        config_path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
        (out/'.woow-source-lock.json').write_text(json.dumps({'source':entry,'local_policy':{'boot':'manual','source_build':source_build,'architecture':arch,'digest_wrapper':bool(entry.get('images')) and not source_build},'local_config_sha256':digest(config_path.read_bytes())},ensure_ascii=False,indent=2)+'\n')
        if target.exists() or target.is_symlink():raise FileExistsError('Destination appeared during download; refusing replacement')
        # mkdir is an exclusive claim; a competing download cannot replace a populated target.
        target.mkdir()
        try:
            for child in out.iterdir():child.rename(target/child.name)
        except BaseException:
            # The exclusively-created directory can safely be removed on failure.
            import shutil
            shutil.rmtree(target)
            raise
    return target

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('addon',nargs='?');p.add_argument('--catalog',default=DEFAULT);p.add_argument('--destination',default='./local-addons');p.add_argument('--arch',default={'x86_64':'amd64','arm64':'aarch64'}.get(platform.machine(),platform.machine()));p.add_argument('--source-build',action='store_true');p.add_argument('--list',action='store_true');a=p.parse_args()
    if a.catalog.startswith('https://'):
        if not a.catalog.startswith('https://raw.githubusercontent.com/WOOWTECH/Woow_HA_App_Store/'):raise SystemExit('Untrusted remote catalog host/repository')
        raw=fetch(a.catalog)
    else:raw=pathlib.Path(a.catalog).read_bytes()
    catalog=json.loads(raw)
    if catalog.get('schema')!=1 or digest(canonical(catalog['components']))!=catalog.get('catalog_id'):raise SystemExit('Catalog integrity check failed')
    if a.list:
        for cid,e in sorted(catalog['components'].items()):print(cid,e['version'],','.join(e['architectures']),e['delivery'])
        return
    if not a.addon or a.addon not in catalog['components']:raise SystemExit('Choose a published addon with --list')
    out=stage(catalog['components'][a.addon],a.destination,a.arch,a.source_build)
    print('Downloaded:',out)
    print('No addon was installed, started, uninstalled, or upgraded. New context boot policy: manual.')
    print('Published runtimes use a digest-pinned local wrapper, NOT source recompilation. Source-only addons build locally.')

if __name__=='__main__':main()
