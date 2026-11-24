#!/usr/bin/env python3
"""How an add-on in a Store directory is built from source, shared by upgrade_check (#144) and apk_pin_check (#228).

build_args(): the upgrade test rebuilds both images the way current Supervisor builds them (supervisor/apps/build.py,
_read_build_config, base_image and get_docker_args): the build file is build.yaml, .yml or .json next to config.yaml.
Without one, BUILD_FROM is not passed and the Dockerfile's own ARG BUILD_FROM default (or a FROM written out) is the
base. With one, BUILD_FROM is its build_from (a string, or one per arch), or ghcr.io/home-assistant/base:latest when
build_from is missing or empty. Dockerfile.<arch> when there is one, else Dockerfile.

base_image(): the image the Dockerfile's last stage starts from, with those build arguments. Order: BUILD_FROM when
passed, else the BUILD_FROM build argument's default, else the FROM as written.
"""
from __future__ import annotations
import json, pathlib, re
import yaml

BUILD_FILES=('build.yaml','build.yml','build.json')

def read_build_file(addon_dir):
    """(path of the add-on's build file or None, its mapping ({} without one)); ValueError when it is not a mapping."""
    root=pathlib.Path(addon_dir)
    found=[root/n for n in BUILD_FILES if (root/n).is_file()]
    if not found:return None,{}
    build=(json.loads if found[0].suffix=='.json' else yaml.safe_load)(found[0].read_text(encoding='utf-8')) or {}
    if not isinstance(build,dict):raise ValueError(f'{found[0].name} is not a mapping')
    return found[0],build

def build_args(addon_dir, version, arch='amd64'):
    """How Supervisor builds the add-on in `addon_dir` at `version` for `arch`: {'dockerfile': its path,
    'args': {build argument: value}}: BUILD_FROM (only with a build file), BUILD_VERSION, BUILD_ARCH and then the build
    file's args (module docstring)."""
    root=pathlib.Path(addon_dir)
    found,build=read_build_file(root)
    base=build.get('build_from')
    if found is None:base=None
    elif not base:base='ghcr.io/home-assistant/base:latest'
    elif isinstance(base,dict):
        if arch not in base:raise ValueError(f'{found.name} build_from has no base image for {arch}')
        base=base[arch]
    extra=build.get('args') or {}
    if not isinstance(extra,dict):raise ValueError(f'{found.name} args is not a mapping')
    args={**({'BUILD_FROM':base} if base is not None else {}),'BUILD_VERSION':version,'BUILD_ARCH':arch,**{str(k):v for k,v in extra.items()}}
    for k in args:
        # docker build --build-arg KEY=VALUE: a key that is empty or holds = or whitespace would become another argument.
        if not k or re.search(r'[=\s]',k):raise ValueError(f'build argument name {k!r} must be non-empty, without = or whitespace')
    for k,v in args.items():
        if not isinstance(v,(str,int,float)) or isinstance(v,bool) or re.search(r'[\x00-\x1f\x7f]',f'{k}={v}'):
            raise ValueError(f'build argument {k} must be one line of text, not {v!r}')
    args={k:str(v) for k,v in args.items()}
    dockerfile=root/f'Dockerfile.{arch}'
    if not dockerfile.is_file():dockerfile=root/'Dockerfile'
    if not dockerfile.is_file():raise ValueError(f'no Dockerfile (or Dockerfile.{arch}) in {root.as_posix()}')
    return {'dockerfile':dockerfile.as_posix(),'args':args}

# --- Dockerfile reading ----------------------------------------------------------------------------------------------

class Unresolved(ValueError):
    """A $VAR with no value where the build would need one."""

_VAR=re.compile(r'\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-+])([^}]*))?\}|([A-Za-z_][A-Za-z0-9_]*))')

def substitute(text, env):
    """`text` with $VAR, ${VAR}, ${VAR:-default}, ${VAR-default} and ${VAR:+alt} replaced from `env`; Unresolved names the
    first variable that has no value and no default. Any other ${...} form (a pattern, a $(...) command) is Unresolved too.
    Quoting is not known here: a $VAR in single quotes is expanded as well."""
    def one(m):
        name=m.group(1) or m.group(4);op=m.group(2)
        value=env.get(name)
        if op in (':-','-'):return value if value not in (None,'') or (op=='-' and value is not None) else substitute(m.group(3),env)
        if op in (':+','+'):return substitute(m.group(3),env) if value not in (None,'') or (op=='+' and value is not None) else ''
        if value is None:raise Unresolved(f'${name} has no value')
        return value
    out=_VAR.sub(one,text)
    # A $ before a name, { or ( that is still there is a form this does not expand; any other $ is literal, as in sh.
    if re.search(r'\$[A-Za-z_{(]',out):raise Unresolved(f'cannot expand {text!r}')
    return out

def instructions(text):
    """[(line number, INSTRUCTION, arguments)] of a Dockerfile: comment lines dropped, backslash continuations joined
    (a comment line inside a continuation is dropped, as Docker does)."""
    out=[];current=None
    for no,line in enumerate(text.splitlines(),1):
        stripped=line.strip()
        if current is None:
            if not stripped or stripped.startswith('#'):continue
            current=[no,[]]
        elif stripped.startswith('#'):continue
        if line.rstrip().endswith('\\'):
            current[1].append(line.rstrip()[:-1]);continue
        current[1].append(line)
        joined=' '.join(p.strip() for p in current[1]).strip()
        word,_,rest=joined.partition(' ')
        out.append((current[0],word.upper(),rest.strip()));current=None
    if current:
        joined=' '.join(p.strip() for p in current[1]).strip();word,_,rest=joined.partition(' ')
        out.append((current[0],word.upper(),rest.strip()))
    return out

def _assignments(rest, instr):
    """ARG/ENV arguments as [(name, raw value or None)]."""
    import shlex
    if instr=='ENV' and '=' not in rest.split(' ',1)[0]:
        name,_,value=rest.partition(' ');return [(name,' '.join(shlex.split(value)) if value.strip() else '')]
    out=[]
    for word in shlex.split(rest):
        name,eq,value=word.partition('=');out.append((name,value if eq else None))
    return out

def stages(text, args):
    """The Dockerfile's stages with `args` (build arguments) applied, in order: [{'name', 'line', 'from' (as written),
    'parent' (index of the stage it starts from, or None), 'image' (resolved image, or None when parent is set),
    'instructions': [(line, INSTRUCTION, arguments, for a RUN the {variable: value} its shell sees, else None)],
    'env': {variable: value} before its first instruction, 'final_env': after its last}].
    Global ARGs (before the first FROM) and build arguments resolve FROM; a stage sees build arguments only for the
    ARGs it declares, and inherits its parent stage's ENV. Unresolved when a FROM cannot be resolved."""
    globals_={};out=[];names={}
    for line,instr,rest in instructions(text):
        if instr=='FROM':
            words=[w for w in rest.split() if not w.startswith('--')]
            raw=words[0];name=words[2].lower() if len(words)>2 and words[1].upper()=='AS' else None
            ref=substitute(raw,globals_)
            parent=names.get(ref.lower())
            stage={'name':name,'line':line,'from':raw,'parent':parent,'image':None if parent is not None else ref,'instructions':[],
                   'env':dict(out[parent]['final_env']) if parent is not None else {}}
            stage['final_env']=dict(stage['env'])
            out.append(stage)
            if name:names[name]=len(out)-1
            continue
        if not out:
            if instr=='ARG':
                for name,value in _assignments(rest,'ARG'):
                    globals_[name]=args[name] if name in args else (substitute(value,globals_) if value is not None else None)
            continue
        stage=out[-1];stage['instructions'].append((line,instr,rest,dict(stage['final_env']) if instr=='RUN' else None))
        if instr in ('ARG','ENV'):
            for name,value in _assignments(rest,instr):
                env=stage['final_env']
                if instr=='ARG' and name in args:env[name]=args[name]
                elif value is None:
                    if globals_.get(name) is not None:env[name]=globals_[name]
                else:
                    try:env[name]=substitute(value,env)
                    except Unresolved:env.pop(name,None)
    return out

def base_image(addon_dir, arch, version='0'):
    """(Dockerfile path, the image its last stage starts from for `arch`, the stage chain from that image to the last
    stage as indexes into stages(), the stages, the build arguments), resolved the way Supervisor builds the add-on
    (module docstring). ValueError (Unresolved included) when that cannot be worked out."""
    spec=build_args(addon_dir,version,arch)
    args=dict(spec['args'])
    text=pathlib.Path(spec['dockerfile']).read_text(encoding='utf-8')
    all_stages=stages(text,args)
    if not all_stages:raise ValueError(f'{pathlib.Path(spec["dockerfile"]).name} has no FROM')
    chain=[len(all_stages)-1]
    while all_stages[chain[0]]['parent'] is not None:chain.insert(0,all_stages[chain[0]]['parent'])
    return spec['dockerfile'],all_stages[chain[0]]['image'],chain,all_stages,args
