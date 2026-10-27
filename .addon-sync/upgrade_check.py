#!/usr/bin/env python3
"""Compare an add-on's new config.yaml with the version users run now (pipeline #89).

Category 1 (configuration compatibility): every breaking change between the
comparison target and the new config must be declared in the add-on's
upgrade-notes.yaml, or the check blocks. No network, no Docker: the reusable
workflow woow-addon-upgrade-check.yml fetches the inputs and calls this.

Breaking changes (`change`, and the `key` it is reported under):
  option-removed      schema key that had an options default removed     schema path, e.g. database.port
  schema-removed      schema key without an options default removed      schema path
  schema-retyped      type or structure changed (a changed match() pattern counts)
  made-required       `type?` became `type`
  range-narrowed      int/float/str bound added, raised (min) or lowered (max)
  enum-value-removed  a list(a|b) value removed
  required-added      new required key with no options default (null is no default; list items have none)
  arch-removed        an arch value removed                              the arch, e.g. aarch64
  port-removed        a container port/protocol removed or changed       the port, e.g. 8069/tcp
  image-changed       `image` changed, added or removed                  image
Report only: default-changed, host-port-changed. Silent: widened ranges, added enum
values, required made optional, added optional keys, added keys with a default.

upgrade-notes.yaml, next to config.yaml, created only when needed:
  "1.3.0":                       # quoted version; only (comparison target, new version] counts
    breaking:
      - change: option-removed   # same change and key as the report
        key: ssl_port
        migration: Use the 443/tcp port mapping instead.   # must not be empty
    accepted_vulnerabilities:    # category 4 (#118): id, package, reason
"""
from __future__ import annotations
import argparse, json, os, pathlib, re, sys
import yaml
from packaging.version import InvalidVersion, Version

RANGED={'int','float','str'}

def parse_type(text):
    """(name, argument or None, optional) for a Supervisor schema type such as `int(0,16)?` or `list(a|b)`."""
    text=str(text).strip();optional=text.endswith('?');text=text[:-1] if optional else text
    if '(' in text and text.endswith(')'):name,arg=text[:-1].split('(',1);return name,arg,optional
    return text,None,optional

def _bounds(arg):
    if arg is None:return None,None
    lo,_,hi=arg.partition(',');num=lambda v:float(v) if v.strip() else None
    return num(lo),num(hi)

def _scalar(old, new, path, out):
    (on,oa,oo),(nn,na,no)=parse_type(old),parse_type(new)
    if on!=nn:out.append(('schema-retyped',path));return
    if oo and not no:out.append(('made-required',path))
    if on=='list' and oa is not None and na is not None:
        if set(oa.split('|'))-set(na.split('|')):out.append(('enum-value-removed',path))
    elif on in RANGED:
        (olo,ohi),(nlo,nhi)=_bounds(oa),_bounds(na)
        if (nlo is not None and (olo is None or nlo>olo)) or (nhi is not None and (ohi is None or nhi<ohi)):out.append(('range-narrowed',path))
    elif oa!=na:out.append(('schema-retyped',path))

def _kind(node):return 'map' if isinstance(node,dict) else 'list' if isinstance(node,list) else 'scalar'
def _sub(opts, key):
    v=opts.get(key) if isinstance(opts,dict) else None
    return v if isinstance(v,dict) else {}

def _added(node, opts, key, path, out):
    """A key only the new schema has breaks old settings when it is required and options gives no usable default (null is none)."""
    kind=_kind(node);has_default=isinstance(opts,dict) and opts.get(key) is not None
    if kind=='map':
        for k,v in node.items():_added(v,_sub(opts,key),k,path+'.'+k,out)
    elif kind=='list':
        if not has_default:out.append(('required-added',path))
    elif not parse_type(node)[2] and not has_default:out.append(('required-added',path))

def _node(old, new, old_opts, new_opts, path, out):
    """Compare one schema node; `*_opts` are the options mapping at the same level (empty inside list items)."""
    if _kind(old)!=_kind(new):out.append(('schema-retyped',path));return
    if _kind(old)=='scalar':_scalar(old,new,path,out)
    elif _kind(old)=='list':
        if old and new:_node(old[0],new[0],{},{},path,out)
    else:_keys(old,new,old_opts,new_opts,path+'.',out)

def _keys(old, new, old_opts, new_opts, prefix, out):
    for key in old:
        p=prefix+key
        if key not in new:out.append(('option-removed' if isinstance(old_opts,dict) and key in old_opts else 'schema-removed',p))
        else:_node(old[key],new[key],_sub(old_opts,key),_sub(new_opts,key),p,out)
    for key in new:
        if key not in old:_added(new[key],new_opts,key,prefix+key,out)

def _defaults(old_opts, new_opts, schema, prefix, out):
    """Changed or dropped option defaults of keys the new schema keeps (report only)."""
    for key,value in old_opts.items():
        if isinstance(schema,dict) and key not in schema and schema:continue
        if key not in new_opts:out.append(('default-changed',prefix+key,f'{value!r} → no default'))
        elif isinstance(value,dict) and isinstance(new_opts[key],dict):_defaults(value,new_opts[key],schema.get(key) if isinstance(schema,dict) else None,prefix+key+'.',out)
        elif new_opts[key]!=value:out.append(('default-changed',prefix+key,f'{value!r} → {new_opts[key]!r}'))

def category1(old, new):
    """(breaking [(change, key)], notices [(change, key, detail)]) between two parsed config.yaml files."""
    found=[];notices=[]
    old_opts,new_opts=old.get('options') or {},new.get('options') or {}
    _keys(old.get('schema') or {},new.get('schema') or {},old_opts,new_opts,'',found)
    _defaults(old_opts,new_opts,new.get('schema') or {},'',notices)
    found+=[('arch-removed',str(a)) for a in old.get('arch') or [] if a not in (new.get('arch') or [])]
    # A port is its container side and protocol; changing either removes the port users mapped.
    old_ports,new_ports=old.get('ports') or {},new.get('ports') or {}
    for port,host in old_ports.items():
        if port not in new_ports:found.append(('port-removed',str(port)))
        elif new_ports[port]!=host:notices.append(('host-port-changed',str(port),f'{host} → {new_ports[port]}'))
    if old.get('image')!=new.get('image'):found.append(('image-changed','image'))
    return found,notices

def version_cmp(a, b):
    """-1, 0 or 1. PEP 440 where possible, else the leading dotted number (nginxpm `2.12.4-v2`); an ambiguous pair is an error."""
    if a==b:return 0
    try:x,y=Version(a),Version(b)
    except InvalidVersion:
        m,n=re.match(r'^(\d+(?:\.\d+)*)',a),re.match(r'^(\d+(?:\.\d+)*)',b)
        if not m or not n:raise ValueError(f'cannot order versions {a!r} and {b!r}')
        x,y=tuple(map(int,m[1].split('.'))),tuple(map(int,n[1].split('.')))
        if x==y:raise ValueError(f'cannot order versions {a!r} and {b!r}')
    return -1 if x<y else 1

SECTIONS={'breaking':('change','key','migration'),'accepted_vulnerabilities':('id','package','reason')}

def declarations(notes, after, upto):
    """Entries of upgrade-notes.yaml whose version is in (after, upto]; `after` None means every version up to `upto`.

    Returns {section: [entry + {'version'}]}. A malformed file raises ValueError (the check fails, it does not pass).
    Shared with the Release-notes mode (#119)."""
    out={k:[] for k in SECTIONS}
    if notes is None:return out
    if not isinstance(notes,dict):raise ValueError('upgrade-notes.yaml must map versions to sections')
    for version,body in notes.items():
        if not isinstance(version,str):raise ValueError(f'version key {version!r} must be a quoted string, e.g. "{version}"')
        if not isinstance(body,dict):raise ValueError(f'{version}: must be a mapping of sections')
        for section,entries in body.items():
            if section not in SECTIONS:raise ValueError(f'{version}: unknown section {section!r} (expected {", ".join(SECTIONS)})')
            if not isinstance(entries,list):raise ValueError(f'{version}.{section}: must be a list')
            for e in entries:
                if not isinstance(e,dict) or any(k not in e for k in SECTIONS[section][:2]):raise ValueError(f'{version}.{section}: every entry needs {" and ".join(SECTIONS[section][:2])}')
        if version_cmp(version,upto)>0 or (after is not None and version_cmp(version,after)<=0):continue
        for section,entries in body.items():out[section]+=[dict(e,version=version) for e in entries]
    return out

def _paste(version, items):
    return '\n'.join([f'"{version}":','  breaking:']+[f'    - change: {i["change"]}\n      key: {i["key"]}\n      migration: ' for i in items])

def compare(old, new, old_version, new_version, notes=None, old_scan=None, new_scan=None, name=None, notes_path='upgrade-notes.yaml'):
    """Judge one add-on.

    `old`/`new`: parsed config.yaml; `old` is None when there is no comparison target (first release).
    `notes`: parsed upgrade-notes.yaml or None. `old_scan`/`new_scan`: Grype JSON for category 4 (#118), None = not scanned.
    Returns blocked, breaking [{change, key, declared}], notices, unmatched declarations, problems, and a Markdown report."""
    if old_scan is not None or new_scan is not None:raise ValueError('vulnerability comparison is not implemented yet (#118)')
    name=name or new.get('slug') or 'add-on'
    declared=declarations(notes,old_version,new_version)['breaking']
    if old is None:
        report=[f'### {name} {new_version}','','**Passed**: no comparison target (no earlier formal Release), so there is nothing to compare.']
        return {'blocked':False,'breaking':[],'notices':[],'unmatched':[],'problems':[],'report':'\n'.join(report)+'\n'}
    found,notes_only=category1(old,new)
    problems=[f'{d["version"]}: {d["change"]} {d["key"]} has no migration' for d in declared if not str(d.get('migration') or '').strip()]
    valid={(d['change'],d['key']):d for d in declared if str(d.get('migration') or '').strip()}
    breaking=[{'change':c,'key':k,'declared':(c,k) in valid} for c,k in found]
    notices=[{'change':c,'key':k,'detail':d} for c,k,d in notes_only]
    unmatched=[{'change':d['change'],'key':d['key'],'version':d['version']} for d in declared if (d['change'],d['key']) not in set(found)]
    blocked=any(not b['declared'] for b in breaking) or bool(problems)
    r=[f'### {name} {old_version} → {new_version}','',('**Blocked**: undeclared breaking change or invalid declaration.' if blocked else '**Passed**.'),'']
    if breaking:
        r+=['Breaking changes (each needs an entry in `'+notes_path+'`):','','| change | key | declared | migration |','|---|---|---|---|']
        r+=[f'| `{b["change"]}` | `{b["key"]}` | {"yes" if b["declared"] else "**no**"} | {valid[(b["change"],b["key"])]["migration"].strip() if b["declared"] else ""} |' for b in breaking]
        missing=[b for b in breaking if not b['declared']]
        if missing:r+=['','Add to `'+notes_path+'` and write the migration:','','```yaml',_paste(new_version,missing),'```']
        r.append('')
    else:r+=['No breaking configuration changes.','']
    if notices:
        r+=['Report only (does not block):','','| change | key | detail |','|---|---|---|']+[f'| `{n["change"]}` | `{n["key"]}` | {n["detail"]} |' for n in notices]+['']
    if unmatched:
        r+=['Declarations with no matching change (check the spelling of `change` and `key`):','']+[f'- {u["version"]}: `{u["change"]}` `{u["key"]}`' for u in unmatched]+['']
    if problems:r+=['Invalid declarations:','']+[f'- {p}' for p in problems]+['']
    r.append('Vulnerability comparison: not run (no scan results).')
    return {'blocked':blocked,'breaking':breaking,'notices':notices,'unmatched':unmatched,'problems':problems,'report':'\n'.join(r)+'\n'}

def _load(path, kind):
    """Parsed YAML/JSON file, or None when `path` is not given or (for optional inputs) does not exist."""
    if not path:return None
    p=pathlib.Path(path)
    if kind=='optional' and not p.exists():return None
    text=p.read_text(encoding='utf-8')
    return json.loads(text) if kind=='json' else yaml.safe_load(text)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0]);sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('compare',help='judge one add-on and write the report')
    c.add_argument('--old',help="comparison target's config.yaml; omit when there is none")
    c.add_argument('--new',required=True,help='config.yaml of this PR');c.add_argument('--notes',help='upgrade-notes.yaml next to the new config.yaml (may be absent)')
    c.add_argument('--old-scan');c.add_argument('--new-scan');c.add_argument('--name');c.add_argument('--notes-path',default='upgrade-notes.yaml')
    c.add_argument('--summary',default=os.environ.get('GITHUB_STEP_SUMMARY'),help='Markdown file the report is appended to')
    a=p.parse_args(argv)
    try:
        old,new=_load(a.old,'yaml'),_load(a.new,'yaml')
        r=compare(old,new,old_version=str(old['version']) if old else None,new_version=str(new['version']),notes=_load(a.notes,'optional'),
            old_scan=_load(a.old_scan,'json'),new_scan=_load(a.new_scan,'json'),name=a.name,notes_path=a.notes_path)
    except (ValueError,KeyError,TypeError,OSError,yaml.YAMLError) as e:
        print(f'::error title=Upgrade comparison failed::{a.name or a.new}: {e}');return 2
    print(r['report'])
    if a.summary:
        with open(a.summary,'a',encoding='utf-8') as f:f.write(r['report']+'\n')
    for b in r['breaking']:
        if not b['declared']:print(f'::error title=Undeclared breaking change::{b["change"]} {b["key"]} — declare it in {a.notes_path}')
    for problem in r['problems']:print(f'::error title=Invalid declaration::{problem}')
    return 1 if r['blocked'] else 0

if __name__=='__main__':sys.exit(main())
