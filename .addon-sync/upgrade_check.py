#!/usr/bin/env python3
"""Compare an add-on's new config.yaml with the version users run now (pipeline #89).

Category 1 (configuration compatibility): every breaking change between the
comparison target and the new config must be declared in the add-on's
upgrade-notes.yaml, or the check blocks.

Category 4 (vulnerabilities, add-ons with a prebuilt image): Grype JSON of the
old and new amd64 images, scanned with the same DB. A new fixable vulnerability,
matched by (vulnerability id, package): in the new image only, severity Critical
or High (any case), Grype fix.state `fixed`. It blocks unless accepted in
upgrade-notes.yaml with a reason. Already in the old image, no fixed version,
or below High: counted in the report only. No network, no Docker: the reusable
workflow woow-addon-upgrade-check.yml fetches the inputs and calls this.

Breaking changes (`change`, and the `key` it is reported under):
  option-removed      schema key that had an options default removed     schema path, e.g. database.port
  schema-removed      schema key without an options default removed      schema path
  schema-retyped      type or structure changed (a changed match() pattern counts)
  made-required       `type?` became `type`
  range-narrowed      int/float/str bound added, raised (min) or lowered (max)
  enum-value-removed  a list(a|b) value removed
  required-added      new required key with no options default (null is no default; list items have none; ["str?"] is optional)
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
    accepted_vulnerabilities:
      - id: CVE-2026-1234        # same id and package as the report
        package: openssl
        reason: Upstream base image not updated yet; replaced in 1.3.1.   # must not be empty

Release notes (#119): `release-notes` prints the declarations since the last formal Release as
two sections, 破壞性變更與遷移方式 and 已接受的漏洞, and nothing when there are none.
addon_sync.release (woow-addon-release.yml) and Woow_ha_odoo's release.yml put them on the Release.
"""
from __future__ import annotations
import argparse, functools, json, os, pathlib, re, secrets, sys
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
        # Supervisor _check_missing_options: a list is optional when its element is an optional scalar, e.g. ["str?"].
        optional=bool(node) and isinstance(node[0],str) and parse_type(node[0])[2]
        if not has_default and not optional:out.append(('required-added',path))
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

REBUILD=re.compile(r'^(\d+(?:\.\d+)*)(?:-v?(\d+))?$')

def version_cmp(a, b):
    """-1, 0 or 1. PEP 440 where possible (Woow_haos_ha_core `2026.9.1-1` is a post-release); else a dotted number with an
    optional rebuild suffix `-v<N>` or `-<N>` (nginxpm `2.12.4-v2` < `2.12.4-v3`; no suffix sorts first); else the leading
    dotted number alone. A pair that cannot be ordered is an error."""
    if a==b:return 0
    try:x,y=Version(a),Version(b)
    except InvalidVersion:
        m,n=REBUILD.match(a),REBUILD.match(b)
        if m and n:x,y=(tuple(map(int,m[1].split('.'))),int(m[2] or -1)),(tuple(map(int,n[1].split('.'))),int(n[2] or -1))
        else:
            m,n=re.match(r'^(\d+(?:\.\d+)*)',a),re.match(r'^(\d+(?:\.\d+)*)',b)
            if not m or not n:raise ValueError(f'cannot order versions {a!r} and {b!r}')
            x,y=tuple(map(int,m[1].split('.'))),tuple(map(int,n[1].split('.')))
        if x==y:raise ValueError(f'cannot order versions {a!r} and {b!r}')
    return -1 if x<y else 1

def _is_version(v):
    """True when version_cmp can read `v` (PEP 440, a dotted number with a rebuild suffix, or a leading dotted number)."""
    try:Version(v);return True
    except InvalidVersion:return bool(re.match(r'^\d+(?:\.\d+)*',v))

def latest_release(versions):
    """The newest of `versions` by version_cmp, or None; strings that are not versions (a stray `nightly` tag) are ignored.
    The PR check's comparison target and the Release notes' window both use this, so they cannot disagree."""
    found=[v for v in versions if _is_version(v)]
    return max(found,key=functools.cmp_to_key(version_cmp)) if found else None

def _text(entry, field):
    """A declaration's migration or reason, stripped; '' when it is missing or blank (the declaration then does not count)."""
    return str(entry.get(field) or '').strip()

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

RELEASE_SECTIONS=(('breaking','破壞性變更與遷移方式',lambda e:f'`{e["change"]}` `{e["key"]}`（{e["version"]}）','migration'),
    ('accepted_vulnerabilities','已接受的漏洞',lambda e:f'{e["id"]}（{e["package"]}，{e["version"]}）','reason'))

def release_notes(notes, version, released=()):
    """Markdown the Release of `version` adds to its notes; '' when nothing is declared.

    `released`: versions that already have a formal Release. Only sections after the newest of them below `version`
    count, the same (comparison target, new] range the PR check used, so a declaration appears on one Release only."""
    def below(v):
        try:return version_cmp(v,version)<0
        except ValueError:return False  # a tag that is not a version (or cannot be ordered) is not a Release of this add-on
    after=latest_release([v for v in released if v!=version and below(v)])
    found=declarations(notes,after,version);out=[]
    for section,title,label,text_key in RELEASE_SECTIONS:
        if not found[section]:continue
        lines=[]
        for e in found[section]:
            text=_text(e,text_key)
            if not text:raise ValueError(f'{e["version"]}.{section}: {label(e)} has no {text_key}')
            lines.append(f'- {label(e)}：'+text.replace('\n','\n  '))
        out.append(f'## {title}\n\n'+'\n'.join(lines)+'\n')
    return '\n'.join(out)

def _cell(value):
    """Text for a Markdown table cell: a | or a line break would end the cell or the row (as branch_rules.main does)."""
    return re.sub(r'\r\n|\r|\n','<br>',str(value).replace('|','\\|'))

def _paste(version, items):
    return '\n'.join([f'"{version}":','  breaking:']+[f'    - change: {i["change"]}\n      key: {i["key"]}\n      migration: ' for i in items])

BLOCKING_SEVERITIES={'critical','high'}

def _blocking(v):
    """Critical or High, in any case."""
    return str(v.get('severity','')).lower() in BLOCKING_SEVERITIES

def _fixable(v):
    """Grype has a fixed version (fix.state fixed)."""
    return (v.get('fix') or {}).get('state')=='fixed'

def _rank(m):
    """Sort key picking a pair's match: new fixable over Critical/High over the rest, then Critical, then a fixed tie-break."""
    v=m['vulnerability'];blocking=_blocking(v)
    return (blocking and _fixable(v),blocking,str(v.get('severity','')).lower()=='critical',json.dumps(m,sort_keys=True))

def _findings(scan):
    """{(vulnerability id, package): match} from Grype JSON; one entry per pair however many locations match."""
    if not isinstance(scan,dict) or not isinstance(scan.get('matches'),list):raise ValueError('scan result is not Grype JSON (no matches list)')
    out={}
    for m in scan['matches']:
        v,a=(m.get('vulnerability') or {},m.get('artifact') or {}) if isinstance(m,dict) else ({},{})
        if not v.get('id') or not a.get('name'):raise ValueError('Grype match without vulnerability.id or artifact.name')
        # Grype repeats a pair per location or package version: keep the most blocking match so the order cannot hide one.
        k=(v['id'],a['name'])
        if k not in out or _rank(m)>_rank(out[k]):out[k]=m
    return out

def _database(scan):
    """The DB a Grype scan used (Grype 0.120: descriptor.db.status), or None when the JSON does not say."""
    # A descriptor, db or status that is not a mapping says nothing either (ValueError in category4, not an AttributeError).
    def mapping(v):return v if isinstance(v,dict) else {}
    db=mapping(mapping(scan.get('descriptor')).get('db'))
    status=mapping(db.get('status')) or db
    found=(status.get('built'),status.get('from') or status.get('checksum'))
    return found if all(found) else None

def category4(old_scan, new_scan):
    """Counts and new fixable vulnerabilities: in the new image only, Critical/High, Grype fix.state fixed."""
    if old_scan is None or new_scan is None:raise ValueError('vulnerability comparison needs both the old and the new scan result')
    old,new=_findings(old_scan),_findings(new_scan)
    dbs=_database(old_scan),_database(new_scan)
    # Two scans without DB info would compare equal and pass, with no proof they used the same DB.
    if None in dbs:raise ValueError('scan result does not say which vulnerability database it used (descriptor.db.status built and from)')
    if dbs[0]!=dbs[1]:raise ValueError(f'old and new images were scanned with different vulnerability databases ({dbs[0]} vs {dbs[1]})')
    fixable=[];skipped={'in_old':0,'not_fixed':0,'low':0}
    for (vid,package),m in new.items():
        v=m['vulnerability'];fix=v.get('fix') or {}
        if (vid,package) in old:skipped['in_old']+=1;continue
        if not _blocking(v):skipped['low']+=1;continue
        if not _fixable(v):skipped['not_fixed']+=1;continue
        fixable.append({'id':vid,'package':package,'severity':v.get('severity'),'fixed_in':list(fix.get('versions') or []),'accepted':False})
    return {'old_count':len(old),'new_count':len(new),'new_fixable':fixable,'not_blocking':skipped}

def compare(old, new, old_version, new_version, notes=None, old_scan=None, new_scan=None, name=None, notes_path='upgrade-notes.yaml', scan_note='no scan results'):
    """Judge one add-on.

    `old`/`new`: parsed config.yaml; `old` is None when there is no comparison target (first release).
    `notes`: parsed upgrade-notes.yaml or None. `old_scan`/`new_scan`: Grype JSON for category 4 (#118), None = not scanned.
    `scan_note`: report text for why there are no scan results.
    Returns blocked, vulnerabilities (None when not scanned), breaking [{change, key, declared}], notices,
    unmatched declarations, problems, and a Markdown report."""
    name=name or new.get('slug') or 'add-on'
    sections=declarations(notes,old_version,new_version);declared,accepted=sections['breaking'],sections['accepted_vulnerabilities']
    # The Release notes (#119) publish every migration and reason and fail on an empty one, so check them here
    # with or without a comparison target or scan: the merge is the release approval (ADR-0005).
    problems=[f'{d["version"]}: {d["change"]} {d["key"]} has no migration' for d in declared if not _text(d,'migration')]
    problems+=[f'{d["version"]}: accepted {d["id"]} {d["package"]} has no reason' for d in accepted if not _text(d,'reason')]
    if old is None:
        report=[f'### {name} {new_version}','',('**Blocked**: invalid declaration; ' if problems else '**Passed**: ')+'no comparison target (no earlier formal Release), so there is nothing to compare.']
        if problems:report+=['','Invalid declarations:','']+[f'- {p}' for p in problems]
        return {'blocked':bool(problems),'vulnerabilities':None,'breaking':[],'notices':[],'unmatched':[],'problems':problems,'report':'\n'.join(report)+'\n'}
    found,notes_only=category1(old,new)
    valid={(d['change'],d['key']):d for d in declared if _text(d,'migration')}
    breaking=[{'change':c,'key':k,'declared':(c,k) in valid} for c,k in found]
    notices=[{'change':c,'key':k,'detail':d} for c,k,d in notes_only]
    unmatched=[{'change':d['change'],'key':d['key'],'version':d['version']} for d in declared if (d['change'],d['key']) not in set(found)]
    vulns=category4(old_scan,new_scan) if (old_scan,new_scan)!=(None,None) else None
    if vulns is not None:
        reasons={(d['id'],d['package']):_text(d,'reason') for d in accepted if _text(d,'reason')}
        for f in vulns['new_fixable']:
            f['accepted']=(f['id'],f['package']) in reasons
            if f['accepted']:f['reason']=reasons[(f['id'],f['package'])]
        listed={(f['id'],f['package']) for f in vulns['new_fixable']}
        vulns['unmatched_accepted']=[{'id':d['id'],'package':d['package'],'version':d['version']} for d in accepted if (d['id'],d['package']) not in listed]
    blocked=any(not b['declared'] for b in breaking) or bool(problems) or bool(vulns and any(not f['accepted'] for f in vulns['new_fixable']))
    r=[f'### {name} {old_version} → {new_version}','',('**Blocked**: undeclared breaking change, new fixable vulnerability, or invalid declaration.' if blocked else '**Passed**.'),'']
    if breaking:
        r+=['Breaking changes (each needs an entry in `'+notes_path+'`):','','| change | key | declared | migration |','|---|---|---|---|']
        r+=[f'| `{_cell(b["change"])}` | `{_cell(b["key"])}` | {"yes" if b["declared"] else "**no**"} | {_cell(_text(valid[(b["change"],b["key"])],"migration")) if b["declared"] else ""} |' for b in breaking]
        missing=[b for b in breaking if not b['declared']]
        if missing:r+=['','Add to `'+notes_path+'` and write the migration:','','```yaml',_paste(new_version,missing),'```']
        r.append('')
    else:r+=['No breaking configuration changes.','']
    if notices:
        r+=['Report only (does not block):','','| change | key | detail |','|---|---|---|']+[f'| `{n["change"]}` | `{_cell(n["key"])}` | {_cell(n["detail"])} |' for n in notices]+['']
    if unmatched:
        r+=['Declarations with no matching change (check the spelling of `change` and `key`):','']+[f'- {u["version"]}: `{u["change"]}` `{u["key"]}`' for u in unmatched]+['']
    if problems:r+=['Invalid declarations:','']+[f'- {p}' for p in problems]+['']
    if vulns is None:r.append(f'Vulnerability comparison: not run ({scan_note}).')
    else:
        r+=[f'Vulnerabilities (Grype, amd64): {vulns["old_count"]} in {old_version}, {vulns["new_count"]} in {new_version}.','']
        if vulns['new_fixable']:
            r+=['New fixable vulnerabilities (Critical/High with a fixed version, not in '+old_version+'; each blocks unless accepted in `'+notes_path+'`):','',
                '| id | package | severity | fixed in | accepted |','|---|---|---|---|---|']
            r+=[f'| {_cell(f["id"])} | {_cell(f["package"])} | {_cell(f["severity"])} | {_cell(", ".join(f["fixed_in"]))} | {_cell(f["reason"]) if f["accepted"] else "**no**"} |' for f in vulns['new_fixable']]+['']
        else:r+=['No new fixable vulnerabilities.','']
        n=vulns['not_blocking']
        if vulns['unmatched_accepted']:
            r+=['Accepted vulnerabilities that are not new fixable ones (check `id` and `package`):','']+[f'- {d["version"]}: {d["id"]} {d["package"]}' for d in vulns['unmatched_accepted']]+['']
        r.append(f'Report only (does not block): {n["in_old"]} already in {old_version}, {n["not_fixed"]} new with no fixed version, {n["low"]} new below High.')
    return {'blocked':blocked,'vulnerabilities':vulns,'breaking':breaking,'notices':notices,'unmatched':unmatched,'problems':problems,'report':'\n'.join(r)+'\n'}

def _load(path, kind):
    """Parsed YAML/JSON file, or None when `path` is not given or (for optional inputs) does not exist."""
    if not path:return None
    p=pathlib.Path(path)
    if kind=='optional' and not p.exists():return None
    text=p.read_text(encoding='utf-8')
    return json.loads(text) if kind=='json' else yaml.safe_load(text)

def _error(title, message):
    """An ::error workflow command; PR-controlled text is escaped the way branch_rules does (addon_sync.annotation)."""
    from addon_sync import annotation  # addon_sync imports this module, so import it here, not at the top
    print('::error title='+annotation(title).replace(':','%3A').replace(',','%2C')+'::'+annotation(message))

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0]);sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('compare',help='judge one add-on and write the report')
    c.add_argument('--old',help="comparison target's config.yaml; omit when there is none")
    c.add_argument('--new',required=True,help='config.yaml of this PR');c.add_argument('--notes',help='upgrade-notes.yaml next to the new config.yaml (may be absent)')
    c.add_argument('--old-scan');c.add_argument('--new-scan');c.add_argument('--name');c.add_argument('--notes-path',default='upgrade-notes.yaml')
    c.add_argument('--scan-note',default='no scan results',help='why there are no scan results (report text)')
    c.add_argument('--summary',default=os.environ.get('GITHUB_STEP_SUMMARY'),help='Markdown file the report is appended to')
    n=sub.add_parser('release-notes',help="print the Release-notes sections for a version's declarations ('' when none)")
    n.add_argument('--notes',required=True,help='upgrade-notes.yaml at the released commit (may be absent)')
    n.add_argument('--version',required=True,help='version being released')
    n.add_argument('--released',nargs='*',default=[],help='versions that already have a formal Release')
    t=sub.add_parser('latest-release',help="read the repository's Releases (GitHub API JSON array) on stdin, print the tag of the add-on's latest formal Release (nothing when none)")
    t.add_argument('--registry',required=True,help='Store registry.json');t.add_argument('--repo',required=True,help='source repository, owner/name')
    t.add_argument('--component',required=True,help='add-on id in the registry')
    a=p.parse_args(argv)
    if a.command=='latest-release':
        # The Release filter and tag rule are addon_sync's, so the PR check and the Release notes agree; addon_sync imports this module.
        from addon_sync import formal_versions, release_tag
        try:
            provider=_load(a.registry,'json')['providers'][a.repo]
            comp=next((c for c in provider['components'] if c['id']==a.component),None)
            if comp is None:raise KeyError(f'no component {a.component}')
            releases=json.load(sys.stdin)
            if not isinstance(releases,list):raise ValueError('stdin is not a JSON array of Releases')
            latest=latest_release(formal_versions(releases,release_tag(provider,comp,'')))
        except (ValueError,KeyError,TypeError,AttributeError,OSError) as e:
            _error('Upgrade comparison failed',f'Releases of {a.repo} {a.component}: {e}');return 2
        if latest is not None:print(release_tag(provider,comp,latest))
        return 0
    if a.command=='release-notes':
        try:text=release_notes(_load(a.notes,'optional'),a.version,a.released)
        except (ValueError,TypeError,OSError,yaml.YAMLError) as e:
            _error('Release notes failed',f'{a.notes}: {e}');return 2
        print(text,end='');return 0
    try:
        old,new=_load(a.old,'yaml'),_load(a.new,'yaml')
        r=compare(old,new,old_version=str(old['version']) if old else None,new_version=str(new['version']),notes=_load(a.notes,'optional'),
            old_scan=_load(a.old_scan,'json'),new_scan=_load(a.new_scan,'json'),name=a.name,notes_path=a.notes_path,scan_note=a.scan_note)
    except (ValueError,KeyError,TypeError,OSError,yaml.YAMLError) as e:
        _error('Upgrade comparison failed',f'{a.name or a.new}: {e}');return 2
    # The report quotes PR text; GitHub must not read a line of it as a workflow command.
    token=secrets.token_hex(16);print('::stop-commands::'+token);print(r['report']);print('::'+token+'::')
    if a.summary:
        with open(a.summary,'a',encoding='utf-8') as f:f.write(r['report']+'\n')
    for b in r['breaking']:
        if not b['declared']:_error('Undeclared breaking change',f'{b["change"]} {b["key"]} — declare it in {a.notes_path}')
    for f in (r.get('vulnerabilities') or {}).get('new_fixable',[]):
        if not f['accepted']:_error('New fixable vulnerability',f'{f["id"]} {f["package"]} ({f["severity"]}, fixed in {", ".join(f["fixed_in"])}) — upgrade the package or accept it in {a.notes_path}')
    for problem in r['problems']:_error('Invalid declaration',problem)
    return 1 if r['blocked'] else 0

if __name__=='__main__':sys.exit(main())
