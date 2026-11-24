#!/usr/bin/env python3
"""Daily check that every shipped Alpine add-on can still install its apk packages (#228).

Alpine's stable branches keep only the newest revision of a package, so a Dockerfile pin such as nginx=1.30.6-r0 stops
installing once 1.30.7-r0 replaces it, and an install from source, a rebuild on the device or a CI build fails. The
`world` file of some base images (hassio-addons/base) pins packages the same way. This check finds that before a build
does.

Scope: the Store registry only, each enabled stable add-on the Store ships (store_enabled), in its Store directory
(store_path), for amd64 and aarch64 when its config.yaml lists them. For each add-on and arch:
  1. the base image, resolved as Supervisor builds it (addon_build.base_image, shared with upgrade_check);
  2. the packages of every `apk add` in the stages that build the final image (the last stage and the stages it starts
     from), and in the add-on's shell scripts those stages run (rootfs/build.sh), with $VARS from ARG and ENV;
  3. one `apk add --simulate` of all of them in the base image, which also resolves the base's /etc/apk/world, and
     `apk policy` for every version-constrained package, to show the version the repository has now.
A `sed` the Dockerfile runs on /etc/apk/world before installing is replayed first (woow-nginxproxymanager strips the
world pins that way).

Results per add-on and arch: pass, cannot-install, not-checked (an `apk add` the check cannot read: a variable
without a value, inside a conditional or loop, in another build stage with a pinned package; or a base image with no
apk), skipped (no Dockerfile, no `apk add`, not Alpine). Not-checked never fails the run.

`apk add --simulate` resolves dependencies only: it does not unpack packages, so a file conflict between a new package
and one in the base (python3-ndbm against an older python3, #241) passes here and still fails the build.

Commands: check (one arch; runs docker) writes the results as JSON; report merges them into the job summary and opens,
updates or closes one Store issue per add-on that cannot install (--dry-run prints the actions instead).
"""
from __future__ import annotations
import argparse, datetime, json, os, pathlib, re, shlex, subprocess, sys
import yaml
from addon_build import Unresolved, base_image, substitute
from addon_sync import Blocked, GitHub, markdown_cell, publishes_releases, workflow_command

ARCHES=('amd64','aarch64')
PLATFORM={'amd64':'linux/amd64','aarch64':'linux/arm64'}
APK_ARCH={'amd64':'x86_64','aarch64':'aarch64'}
PASS,FAIL,UNCHECKED,SKIPPED='pass','cannot install','not checked','skipped'
RESULTS=(PASS,FAIL,UNCHECKED,SKIPPED)
WORLD='/etc/apk/world'
FILE_CONFLICT_NOTE=('`apk add --simulate` resolves dependencies only. It does not unpack packages, so it does not detect file '
    'conflicts (a new package overwriting a file another installed package owns); a build can still fail that way.')

# --- apk package arguments -------------------------------------------------------------------------------------------

_SPEC=re.compile(r'(?P<name>!?[A-Za-z0-9_.+-][A-Za-z0-9_.+:-]*?)(?:(?P<op>>=|<=|=~|><|[<>=~])(?P<version>[^@\s]+))?(?:@(?P<tag>[A-Za-z0-9_.-]+))?')

def parse_spec(word):
    """{'name', 'op' ('' when unconstrained), 'version', 'tag', 'spec'} of an apk package argument; None when it is not one."""
    m=_SPEC.fullmatch(word)
    if not m:return None
    return {'name':m['name'],'op':m['op'] or '','version':m['version'] or '','tag':m['tag'] or '','spec':word}

def _fuzzy(version, wanted):
    """apk's ~ match: `version` is `wanted` or continues it at a component boundary (~3.14 takes 3.14.10-r2, not 3.140)."""
    return version==wanted or (version.startswith(wanted) and not version[len(wanted)].isdigit())

def satisfies(version, op, wanted):
    """True when `version` meets an = or ~ constraint; None for operators this check does not compare (apk still does)."""
    if op=='=':return version==wanted
    if op=='~':return _fuzzy(version,wanted)
    return None

# --- reading the build: Dockerfile RUN and the shell scripts it runs -------------------------------------------------

_OPS=set(';&|()<>\n')
_OPEN={'if','for','while','until','case','select'}
_CLOSE={'fi','done','esac'}
_MIDDLE={'then','else','elif','do','in','!','{','}'}
# apk options that take a value (apk 2 and 3); every other option is a flag.
_VALUED={'-X','--repository','-t','--virtual','-p','--root','--arch','--cache-dir','--keys-dir','--repositories-file',
    '--cache-max-age','--wait','--progress-fd','--from'}

def _lex(line):
    lex=shlex.shlex(line,posix=True,punctuation_chars=';&|()<>');lex.whitespace_split=True;lex.commenters=''
    return list(lex)

def _logical_lines(text):
    """[(first line number, text)] of a shell script: backslash continuations joined, comment-only lines dropped."""
    out=[];buf=[];start=None
    for no,line in enumerate(text.splitlines(),1):
        if not buf and line.strip().startswith('#'):continue
        if start is None:start=no
        if line.rstrip().endswith('\\'):buf.append(line.rstrip()[:-1]);continue
        buf.append(line);out.append((start,' '.join(p.strip() for p in buf)));buf=[];start=None
    if buf:out.append((start,' '.join(p.strip() for p in buf)))
    return out

def simple_commands(text, first_line=1, script=True):
    """[(line, words, depth, redirect targets, raw text)] for each simple command of shell `text`: depth > 0 inside if,
    for, while or case. A Dockerfile RUN (script=False) is one logical line."""
    lines=_logical_lines(text) if script else [(first_line,text)]
    out=[];depth=0
    for no,line in lines:
        try:tokens=_lex(line)
        except ValueError:out.append((no,None,depth,[],line.strip()));continue
        words=[];redirects=[];at_start=True;i=0
        def flush():
            if words:out.append((no,list(words),depth,list(redirects),line.strip()))
            words.clear();redirects.clear()
        while i<len(tokens):
            t=tokens[i]
            if t.startswith('#'):break  # an unquoted word starting with # comments out the rest of the line
            if set(t)<=_OPS:
                if '<' in t or '>' in t:
                    if words and words[-1].isdigit():words.pop()
                    if i+1<len(tokens):redirects.append(tokens[i+1]);i+=2;continue
                flush();at_start=True;i+=1;continue
            if at_start and t in _OPEN:depth+=1;i+=1;continue
            if at_start and t in _CLOSE:depth=max(0,depth-1);i+=1;continue
            if at_start and t in _MIDDLE:i+=1;continue
            words.append(t);at_start=False;i+=1
        flush()
    return out

def _expand(word, env):
    return substitute(word,env)

def _is_apk_add(words):
    """True when `words` run `apk add`, read without expanding anything."""
    try:return (apk_command(words,{},expand=False) or {}).get('applet')=='add'
    except ValueError:return False

def apk_command(words, env, expand=True):
    """For an `apk` simple command: {'applet', 'packages': [spec], 'repositories', 'upgrade'}; Unresolved or ValueError
    when its arguments cannot be read. None when `words` is not an apk command."""
    i=0
    while i<len(words) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*',words[i]):i+=1
    while i<len(words) and words[i] in ('sudo','command','exec'):i+=1
    if i>=len(words) or words[i].rsplit('/',1)[-1]!='apk':return None
    args=words[i+1:];applet=None;packages=[];repos=[];upgrade=False;j=0
    while j<len(args):
        a=args[j]
        if a.startswith('-'):
            name=a.split('=',1)[0]
            if name in _VALUED and '=' not in a:
                if j+1>=len(args):raise ValueError(f'{a} has no value')
                if name in ('-X','--repository'):repos.append(_expand(args[j+1],env))
                j+=2;continue
            if name in ('-X','--repository'):repos.append(_expand(a.split('=',1)[1],env))
            if name in ('-u','--upgrade'):upgrade=True
            j+=1;continue
        if applet is None:applet=a;j+=1;continue
        if not expand:j+=1;continue
        value=_expand(a,env)
        if any(c in value for c in '*?[]`'):raise ValueError(f'{a!r} is not a package name')
        for w in value.split():
            spec=parse_spec(w)
            if spec is None:raise ValueError(f'{w!r} is not a package name')
            packages.append(spec)
        j+=1
    return {'applet':applet,'packages':packages,'repositories':repos,'upgrade':upgrade}

_SHELLS={'sh','bash','ash','dash','.','source'}

def _runs(words):
    """The script a simple command runs, as [word]: its command word (/build.sh), or the first operand of sh, bash, . ..."""
    i=0
    while i<len(words) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*',words[i]):i+=1
    if i>=len(words):return []
    if words[i].rsplit('/',1)[-1] in _SHELLS:
        rest=[w for w in words[i+1:] if not w.startswith('-')]
        return rest[:1]
    return [words[i]]

def _script_file(root, word):
    """The add-on file a RUN word names as a shell script it runs (/build.sh: rootfs/build.sh), or None."""
    if not word.endswith('.sh'):return None
    rel=word.lstrip('/')
    for candidate in (root/'rootfs'/rel,root/rel):
        if rel and candidate.is_file():return candidate
    named=[p for p in root.rglob(pathlib.PurePosixPath(word).name) if p.is_file() and not {'test','tests'}&set(p.relative_to(root).parts)]
    return named[0] if len(named)==1 else None

def read_commands(root, text, env, file, first_line=1, script=True, seen=None):
    """What a RUN instruction or shell script installs. {'adds': [{'file', 'line', 'text', 'packages', 'repositories',
    'upgrade'}], 'unchecked': [{'file', 'line', 'text', 'reason'}], 'world_edits': [command], 'scripts': [file]}."""
    seen=set() if seen is None else seen
    out={'adds':[],'unchecked':[],'world_edits':[],'scripts':[]}
    env=dict(env)
    for line,words,depth,redirects,raw in simple_commands(text,first_line,script):
        where={'file':file,'line':line,'text':(shlex.join(words) if words else raw)[:300]}
        if words is None:
            if re.search(r'\bapk\b',raw):out['unchecked'].append(dict(where,reason='the shell line cannot be read'))
            continue
        if any(r.endswith(WORLD) for r in redirects):
            out['unchecked'].append(dict(where,reason=f'writes {WORLD} in a way the check does not replay'))
        if words[0].rsplit('/',1)[-1]=='sed' and any(w.endswith(WORLD) for w in words[1:]):
            try:out['world_edits'].append(shlex.join(_expand(w,env) for w in words))
            except Unresolved as e:out['unchecked'].append(dict(where,reason=f'edits {WORLD}: {e}'))
            continue
        # A script's own assignment (NAME=value alone) is visible to the commands after it; one in a branch is not known.
        if script and all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*',w) for w in words):
            for w in words:
                name,_,value=w.partition('=')
                try:
                    if depth:raise Unresolved(name)
                    env[name]=_expand(value,env)
                except Unresolved:env.pop(name,None)
            continue
        if depth and _is_apk_add(words):
            out['unchecked'].append(dict(where,reason='inside a conditional or loop'));continue
        try:apk=apk_command(words,env)
        except (Unresolved,ValueError) as e:
            out['unchecked'].append(dict(where,reason=str(e)));continue
        if apk is not None:
            if apk['applet']!='add':continue
            if apk['packages']:out['adds'].append(dict(where,packages=apk['packages'],repositories=apk['repositories'],upgrade=apk['upgrade']))
            continue
        for w in _runs(words):
            path=_script_file(root,w)
            if path is None or path in seen:continue
            seen.add(path);rel=path.relative_to(root).as_posix();out['scripts'].append(rel)
            sub=read_commands(root,path.read_text(encoding='utf-8',errors='replace'),env,rel,seen=seen)
            if depth:
                for add in sub['adds']:sub['unchecked'].append({k:add[k] for k in ('file','line','text')}|{'reason':f'{file} runs it inside a conditional or loop'})
                sub['adds']=[]
            for k in out:out[k]+=sub[k]
    return out

def _run_text(rest):
    """A RUN's shell command: exec form ["a", "b"] joined, flags such as --mount dropped."""
    rest=rest.strip()
    while rest.startswith('--'):rest=rest.split(None,1)[1] if ' ' in rest else ''
    if rest.startswith('['):
        try:return shlex.join(json.loads(rest))
        except (ValueError,TypeError):pass
    return rest

def collect(addon_dir, arch, version='0'):
    """What the build of the add-on in `addon_dir` for `arch` installs with apk (module docstring, steps 1 and 2)."""
    root=pathlib.Path(addon_dir)
    dockerfile,image,chain,all_stages,args=base_image(root,arch,version)
    name=pathlib.Path(dockerfile).name
    found={'adds':[],'unchecked':[],'world_edits':[],'scripts':[]}
    for index,stage in enumerate(all_stages):
        part={'adds':[],'unchecked':[],'world_edits':[],'scripts':[]}
        for line,instr,rest,env in stage['instructions']:
            if instr!='RUN':continue
            got=read_commands(root,_run_text(rest),env,name,line,script=False)
            for k in part:part[k]+=got[k]
        if index in chain:
            for k in found:found[k]+=part[k]
            continue
        # Another stage (a builder from its own image): only a pinned package there is worth naming.
        start=stage['image'] or f'stage {all_stages[stage["parent"]]["name"]}'
        for add in part['adds']:
            pins=[p['spec'] for p in add['packages'] if p['op']]
            if pins:found['unchecked'].append({k:add[k] for k in ('file','line','text')}|{'reason':f'build stage {stage["name"] or index} starts from {start}, which this check does not test'})
    return {'base':image,'dockerfile':name,**found}

# --- scope -----------------------------------------------------------------------------------------------------------

def shipped(registry):
    """[(repository, component)] of every add-on the Store ships: enabled, stable channel, not delisted (store_enabled).
    ValueError when the registry is not in the expected shape."""
    if not isinstance(registry,dict) or not isinstance(registry.get('providers'),dict):raise ValueError('registry has no providers mapping')
    out=[]
    for repo,provider in registry['providers'].items():
        comps=provider.get('components') if isinstance(provider,dict) else None
        if not isinstance(comps,list):raise ValueError(f'{repo}: components is not a list')
        for comp in comps:
            if not isinstance(comp,dict) or not comp.get('id') or not comp.get('store_path'):raise ValueError(f'{repo}: a component without id or store_path')
            if publishes_releases(comp) and comp.get('store_enabled',True):out.append((repo,comp))
    return out

def plan(registry, store, arches=ARCHES, only=None):
    """One row per shipped add-on and arch its config.yaml lists: {'id', 'arch', 'store_path', and collect()'s fields or
    a 'result' already decided (skipped, not checked)}."""
    rows=[]
    for repo,comp in shipped(registry):
        if only and comp['id'] not in only:continue
        root=pathlib.Path(store)/comp['store_path']
        config_path=root/comp.get('config_file','config.yaml')
        config=(json.loads if config_path.suffix=='.json' else yaml.safe_load)(config_path.read_text(encoding='utf-8')) or {}
        version=str(config.get('version','0'))
        for arch in [a for a in arches if a in (config.get('arch') or [])]:
            row={'id':comp['id'],'arch':arch,'store_path':comp['store_path'],'base':'','adds':[],'unchecked':[],'world_edits':[],'scripts':[]}
            rows.append(row)
            if not ((root/'Dockerfile').is_file() or (root/f'Dockerfile.{arch}').is_file()):
                row.update(result=SKIPPED,reason='no Dockerfile (installs the published image)');continue
            try:row.update(collect(root,arch,version))
            except (ValueError,OSError,yaml.YAMLError) as e:
                row.update(result=UNCHECKED,reason=f'base image not resolved: {e}');continue
            if not row['adds'] and not row['unchecked']:
                row.update(result=SKIPPED,reason='no apk add in the build')
    return rows

def pins(row):
    """Version-constrained packages of the row's apk adds, each once."""
    seen={}
    for add in row['adds']:
        for p in add['packages']:
            if p['op']:seen.setdefault(p['spec'],p)
    return list(seen.values())

# --- running apk in the base image -----------------------------------------------------------------------------------

def container_script(row, root=''):
    """The sh script that checks `row` in its base image: native (root '') or on a rootfs under `root` with the
    helper's apk (--root, --arch). Alpine: /etc/alpine-release, or an apk database (Docker Hardened Images have no
    alpine-release; their os-release gives the version)."""
    apk=f'apk --root {root} --arch {APK_ARCH[row["arch"]]}' if root else 'apk'
    names=sorted({p['name'].lstrip('!') for p in pins(row)}|{'$WORLD_PINS'})
    packages=[p['spec'] for add in row['adds'] for p in add['packages']]
    flags=['--simulate','--no-cache']+(['--upgrade'] if any(a['upgrade'] for a in row['adds']) else [])
    for repo in dict.fromkeys(r for a in row['adds'] for r in a['repositories']):flags+=['-X',shlex.quote(repo)]
    edits=[e.replace(WORLD,root+WORLD) for e in row['world_edits']]
    lines=['set -u',
        'echo @@ALPINE',
        f'cat {root}/etc/alpine-release 2>/dev/null || {{ [ -f {root}/lib/apk/db/installed ] && '
        f"{{ sed -n 's/^VERSION_ID=//p' {root}/etc/os-release 2>/dev/null | tr -d '\"'; echo unknown; }}; }} || {{ echo @@NOTALPINE; exit 0; }}",
        (f'[ -f {root}/lib/apk/db/installed ]' if root else
         f'[ -n "$(ls /sbin/apk /usr/sbin/apk /bin/apk /usr/bin/apk 2>/dev/null)" ]')+' || { echo @@NOAPK; exit 0; }',
        # The Dockerfile's edits of the world first: the world reported and checked is the one the build installs with.
        'echo @@EDITS']+[f'{e} || echo @@EDITFAILED {i}' for i,e in enumerate(edits)]+[
        f'echo @@WORLD; cat {root}{WORLD} 2>/dev/null',
        f"WORLD_PINS=$(sed -n 's/^\\([^<>=~ ]*\\)[<>=~].*$/\\1/p' {root}{WORLD} 2>/dev/null | tr '\\n' ' ')",
        'echo @@SIMULATE',
        f'{apk} add {" ".join(flags)} {" ".join(shlex.quote(p) for p in packages)} 2>&1; echo "@@EXIT $?"',
        'echo @@POLICY',
        f'{apk} policy --no-cache {" ".join(shlex.quote(n) if n!="$WORLD_PINS" else n for n in names)} 2>&1',
        'echo @@END']
    return '\n'.join(lines)+'\n'

def parse_output(text):
    """Sections of container_script()'s output: {'alpine': release or None, 'apk': bool, 'world': [lines], 'edit_failed',
    'exit', 'simulate', 'policy': {name: {'available': [versions], 'installed': [versions]}}, 'complete'}."""
    out={'alpine':None,'apk':True,'world':[],'edit_failed':[],'exit':None,'simulate':'','policy':{},
        'complete':any(m in text.splitlines() for m in ('@@END','@@NOTALPINE','@@NOAPK'))}
    section=None;sim=[];name=version=None
    for line in text.splitlines():
        if line=='@@ALPINE':section='alpine';continue
        if line=='@@NOTALPINE':out['alpine']=None;section=None;continue
        if line=='@@NOAPK':out['apk']=False;continue
        if line in ('@@WORLD','@@EDITS','@@SIMULATE','@@POLICY','@@END'):section=line[2:].lower();continue
        if line.startswith('@@EDITFAILED '):out['edit_failed'].append(int(line.split()[1]));continue
        if line.startswith('@@EXIT '):out['exit']=int(line.split()[1]);continue
        if section=='alpine' and line.strip():out['alpine']=out['alpine'] or line.strip()
        elif section=='world' and line.strip():out['world'].append(line.strip())
        elif section=='simulate':sim.append(line)
        elif section=='policy':
            m=re.fullmatch(r'(\S+) policy:',line)
            if m:name=m[1];out['policy'][name]={'available':[],'installed':[]};version=None;continue
            m=re.fullmatch(r'  (\S+):',line)
            if m and name:version=m[1];continue
            if line.startswith('    ') and name and version:
                kind='installed' if line.strip().endswith('lib/apk/db/installed') else 'available'
                if version not in out['policy'][name][kind]:out['policy'][name][kind].append(version)
    out['simulate']='\n'.join(sim).strip()
    return out

def world_pins(world):
    """Version-constrained entries of a world file's lines."""
    return [s for s in (parse_spec(w) for w in world) if s and s['op']]

def _unsatisfiable(text):
    """True when apk's output is only its answer that the packages cannot be installed: `unable to select packages` with
    every repository index read. An index it could not fetch or trust (apk 3 and 2.14 `WARNING: fetching`, apk 2.12
    `WARNING: Ignoring`) or any other ERROR (a database it could not open) is a tool error."""
    lines=text.splitlines()
    return ('ERROR: unable to select packages:' in lines and not any(re.match(r'WARNING: (fetching|Ignoring) ',l) for l in lines)
        and all(l=='ERROR: unable to select packages:' for l in lines if l.startswith('ERROR:')))

def evaluate(row, output):
    """The row with the result of container_script()'s parsed `output` (module docstring)."""
    row=dict(row)
    if not output['complete']:
        row.update(result=UNCHECKED,reason='the check did not finish in the base image',error=True);return row
    if output['alpine'] is None:row.update(result=SKIPPED,reason='not Alpine (no /etc/alpine-release)');return row
    row['alpine']=output['alpine']
    if not output['apk']:row.update(result=UNCHECKED,reason='the base image has no apk database');return row
    row['world']=output['world'];row['world_pins']=[p['spec'] for p in world_pins(output['world'])]
    stale=[]
    for p,where in [(p,'apk add') for p in pins(row)]+[(p,'base world') for p in world_pins(output['world'])]:
        if p['op'] not in ('=','~'):continue  # >=, <, a checksum pin (><): apk's own answer is the check
        policy=output['policy'].get(p['name'].lstrip('!'),{'available':[],'installed':[]})
        if not any(satisfies(v,p['op'],p['version']) for v in policy['available']):stale.append({'spec':p['spec'],'source':where,'available':policy['available'],'installed':policy['installed']})
    row['stale']=stale;row['apk_output']=output['simulate'];row['exit']=output['exit']
    if output['edit_failed']:row['unchecked']=row['unchecked']+[{'file':row['dockerfile'],'line':0,'text':row['world_edits'][i],'reason':f'replaying this edit of {WORLD} failed'} for i in output['edit_failed']]
    if output['exit']!=0 and not _unsatisfiable(output['simulate']):
        row.update(result=UNCHECKED,reason='apk add --simulate failed without a package answer',error=True)
    elif output['exit']!=0:row.update(result=FAIL,reason='apk add --simulate failed')
    elif row['unchecked']:row.update(result=UNCHECKED,reason='some apk add lines were not checked')
    else:row.update(result=PASS,reason='')
    return row

def _docker(args, timeout=1800, stdin_from=None):
    """Run docker with `args`; stdin_from: docker arguments whose output is piped into it (docker export)."""
    if stdin_from is None:return subprocess.run(['docker',*args],capture_output=True,text=True,timeout=timeout)
    with subprocess.Popen(['docker',*stdin_from],stdout=subprocess.PIPE) as source:
        r=subprocess.run(['docker',*args],stdin=source.stdout,capture_output=True,text=True,timeout=timeout)
        source.stdout.close()
    return r

HELPER='docker.io/library/alpine:3.24'

def run_rows(rows, arch, mode='native', docker=_docker):
    """Check each planned row of `arch` in its base image (module docstring, step 3); rows already decided pass through.
    native runs the base image itself; rootfs exports it and runs the helper image's apk with --root --arch (no qemu,
    for a host of another arch). Each image is pulled once and removed after its last row unless it was there before;
    one that was there before and was pulled for another arch than the host's is pulled back for the host's arch."""
    out=[];todo=[r for r in rows if 'result' not in r]
    last={r['base']:i for i,r in enumerate(todo)}
    pulled={}
    # An image is ours to remove only when no local image had its ID before: a digest-only copy counts, and removing
    # the tag the pull added would delete that copy too (docker rmi drops its digest reference), so the tag stays.
    local=set(docker(['images','--all','--quiet','--no-trunc']).stdout.split()) if todo else set()
    for i,row in enumerate(todo):
        image=row['base']
        if image not in pulled:
            had=docker(['image','inspect','--format','{{.Id}}',image]).returncode==0
            p=docker(['pull','--quiet','--platform',PLATFORM[arch],image])
            if p.returncode==0 and not had:had=docker(['image','inspect','--format','{{.Id}}',image]).stdout.strip() in local
            pulled[image]=(had,p)
        had,p=pulled[image]
        if p.returncode!=0:
            msg=(p.stderr or p.stdout).strip().splitlines()[-1:] or ['docker pull failed']
            missing='no matching manifest' in msg[0] or 'does not match the specified platform' in msg[0]
            out.append(dict(row,result=UNCHECKED,reason=(f'the base image has no {PLATFORM[arch]} variant' if missing else f'cannot pull the base image: {msg[0]}'),error=not missing))
        else:
            via=mode
            if mode=='native':
                r=docker(['run','--rm','--pull','never','--platform',PLATFORM[arch],'--user','0','--entrypoint','/bin/sh',image,'-c',container_script(row)])
                text=r.stdout+r.stderr
                # A base without sh or without apk (Docker Hardened Images): the helper's apk on its exported rootfs.
                if '@@ALPINE' not in text.splitlines() or '@@NOAPK' in text.splitlines():via='rootfs'
            if via=='rootfs':text=_on_rootfs(row,arch,image,docker)
            parsed=parse_output(text)
            done=evaluate(row,parsed)
            if via!=mode:done['via']='apk of the check on the exported image (the base has no sh or no apk)'
            if done.get('error'):done['reason']+=f': {text.strip()[-300:]}'
            out.append(done)
        if last[image]==i and p.returncode==0:
            if not had:docker(['rmi',image])
            elif PLATFORM[arch]!='linux/'+_host_platform():
                other=docker(['image','inspect','--format','{{.Id}}',image]).stdout.strip()
                if docker(['pull','--quiet','--platform','linux/'+_host_platform(),image]).returncode==0:
                    back=docker(['image','inspect','--format','{{.Id}}',image]).stdout.strip()
                    if other and back and other!=back:docker(['rmi',other])
    decided=[r for r in rows if 'result' in r]
    return decided+out

def _on_rootfs(row, arch, image, docker):
    """container_script()'s output for `row`, run by the helper image's apk on `image` exported to /r."""
    c=docker(['create','--platform',PLATFORM[arch],image,'/bin/true'])
    if c.returncode!=0:return c.stderr
    cid=c.stdout.strip()
    try:
        script='mkdir /r && tar -x -C /r -f - 2>/dev/null; '+container_script(row,'/r')
        r=docker(['run','-i','--rm','--platform','linux/'+_host_platform(),HELPER,'sh','-c',script],stdin_from=['export',cid])
        return r.stdout+r.stderr
    finally:docker(['rm','-f',cid])

def _host_platform():
    import platform
    return 'arm64' if platform.machine() in ('aarch64','arm64') else 'amd64'

# --- report ----------------------------------------------------------------------------------------------------------

def _pin_count(row):
    n=len(pins(row));w=len(row.get('world_pins') or [])
    return f'{n} + {w} in world' if w else str(n)

def _details(row):
    parts=[]
    if row.get('reason'):parts.append(row['reason'])
    if row.get('via'):parts.append(row['via'])
    for s in row.get('stale') or []:
        # A pass lists only the count of world pins behind the repository; a failure names each.
        if row.get('result')!=FAIL and s['source']=='base world':continue
        parts.append(f'{s["spec"]} ({s["source"]}): repository has {", ".join(s["available"]) or "none"}')
    if row.get('world_pins'):
        behind=sum(1 for s in row.get('stale') or [] if s['source']=='base world')
        parts.append(f'world pins checked: {len(row["world_pins"])}'+(f' ({behind} older than the repository)' if behind else ''))
    if row.get('world_edits'):parts.append('replayed world edit: '+'; '.join(f'`{e}`' for e in row['world_edits']))
    for u in row.get('unchecked') or []:parts.append(f'not checked, {u["file"]}:{u["line"]}: `{u["text"]}` ({u["reason"]})')
    return '<br>'.join(markdown_cell(p) for p in parts)

def summary(rows):
    """The job summary: one table row per add-on and arch, then the apk output of each that cannot install."""
    rows=sorted(rows,key=lambda r:(r['id'],ARCHES.index(r['arch'])))
    counts={k:sum(1 for r in rows if r['result']==k) for k in RESULTS}
    lines=['## apk pin check','',', '.join(f'{k}: {v}' for k,v in counts.items()),'',f'> {FILE_CONFLICT_NOTE}','',
        '| Add-on | Arch | Base | Pins | Result | Details |','|---|---|---|---|---|---|']
    for r in rows:
        base=f'`{r["base"]}`'+(f' (Alpine {r["alpine"]})' if r.get('alpine') else '') if r.get('base') else ''
        lines.append(f'| {r["id"]} | {r["arch"]} | {markdown_cell(base)} | {_pin_count(r)} | {r["result"]} | {_details(r)} |')
    for r in rows:
        if r['result']==FAIL:lines+=['',f'### {r["id"]} ({r["arch"]})','','```',r.get('apk_output','')[-4000:],'```']
    return '\n'.join(lines)+'\n'

# --- Store issues ----------------------------------------------------------------------------------------------------

def issue_title(cid):return f'apk pin check: {cid} cannot install its packages'
def _marker(cid):return f'<!-- apk-pin-check:{cid} -->'

def issue_body(cid, rows):
    """Issue text for add-on `cid`: package names, versions and apk's output only (the Store is public)."""
    lines=[_marker(cid),f'The daily apk pin check could not install the packages of **{cid}** in its base image.','']
    for r in sorted(rows,key=lambda r:ARCHES.index(r['arch'])):
        if r['result']!=FAIL:continue
        lines+=[f'### {r["arch"]}','',f'Base image: `{r["base"]}`'+(f' (Alpine {r["alpine"]})' if r.get('alpine') else ''),'']
        stale=r.get('stale') or []
        if stale:
            lines+=['| Pinned | From | Repository has now |','|---|---|---|']
            lines+=[f'| `{s["spec"]}` | {s["source"]} | {", ".join(s["available"]) or "none"} |' for s in stale]
            lines.append('')
        lines+=['`apk add --simulate` output:','','```',(r.get('apk_output') or '')[-4000:],'```','']
    lines+=['This issue is updated by each run while the problem stays, and closed when the check passes.',
        f'Note: {FILE_CONFLICT_NOTE}']
    return '\n'.join(lines)+'\n'

def open_issues(gh, repo):
    """{add-on id: issue} of this check's open issues in `repo`, found by the marker in the body or the title."""
    found={};page=1
    while True:
        batch=gh.api(repo,f'issues?state=open&per_page=100&page={page}')
        for issue in batch:
            if 'pull_request' in issue:continue
            m=re.search(r'<!-- apk-pin-check:(\S+) -->',issue.get('body') or '')
            cid=m[1] if m else (re.fullmatch(r'apk pin check: (\S+) cannot install its packages',issue.get('title') or '') or [None,None])[1]
            if cid:found.setdefault(cid,issue)
        if len(batch)<100:return found
        page+=1

def sync_issues(gh, repo, rows, today=None, dry_run=False):
    """Open, update or close one issue per add-on (module docstring). Only add-ons with rows are touched; one whose rows
    include a tool error keeps its issue as it is, and one is closed only when every row passes. Returns the actions as (action, add-on id, issue number or None)."""
    today=today or datetime.date.today().isoformat()
    by_id={}
    for r in rows:by_id.setdefault(r['id'],[]).append(r)
    existing=open_issues(gh,repo);actions=[]
    for cid,its in sorted(by_id.items()):
        issue=existing.get(cid)
        if any(r.get('error') for r in its):continue
        if any(r['result']==FAIL for r in its):
            body=issue_body(cid,its)
            if issue is None:
                actions.append(('open',cid,None))
                if not dry_run:gh.api(repo,'issues',{'title':issue_title(cid),'body':body},'POST')
            elif (issue.get('body') or '')!=body:
                actions.append(('update',cid,issue['number']))
                if not dry_run:gh.api(repo,f'issues/{issue["number"]}',{'body':body},'PATCH')
            else:actions.append(('unchanged',cid,issue['number']))
        elif issue is not None and all(r['result']==PASS for r in its):
            actions.append(('close',cid,issue['number']))
            if not dry_run:
                gh.api(repo,f'issues/{issue["number"]}/comments',{'body':f'The apk pin check passed on {today}: every package of {cid} installs again. Closing.'},'POST')
                gh.api(repo,f'issues/{issue["number"]}',{'state':'closed','state_reason':'completed'},'PATCH')
    return actions

# --- command line ----------------------------------------------------------------------------------------------------

def _check(a):
    try:
        registry=json.loads(pathlib.Path(a.registry).read_text(encoding='utf-8'))
        rows=plan(registry,a.store,(a.arch,),set(a.only.split(',')) if a.only else None)
    except (ValueError,OSError,yaml.YAMLError) as e:
        print(workflow_command('error','apk pin check',f'cannot read the Store: {e}'));return 2
    if a.only and not rows:
        print(workflow_command('error','apk pin check',f'{a.only}: no shipped add-on with that id lists {a.arch}'));return 2
    rows=run_rows(rows,a.arch,a.mode)
    pathlib.Path(a.out).write_text(json.dumps(rows,ensure_ascii=False,indent=1),encoding='utf-8')
    for r in rows:print(f'{r["id"]} {r["arch"]}: {r["result"]} {r.get("reason","")}')
    return 0

def _report(a):
    rows=[r for f in a.results for r in json.loads(pathlib.Path(f).read_text(encoding='utf-8'))]
    text=summary(rows);print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:f.write(text)
    status=0
    for r in rows:
        if r['result']==FAIL:print(workflow_command('error',f'{r["id"]} ({r["arch"]})','cannot install its apk packages'));status=1
        if r.get('error'):print(workflow_command('error',f'{r["id"]} ({r["arch"]})',r['reason']));status=1
    for r in rows:
        if r['result'] not in RESULTS:print(workflow_command('error',r['id'],f'unknown result {r["result"]}'));status=1
    if a.repo:
        try:
            for action,cid,number in sync_issues(GitHub(),a.repo,rows,dry_run=a.dry_run):
                print(('would ' if a.dry_run else '')+f'{action} issue for {cid}'+(f' (#{number})' if number else ''))
        except Blocked as e:
            print(workflow_command('error','apk pin check issues',str(e)));status=1
    return status

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0]);sub=p.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('check',help='check one arch with docker and write the rows as JSON')
    c.add_argument('--registry',default='.addon-sync/registry.json');c.add_argument('--store',default='.')
    c.add_argument('--arch',choices=ARCHES,required=True);c.add_argument('--mode',choices=('native','rootfs'),default='native')
    c.add_argument('--only',help='comma-separated add-on ids');c.add_argument('--out',required=True)
    r=sub.add_parser('report',help='job summary from check results; with --repo, open, update or close the Store issues')
    r.add_argument('results',nargs='+');r.add_argument('--repo');r.add_argument('--dry-run',action='store_true')
    a=p.parse_args(argv)
    return {'check':_check,'report':_report}[a.cmd](a)

if __name__=='__main__':sys.exit(main())
