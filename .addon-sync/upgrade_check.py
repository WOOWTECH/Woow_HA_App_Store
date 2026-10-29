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
                      a new map is required even when every sub-key is optional ({} is a default); its sub-keys are still compared
  arch-removed        an arch value removed                              the arch, e.g. aarch64
  port-removed        a container port/protocol removed or changed       the port, e.g. 8069/tcp
  image-changed       `image` changed, added or removed                  image
Report only: default-changed, host-port-changed. Silent: widened ranges, added enum
values, required made optional, added optional keys (not maps), added keys with a default.

upgrade-notes.yaml format, version order and Release notes (#119): addon_sync, the comment above REBUILD.
"""
from __future__ import annotations
import argparse, contextlib, json, os, pathlib, secrets, sys
import yaml
# addon_sync owns the Release rules (version order, upgrade-notes.yaml parsing, Release notes); it does not import this module.
from addon_sync import Blocked, comparison_target, config_version, declaration_text, declarations, find_component, find_provider, locations, markdown_cell, publishes_releases, release_notes, release_tag, require_newer, source_file, stable_versions, version_cmp, workflow_command

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
        # Supervisor _check_missing_options: a missing map is "Missing option" even when every sub-key is optional.
        if not has_default:out.append(('required-added',path))
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

def _paste(version, items):
    return '\n'.join([f'"{version}":','  breaking:']+[f'    - change: {i["change"]}\n      key: {i["key"]}\n      migration: ' for i in items])

BLOCKING_SEVERITIES={'critical','high'}

def _severity(v):
    """Grype's severity in lower case: it is compared in any case."""
    return str(v.get('severity','')).lower()

def _blocking(v):
    """Critical or High, in any case."""
    return _severity(v) in BLOCKING_SEVERITIES

def _fixable(v):
    """Grype has a fixed version (fix.state fixed)."""
    return (v.get('fix') or {}).get('state')=='fixed'

def _rank(m):
    """Sort key picking a pair's match: new fixable over Critical/High over the rest, then Critical, then a fixed tie-break."""
    v=m['vulnerability'];blocking=_blocking(v)
    return (blocking and _fixable(v),blocking,_severity(v)=='critical',json.dumps(m,sort_keys=True))

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
    ValueError unless new_version is newer than old_version (addon_sync.require_newer; the plan step already checked, check_target).
    Returns blocked, vulnerabilities (None when not scanned), breaking [{change, key, declared}], notices,
    unmatched declarations, problems, and a Markdown report (_first_report, _report)."""
    name=name or new.get('slug') or 'add-on'
    if old is not None:require_newer(new_version,old_version)
    sections=declarations(notes,old_version,new_version);declared,accepted=sections['breaking'],sections['accepted_vulnerabilities']
    # The Release notes (#119) publish every migration and reason and fail on an empty one, so check them here
    # with or without a comparison target or scan: the merge is the release approval (ADR-0005).
    problems=[f'{d["version"]}: {d["change"]} {d["key"]} has no migration' for d in declared if not declaration_text(d,'migration')]
    problems+=[f'{d["version"]}: accepted {d["id"]} {d["package"]} has no reason' for d in accepted if not declaration_text(d,'reason')]
    if old is None:
        return {'blocked':bool(problems),'vulnerabilities':None,'breaking':[],'notices':[],'unmatched':[],'problems':problems,'report':_first_report(name,new_version,problems)}
    found,notes_only=category1(old,new)
    migrations={(d['change'],d['key']):declaration_text(d,'migration') for d in declared if declaration_text(d,'migration')}
    breaking=[{'change':c,'key':k,'declared':(c,k) in migrations} for c,k in found]
    notices=[{'change':c,'key':k,'detail':d} for c,k,d in notes_only]
    unmatched=[{'change':d['change'],'key':d['key'],'version':d['version']} for d in declared if (d['change'],d['key']) not in set(found)]
    vulns=category4(old_scan,new_scan) if (old_scan,new_scan)!=(None,None) else None
    if vulns is not None:
        reasons={(d['id'],d['package']):declaration_text(d,'reason') for d in accepted if declaration_text(d,'reason')}
        for f in vulns['new_fixable']:
            f['accepted']=(f['id'],f['package']) in reasons
            if f['accepted']:f['reason']=reasons[(f['id'],f['package'])]
        listed={(f['id'],f['package']) for f in vulns['new_fixable']}
        vulns['unmatched_accepted']=[{'id':d['id'],'package':d['package'],'version':d['version']} for d in accepted if (d['id'],d['package']) not in listed]
    blocked=any(not b['declared'] for b in breaking) or bool(problems) or bool(vulns and any(not f['accepted'] for f in vulns['new_fixable']))
    result={'blocked':blocked,'vulnerabilities':vulns,'breaking':breaking,'notices':notices,'unmatched':unmatched,'problems':problems}
    return {**result,'report':_report(result,migrations,name,old_version,new_version,notes_path,scan_note)}

def _first_report(name, new_version, problems):
    """The report when there is no comparison target: only the declarations are checked."""
    report=[f'### {name} {new_version}','',('**Blocked**: invalid declaration; ' if problems else '**Passed**: ')+'no comparison target (no earlier stable Release), so there is nothing to compare.']
    if problems:report+=['','Invalid declarations:','']+[f'- {p}' for p in problems]
    return '\n'.join(report)+'\n'

def _report(result, migrations, name, old_version, new_version, notes_path, scan_note):
    """The Markdown report of compare()'s `result`; `migrations`: {(change, key): migration} of the valid declarations."""
    breaking,notices,unmatched,problems,vulns=(result[k] for k in ('breaking','notices','unmatched','problems','vulnerabilities'))
    r=[f'### {name} {old_version} → {new_version}','',('**Blocked**: undeclared breaking change, new fixable vulnerability, or invalid declaration.' if result['blocked'] else '**Passed**.'),'']
    if breaking:
        r+=['Breaking changes (each needs an entry in `'+notes_path+'`):','','| change | key | declared | migration |','|---|---|---|---|']
        r+=[f'| `{markdown_cell(b["change"])}` | `{markdown_cell(b["key"])}` | {"yes" if b["declared"] else "**no**"} | {markdown_cell(migrations[(b["change"],b["key"])]) if b["declared"] else ""} |' for b in breaking]
        missing=[b for b in breaking if not b['declared']]
        if missing:r+=['','Add to `'+notes_path+'` and write the migration:','','```yaml',_paste(new_version,missing),'```']
        r.append('')
    else:r+=['No breaking configuration changes.','']
    if notices:
        r+=['Report only (does not block):','','| change | key | detail |','|---|---|---|']+[f'| `{n["change"]}` | `{markdown_cell(n["key"])}` | {markdown_cell(n["detail"])} |' for n in notices]+['']
    if unmatched:
        r+=['Declarations with no matching change (check the spelling of `change` and `key`):','']+[f'- {u["version"]}: `{u["change"]}` `{u["key"]}`' for u in unmatched]+['']
    if problems:r+=['Invalid declarations:','']+[f'- {p}' for p in problems]+['']
    if vulns is None:r.append(f'Vulnerability comparison: not run ({scan_note}).')
    else:
        r+=[f'Vulnerabilities (Grype, amd64): {vulns["old_count"]} in {old_version}, {vulns["new_count"]} in {new_version}.','']
        if vulns['new_fixable']:
            r+=['New fixable vulnerabilities (Critical/High with a fixed version, not in '+old_version+'; each blocks unless accepted in `'+notes_path+'`):','',
                '| id | package | severity | fixed in | accepted |','|---|---|---|---|---|']
            r+=[f'| {markdown_cell(f["id"])} | {markdown_cell(f["package"])} | {markdown_cell(f["severity"])} | {markdown_cell(", ".join(f["fixed_in"]))} | {markdown_cell(f["reason"]) if f["accepted"] else "**no**"} |' for f in vulns['new_fixable']]+['']
        else:r+=['No new fixable vulnerabilities.','']
        n=vulns['not_blocking']
        if vulns['unmatched_accepted']:
            r+=['Accepted vulnerabilities that are not new fixable ones (check `id` and `package`):','']+[f'- {d["version"]}: {d["id"]} {d["package"]}' for d in vulns['unmatched_accepted']]+['']
        r.append(f'Report only (does not block): {n["in_old"]} already in {old_version}, {n["not_fixed"]} new with no fixed version, {n["low"]} new below High.')
    return '\n'.join(r)+'\n'

def check_target(version, target, config, target_config_version, tag_version=None):
    """ValueError unless the comparison target's config (path `config`) gives the version its tag does (`tag_version`; None
    under ref_policy main, whose target is the PR base) and `version` is newer than it (require_newer), so a PR fails
    before any scan; compare() reads the config's and requires the same. Tag and config are compared with version_cmp,
    so 1.3 and 1.3.0 agree; a pair that cannot be ordered does not. A config with no version (None) is the target's fault."""
    if target_config_version is None:raise ValueError(f'the comparison target {target} has no version in {config}; '+('correct that Release' if tag_version is not None else 'add a version to that config on the default branch')+', then re-run this check')
    try:same=tag_version is None or version_cmp(tag_version,target_config_version)==0
    except ValueError:same=False
    if not same:raise ValueError(f'the comparison target {target} is version {tag_version} by its tag but {target_config_version} by {config}; correct that Release so its tag and config agree, then re-run this check')
    require_newer(version,target_config_version)

def _load(path, fmt, optional=False):
    """Parsed `fmt` ('yaml' or 'json') file, or None when `path` is not given or, if `optional`, does not exist."""
    if not path:return None
    p=pathlib.Path(path)
    if optional and not p.exists():return None
    text=p.read_text(encoding='utf-8')
    return json.loads(text) if fmt=='json' else yaml.safe_load(text)

def _version(path, as_written=False):
    """The version of the config.yaml at `path` (addon_sync.config_version); ValueError when it has none."""
    version=config_version(pathlib.Path(path).read_text(encoding='utf-8'),as_written)
    if version is None:raise ValueError(f"{path} has no version")
    return version

def _error(title, message):
    """An ::error workflow command; PR-controlled text is escaped (addon_sync.workflow_command)."""
    print(workflow_command('error',title,message))

def components(registry, repo):
    """What the reusable workflow needs from repo's registry entry: ref_policy, the approved reason to skip category 4
    ('' when not approved) and, for each add-on it releases (addon_sync.publishes_releases: a retired or prerelease add-on
    is not compared), the repository paths of its config and upgrade-notes.yaml (config, notes) and, while a config move
    is in progress, of the location it left (previous_config, previous_notes; '' when none). The workflow reads the
    previous ones at a commit that does not have the registry's path, as addon_sync.locate does."""
    provider=find_provider(registry,repo)
    def paths(comp):
        out={'previous_config':'','previous_notes':''}
        try:
            for prefix,c in zip(('','previous_'),locations(comp)):
                out[prefix+'config'],out[prefix+'notes']=source_file(c,c['config_file']),source_file(c,'upgrade-notes.yaml')
        except Blocked as e:raise ValueError(f'{repo} {comp["id"]}: {e}') from None
        return out
    return {'ref_policy':provider['ref_policy'],'skip_vulnerability_scan':(provider.get('upgrade_comparison') or {}).get('skip_vulnerability_scan',''),
        'components':[{'id':c['id'],**paths(c)} for c in provider['components'] if publishes_releases(c)]}

class _Failed(Exception):
    """A command's expected failure: main() reports it as an ::error (title, message) and exits 2."""

@contextlib.contextmanager
def _failing(errors, prefix='', title='Upgrade comparison failed'):
    """Raise _Failed for `errors` raised inside, with `prefix` before the message."""
    try:yield
    except errors as e:raise _Failed(title,prefix+str(e)) from None

def _components(a):
    # Its errors name the repository (find_provider, components).
    with _failing((ValueError,KeyError,TypeError,OSError,Blocked)):print(json.dumps(components(_load(a.registry,'json'),a.repo)))
    return 0

def _comparison_target(a):
    # The registry lookup, Release filter, tag rule and order are addon_sync's, so the PR check and the Release notes agree.
    with _failing((ValueError,KeyError,TypeError,OSError)):provider,comp=find_component(_load(a.registry,'json'),a.repo,a.component)  # names the repository and add-on
    with _failing((ValueError,KeyError,TypeError,AttributeError,OSError),f'Releases of {a.repo} {a.component}: '):
        releases=json.load(sys.stdin)
        if not isinstance(releases,list):raise ValueError('stdin is not a JSON array of Releases')
        target=comparison_target(stable_versions(provider,comp,releases),a.version)
    if target is not None:print(release_tag(provider,comp,target)+'\t'+target)
    return 0

def _version_command(a):
    with _failing((ValueError,OSError,yaml.YAMLError),f'{a.name}: {a.path or a.file}: '):print(config_version(pathlib.Path(a.file).read_text(encoding='utf-8'),a.as_written) or '')
    return 0

def _check_target(a):
    with _failing(ValueError,f'{a.name}: '):check_target(a.version,a.target,a.config,a.config_version or None,a.tag_version or None)
    return 0

def _release_notes(a):
    with _failing((ValueError,TypeError,OSError,yaml.YAMLError),f'{a.notes}: ','Release notes failed'):text=release_notes(_load(a.notes,'yaml',optional=True),a.version,a.released)
    print(text,end='');return 0

def _compare(a):
    with _failing((ValueError,KeyError,TypeError,OSError,yaml.YAMLError),f'{a.name or a.new}: '):
        old,new=_load(a.old,'yaml'),_load(a.new,'yaml')
        r=compare(old,new,old_version=_version(a.old) if old else None,new_version=_version(a.new,True),notes=_load(a.notes,'yaml',optional=True),
            old_scan=_load(a.old_scan,'json'),new_scan=_load(a.new_scan,'json'),name=a.name,notes_path=a.notes_path,scan_note=a.scan_note)
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

COMMANDS={'components':_components,'comparison-target':_comparison_target,'version':_version_command,'check-target':_check_target,'release-notes':_release_notes,'compare':_compare}

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
    n.add_argument('--released',nargs='*',default=[],help='versions that already have a stable Release')
    t=sub.add_parser('comparison-target',help="read the repository's Releases (GitHub API JSON array) on stdin, print the tag of the add-on's latest stable Release and its version, tab-separated (nothing when none); fails unless --version is newer")
    t.add_argument('--registry',required=True,help='Store registry.json');t.add_argument('--repo',required=True,help='source repository, owner/name')
    t.add_argument('--component',required=True,help='add-on id in the registry')
    t.add_argument('--version',required=True,help="the PR's version: it must be newer than the target, as for the Release notes")
    g=sub.add_parser('check-target',help="fail unless the comparison target's config gives the version its tag does and --version is newer (check_target)")
    g.add_argument('--name',required=True,help='add-on id, for the error');g.add_argument('--version',required=True,help="the PR's version")
    g.add_argument('--target',required=True,help="the target's tag, or the PR base");g.add_argument('--tag-version',default='',help="the target's version by its tag; '' when it has none")
    g.add_argument('--config',required=True,help="path of the target's config.yaml in the repository")
    g.add_argument('--config-version',required=True,help="the target's version by its config ('' when it has none; upgrade_check.py version)")
    v=sub.add_parser('version',help="print the version of a config.yaml as Home Assistant Supervisor reads it (addon_sync.config_version; nothing when it has none)")
    v.add_argument('--file',required=True,help='the config.yaml');v.add_argument('--path',help='its path in the repository, for the error')
    v.add_argument('--name',required=True,help='add-on id, for the error')
    v.add_argument('--as-written',action='store_true',help="the PR's version: fail unless it reads as its text does (unquoted 1.10 is 1.1)")
    k=sub.add_parser('components',help="print what the workflow needs from the repository's registry entry (JSON, see components())")
    k.add_argument('--registry',required=True,help='Store registry.json');k.add_argument('--repo',required=True,help='source repository, owner/name')
    a=p.parse_args(argv)
    try:return COMMANDS[a.command](a)
    except _Failed as e:
        _error(*e.args);return 2

if __name__=='__main__':sys.exit(main())
