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

Category 3 (regression comparison, #139): the checks of the add-on's smoke hook
on the comparison target and on the new version, compared by name in the
upgrade test's result (regression(); upgrade_runtime.py runs the hook).

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
import argparse, contextlib, json, os, pathlib, re, secrets, sys
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
    under ref_policy main, whose target is the commit on the PR base where its version first appeared) and `version` is newer than it (require_newer), so a PR fails
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
    ('' when not approved), the approved reason to scan, on both sides, the image config.yaml names at its version
    instead of the PR build's SBOM (scan_published_image, #147: a repository that ships a third-party image; '' when
    not approved; never together with the skip) and, for each add-on it releases (addon_sync.publishes_releases: a retired or prerelease add-on
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
    approved=provider.get('upgrade_comparison') or {}
    skip,published=approved.get('skip_vulnerability_scan',''),approved.get('scan_published_image','')
    if skip and published:raise ValueError(f'{repo}: the Store registry gives both skip_vulnerability_scan and scan_published_image; category 4 is either skipped or scans the published image, keep one')
    return {'ref_policy':provider['ref_policy'],'skip_vulnerability_scan':skip,'scan_published_image':published,
        'components':[{'id':c['id'],**paths(c)} for c in provider['components'] if publishes_releases(c)]}

# Upgrade test (#137, #156, category 2). Every `map` type Supervisor accepts and where it mounts it when the entry
# gives no `path` (home-assistant/supervisor@bde7fb7: supervisor/apps/const.py MappingType, apps/validate.py
# RE_VOLUME and _migrate_app_config, docker/app.py DockerApp.mounts, docker/const.py PATH_*). `data` is the
# add-on's private data, always read-write, mounted once at its `path` or /data.
MAP_PATHS={'data':'/data','config':'/config','homeassistant_config':'/homeassistant','app_config':'/config','addon_config':'/config',
    'all_app_configs':'/app_configs','all_addon_configs':'/addon_configs','local_apps':'/local_apps','addons':'/addons',
    'ssl':'/ssl','backup':'/backup','share':'/share','media':'/media'}
# The host directory under <root> each type is mounted from, when it is not <root>/<type>. Supervisor mounts the
# add-on → app renames (2026.07) and `config` (the legacy name for Home Assistant's config) from the same host
# directory as the new name, so a version that renames one keeps its data. An add-on's own config folder is
# <app_configs>/<slug>, the folder all_app_configs shows as a whole (apps/app.py path_extern_config,
# config.py path_extern_app_configs).
MAP_SOURCES={'app_config':'all_app_configs/{slug}','addon_config':'all_app_configs/{slug}','all_addon_configs':'all_app_configs',
    'addons':'local_apps','config':'homeassistant_config'}
# Entries Supervisor ignores when another type is present, whatever their order (docker/app.py DockerApp.mounts
# keys entries by type and prefers the new name; validate.py _migrate_app_config logs it): `config` drops
# app_config, addon_config and homeassistant_config; a new name drops its legacy one.
MAP_IGNORED_BY={'config':('app_config','addon_config','homeassistant_config'),'app_config':('addon_config',),
    'all_app_configs':('all_addon_configs',),'local_apps':('addons',)}
_MAP_STRING=re.compile(r'^(\w+)(?::(rw|ro))?$')

def _map_entries(config):
    """config.yaml's `map` as {type: (path, read_only)} after Supervisor drops the entries it skips or ignores, and
    a warning for each dropped one. As in apps/validate.py (_migrate and the map schema): a string entry that is
    not <type>[:rw|:ro] with a known type, a mapping without `type`, and an entry that is neither are skipped, so
    the add-on still loads; a mapping with `type` must have a known type, a boolean read_only (default true) and
    a string path, and no other key, or Supervisor does not load the add-on. A string is read-only unless :rw."""
    entries,warnings={},[]
    for entry in config.get('map') or []:
        if isinstance(entry,str):
            if not ((m:=_MAP_STRING.match(entry)) and m[1] in MAP_PATHS):
                warnings.append(f'map entry {entry!r} is skipped because it is not <type>[:rw|:ro] (as Supervisor does)');continue
            kind,read_only,path=m[1],m[2]!='rw',None
        elif isinstance(entry,dict):
            if 'type' not in entry:
                warnings.append(f"map entry {entry!r} is skipped because it has no 'type' (as Supervisor does)");continue
            kind,read_only,path=entry['type'],entry.get('read_only',True),entry.get('path')
            if not (isinstance(kind,str) and kind in MAP_PATHS and isinstance(read_only,bool)
                    and isinstance(entry.get('path',''),str) and set(entry)<={'type','read_only','path'}):
                raise ValueError(f'invalid map entry {entry!r}; Supervisor does not load an add-on with it')
        else:
            warnings.append(f'map entry {entry!r} is skipped because it is neither a string nor a mapping (as Supervisor does)');continue
        entries[kind]=(path,read_only)
    for kind,ignored in MAP_IGNORED_BY.items():
        if kind in entries:
            for other in ignored:
                if entries.pop(other,None) is not None:warnings.append(f"map entry '{other}' is ignored because '{kind}' is present (as Supervisor does)")
    return entries,warnings

def map_warnings(config):
    """The `map` entries Supervisor ignores for this config.yaml, one message each, for the upgrade test's report."""
    return _map_entries(config)[1]

def mounts(config, root):
    """The data directories of an add-on: <root>/data at /data (or at the `path` of its `data` entry), then one per
    other `map` entry at its `path` (or Supervisor's default), from <root>/<MAP_SOURCES[type] or type>. The
    comparison target and the new version share the same set even when one of them moves or renames a type. As
    in Supervisor, a repeated type keeps its last entry and skipped or ignored entries are dropped (map_warnings lists them).
    Each is {type, source, target, read_only}; type is 'data' for the data mount, else the map type as config.yaml
    writes it (addon_config stays addon_config), for naming per-directory settings such as the hooks' variables."""
    entries,_=_map_entries(config)
    data_path,_=entries.pop('data',(None,False))
    out=[{'type':'data','source':f'{root}/data','target':data_path or MAP_PATHS['data'],'read_only':False}]
    for kind,(path,read_only) in entries.items():
        source=MAP_SOURCES.get(kind,kind)
        if '{slug}' in source:
            if not config.get('slug'):raise ValueError(f'map entry {kind!r} needs the add-on slug')
            source=source.format(slug=config['slug'])
        out.append({'type':kind,'source':f'{root}/{source}','target':path or MAP_PATHS[kind],'read_only':read_only})
    # Two entries at one path (a custom path onto another type's) cannot both be mounted.
    targets=[m['target'] for m in out]
    for t in targets:
        if targets.count(t)>1:raise ValueError(f'two data directories are mounted at {t}; give one of the map entries a path')
    return out

# Regression comparison (#139, category 3): the add-on's upgrade-check/smoke runs on the comparison target and on the
# new version; regression() compares the two runs check by check. HOOK_ROW is the row of the hook's own outcome, the
# only row when it writes no report; STARTS_ROW the only row without a smoke hook.
HOOK_ROW,STARTS_ROW='(the hook)','starts'

def _smoke_run(phase):
    """The smoke run in a phase of upgrade_runtime.py's result, or None when smoke did not run there."""
    return next((h for h in (phase or {}).get('hooks') or [] if h.get('hook')=='smoke'),None)

def _verdict(old,new,only_new_counts):
    """'pass', 'fail' or 'not compared' for one row: what passes on the comparison target must pass on the new
    version; what fails or is skipped there is only reported; a check only the new version has (only_new_counts) must pass."""
    if old=='pass' or (old is None and only_new_counts):return 'pass' if new=='pass' else 'fail'
    return 'not compared'

def regression(result):
    """Category 3 of upgrade_runtime.py's result (pipeline #90, #139): {smoke, compared, passed, rows, reason}.

    With upgrade-check/smoke (result hooks has 'smoke'), rows are HOOK_ROW, then each check by name in the order
    the comparison target's report, then the new version's, lists them. HOOK_ROW is 'pass' when the hook exited 0
    and its report, if any, could be read; a hook that writes no report is judged by this row alone, by its exit
    code. Each row is {name, old, new, verdict, old_detail, new_detail}: old/new are pass, fail, skip or None
    (absent from that report, or smoke did not run there); verdict as _verdict: the comparison target pass and the
    new version not pass is 'fail'; the comparison target fail, skip or None is 'not compared' (未比對, report only),
    except that a check only in the new version's report must pass when the comparison target's smoke is usable
    (exited 0 and wrote a report that could be read). When smoke did not run on the new version (category 2 failed
    first), nothing is compared: compared is false, rows is empty and not_run says why. Without smoke the only row is
    STARTS_ROW, whether each version started. passed: no row is 'fail'; reason names the failing rows ('' when passed)."""
    if not isinstance(result,dict) or not isinstance(result.get('phases'),list):raise ValueError('not an upgrade test result (no phases list)')
    phases={p.get('phase'):p for p in result['phases'] if isinstance(p,dict)}
    old,new=phases.get('old'),phases.get('new')
    def row(name,o,n,only_new_counts=False,od='',nd=''):
        return {'name':name,'old':o,'new':n,'verdict':_verdict(o,n,only_new_counts),'old_detail':od,'new_detail':nd}
    smoke='smoke' in (result.get('hooks') or [])
    if not smoke:
        started=lambda p:None if p is None else 'pass' if p.get('started') else 'fail'
        rows=[row(STARTS_ROW,started(old),started(new),od=(old or {}).get('detail',''),nd=(new or {}).get('detail',''))]
    else:
        runs=_smoke_run(old),_smoke_run(new)
        if runs[1] is None:
            why=(new or {}).get('smoke_not_run') or 'the upgrade test ended before the new version ran'
            return {'smoke':True,'compared':False,'passed':True,'rows':[],'reason':'','not_run':why}
        def outcome(run):
            if run is None:return None
            return 'pass' if run.get('exit_code')==0 and not run.get('report_error') else 'fail'
        rows=[row(HOOK_ROW,*map(outcome,runs),od=(runs[0] or {}).get('detail',''),nd=(runs[1] or {}).get('detail',''))]
        checks=[{c['name']:c for c in (r or {}).get('checks') or []} for r in runs]
        # A comparison target whose smoke did not run, exited non-zero (a timeout or crash too) or wrote no usable
        # report has no checks to go by: then nothing is "only in the new version" (未比對).
        target_reported=outcome(runs[0])=='pass' and bool(runs[0].get('reported'))
        for name in [*checks[0],*(n for n in checks[1] if n not in checks[0])]:
            o,n=(c.get(name) or {} for c in checks)
            rows.append(row(name,o.get('result'),n.get('result'),target_reported,o.get('detail',''),n.get('detail','')))
    failed=[r for r in rows if r['verdict']=='fail']
    def why(r):
        # With smoke, a check missing from the new version's report is absent; without, a version that did not run is not run.
        new=r['new'] or ('absent from its report' if smoke else 'not run')
        if r['old']=='pass':return f'{r["name"]} passes on the comparison target but is {new} on the new version'
        return f'{r["name"]} is only in the new version and is {new}, not pass'
    reason=('regression (category 3): '+'; '.join(why(r) for r in failed[:10])+(f'; and {len(failed)-10} more' if len(failed)>10 else '')) if failed else ''
    return {'smoke':smoke,'compared':True,'passed':not failed,'rows':rows,'reason':reason}

# watchdog and webui as Supervisor writes them: [HOST] is the add-on's address, [PORT:n] its container port n,
# [PROTO:option] https when that option is true.
_URL=re.compile(r'^(https?|tcp|\[PROTO:(\w+)\])://\[HOST\]:(?:\[PORT:)?(\d+)\]?(.*)$')
# upgrade-check/settings.yaml: the startup limits (startup_probe) and the data hooks' limit (#138, upgrade_runtime.py).
SETTINGS_DEFAULTS={'startup_timeout':300,'stable_seconds':60,'hook_timeout':600}
# Supervisor gives an ingress_port of 0 a free port in 62000-65500 at install and keeps it for the add-on
# (supervisor/apps/app.py _check_ingress_port); the upgrade test assigns the first one, the same for both versions.
ASSIGNED_INGRESS_PORT=62000

def ingress_port(config):
    """The port Supervisor serves the add-on's ingress on: config.yaml's ingress_port (default 8099), or the
    port it assigns when that is 0. None without ingress."""
    if not config.get('ingress'):return None
    port=config.get('ingress_port',8099)
    return ASSIGNED_INGRESS_PORT if port==0 else port

def _probe_url(text, options):
    m=_URL.match(str(text))
    if not m:raise ValueError(f'cannot read {text!r} as Supervisor does ([HOST] and [PORT:n])')
    scheme,option,port,path=m.groups()
    if option:scheme='https' if (options or {}).get(option) else 'http'
    return f'{scheme}://[HOST]:{port}{path}'

def webui_endpoint(config):
    """(scheme, port) of config.yaml's webui as Supervisor reads it ([PROTO:option] resolved from the option
    defaults), or None without a webui."""
    if not config.get('webui'):return None
    scheme,rest=_probe_url(config['webui'],config.get('options')).split('://',1)
    return scheme,int(rest.split(':',1)[1].split('/',1)[0])

def upgrade_settings(settings):
    """The time limits of the upgrade test: SETTINGS_DEFAULTS, overridden by upgrade-check/settings.yaml (parsed, or
    None). Each value is a whole number of seconds above 0, and stable_seconds stays below startup_timeout."""
    limits=dict(SETTINGS_DEFAULTS)
    if settings is not None and not isinstance(settings,dict):raise ValueError('settings must be a mapping of setting: seconds')
    for key,value in (settings or {}).items():
        if key==SKIP_KEY:continue  # not a time limit: upgrade_test_skip() refuses it unless the registry approves the skip
        if key not in limits:raise ValueError(f'unknown setting {key!r} (known: {", ".join(limits)})')
        if not isinstance(value,int) or isinstance(value,bool) or value<=0:raise ValueError(f'{key} must be a whole number of seconds above 0, not {value!r}')
        limits[key]=value
    if limits['stable_seconds']>=limits['startup_timeout']:raise ValueError(f'stable_seconds ({limits["stable_seconds"]}) must be below startup_timeout ({limits["startup_timeout"]})')
    return limits

def startup_probe(config, settings=None):
    """How the upgrade test judges that a version starts. One probe, the first config.yaml declares, in Supervisor's
    order (no fallback to the next when it does not answer): the watchdog answers with success (HTTP below 300, or
    the TCP port accepts); else the ingress port answers; else the webui port answers (any HTTP status below 500);
    else none. The probe must answer within startup_timeout seconds; then (or at once, with no probe) the container
    must run stable_seconds without exiting or restarting (owner, 2026-11-03). `settings`: the add-on's upgrade-check/settings.yaml (parsed, or None), which may
    override startup_timeout and stable_seconds. The url keeps [HOST] for the runtime to fill in; `below` is the HTTP
    status an answer must stay under (None for tcp and stays-up). An ingress_port of 0 (a port Supervisor picks) is
    still ingress, probed at the port the upgrade test assigns (ingress_port())."""
    limits=upgrade_settings(settings)
    options=config.get('options') or {}
    if config.get('watchdog'):method,url,below='watchdog',_probe_url(config['watchdog'],options),300
    elif config.get('ingress'):method,url,below='ingress',f'http://[HOST]:{ingress_port(config)}/',500
    elif config.get('webui'):method,url,below='webui',_probe_url(config['webui'],options),500
    else:method,url,below='stays-up','',None
    if url.startswith('tcp://'):below=None
    return {'method':method,'url':url,'below':below,'timeout':limits['startup_timeout'],'stable_seconds':limits['stable_seconds']}

# Add-ons built on the device (#144): the upgrade test rebuilds both images the way Supervisor builds them
# (supervisor/addons/build.py): build.yaml, .yml or .json next to config.yaml; base image build_from (a string, or
# one per arch), else Home Assistant's base image; Dockerfile.<arch> when there is one, else Dockerfile.
BUILD_FILES=('build.yaml','build.yml','build.json')

def build_args(addon_dir, version, arch='amd64'):
    """How Supervisor builds the add-on in `addon_dir` at `version` for `arch`: {'dockerfile': its path,
    'args': {build argument: value}}, BUILD_FROM, BUILD_VERSION, BUILD_ARCH and then build.yaml's args."""
    root=pathlib.Path(addon_dir);build={}
    found=[root/n for n in BUILD_FILES if (root/n).is_file()]
    if found:
        build=(json.loads if found[0].suffix=='.json' else yaml.safe_load)(found[0].read_text(encoding='utf-8')) or {}
        if not isinstance(build,dict):raise ValueError(f'{found[0].name} is not a mapping')
    base=build.get('build_from')
    if isinstance(base,dict):
        if arch not in base:raise ValueError(f'{found[0].name} build_from has no base image for {arch}')
        base=base[arch]
    elif not base:base=f'ghcr.io/home-assistant/{arch}-base:latest'
    extra=build.get('args') or {}
    if not isinstance(extra,dict):raise ValueError(f'{found[0].name} args is not a mapping')
    args={'BUILD_FROM':base,'BUILD_VERSION':version,'BUILD_ARCH':arch,**{str(k):v for k,v in extra.items()}}
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

SKIP_KEY='skip_upgrade_test'

def approved_upgrade_test_skip(component):
    """The reason the Store registry approves for skipping the upgrade test (categories 2 and 3) of `component` (its
    registry entry), or '' when none is approved (#140, pipeline #90). Approved per add-on, like
    skip_vulnerability_scan per provider: upgrade_comparison.skip_upgrade_test holds the reason and its ticket; the
    report gives that reason. A malformed entry (upgrade_comparison not a mapping, the reason not a non-empty
    string) is a ValueError naming the add-on, never an empty reason."""
    given=component.get('upgrade_comparison',{})
    if given is None:given={}
    if not isinstance(given,dict):
        raise ValueError(f'the Store registry entry for {component.get("id")} is malformed: upgrade_comparison must be a mapping, not {given!r}')
    approved=given.get(SKIP_KEY,'')
    if SKIP_KEY in given and (not isinstance(approved,str) or not approved.strip()):
        raise ValueError(f'the Store registry entry for {component.get("id")} is malformed: upgrade_comparison.{SKIP_KEY} must be the approved reason '
            f'and its ticket (a non-empty string), not {approved!r}')
    return approved.strip()

def upgrade_test_skip(component, settings=None):
    """approved_upgrade_test_skip(component). The registry alone decides, so a source repository cannot skip by
    itself: `settings` (the add-on's upgrade-check/settings.yaml, parsed, or None) that asks for the skip without the
    approval is a ValueError saying to get it approved in the registry. Only a non-empty string skip_upgrade_test
    asks (the reason, as in the registry); false, null, "" or any other value is no request. With the approval the
    settings are not looked at (_upgrade_test_skip does not even read them)."""
    approved=approved_upgrade_test_skip(component)
    if approved:return approved
    asked=settings.get(SKIP_KEY) if isinstance(settings,dict) else None
    if isinstance(asked,str) and asked.strip():
        raise ValueError(f'upgrade-check/settings.yaml asks for {SKIP_KEY}, but skipping the upgrade test is not approved for {component.get("id")}: '
            f'the Store registry entry of this add-on needs upgrade_comparison.{SKIP_KEY} with the reason. Remove it from settings.yaml or get the skip approved in the registry.')
    return ''

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

def _mounts(a):
    with _failing((ValueError,OSError,yaml.YAMLError),f'{a.config}: '):print(json.dumps(mounts(_load(a.config,'yaml') or {},a.root)))
    return 0

def _startup_probe(a):
    with _failing((ValueError,OSError,yaml.YAMLError,AttributeError),f'{a.settings or a.config}: '):
        print(json.dumps(startup_probe(_load(a.config,'yaml') or {},_load(a.settings,'yaml',optional=True))))
    return 0

def _build_args(a):
    with _failing((ValueError,OSError,yaml.YAMLError,json.JSONDecodeError,AttributeError),f'{a.name}: {a.addon_dir}: '):print(json.dumps(build_args(a.addon_dir,a.version)))
    return 0

def _upgrade_test_skip(a):
    with _failing((ValueError,KeyError,TypeError,OSError)):_,comp=find_component(_load(a.registry,'json'),a.repo,a.component)  # names the repository and add-on
    with _failing((ValueError,OSError,yaml.YAMLError),f'{a.component}: '):
        # Approved: the registry decides, so the repository's settings.yaml is not read (a malformed one cannot fail it).
        approved=approved_upgrade_test_skip(comp)
        print(approved or upgrade_test_skip(comp,_load(a.settings,'yaml',optional=True)))
    return 0

COMMANDS={'build-args':_build_args,'upgrade-test-skip':_upgrade_test_skip,'mounts':_mounts,'startup-probe':_startup_probe,'components':_components,'comparison-target':_comparison_target,'version':_version_command,'check-target':_check_target,'release-notes':_release_notes,'compare':_compare}

def _regression(a):
    with _failing((ValueError,KeyError,TypeError,AttributeError,OSError),f'{a.result}: '):r=regression(_load(a.result,'json'))
    print(json.dumps(r));return 0 if r['passed'] else 1
COMMANDS['regression']=_regression  # #139

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
    g.add_argument('--target',required=True,help="the target's tag, or under ref_policy main the commit where the PR base's version first appeared");g.add_argument('--tag-version',default='',help="the target's version by its tag; '' when it has none")
    g.add_argument('--config',required=True,help="path of the target's config.yaml in the repository")
    g.add_argument('--config-version',required=True,help="the target's version by its config ('' when it has none; upgrade_check.py version)")
    v=sub.add_parser('version',help="print the version of a config.yaml as Home Assistant Supervisor reads it (addon_sync.config_version; nothing when it has none)")
    v.add_argument('--file',required=True,help='the config.yaml');v.add_argument('--path',help='its path in the repository, for the error')
    v.add_argument('--name',required=True,help='add-on id, for the error')
    v.add_argument('--as-written',action='store_true',help="the PR's version: fail unless it reads as its text does (unquoted 1.10 is 1.1)")
    k=sub.add_parser('components',help="print what the workflow needs from the repository's registry entry (JSON, see components())")
    k.add_argument('--registry',required=True,help='Store registry.json');k.add_argument('--repo',required=True,help='source repository, owner/name')
    m=sub.add_parser('mounts',help="print the upgrade test's data directories as JSON [{type, source, target, read_only}] (mounts())")
    m.add_argument('--config',required=True,help="the version's config.yaml");m.add_argument('--root',required=True,help='directory holding one directory per type')
    r=sub.add_parser('regression',help="compare the smoke checks of an upgrade test result (category 3): print {smoke, passed, rows, reason} as JSON (regression()); exits 1 on a regression")
    r.add_argument('--result',required=True,help="upgrade_runtime.py's result, <name>.json")
    s=sub.add_parser('startup-probe',help='print how the upgrade test judges that a version starts, as JSON {method, url, below, timeout, stable_seconds} (startup_probe())')
    s.add_argument('--config',required=True,help="the version's config.yaml");s.add_argument('--settings',help='upgrade-check/settings.yaml of the add-on (may be absent)')
    b=sub.add_parser('build-args',help="print how Supervisor builds an add-on built on the device for amd64, as JSON {dockerfile, args} (build_args())")
    b.add_argument('--addon-dir',required=True,help="the add-on's directory (config.yaml, build.yaml, Dockerfile)");b.add_argument('--version',required=True,help='its version (BUILD_VERSION)')
    b.add_argument('--name',required=True,help='add-on id, for the error')
    x=sub.add_parser('upgrade-test-skip',help="print the reason the Store registry approves for skipping the add-on's upgrade test (categories 2 and 3); nothing when none (upgrade_test_skip())")
    x.add_argument('--registry',required=True,help='Store registry.json');x.add_argument('--repo',required=True,help='source repository, owner/name')
    x.add_argument('--component',required=True,help='add-on id in the registry');x.add_argument('--settings',help='upgrade-check/settings.yaml of the add-on (may be absent)')
    a=p.parse_args(argv)
    try:return COMMANDS[a.command](a)
    except _Failed as e:
        _error(*e.args);return 2

if __name__=='__main__':sys.exit(main())
