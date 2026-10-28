import contextlib,copy,io,json,pathlib,shutil,tempfile,unittest,unittest.mock
import yaml
import upgrade_check as u

# A config shaped like odoo's: flat schema, required password keys whose options default is null.
BASE={'name':'Test','version':'1.0.0','slug':'test','image':'ghcr.io/woowtech/test-{arch}','arch':['amd64','aarch64'],
    'ports':{'8069/tcp':8069,'8072/tcp':8072},
    'options':{'admin_passwd':None,'log_level':'info','workers':2,'proxy_mode':True},
    'schema':{'admin_passwd':'password','log_level':'list(debug|info|warn)?','workers':'int(0,16)?','proxy_mode':'bool?','db_filter':'str?'}}
def new(**changes):
    cfg=copy.deepcopy(BASE);cfg['version']='1.1.0'
    for k,v in changes.items():cfg[k]=v(cfg[k]) if callable(v) else v
    return cfg
def drop(key):
    def f(d):d=dict(d);d.pop(key);return d
    return f
def put(key,value):
    def f(d):d=dict(d);d[key]=value;return d
    return f
def run(cfg,notes=None,old=BASE,old_version='1.0.0'):
    return u.compare(old,cfg,old_version=old_version,new_version=cfg['version'],notes=notes)
def pairs(items):return [(i['change'],i['key']) for i in items]

class Tests(unittest.TestCase):
    def test_removed_option_is_blocked_and_named(self):
        r=run(new(options=drop('workers'),schema=drop('workers')))
        self.assertTrue(r['blocked'])
        self.assertEqual(pairs(r['breaking']),[('option-removed','workers')])
        self.assertIn('option-removed',r['report']);self.assertIn('workers',r['report'])
    def test_each_blocking_schema_row(self):
        rows=[('schema key without a default removed',new(schema=drop('db_filter')),('schema-removed','db_filter')),
            ('type changed',new(schema=put('workers','str?')),('schema-retyped','workers')),
            ('optional made required',new(schema=put('db_filter','str')),('made-required','db_filter')),
            ('upper bound lowered',new(schema=put('workers','int(0,8)?')),('range-narrowed','workers')),
            ('lower bound raised',new(schema=put('workers','int(1,16)?')),('range-narrowed','workers')),
            ('bound added',new(schema=put('db_filter','str(1,)?')),('range-narrowed','db_filter')),
            ('enum value removed',new(schema=put('log_level','list(info|warn)?')),('enum-value-removed','log_level'))]
        for name,cfg,expected in rows:
            with self.subTest(name):
                r=run(cfg);self.assertTrue(r['blocked']);self.assertEqual(pairs(r['breaking']),[expected])
    def test_widening_changes_are_silent(self):
        rows=[('range widened',new(schema=put('workers','int(0,32)?'))),
            ('bound dropped',new(schema=put('workers','int?'))),
            ('enum value added',new(schema=put('log_level','list(debug|info|warn|error)?'))),
            ('required made optional',new(schema=put('admin_passwd','password?'))),
            ('optional key added',new(schema=put('extra','str?'))),
            ('required key added with an options default',new(schema=put('extra','str'),options=put('extra','x')))]
        for name,cfg in rows:
            with self.subTest(name):
                r=run(cfg);self.assertFalse(r['blocked']);self.assertEqual(r['breaking'],[]);self.assertEqual(r['notices'],[])
    def test_required_key_added_without_a_usable_default_is_blocked(self):
        for name,cfg in [('no options entry',new(schema=put('db_password','password'))),
                ('options default is null',new(schema=put('db_password','password'),options=put('db_password',None)))]:
            with self.subTest(name):
                r=run(cfg);self.assertTrue(r['blocked']);self.assertEqual(pairs(r['breaking']),[('required-added','db_password')])
    def test_new_list_key_follows_supervisor_missing_option_rule(self):
        # Supervisor (addons/options.py _check_missing_options): a missing list option is optional when its element
        # schema is an optional scalar such as ["str?"]; any other list (required scalar, mapping items) is required.
        for schema,blocked in [(['str?'],False),(['int(1,5)?'],False),(['str'],True),([{'name':'str?'}],True)]:
            with self.subTest(schema=schema):
                r=run(new(schema=put('tags',schema)))
                self.assertEqual(pairs(r['breaking']),[('required-added','tags')] if blocked else [])
        self.assertEqual(run(new(schema=put('tags',['str']),options=put('tags',[])))['breaking'],[])
    def test_nested_keys_use_the_schema_path(self):
        old=new(schema=put('database',{'host':'str','port':'port?'}),options=put('database',{'host':'db','port':5432}))
        old['version']='1.0.0'
        cfg=copy.deepcopy(old);cfg['version']='1.1.0';cfg['schema']['database']={'host':'str','user':'str'};cfg['options']['database']={'host':'db'}
        self.assertEqual(pairs(run(cfg,old=old)['breaking']),[('option-removed','database.port'),('required-added','database.user')])
    def test_list_item_keys_use_the_schema_path(self):
        # omnigent's env_vars: a list of {key, value}; list items have no per-item defaults.
        old=new(schema=put('env_vars',[{'key':'match(^[A-Z]+$)','value':'str'}]),options=put('env_vars',[]));old['version']='1.0.0'
        cfg=copy.deepcopy(old);cfg['version']='1.1.0';cfg['schema']['env_vars']=[{'key':'match(^[A-Z]+$)','value':'str','scope':'str'}]
        self.assertEqual(pairs(run(cfg,old=old)['breaking']),[('required-added','env_vars.scope')])
        cfg['schema']['env_vars']=[{'key':'match(^[A-Z]+$)','value':'str','scope':'str?'}]
        self.assertEqual(run(cfg,old=old)['breaking'],[])
    def test_scalar_becoming_a_mapping_is_retyped(self):
        r=run(new(schema=put('db_filter',{'pattern':'str?'})))
        self.assertEqual(pairs(r['breaking']),[('schema-retyped','db_filter')])
    def test_each_blocking_install_row(self):
        rows=[('arch removed',new(arch=['amd64']),[('arch-removed','aarch64')]),
            ('port removed',new(ports=drop('8072/tcp')),[('port-removed','8072/tcp')]),
            ('container port changed',new(ports={'8069/tcp':8069,'8073/tcp':8072}),[('port-removed','8072/tcp')]),
            ('protocol changed',new(ports={'8069/tcp':8069,'8072/udp':8072}),[('port-removed','8072/tcp')]),
            ('image renamed',new(image='ghcr.io/woowtech/other-{arch}'),[('image-changed','image')]),
            ('image dropped for a local build',new(image=None),[('image-changed','image')])]
        for name,cfg,expected in rows:
            with self.subTest(name):
                if cfg['image'] is None:del cfg['image']
                r=run(cfg);self.assertTrue(r['blocked']);self.assertEqual(pairs(r['breaking']),expected)
    def test_report_only_rows_are_listed_but_do_not_block(self):
        rows=[('default changed',new(options=put('workers',4)),('default-changed','workers')),
            ('host port changed',new(ports=put('8072/tcp',9072)),('host-port-changed','8072/tcp'))]
        for name,cfg,expected in rows:
            with self.subTest(name):
                r=run(cfg);self.assertFalse(r['blocked']);self.assertEqual(r['breaking'],[])
                self.assertEqual(pairs(r['notices']),[expected]);self.assertIn(expected[0],r['report'])
    def test_arch_or_port_added_is_silent(self):
        r=run(new(arch=['amd64','aarch64','armv7'],ports=put('9000/tcp',9000)))
        self.assertEqual((r['blocked'],r['breaking'],r['notices']),(False,[],[]))
    REMOVED=staticmethod(lambda:new(options=drop('workers'),schema=drop('workers')))
    def notes(self,version='1.1.0',change='option-removed',key='workers',migration='Set workers in the Odoo config file instead.'):
        return {version:{'breaking':[{'change':change,'key':key,'migration':migration}]}}
    def test_matching_declaration_passes(self):
        r=run(self.REMOVED(),self.notes())
        self.assertFalse(r['blocked']);self.assertEqual(r['breaking'],[{'change':'option-removed','key':'workers','declared':True}])
        self.assertIn('Set workers in the Odoo config file instead.',r['report'])
    def test_misspelled_declaration_blocks_and_is_reported(self):
        for name,kw in [('change',{'change':'option-remove'}),('key',{'key':'worker'})]:
            with self.subTest(name):
                r=run(self.REMOVED(),self.notes(**kw))
                self.assertTrue(r['blocked']);self.assertEqual(r['breaking'],[{'change':'option-removed','key':'workers','declared':False}])
                self.assertEqual(pairs(r['unmatched']),[(kw.get('change','option-removed'),kw.get('key','workers'))])
    def test_only_sections_after_the_target_up_to_the_new_version_count(self):
        for version,blocked in [('1.0.0',True),('0.9.0',True),('1.2.0',True),('1.0.1',False),('1.1.0',False)]:
            with self.subTest(version):self.assertEqual(run(self.REMOVED(),self.notes(version))['blocked'],blocked)
    def test_declaration_without_migration_does_not_count(self):
        for migration in ['','  ',None]:
            with self.subTest(repr(migration)):
                r=run(self.REMOVED(),self.notes(migration=migration))
                self.assertTrue(r['blocked']);self.assertEqual(r['problems'],['1.1.0: option-removed workers has no migration'])
    def test_declaration_with_no_matching_change_is_reported_only(self):
        r=run(new(),self.notes())
        self.assertFalse(r['blocked']);self.assertEqual(pairs(r['unmatched']),[('option-removed','workers')])
        self.assertIn('workers',r['report'])
    def test_undeclared_change_report_has_a_paste_ready_entry(self):
        r=run(self.REMOVED())
        self.assertIn('"1.1.0":'+chr(10)+'  breaking:'+chr(10)+'    - change: option-removed'+chr(10)+'      key: workers'+chr(10)+'      migration:',r['report'])
    def test_malformed_notes_are_an_error(self):
        for name,notes in [('unquoted version key',{1.1:{'breaking':[]}}),('not a mapping',['1.1.0']),
                ('entry without key',{'1.1.0':{'breaking':[{'change':'option-removed','migration':'x'}]}}),
                ('unknown section',{'1.1.0':{'breakng':[]}})]:
            with self.subTest(name):
                with self.assertRaises(ValueError):run(self.REMOVED(),notes)
    def test_no_comparison_target_passes_and_says_so(self):
        r=u.compare(None,new(),old_version=None,new_version='1.1.0')
        self.assertFalse(r['blocked']);self.assertIn('no comparison target',r['report'])
    def test_no_comparison_target_still_needs_a_migration(self):
        # The Release notes (#119) reject an empty migration, so the PR must fail before the merge.
        r=u.compare(None,new(),old_version=None,new_version='1.1.0',notes=self.notes(migration=''))
        self.assertTrue(r['blocked']);self.assertEqual(r['problems'],['1.1.0: option-removed workers has no migration'])
        self.assertIn('no comparison target',r['report']);self.assertIn('has no migration',r['report'])
    def test_version_that_does_not_go_up_is_an_error(self):
        # A comparison target at or above the PR's version (a newer formal Release, or a downgrade from the PR base) is no upgrade.
        for old_version in ('1.1.0','1.2.0'):
            with self.subTest(old_version):
                with self.assertRaisesRegex(ValueError,'not newer than the comparison target'):run(new(),old=dict(BASE,version=old_version),old_version=old_version)
    def test_nonstandard_versions_order_by_their_leading_number(self):
        old=copy.deepcopy(BASE);old['version']='2.12.4-v2'
        cfg=self.REMOVED();cfg['version']='2.12.5-v1'
        for version,blocked in [('2.12.5-v1',False),('2.12.4-v2',True)]:
            with self.subTest(version):self.assertEqual(run(cfg,self.notes(version),old=old,old_version='2.12.4-v2')['blocked'],blocked)
        with self.assertRaises(ValueError):run(cfg,self.notes('2.12.4-beta'),old=old,old_version='2.12.4-v2')
    def test_rebuild_suffix_bumps_order_by_their_suffix_number(self):
        # nginxpm (ref_policy main) bumps only its -v<N> suffix while upstream stays put: 2.12.4-v2 -> 2.12.4-v3.
        old=copy.deepcopy(BASE);old['version']='2.12.4-v2'
        cfg=self.REMOVED();cfg['version']='2.12.4-v3'
        for version,blocked in [('2.12.4-v3',False),('2.12.4-v2',True),('2.12.4-v10',True),('2.12.4',True),('2.12.3-v9',True)]:
            with self.subTest(version):self.assertEqual(run(cfg,self.notes(version),old=old,old_version='2.12.4-v2')['blocked'],blocked)
    def test_haos_core_dash_revision_versions(self):
        # Woow_haos_ha_core (ref_policy main) versions as <HA release>-<revision>: 2026.9.1-1 -> 2026.9.1-2, then 2026.9.2.
        old=copy.deepcopy(BASE);old['version']='2026.9.1-1'
        for new_version,declared,blocked in [('2026.9.1-2','2026.9.1-2',False),('2026.9.1-2','2026.9.1-1',True),
                ('2026.9.2','2026.9.1-2',False),('2026.9.2','2026.9.2-1',True),('2026.9.1-10','2026.9.1-2',False)]:
            cfg=self.REMOVED();cfg['version']=new_version
            with self.subTest(new=new_version,declared=declared):
                self.assertEqual(run(cfg,self.notes(declared),old=old,old_version='2026.9.1-1')['blocked'],blocked)

def match(vid,package,severity='High',state='fixed',versions=('1.2.3',)):
    return {'vulnerability':{'id':vid,'severity':severity,'fix':{'state':state,'versions':list(versions)}},'artifact':{'name':package,'version':'1.0'}}
def db(built='2026-10-27T00:00:00Z'):
    return {'db':{'status':{'schemaVersion':'v6.1.10','built':built,'from':'https://grype.anchore.io/databases/v6/db.tar.zst?checksum=sha256%3A'+'b'*64,'valid':True}}}
def scan(*matches):return {'matches':list(matches),'descriptor':db()}
OLD_SCAN=scan(match('CVE-2026-0001','openssl'))
def vrun(new_scan,old_scan=OLD_SCAN,notes=None):
    return u.compare(BASE,new(),'1.0.0','1.1.0',notes=notes,old_scan=old_scan,new_scan=new_scan)

class Vulnerabilities(unittest.TestCase):
    def test_new_fixable_vulnerability_blocks_and_is_listed(self):
        r=vrun(scan(match('CVE-2026-0001','openssl'),match('CVE-2026-0002','zlib','Critical',versions=('1.3.1','1.4.0'))))
        self.assertTrue(r['blocked'])
        self.assertEqual(r['vulnerabilities']['new_fixable'],[{'id':'CVE-2026-0002','package':'zlib','severity':'Critical','fixed_in':['1.3.1','1.4.0'],'accepted':False}])
        self.assertEqual((r['vulnerabilities']['old_count'],r['vulnerabilities']['new_count']),(1,2))
        self.assertIn('| CVE-2026-0002 | zlib | Critical | 1.3.1, 1.4.0 |',r['report'])
    def test_three_cases_that_do_not_block(self):
        rows=[('already in the old image',match('CVE-2026-0001','openssl',state='fixed'),'already in 1.0.0'),
            ('no fixed version',match('CVE-2026-0003','curl','Critical',state='not-fixed',versions=()),'no fixed version'),
            ('below High',match('CVE-2026-0004','bash','Medium'),'below High')]
        for name,m,reason in rows:
            with self.subTest(name):
                r=vrun(scan(m))
                self.assertFalse(r['blocked']);self.assertEqual(r['vulnerabilities']['new_fixable'],[])
                self.assertIn(reason,r['report'])
    def test_severity_is_compared_case_insensitively(self):
        self.assertTrue(vrun(scan(match('CVE-2026-0005','glibc','HIGH')))['blocked'])
    NEW=staticmethod(lambda:scan(match('CVE-2026-0002','zlib')))
    def accept(self,vid='CVE-2026-0002',package='zlib',reason='Upstream base image not updated yet; replaced in 1.1.1.',version='1.1.0'):
        return {version:{'accepted_vulnerabilities':[{'id':vid,'package':package,'reason':reason}]}}
    def test_accepted_vulnerability_passes_and_shows_the_reason(self):
        r=vrun(self.NEW(),notes=self.accept())
        self.assertFalse(r['blocked']);self.assertTrue(r['vulnerabilities']['new_fixable'][0]['accepted'])
        self.assertIn('Upstream base image not updated yet; replaced in 1.1.1.',r['report'])
    def test_acceptance_needs_the_same_id_and_package_and_a_reason(self):
        for name,kw in [('other id',{'vid':'CVE-2026-9999'}),('other package',{'package':'zlib1g'}),('old section',{'version':'1.0.0'})]:
            with self.subTest(name):self.assertTrue(vrun(self.NEW(),notes=self.accept(**kw))['blocked'])
        for reason in ['',' ',None]:
            with self.subTest(repr(reason)):
                r=vrun(self.NEW(),notes=self.accept(reason=reason))
                self.assertTrue(r['blocked']);self.assertEqual(r['problems'],['1.1.0: accepted CVE-2026-0002 zlib has no reason'])
    def test_acceptance_needs_a_reason_without_a_scan(self):
        # Device-built and skip_vulnerability_scan add-ons are not scanned, but the Release notes still publish the reason.
        for name,old,old_version in [('not scanned',BASE,'1.0.0'),('no comparison target',None,None)]:
            with self.subTest(name):
                r=u.compare(old,new(),old_version,'1.1.0',notes=self.accept(reason=''))
                self.assertTrue(r['blocked']);self.assertEqual(r['problems'],['1.1.0: accepted CVE-2026-0002 zlib has no reason'])
    def test_acceptance_with_no_matching_vulnerability_is_reported_only(self):
        r=vrun(scan(),notes=self.accept())
        self.assertFalse(r['blocked']);self.assertIn('CVE-2026-0002',r['report'])
    def test_blocked_headline_names_the_vulnerability(self):
        self.assertIn('new fixable vulnerability',vrun(self.NEW())['report'].splitlines()[2])
    def test_no_scan_results_says_why(self):
        r=u.compare(BASE,new(),'1.0.0','1.1.0',scan_note='built on the device; compared in #90')
        self.assertFalse(r['blocked']);self.assertIsNone(r['vulnerabilities'])
        self.assertIn('Vulnerability comparison: not run (built on the device; compared in #90).',r['report'])
    def test_one_sided_or_malformed_scans_are_an_error(self):
        rows=[('old scan missing',None,self.NEW()),('new scan missing',OLD_SCAN,None),('not Grype JSON',OLD_SCAN,{'results':[]}),
            ('match without id',OLD_SCAN,scan({'vulnerability':{'severity':'High'},'artifact':{'name':'zlib'}}))]
        for name,old_scan,new_scan in rows:
            with self.subTest(name):
                with self.assertRaises(ValueError):vrun(new_scan,old_scan=old_scan)
    def test_scans_from_different_databases_are_an_error(self):
        self.assertFalse(vrun(scan())['blocked'])
        with self.assertRaises(ValueError):vrun(dict(scan(),descriptor=db('2026-10-26T00:00:00Z')))
    def test_scan_without_database_info_is_an_error(self):
        # Without descriptor.db there is no proof both images were scanned with the same DB.
        for name,descriptor in [('no descriptor',None),('no db',{}),('empty status',{'db':{'status':{}}}),
                ('descriptor not a mapping','x'),('db not a mapping',{'db':[]}),('status not a mapping',{'db':{'status':'ok'}})]:
            without=lambda s:{'matches':s['matches']} if descriptor is None else dict(s,descriptor=descriptor)
            for side,new_scan,old_scan in [('old',scan(),without(OLD_SCAN)),('new',without(scan()),OLD_SCAN),('both',without(scan()),without(OLD_SCAN))]:
                with self.subTest(name,side=side):
                    with self.assertRaises(ValueError):vrun(new_scan,old_scan=old_scan)
    def test_duplicate_matches_do_not_depend_on_order(self):
        # Grype reports a pair once per location; any qualifying match makes it new fixable, with that match's details.
        rows=[('not fixed and fixed',match('CVE-2026-0002','zlib','Critical',state='not-fixed',versions=()),match('CVE-2026-0002','zlib',versions=('1.3.1',)),
                [{'id':'CVE-2026-0002','package':'zlib','severity':'High','fixed_in':['1.3.1'],'accepted':False}]),
            ('below High and Critical',match('CVE-2026-0002','zlib','Low'),match('CVE-2026-0002','zlib','Critical',versions=('1.3.1',)),
                [{'id':'CVE-2026-0002','package':'zlib','severity':'Critical','fixed_in':['1.3.1'],'accepted':False}]),
            ('below High and not fixed',match('CVE-2026-0002','zlib','Low'),match('CVE-2026-0002','zlib','Critical',state='not-fixed',versions=()),[]),
            ('below High and upper-case HIGH',match('CVE-2026-0002','zlib','Low',versions=('1.3.1',)),match('CVE-2026-0002','zlib','HIGH',versions=('1.3.1',)),
                [{'id':'CVE-2026-0002','package':'zlib','severity':'HIGH','fixed_in':['1.3.1'],'accepted':False}])]
        for name,a,b,fixable in rows:
            with self.subTest(name):
                ab,ba=vrun(scan(a,b))['vulnerabilities'],vrun(scan(b,a))['vulnerabilities']
                self.assertEqual(ab,ba);self.assertEqual(ab['new_fixable'],fixable);self.assertEqual(ab['new_count'],1)
    def test_no_comparison_target_with_a_scan_passes(self):
        r=u.compare(None,new(),None,'1.1.0',new_scan=self.NEW())
        self.assertFalse(r['blocked']);self.assertIn('no comparison target',r['report'])

class CommandLine(unittest.TestCase):
    def setUp(self):
        self.dir=pathlib.Path(tempfile.mkdtemp());self.summary=self.dir/'summary.md'
        self.addCleanup(shutil.rmtree,self.dir)
    def write(self,name,data):
        path=self.dir/name;path.write_text(data if isinstance(data,str) else yaml.safe_dump(data),encoding='utf-8');return str(path)
    def main(self,*args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code=u.main(['compare','--summary',str(self.summary),*args])
        return code,out.getvalue()
    def test_blocked_comparison_exits_1_and_writes_the_summary(self):
        code,out=self.main('--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new(schema=drop('db_filter'))))
        self.assertEqual(code,1);self.assertIn('schema-removed',self.summary.read_text(encoding='utf-8'))
        self.assertIn('::error',out)
    def test_declared_change_and_missing_notes_file(self):
        cfg=new(schema=drop('db_filter'));notes={'1.1.0':{'breaking':[{'change':'schema-removed','key':'db_filter','migration':'Use the list filter.'}]}}
        args=['--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',cfg)]
        self.assertEqual(self.main(*args,'--notes',self.write('notes.yaml',notes))[0],0)
        self.assertEqual(self.main(*args,'--notes',str(self.dir/'absent.yaml'))[0],1)
    def test_without_old_config_there_is_no_comparison_target(self):
        self.assertEqual(self.main('--new',self.write('new.yaml',new()))[0],0)
        self.assertIn('no comparison target',self.summary.read_text(encoding='utf-8'))
    def test_malformed_notes_exit_2(self):
        code,out=self.main('--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new()),'--notes',self.write('notes.yaml','1.1: {}\n'))
        self.assertEqual(code,2);self.assertIn('quoted string',out)
    def test_new_fixable_vulnerability_exits_1_with_an_annotation(self):
        import json
        args=['--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new()),'--old-scan',self.write('old.json',json.dumps(OLD_SCAN))]
        code,out=self.main(*args,'--new-scan',self.write('new.json',json.dumps(scan(match('CVE-2026-0002','zlib')))))
        self.assertEqual(code,1);self.assertIn('::error title=New fixable vulnerability::CVE-2026-0002 zlib',out)
        self.assertIn('CVE-2026-0002',self.summary.read_text(encoding='utf-8'))
        self.assertEqual(self.main(*args,'--new-scan',self.write('bad.json','{}'))[0],2)
    def test_scan_note_explains_a_skipped_comparison(self):
        self.main('--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new()),'--scan-note','built on the device; compared in #90')
        self.assertIn('not run (built on the device; compared in #90)',self.summary.read_text(encoding='utf-8'))
    def commands(self,out):
        # Workflow commands GitHub would run: everything between ::stop-commands::<token> and ::<token>:: is plain text.
        lines=[];stop=None
        for line in out.splitlines():
            if stop:stop=None if line=='::'+stop+'::' else stop
            elif line.startswith('::stop-commands::'):stop=line.split('::',2)[2]
            elif line.startswith('::'):lines.append(line)
        return lines
    def test_pr_controlled_text_cannot_inject_a_workflow_command(self):
        # upgrade-notes.yaml keys and values come from the PR: a newline in them must not start a new workflow command.
        evil='x\n::warning title=Injected::boom'
        notes={'1.1.0':{'breaking':[{'change':'option-removed','key':evil,'migration':''}]}}
        code,out=self.main('--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new()),'--notes',self.write('notes.yaml',notes))
        self.assertEqual(code,1);(line,)=self.commands(out)
        self.assertTrue(line.startswith('::error title=Invalid declaration::'));self.assertIn('x%0A::warning',line)
    def test_error_text_is_escaped(self):
        code,out=self.main('--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new()),'--name','a,b:c','--notes',self.write('notes.yaml','{"1.1.0": {"breaking": [{"change": "x"}]}}\n'))
        self.assertEqual(code,2);(line,)=self.commands(out)
        self.assertTrue(line.startswith('::error title=Upgrade comparison failed::a,b:c: '),line)
        code,out=self.main('--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new()),'--notes',self.write('notes.yaml','"1.1.0":\n  "50%\\nbreaking": []\n'))
        self.assertEqual(code,2);(line,)=self.commands(out);self.assertIn("unknown section '50%25",line)
class MarkdownCells(unittest.TestCase):
    """Text from the PR goes into Markdown table cells: a | or a newline must not break the row."""
    def test_migration_and_key_are_escaped(self):
        old=new(schema=put('a|b','str?'));old['version']='1.0.0'
        cfg=copy.deepcopy(old);cfg['version']='1.1.0';del cfg['schema']['a|b']
        r=run(cfg,{'1.1.0':{'breaking':[{'change':'schema-removed','key':'a|b','migration':'Use x | y.\nThen restart.'}]}},old=old)
        self.assertFalse(r['blocked'])
        self.assertIn('| `schema-removed` | `a\\|b` | yes | Use x \\| y.<br>Then restart. |',r['report'])
    def test_acceptance_reason_is_escaped(self):
        r=vrun(scan(match('CVE-2026-0002','zlib')),notes={'1.1.0':{'accepted_vulnerabilities':[{'id':'CVE-2026-0002','package':'zlib','reason':'a | b\nc'}]}})
        self.assertIn('| CVE-2026-0002 | zlib | High | 1.2.3 | a \\| b<br>c |',r['report'])
# The spec's example declarations: what users read on the Release page.
NOTES={'1.3.0':{'breaking':[{'change':'option-removed','key':'ssl_port','migration':'改用 ports 設定的 443/tcp。'}],
    'accepted_vulnerabilities':[{'id':'CVE-2026-1234','package':'openssl','reason':'上游 base image 還沒更新，預計 1.3.1 換掉。'}]}}
class ReleaseNotes(unittest.TestCase):
    def test_both_sections(self):
        self.assertEqual(u.release_notes(NOTES,'1.3.0',released=['1.2.0']),
            '## 破壞性變更與遷移方式\n\n- `option-removed` `ssl_port`（1.3.0）：改用 ports 設定的 443/tcp。\n\n'
            '## 已接受的漏洞\n\n- CVE-2026-1234（openssl，1.3.0）：上游 base image 還沒更新，預計 1.3.1 換掉。\n')
    def test_only_one_section(self):
        for section,title,other in [('breaking','## 破壞性變更與遷移方式','已接受的漏洞'),('accepted_vulnerabilities','## 已接受的漏洞','破壞性變更')]:
            with self.subTest(section):
                text=u.release_notes({'1.3.0':{section:NOTES['1.3.0'][section]}},'1.3.0',released=['1.2.0'])
                self.assertTrue(text.startswith(title+'\n\n- '));self.assertNotIn(other,text)
    def test_nothing_declared_adds_nothing(self):
        for name,notes in [('no file',None),('empty file',{}),('empty sections',{'1.3.0':{'breaking':[]}}),
                ('only an already released version',{'1.2.0':NOTES['1.3.0']}),('only a later version',{'1.4.0':NOTES['1.3.0']})]:
            with self.subTest(name):self.assertEqual(u.release_notes(notes,'1.3.0',released=['1.1.0','1.2.0']),'')
    def test_versions_since_the_last_formal_release_all_count(self):
        # 1.2.1 never got a Release, so its declarations belong to the 1.3.0 Release; 1.2.0's were on its own page.
        notes={'1.2.0':{'breaking':[dict(NOTES['1.3.0']['breaking'][0],key='old_port')]},'1.2.1':{'breaking':[dict(NOTES['1.3.0']['breaking'][0],key='mid_port')]},**NOTES}
        text=u.release_notes(notes,'1.3.0',released=['1.1.0','1.2.0','1.3.0'])
        self.assertIn('`mid_port`（1.2.1）',text);self.assertIn('`ssl_port`（1.3.0）',text);self.assertNotIn('old_port',text)
        self.assertIn('old_port',u.release_notes(notes,'1.3.0'))
    def test_a_released_tag_that_is_not_a_version_is_ignored(self):
        # A stray tag on the Releases page must not block the Release it has nothing to do with.
        self.assertEqual(u.release_notes(NOTES,'1.3.0',released=['1.2.0','nightly']),u.release_notes(NOTES,'1.3.0',released=['1.2.0']))
    def test_a_newer_formal_release_is_an_error(self):
        # The PR check compares with the latest formal Release; the notes must not quietly use an older one instead.
        with self.assertRaisesRegex(ValueError,'1.3.0 is not newer than the comparison target 1.4.0'):u.release_notes(NOTES,'1.3.0',released=['1.2.0','1.4.0'])
    def test_multiline_text_stays_inside_its_bullet(self):
        notes={'1.3.0':{'breaking':[dict(NOTES['1.3.0']['breaking'][0],migration='第一步。\n第二步。\n')]}}
        self.assertIn('：第一步。\n  第二步。\n',u.release_notes(notes,'1.3.0'))
    def test_empty_migration_or_reason_is_an_error(self):
        for section,field in [('breaking','migration'),('accepted_vulnerabilities','reason')]:
            with self.subTest(section):
                with self.assertRaises(ValueError):u.release_notes({'1.3.0':{section:[dict(NOTES['1.3.0'][section][0],**{field:' '})]}},'1.3.0')
class LatestRelease(unittest.TestCase):
    """The PR check's comparison target and the Release notes' window use one ordering: version_cmp."""
    def test_addon_sync_does_not_import_this_module(self):
        # One direction only: upgrade_check uses addon_sync's Release rules, addon_sync never needs upgrade_check.
        import subprocess,sys
        r=subprocess.run([sys.executable,'-c',"import sys,addon_sync;print('upgrade_check' in sys.modules)"],cwd=pathlib.Path(__file__).resolve().parent,capture_output=True,text=True)
        self.assertEqual(r.stdout.strip(),'False',r.stderr)
    def test_orders_with_version_cmp_where_sort_v_disagrees(self):
        # sort -V puts 1.2.0rc1 after 1.2.0 and 2026.9.1-10 is fine either way; PEP 440 says rc1 comes first.
        self.assertEqual(u.comparison_target(['1.2.0rc1','1.2.0','1.1.9']),'1.2.0')
        self.assertEqual(u.comparison_target(['2.12.4-v9','2.12.4-v10','2.12.4']),'2.12.4-v10')
        self.assertEqual(u.comparison_target(['1.9.0','1.10.0','nightly']),'1.10.0')
        self.assertIsNone(u.comparison_target(['nightly']));self.assertIsNone(u.comparison_target([]))
    def main(self,releases,component,components=('t',),version=None):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d)
        (d/'registry.json').write_text(json.dumps({'providers':{'WOOWTECH/r':{'components':[{'id':c} for c in components]}}}))
        stdin=releases if isinstance(releases,str) else json.dumps([r if isinstance(r,dict) else {'tag_name':r,'draft':False,'prerelease':False} for r in releases])
        with contextlib.redirect_stdout(io.StringIO()) as out,unittest.mock.patch('sys.stdin',io.StringIO(stdin)):
            code=u.main(['latest-release','--registry',str(d/'registry.json'),'--repo','WOOWTECH/r','--component',component]+(['--version',version] if version else []))
        return code,out.getvalue()
    def test_prints_the_tag_of_the_latest_formal_release(self):
        self.assertEqual(self.main(['v1.2.0rc1','v1.2.0','v1.1.0'],'t'),(0,'v1.2.0\n'))
        self.assertEqual(self.main([],'t'),(0,''))
    def test_drafts_prereleases_and_other_prefixes_are_not_formal_releases(self):
        releases=[{'tag_name':'v2.0.0','draft':True,'prerelease':False},{'tag_name':'v1.9.0','draft':False,'prerelease':True},'x-v3.0.0','v1.1.0']
        self.assertEqual(self.main(releases,'t'),(0,'v1.1.0\n'))
        self.assertEqual(self.main(releases[:3],'t'),(0,''))
    def test_version_must_be_newer_than_the_latest_formal_release(self):
        # --version applies the Release notes' rule: the target is the latest formal Release, and it must be older.
        self.assertEqual(self.main(['v1.2.0','v1.1.0'],'t',version='1.3.0'),(0,'v1.2.0\n'))
        self.assertEqual(self.main([],'t',version='1.3.0'),(0,''))
        for version in ('1.2.0','1.1.5'):
            with self.subTest(version):
                code,out=self.main(['v1.2.0','v1.1.0'],'t',version=version)
                self.assertEqual(code,2);self.assertTrue(out.startswith('::error title=Upgrade comparison failed::'),out);self.assertIn('comparison target 1.2.0',out)
    def test_tag_rule_is_addon_syncs(self):
        # v<ver> for a single add-on, <slug>-v<ver> when the repository has several (addon_sync.release_tag).
        releases=['v9.0.0','woow_ha_core-v2.4.0','woow_ha_core_2-v2.3.0','woow_ha_core_2-v2.2.0']
        both=('woow_ha_core','woow_ha_core_2')
        self.assertEqual(self.main(releases,'woow_ha_core_2',both),(0,'woow_ha_core_2-v2.3.0\n'))
        self.assertEqual(self.main(releases,'woow_ha_core',both),(0,'woow_ha_core-v2.4.0\n'))
        self.assertEqual(self.main(releases,'t'),(0,'v9.0.0\n'))
    def test_unknown_component_or_bad_input_exits_2(self):
        for releases,component in [(['v1.0.0'],'other'),('not json','t'),('{}','t')]:
            with self.subTest(component=component,releases=releases):
                code,out=self.main(releases,component)
                self.assertEqual(code,2);self.assertTrue(out.startswith('::error title=Upgrade comparison failed::'),out)
    def test_workflow_leaves_the_filter_and_tag_rule_to_python(self):
        wf=yaml.safe_load((pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/woow-addon-upgrade-check.yml').read_text(encoding='utf-8'))
        plan=next(s for s in wf['jobs']['compare']['steps'] if s.get('id')=='plan')['run']
        self.assertIn('upgrade_check.py latest-release --registry',plan)
        for duplicate in ('sort -V','prerelease','draft','-v"','prefix='):
            with self.subTest(duplicate):self.assertNotIn(duplicate,plan)
class ReleaseNotesCommand(unittest.TestCase):
    """The exact invocation Woow_ha_odoo's release.yml uses."""
    def setUp(self):
        self.dir=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.dir)
    def main(self,*args):
        with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(['release-notes',*args])
        return code,out.getvalue()
    def test_prints_the_sections_for_the_version(self):
        path=self.dir/'upgrade-notes.yaml';path.write_text(yaml.safe_dump(NOTES,allow_unicode=True),encoding='utf-8')
        self.assertEqual(self.main('--notes',str(path),'--version','1.3.0','--released','1.1.0','1.2.0'),(0,u.release_notes(NOTES,'1.3.0')))
    def test_missing_notes_file_prints_nothing(self):
        self.assertEqual(self.main('--notes',str(self.dir/'absent.yaml'),'--version','1.3.0','--released'),(0,''))
    def test_malformed_notes_exit_2(self):
        path=self.dir/'upgrade-notes.yaml';path.write_text('1.3: {}\n',encoding='utf-8')
        code,out=self.main('--notes',str(path),'--version','1.3.0')
        self.assertEqual(code,2);self.assertIn('::error',out)
class ComponentsCommand(unittest.TestCase):
    """What the reusable workflow reads from the registry; the paths follow addon_sync.source_file, as the Release does."""
    def main(self,registry,repo='WOOWTECH/r'):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d);(d/'registry.json').write_text(json.dumps(registry))
        with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(['components','--registry',str(d/'registry.json'),'--repo',repo])
        return code,out.getvalue()
    def test_paths_policy_and_approved_skip(self):
        comps=[{'id':'a','source_path':'.','config_file':'config.yaml'},{'id':'b','source_path':'addons/b','config_file':'config.yml'}]
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'main','components':comps,'upgrade_comparison':{'skip_vulnerability_scan':'#1: why'}}}})
        self.assertEqual(code,0);self.assertEqual(json.loads(out),{'ref_policy':'main','skip_vulnerability_scan':'#1: why','components':[
            {'id':'a','config':'config.yaml','notes':'upgrade-notes.yaml'},{'id':'b','config':'addons/b/config.yml','notes':'addons/b/upgrade-notes.yaml'}]})
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps}}})
        self.assertEqual(json.loads(out)['skip_vulnerability_scan'],'')
    def test_unknown_repository_or_unsafe_path_exits_2(self):
        for name,registry in [('unknown',{'providers':{}}),('unsafe',{'providers':{'WOOWTECH/r':{'ref_policy':'release','components':[{'id':'a','source_path':'../x','config_file':'config.yaml'}]}}})]:
            with self.subTest(name):
                code,out=self.main(registry)
                self.assertEqual(code,2);self.assertTrue(out.startswith('::error title=Upgrade comparison failed::WOOWTECH/r: '),out)
class ReusableWorkflow(unittest.TestCase):
    """Shape that callers and the ruleset depend on; the shell itself is verified on pilot PRs (#89 Testing Decisions)."""
    def setUp(self):
        path=pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/woow-addon-upgrade-check.yml'
        self.text=path.read_text(encoding='utf-8');self.wf=yaml.safe_load(self.text)
    def test_single_compare_job_reports_on_every_event(self):
        # The required check is "Upgrade comparison / compare": caller job name / this job's name.
        self.assertIn('workflow_call',self.wf['on']);self.assertEqual(list(self.wf['jobs']),['compare'])
        job=self.wf['jobs']['compare'];self.assertEqual(job['name'],'compare');self.assertNotIn('if',job)
        # actions: read lets the job find this run's SBOM artifact without `needs:` on the build (user story 5).
        self.assertEqual(self.wf['permissions'],{'contents':'read','actions':'read'})
    def test_store_tooling_is_tested_in_store_ci_not_in_every_source_pr(self):
        steps=self.wf['jobs']['compare']['steps']
        tooling=[s for s in steps if s.get('with',{}).get('repository')=='WOOWTECH/Woow_HA_App_Store'][0]['with']
        self.assertEqual((tooling['ref'],tooling['persist-credentials']),('${{ inputs.tooling_ref }}',False))
        # The tooling's tests run in the Store's own CI before a change reaches main, not in each source repo's PRs.
        self.assertNotIn('test_',self.text)
        ci=yaml.safe_load((pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/upgrade-check-tests.yml').read_text(encoding='utf-8'))
        self.assertIn('python3 .addon-sync/test_upgrade_check.py -v',[s.get('run') for s in ci['jobs']['test']['steps']])
    def test_no_secrets_beyond_the_job_token(self):
        self.assertNotIn('secrets.',self.text)
    def test_db_is_updated_once_before_scanning_and_has_an_age_limit(self):
        steps=self.wf['jobs']['compare']['steps'];runs=[s.get('run','') for s in steps]
        update=next(i for i,r in enumerate(runs) if 'grype" db update' in r);compare=next(i for i,r in enumerate(runs) if 'upgrade_check.py compare' in r)
        self.assertLess(update,compare);self.assertIn('GRYPE_DB_AUTO_UPDATE=false',runs[compare])
        self.assertEqual(self.wf['jobs']['compare']['env']['DB_MAX_AGE_HOURS'],'120')
    def test_new_sbom_is_awaited_in_the_same_run_not_through_needs(self):
        # A no-version-change PR must not wait on the caller's build; only a version change waits for the SBOM,
        # bounded by sbom_wait_minutes, and the download comes after the wait.
        steps=self.wf['jobs']['compare']['steps'];names=[s.get('name','') for s in steps]
        wait=names.index("Wait for the new images' SBOMs");download=names.index("Download the new images' SBOMs")
        self.assertLess(wait,download)
        self.assertIn("steps.detect.outputs.changed == 'true'",steps[wait]['if'])
        self.assertIn('actions/runs/${RUN_ID}/artifacts',steps[wait]['run'])
        self.assertEqual(self.wf['on']['workflow_call']['inputs']['sbom_wait_minutes']['default'],40)
        self.assertGreater(self.wf['jobs']['compare']['timeout-minutes'],40)
    def test_ref_policy_main_compares_with_the_pr_base(self):
        # apporo_ha_multi_ha_core, Woow_haos_ha_core, nginxpm have no formal Release: the Store follows main (#121).
        plan=self.step('Find the comparison targets')
        self.assertRegex(plan,r'if \[ "\$\{policy\}" = "main" \]; then\s+(#.*\s+)*target="\$\{BASE_SHA\}"')
        self.assertEqual(self.step_env('Find the comparison targets')['BASE_SHA'],'${{ github.event.pull_request.base.sha }}')
    def test_only_add_ons_whose_version_changed_are_compared(self):
        # Multi-add-on repositories: an add-on whose version is unchanged is listed as unchanged and never compared.
        detect=self.step('Find add-ons whose version changed')
        self.assertIn('if [ "${current}" != "${previous}" ]; then',detect)
        self.assertLess(detect.index('>> changed.jsonl'),detect.index('version ${current} unchanged'))
        self.assertIn('done < changed.jsonl',self.step('Find the comparison targets'))
        self.assertIn('done < plan.jsonl',self.step('Compare with the comparison target'))
    def test_registry_lookup_and_paths_are_left_to_python(self):
        # One implementation of the registry layout and the source_path/'.' rule: addon_sync, through `components`.
        self.assertIn('upgrade_check.py components --registry',self.step('Find add-ons whose version changed'))
        for duplicate in ('.providers[','source_path','config_file','upgrade-notes.yaml"','[ "${dir}" = "." ]'):
            with self.subTest(duplicate):self.assertNotIn(duplicate,self.text.split('jobs:',1)[1])
    def test_device_built_add_ons_are_reported_as_compared_in_90(self):
        self.assertIn('built on the device; the vulnerability comparison for these add-ons is #90',self.step('Find the comparison targets'))
    def step(self,name):return next(s for s in self.wf['jobs']['compare']['steps'] if s.get('name')==name)['run']
    def step_env(self,name):return next(s for s in self.wf['jobs']['compare']['steps'] if s.get('name')==name)['env']
SHELL_TOOLS=all(shutil.which(t) for t in ('bash','jq','yq'))
needs_shell=unittest.skipUnless(SHELL_TOOLS,'needs bash, jq and yq (present on GitHub runners)')
class StepHarness(unittest.TestCase):
    """Runs a real step script of the reusable workflow against a fake repository, gh stubbed (bash, jq, yq: CI runners)."""
    STORE=pathlib.Path(__file__).resolve().parent.parent
    WF=STORE/'.github/workflows/woow-addon-upgrade-check.yml'
    def setUp(self):self.wf=yaml.safe_load(self.WF.read_text(encoding='utf-8'))
    def step(self,ident):return next(s for s in self.wf['jobs']['compare']['steps'] if ident in (s.get('id'),s.get('name')))
    def run_step(self,ident,*,policy='release',extra=None,releases=('v1.0.0',),old_config=True,new_config=True,skip='',sbom='',version='1.1.0',old=None):
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'tooling/.addon-sync').mkdir(parents=True);(tmp/'source/addon').mkdir(parents=True);(tmp/'bin').mkdir()
        for f in (self.STORE/'.addon-sync').iterdir():
            if f.suffix in ('.py','.sh'):shutil.copy(f,tmp/'tooling/.addon-sync'/f.name)
        (tmp/'tooling/.addon-sync/registry.json').write_text(json.dumps({'providers':{'WOOWTECH/t':{'ref_policy':policy,'components':[
            {'id':'t','source_path':'addon','config_file':'config.yaml'}],**(extra or {})}}}))
        cfg=dict(BASE,image='ghcr.io/da-anda/addon-{arch}')
        if new_config:(tmp/'source/addon/config.yaml').write_text(yaml.safe_dump(dict(cfg,version=version)))
        (tmp/'old.yaml').write_text(yaml.safe_dump(dict(cfg,**(old or {}))) if old_config else '')
        with contextlib.redirect_stdout(io.StringIO()) as provider:
            self.assertEqual(u.main(['components','--registry',str(tmp/'tooling/.addon-sync/registry.json'),'--repo','WOOWTECH/t']),0)
        (tmp/'provider.json').write_text(provider.getvalue())
        (tmp/'changed.jsonl').write_text(json.dumps({'id':'t','config':'addon/config.yaml','notes':'addon/upgrade-notes.yaml','version':'1.1.0'})+'\n')
        gh=tmp/'bin/gh'
        gh.write_text('#!/bin/bash\ncase "$*" in\n  *releases*) [ -z "$RELEASES" ] || printf "%s\\n" "$RELEASES";;\n'
            '  *contents*) if [ -s "$OLD" ]; then cat "$OLD"; else echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi;;\n  *) exit 1;;\nesac\n')
        gh.chmod(0o755)
        # What `gh api --paginate .../releases --jq '.[]'` prints: one Release object per line; a bare tag is a formal Release.
        releases='\n'.join(json.dumps(r if isinstance(r,dict) else {'tag_name':r,'draft':False,'prerelease':False}) for r in releases)
        env=dict(os.environ,PATH=f"{tmp/'bin'}{os.pathsep}{os.environ['PATH']}",OLD=str(tmp/'old.yaml'),RELEASES=releases,REPO='WOOWTECH/t',BASE_SHA='b',
            GH_TOKEN='x',SBOM_ARTIFACT=sbom,SKIP_VULNERABILITY_SCAN=skip,RUNNER_TEMP=str(tmp),RUN_ATTEMPT='1',
            GITHUB_OUTPUT=str(tmp/'out'),GITHUB_STEP_SUMMARY=str(tmp/'summary'))
        (tmp/'step.sh').write_text(self.step(ident)['run'])
        r=subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=env,capture_output=True,text=True)
        plan=json.loads((tmp/'plan.jsonl').read_text().splitlines()[0]) if (tmp/'plan.jsonl').exists() and (tmp/'plan.jsonl').read_text() else {}
        return r,plan,(tmp/'out').read_text() if (tmp/'out').exists() else ''

class SkipVulnerabilityScan(StepHarness):
    """skip_vulnerability_scan: a caller whose prebuilt image is not the one it builds (knxd ships a third-party image),
    or whose category 4 moved elsewhere, opts out with a reason; category 1 still runs and the report says why.
    Only a provider the Store registry approves may skip (upgrade_comparison.skip_vulnerability_scan, with the reason)."""
    REASON='the shipped image is third-party; category 4 for it is out of scope'
    APPROVED={'upgrade_comparison':{'skip_vulnerability_scan':'#122: third-party image; category 4 moves to #90'}}
    def test_optional_string_input_that_defaults_to_scanning(self):
        inp=self.wf['on']['workflow_call']['inputs']['skip_vulnerability_scan']
        self.assertEqual((inp['type'],inp['default']),('string',''))
        for ident in ('detect','plan'):
            with self.subTest(ident):self.assertEqual(self.step(ident)['env']['SKIP_VULNERABILITY_SCAN'],'${{ inputs.skip_vulnerability_scan }}')
    def test_registry_approves_the_skip_only_for_knxd_and_mcp_addons(self):
        # #122 (knxd ships a third-party image) and #123 (mcp_addons builds no PR image): category 4 moves to #90.
        registry=json.loads((self.STORE/'.addon-sync/registry.json').read_text(encoding='utf-8'))
        approved={repo:p['upgrade_comparison']['skip_vulnerability_scan'] for repo,p in registry['providers'].items()
            if 'skip_vulnerability_scan' in (p.get('upgrade_comparison') or {})}
        self.assertEqual(sorted(approved),['WOOWTECH/Woow_ha_knxd_add_on','WOOWTECH/Woow_ha_mcp_addons'])
        self.assertIn('#122',approved['WOOWTECH/Woow_ha_knxd_add_on']);self.assertIn('#123',approved['WOOWTECH/Woow_ha_mcp_addons'])
        for reason in approved.values():self.assertIn('#90',reason)
    @needs_shell
    def test_unapproved_provider_that_sets_the_skip_fails(self):
        r,_,_=self.run_step('detect',skip=self.REASON)
        self.assertEqual(r.returncode,1);self.assertIn('not approved',r.stdout+r.stderr)
    @needs_shell
    def test_approved_provider_may_skip(self):
        r,_,out=self.run_step('detect',skip=self.REASON,extra=self.APPROVED)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('changed=true',out)
    @needs_shell
    def test_skip_drops_category_4_and_reports_the_reason(self):
        r,plan,out=self.run_step('plan',skip=self.REASON,extra=self.APPROVED)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        # target still found (category 1 runs), no image ref to scan; the report's scan note is the registry's approved
        # reason, not the caller's text (owner decision: skip only where approved, and the report says why).
        note=f"skipped as approved in the Store registry: {self.APPROVED['upgrade_comparison']['skip_vulnerability_scan']}"
        self.assertEqual([plan['target'],plan['ref'],plan['note']],['v1.0.0','',note]);self.assertIn('scan=false',out)
    @needs_shell
    def test_without_skip_a_prebuilt_image_still_needs_its_sbom(self):
        r,_,_=self.run_step('plan')
        self.assertEqual(r.returncode,1);self.assertIn('passes no sbom_artifact',r.stdout+r.stderr)

class ComparisonTarget(StepHarness):
    """"No comparison target" only when there is no formal Release (or, for ref_policy main, no config at the PR base)."""
    @needs_shell
    def test_release_whose_config_cannot_be_read_fails(self):
        r,plan,_=self.run_step('plan',old_config=False,skip='x')
        self.assertEqual(r.returncode,1);self.assertIn('v1.0.0 has no addon/config.yaml',r.stdout+r.stderr);self.assertEqual(plan,{})
    @needs_shell
    def test_no_formal_release_has_no_comparison_target(self):
        r,plan,_=self.run_step('plan',releases=(),old_config=False)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual([plan['target'],plan['ref'],plan['note']],['','','no comparison target'])
    @needs_shell
    def test_config_deleted_or_moved_by_the_pr_fails(self):
        # Spec: a tool error fails the check; a registry add-on whose config the PR removes is not "unchanged".
        r,_,_=self.run_step('detect',new_config=False)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('this PR deletes or moves addon/config.yaml',r.stdout)
    @needs_shell
    def test_config_absent_in_the_pr_and_its_base_is_not_compared(self):
        r,_,out=self.run_step('detect',new_config=False,old_config=False)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('changed=false',out)
    @needs_shell
    def test_ref_policy_main_without_config_at_the_base_is_a_new_add_on(self):
        r,plan,_=self.run_step('plan',policy='main',old_config=False)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual([plan['target'],plan['ref'],plan['note']],['b','','no comparison target'])
    @needs_shell
    def test_latest_release_is_ordered_like_the_release_notes(self):
        # sort -V would pick v1.0.0rc1; version_cmp (PEP 440) puts the rc before 1.0.0.
        r,plan,_=self.run_step('plan',releases=('v0.9.0','v1.0.0','v1.0.0rc1'),skip='x')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'v1.0.0')
    @needs_shell
    def test_version_not_newer_than_the_target_fails_when_the_target_is_chosen(self):
        # The Release notes' rule (addon_sync.comparison_target): the PR's version must go up from the latest formal Release.
        r,plan,_=self.run_step('plan',releases=('v1.0.0','v1.2.0'),skip='x')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('comparison target 1.2.0',r.stdout);self.assertEqual(plan,{})
    @needs_shell
    def test_drafts_and_prereleases_are_not_comparison_targets(self):
        releases=('v1.0.0',{'tag_name':'v1.2.0','draft':True,'prerelease':False},{'tag_name':'v1.1.0','draft':False,'prerelease':True})
        r,plan,_=self.run_step('plan',releases=releases,skip='x')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'v1.0.0')
    @needs_shell
    def test_multi_add_on_repository_uses_the_slug_tag(self):
        comps=[{'id':i,'source_path':'addon','config_file':'config.yaml'} for i in ('t','t_2')]
        r,plan,_=self.run_step('plan',extra={'components':comps},releases=('v9.0.0','t_2-v2.0.0','t-v1.0.0'),skip='x')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'t-v1.0.0')
    @needs_shell
    def test_version_with_a_newline_is_rejected_before_it_reaches_the_log(self):
        r,_,_=self.run_step('detect',version='1.1.0\n::warning title=Injected::boom')
        self.assertEqual(r.returncode,1);self.assertIn('contains a control character',r.stdout)
        self.assertEqual([l for l in r.stdout.splitlines() if l.startswith('::') and not l.startswith('::error title=Upgrade comparison failed::')],[])
    @needs_shell
    def test_target_image_or_version_with_a_newline_is_rejected(self):
        # The comparison target's config was released earlier, but a newline in it is still refused before use.
        for key,value in [('image','ghcr.io/x/a-{arch}\n::warning title=Injected::boom'),('version','1.0.0\n::warning title=Injected::boom')]:
            with self.subTest(key):
                r,plan,_=self.run_step('plan',old={key:value},sbom='*')
                self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('control character',r.stdout);self.assertEqual(plan,{})
                self.assertEqual([l for l in r.stdout.splitlines() if l.startswith('::') and not l.startswith('::error title=Upgrade comparison failed::')],[])
    def test_the_raw_file_fetch_is_defined_once(self):
        text=self.WF.read_text(encoding='utf-8')
        self.assertNotIn('fetch() {',text);self.assertTrue((self.STORE/'.addon-sync/gh_raw.sh').exists())
        for ident in ('detect','plan'):
            with self.subTest(ident):self.assertIn('source tooling/.addon-sync/gh_raw.sh',self.step(ident)['run'])
    def test_each_step_sources_exactly_the_helpers_it_uses(self):
        import re
        for step in self.wf['jobs']['compare']['steps']:
            run=step.get('run','')
            for helper,use in [('gh_raw.sh',r'\bfetch '),('log.sh',r'\b(esc|fail) "')]:
                with self.subTest(step=step.get('name'),helper=helper):
                    self.assertEqual('source tooling/.addon-sync/'+helper in run,bool(re.search(use,run)))

class LogEscaping(StepHarness):
    """Values from the PR or its Releases are echoed through esc (log.sh), the escaping addon_sync.annotation uses."""
    PR_VALUES=('version','current','target','ref','SBOM_ARTIFACT','SKIP_VULNERABILITY_SCAN','old_image','old_version','image')
    @unittest.skipUnless(shutil.which('bash'),'needs bash')
    def test_esc_matches_annotation(self):
        import subprocess,addon_sync
        text='50%\r\n::warning title=Injected::boom\n'
        r=subprocess.run([shutil.which('bash'),'-c','source "$1"; esc "$2"','-',(self.STORE/'.addon-sync/log.sh').as_posix(),text],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.decode(),addon_sync.annotation(text))
    @unittest.skipUnless(shutil.which('bash'),'needs bash')
    def test_fail_is_the_escaped_error_line(self):
        import subprocess,addon_sync
        text='50%\r\n::warning title=Injected::boom\n'
        r=subprocess.run([shutil.which('bash'),'-c','source "$1"; fail "$2"','-',(self.STORE/'.addon-sync/log.sh').as_posix(),text],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.decode(),addon_sync.workflow_command('error','Upgrade comparison failed',text)+'\n')
    def test_every_echo_escapes_pr_values(self):
        import re
        for step in self.wf['jobs']['compare']['steps']:
            run=step.get('run','')
            for line in run.splitlines():
                # The step summary is Markdown, never read for workflow commands.
                # The check's errors go through fail, which escapes the whole message.
                self.assertNotIn('::error title=Upgrade comparison failed::',line)
                if 'echo ' not in line or 'GITHUB_STEP_SUMMARY' in line or 'GITHUB_OUTPUT' in line:continue
                bare=re.sub(r'\$\(esc "\$\{\w+\}"\)','',line[line.index('echo '):])
                for name in self.PR_VALUES:
                    with self.subTest(step=step.get('name'),value=name):self.assertNotIn('${'+name+'}',bare)
            if 'esc "' in run or 'fail "' in run:
                with self.subTest(step=step.get('name')):self.assertIn('source tooling/.addon-sync/log.sh',run)

class SbomAttempt(unittest.TestCase):
    """A re-run must judge the image its own build made, not an earlier attempt's SBOM."""
    STORE=pathlib.Path(__file__).resolve().parent.parent
    def test_artifact_name_carries_the_run_attempt(self):
        action=yaml.safe_load((self.STORE/'.github/actions/addon-sbom/action.yml').read_text(encoding='utf-8'))
        upload=next(s for s in action['runs']['steps'] if s.get('uses','').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['with']['name'],'upgrade-comparison-sbom-${{ inputs.component }}-attempt-${{ github.run_attempt }}')
    def test_wait_accepts_only_this_attempts_artifact(self):
        # The plan names each add-on's artifact once, as the action does; the wait looks for exactly that name.
        text=(self.STORE/'.github/workflows/woow-addon-upgrade-check.yml').read_text(encoding='utf-8');wf=yaml.safe_load(text)
        steps={s.get('id') or s.get('name'):s for s in wf['jobs']['compare']['steps']}
        self.assertEqual(steps['plan']['env']['RUN_ATTEMPT'],'${{ github.run_attempt }}')
        self.assertIn('artifact="upgrade-comparison-sbom-${id}-attempt-${RUN_ATTEMPT}"',steps['plan']['run'])
        self.assertEqual(text.count('upgrade-comparison-sbom-${id}'),1)
        self.assertIn("[.id, .artifact]",steps["Wait for the new images' SBOMs"]['run'])
    def test_callers_glob_still_matches(self):
        import fnmatch
        self.assertTrue(fnmatch.fnmatchcase('upgrade-comparison-sbom-odoo18ce-attempt-2','upgrade-comparison-sbom-*'))

class Scanners(unittest.TestCase):
    ACTION=pathlib.Path(__file__).resolve().parent.parent/'.github/actions/addon-sbom'
    def test_pinned_versions_and_checksums(self):
        import json,re
        pins=json.loads((self.ACTION/'scanner-pins.json').read_text(encoding='utf-8'))
        self.assertEqual({k:v['version'] for k,v in pins.items()},{'syft':'1.54.0','grype':'0.120.0'})
        for name,pin in pins.items():
            with self.subTest(name):
                self.assertRegex(pin['sha256'],r'^[0-9a-f]{64}$');self.assertIn(f'/v{pin["version"]}/',pin['url'])
    def test_third_party_actions_are_pinned_by_commit(self):
        import re
        for path in [self.ACTION/'action.yml',self.ACTION.parent.parent/'workflows/woow-addon-upgrade-check.yml']:
            for ref in re.findall(r'uses: *([^\s#]+)',path.read_text(encoding='utf-8')):
                with self.subTest(ref):
                    if not ref.startswith('WOOWTECH/'):self.assertRegex(ref,r'@[0-9a-f]{40}$')

if __name__=='__main__':unittest.main()
