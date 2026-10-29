import contextlib,copy,io,json,pathlib,re,shutil,tempfile,unittest,unittest.mock
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
        # Supervisor (apps/options.py _check_missing_options): a missing list option is optional when its element
        # schema is an optional scalar such as ["str?"]; any other list (required scalar, mapping items) is required.
        for schema,blocked in [(['str?'],False),(['int(1,5)?'],False),(['str'],True),([{'name':'str?'}],True)]:
            with self.subTest(schema=schema):
                r=run(new(schema=put('tags',schema)))
                self.assertEqual(pairs(r['breaking']),[('required-added','tags')] if blocked else [])
        self.assertEqual(run(new(schema=put('tags',['str']),options=put('tags',[])))['breaking'],[])
    def test_new_map_key_follows_supervisor_missing_option_rule(self):
        # Supervisor (apps/options.py _check_missing_options): a missing dict option is always "Missing option", even when
        # every sub-key is optional; an options default for the map ({} included) fills it in before validation.
        optional,mixed={'host':'str?','port':'port?'},{'host':'str','port':'port?'}
        for name,options,expected in [('no options entry',lambda d:d,[('required-added','database')]),
                ('options default is null',put('database',None),[('required-added','database')]),
                ('options default is {}',put('database',{}),[]),
                ('options default fills the map',put('database',{'host':'db'}),[])]:
            with self.subTest(name):
                self.assertEqual(pairs(run(new(schema=put('database',optional),options=options))['breaking']),expected)
        r=run(new(schema=put('database',mixed)))
        self.assertEqual(pairs(r['breaking']),[('required-added','database'),('required-added','database.host')])
        r=run(new(schema=put('database',mixed),options=put('database',{})))
        self.assertEqual(pairs(r['breaking']),[('required-added','database.host')])
        # List items have no per-item defaults, so a map added to an existing list item is always missing in old items.
        old=new(schema=put('servers',[{'name':'str'}]),options=put('servers',[]));old['version']='1.0.0'
        cfg=copy.deepcopy(old);cfg['version']='1.1.0';cfg['schema']['servers']=[{'name':'str','tls':{'ca':'str?'}}]
        self.assertEqual(pairs(run(cfg,old=old)['breaking']),[('required-added','servers.tls')])
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
    def test_version_not_newer_than_the_target_is_an_error(self):
        # Every Release becomes the latest one users get, so a lower or equal version is a downgrade (ref_policy main: the PR base).
        for target,version in [('1.2.0','1.1.0'),('1.1.0','1.1.0'),('1.1.0','1.1')]:
            with self.subTest(target=target,version=version):
                with self.assertRaisesRegex(ValueError,f'version {re.escape(version)} is not newer than {re.escape(target)}'):
                    u.compare(dict(BASE,version=target),dict(new(),version=version),old_version=target,new_version=version)
    def test_nonstandard_versions_order_by_their_leading_number(self):
        old=copy.deepcopy(BASE);old['version']='2.12.4-v2'
        cfg=self.REMOVED();cfg['version']='2.12.5-v1'
        for version,blocked in [('2.12.5-v1',False),('2.12.4-v2',True)]:
            with self.subTest(version):self.assertEqual(run(cfg,self.notes(version),old=old,old_version='2.12.4-v2')['blocked'],blocked)
        # 2.12.4-beta is PEP 440 2.12.4b0, before 2.12.4-v2, so it does not count; 2.12.4-foo reads only as 2.12.4: no order.
        self.assertTrue(run(cfg,self.notes('2.12.4-beta'),old=old,old_version='2.12.4-v2')['blocked'])
        with self.assertRaises(ValueError):run(cfg,self.notes('2.12.4-foo'),old=old,old_version='2.12.4-v2')
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
    def test_version_not_newer_than_the_pr_base_exits_2(self):
        # ref_policy main compares with the PR base in this command; a revert there fails with the reason.
        code,out=self.main('--old',self.write('old.yaml',dict(BASE,version='1.2.0')),'--new',self.write('new.yaml',new()),'--name','t')
        self.assertEqual(code,2);self.assertIn('::error title=Upgrade comparison failed::t: version 1.1.0 is not newer than 1.2.0',out)
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
    def test_versions_since_the_last_stable_release_all_count(self):
        # 1.2.1 never got a Release, so its declarations belong to the 1.3.0 Release; 1.2.0's were on its own page.
        notes={'1.2.0':{'breaking':[dict(NOTES['1.3.0']['breaking'][0],key='old_port')]},'1.2.1':{'breaking':[dict(NOTES['1.3.0']['breaking'][0],key='mid_port')]},**NOTES}
        text=u.release_notes(notes,'1.3.0',released=['1.1.0','1.2.0','1.3.0'])
        self.assertIn('`mid_port`（1.2.1）',text);self.assertIn('`ssl_port`（1.3.0）',text);self.assertNotIn('old_port',text)
        self.assertIn('old_port',u.release_notes(notes,'1.3.0'))
    def test_a_released_tag_that_is_not_a_version_is_ignored(self):
        # A stray tag on the Releases page must not block the Release it has nothing to do with.
        self.assertEqual(u.release_notes(NOTES,'1.3.0',released=['1.2.0','nightly']),u.release_notes(NOTES,'1.3.0',released=['1.2.0']))
    def test_a_version_not_newer_than_the_latest_release_is_an_error(self):
        # 1.2.5 after 1.3.0 would be a downgrade for users on 1.3.0, the latest Release: no window, an error.
        for version in ('1.2.5','1.3'):
            with self.subTest(version):
                with self.assertRaisesRegex(ValueError,'not newer than 1.3.0'):u.release_notes(NOTES,version,released=['1.2.4','1.3.0'])
    def test_a_tag_that_cannot_be_ordered_is_ignored(self):
        # 1.2.0-foo cannot be ordered against 1.2.0 (nor 1.3.0-foo against 1.3.0): ignored in any order, not a blocked Release.
        for released in (['1.2.0','1.2.0-foo'],['1.2.0-foo','1.2.0'],['1.2.0','1.3.0-foo']):
            with self.subTest(released):self.assertEqual(u.release_notes(NOTES,'1.3.0',released=released),u.release_notes(NOTES,'1.3.0',released=['1.2.0']))
    def test_multiline_text_stays_inside_its_bullet(self):
        notes={'1.3.0':{'breaking':[dict(NOTES['1.3.0']['breaking'][0],migration='第一步。\n第二步。\n')]}}
        self.assertIn('：第一步。\n  第二步。\n',u.release_notes(notes,'1.3.0'))
    def test_empty_migration_or_reason_is_an_error(self):
        for section,field in [('breaking','migration'),('accepted_vulnerabilities','reason')]:
            with self.subTest(section):
                with self.assertRaises(ValueError):u.release_notes({'1.3.0':{section:[dict(NOTES['1.3.0'][section][0],**{field:' '})]}},'1.3.0')
class ComparisonTargetCommand(unittest.TestCase):
    """The PR check's comparison target and the Release notes' window use one ordering: version_cmp."""
    def test_addon_sync_does_not_import_this_module(self):
        # One direction only: upgrade_check uses addon_sync's Release rules, addon_sync never needs upgrade_check.
        import subprocess,sys
        r=subprocess.run([sys.executable,'-c',"import sys,addon_sync;print('upgrade_check' in sys.modules)"],cwd=pathlib.Path(__file__).resolve().parent,capture_output=True,text=True)
        self.assertEqual(r.stdout.strip(),'False',r.stderr)
    def test_orders_with_version_cmp_where_sort_v_disagrees(self):
        # sort -V puts 1.2.0rc1 after 1.2.0 and 2026.9.1-10 is fine either way; PEP 440 says rc1 comes first.
        self.assertEqual(u.comparison_target(['1.2.0rc1','1.2.0','1.1.9'],'9'),'1.2.0')
        self.assertEqual(u.comparison_target(['2.12.4-v9','2.12.4-v10','2.12.4'],'9'),'2.12.4-v10')
        self.assertEqual(u.comparison_target(['1.9.0','1.10.0','nightly'],'9'),'1.10.0')
        self.assertIsNone(u.comparison_target(['nightly'],'9'));self.assertIsNone(u.comparison_target([],'9'))
    def test_target_is_the_latest_release_and_the_version_must_be_newer(self):
        self.assertEqual(u.comparison_target(['1.2.4','1.3.0'],'1.4.0'),'1.3.0')
        for released,version in [(['1.2.4','1.3.0'],'1.2.5'),(['1.3.0'],'1.3.0'),(['1.3.0'],'1.3')]:
            with self.subTest(released=released,version=version):
                with self.assertRaisesRegex(ValueError,f'version {re.escape(version)} is not newer than 1.3.0'):u.comparison_target(released,version)
        with self.assertRaisesRegex(ValueError,r'version 1\.3 is not newer than 1\.3\.0 \(the same version, written differently\), the version users run now'):
            u.comparison_target(['1.3.0'],'1.3')
    def test_a_tag_that_cannot_be_ordered_is_ignored(self):
        # Only a version that reads whole (PEP 440 or a rebuild suffix) can be the target: a stray v9.0-test, read by its
        # leading number alone, would otherwise be higher than every real Release and block every PR.
        for released in (['1.2.0','1.3.0-foo'],['1.3.0-foo','1.2.0'],['1.2.0','1.2.0-foo'],['nightly','1.2.0'],['1.2.0','9.0-test']):
            with self.subTest(released):self.assertEqual(u.comparison_target(released,'1.3.0'),'1.2.0')
    def test_a_version_that_cannot_be_ordered_against_the_target_fails(self):
        # The PR's version is not a stray tag: when it cannot be shown newer than the latest Release, it is not released.
        with self.assertRaisesRegex(ValueError,'version 1.3.0-foo cannot be ordered against 1.3.0, the version users run now') as e:
            u.comparison_target(['1.2.0','1.3.0'],'1.3.0-foo')
        # Raising it would not help (1.4-foo still cannot be ordered against 1.4): the fix is a version that reads whole.
        self.assertRegex(str(e.exception),r'; use a newer version that reads whole: PEP 440, or a dotted number with a rebuild suffix -v<N>$')
        self.assertNotIn('raise the version',str(e.exception))
        with self.assertRaisesRegex(ValueError,r'is not newer than 1\.3\.0, .*; raise the version$'):u.comparison_target(['1.3.0'],'1.2.0')
        self.assertEqual(u.comparison_target(['1.2.0','1.3.0'],'1.4.0-foo'),'1.3.0')
    def test_a_target_config_that_cannot_be_ordered_against_its_tag_disagrees(self):
        u.check_target('1.4','v1.3','addon/config.yaml','1.3.0','1.3')
        with self.assertRaisesRegex(ValueError,r'v1\.3 is version 1\.3 by its tag but 1\.3-foo by addon/config\.yaml; correct that Release'):
            u.check_target('1.4','v1.3','addon/config.yaml','1.3-foo','1.3')
    def test_a_target_config_without_a_version_is_the_targets_fault(self):
        for tag_version,fix in [('1.3','correct that Release'),(None,'add a version to that config on the default branch')]:
            with self.subTest(tag_version):
                with self.assertRaisesRegex(ValueError,f'^the comparison target v1.3 has no version in addon/config.yaml; {fix}, then re-run this check$'):
                    u.check_target('1.4','v1.3','addon/config.yaml',None,tag_version)
    def main(self,releases,component,components=('t',),version='99.0.0'):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d)
        (d/'registry.json').write_text(json.dumps({'providers':{'WOOWTECH/r':{'components':[{'id':c} for c in components]}}}))
        stdin=releases if isinstance(releases,str) else json.dumps([r if isinstance(r,dict) else {'tag_name':r,'draft':False,'prerelease':False} for r in releases])
        with contextlib.redirect_stdout(io.StringIO()) as out,unittest.mock.patch('sys.stdin',io.StringIO(stdin)):
            code=u.main(['comparison-target','--registry',str(d/'registry.json'),'--repo','WOOWTECH/r','--component',component,'--version',version])
        return code,out.getvalue()
    def test_prints_the_tag_of_the_latest_stable_release(self):
        # And its version, tab-separated: the plan step checks that the config at the tag says the same version.
        self.assertEqual(self.main(['v1.2.0rc1','v1.2.0','v1.1.0'],'t'),(0,'v1.2.0\t1.2.0\n'))
        self.assertEqual(self.main([],'t'),(0,''))
    def test_drafts_prereleases_and_other_prefixes_are_not_stable_releases(self):
        releases=[{'tag_name':'v2.0.0','draft':True,'prerelease':False},{'tag_name':'v1.9.0','draft':False,'prerelease':True},'x-v3.0.0','v1.1.0']
        self.assertEqual(self.main(releases,'t'),(0,'v1.1.0\t1.1.0\n'))
        self.assertEqual(self.main(releases[:3],'t'),(0,''))
    def test_a_version_not_newer_than_the_latest_release_exits_2(self):
        # --version applies the Release notes' rule: the target is the latest stable Release and the version must be newer.
        self.assertEqual(self.main(['v1.2.0','v1.1.0'],'t',version='1.3.0'),(0,'v1.2.0\t1.2.0\n'))
        self.assertEqual(self.main([],'t',version='1.3.0'),(0,''))
        for version in ('1.2.5','1.3.0'):
            with self.subTest(version):
                code,out=self.main(['v1.3.0','v1.2.4'],'t',version=version)
                self.assertEqual(code,2);self.assertIn(f'version {version} is not newer than 1.3.0',out)
    def test_tag_rule_is_addon_syncs(self):
        # v<ver> for a single add-on, <slug>-v<ver> when the repository has several (addon_sync.release_tag).
        releases=['v9.0.0','woow_ha_core-v2.4.0','woow_ha_core_2-v2.3.0','woow_ha_core_2-v2.2.0']
        both=('woow_ha_core','woow_ha_core_2')
        self.assertEqual(self.main(releases,'woow_ha_core_2',both),(0,'woow_ha_core_2-v2.3.0\t2.3.0\n'))
        self.assertEqual(self.main(releases,'woow_ha_core',both),(0,'woow_ha_core-v2.4.0\t2.4.0\n'))
        self.assertEqual(self.main(releases,'t'),(0,'v9.0.0\t9.0.0\n'))
    def test_unknown_repository_is_the_registry_lookups_error(self):
        # One provider lookup (addon_sync.find_provider) for comparison-target and components.
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d);(d/'registry.json').write_text('{"providers":{}}')
        with contextlib.redirect_stdout(io.StringIO()) as out,unittest.mock.patch('sys.stdin',io.StringIO('[]')):
            code=u.main(['comparison-target','--registry',str(d/'registry.json'),'--repo','WOOWTECH/x','--component','t','--version','1.0.0'])
        # A ValueError naming the repository, printed once and unquoted (a KeyError's str() is quoted).
        self.assertEqual(code,2);self.assertEqual(out.getvalue(),'::error title=Upgrade comparison failed::WOOWTECH/x is not in the Store registry\n')
        code,out=self.main(['v1.0.0'],'other')
        self.assertEqual(out,'::error title=Upgrade comparison failed::WOOWTECH/r has no add-on other in the Store registry\n')
    def test_unknown_component_or_bad_input_exits_2(self):
        for releases,component in [(['v1.0.0'],'other'),('not json','t'),('{}','t')]:
            with self.subTest(component=component,releases=releases):
                code,out=self.main(releases,component)
                self.assertEqual(code,2);self.assertTrue(out.startswith('::error title=Upgrade comparison failed::'),out)
    def test_workflow_leaves_the_filter_and_tag_rule_to_python(self):
        wf=yaml.safe_load((pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/woow-addon-upgrade-check.yml').read_text(encoding='utf-8'))
        plan=next(s for s in wf['jobs']['compare']['steps'] if s.get('id')=='plan')['run']
        self.assertIn('upgrade_check.py comparison-target --registry',plan)
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
            {'id':'a','config':'config.yaml','notes':'upgrade-notes.yaml','previous_config':'','previous_notes':''},
            {'id':'b','config':'addons/b/config.yml','notes':'addons/b/upgrade-notes.yaml','previous_config':'','previous_notes':''}]})
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps}}})
        self.assertEqual(json.loads(out)['skip_vulnerability_scan'],'')
    def test_a_move_in_progress_gives_the_previous_config_and_its_notes(self):
        # addon_sync.locations: previous_config is a config at the root of its add-on directory, with upgrade-notes.yaml beside it.
        comps=[{'id':'a','source_path':'addons/a','config_file':'config.yaml','previous_config':'a/config.yml'},
            {'id':'b','source_path':'b','config_file':'config.yaml','previous_config':'config.yaml'}]
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps}}})
        self.assertEqual(code,0,out);self.assertEqual([(c['previous_config'],c['previous_notes']) for c in json.loads(out)['components']],
            [('a/config.yml','a/upgrade-notes.yaml'),('config.yaml','upgrade-notes.yaml')])
    def test_only_add_ons_that_get_releases_are_compared(self):
        # The same filter as addon_sync.release: deleting a retired add-on's config must not fail the check.
        comps=[{'id':i,'source_path':i,'config_file':'config.yaml',**extra} for i,extra in [('a',{}),('off',{'enabled':False}),('beta',{'channel':'prerelease'}),('b',{'channel':'stable'})]]
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps}}})
        self.assertEqual(code,0);self.assertEqual([c['id'] for c in json.loads(out)['components']],['a','b'])
    def test_unknown_repository_or_unsafe_path_exits_2(self):
        for name,registry in [('unknown',{'providers':{}}),('unsafe',{'providers':{'WOOWTECH/r':{'ref_policy':'release','components':[{'id':'a','source_path':'../x','config_file':'config.yaml'}]}}}),
                ('unsafe previous',{'providers':{'WOOWTECH/r':{'ref_policy':'release','components':[{'id':'a','source_path':'a','config_file':'config.yaml','previous_config':'../x/config.yaml'}]}}})]:
            with self.subTest(name):
                code,out=self.main(registry)
                self.assertEqual(code,2);self.assertTrue(out.startswith('::error title=Upgrade comparison failed::WOOWTECH/r '),out)
        self.assertEqual(self.main({'providers':{}})[1],'::error title=Upgrade comparison failed::WOOWTECH/r is not in the Store registry\n')
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
    def test_ref_policy_main_compares_with_where_the_base_version_first_appeared(self):
        # apporo_ha_multi_ha_core, Woow_haos_ha_core, nginxpm have no stable Release: the Store follows main (#121), and the
        # target is the commit on the PR base where its version first appeared (#129; MainFirstVersion runs it).
        plan=self.step('Find the comparison targets')
        self.assertRegex(plan,r'if \[ "\$\{policy\}" = "main" \]; then\s+(#.*\s+)*target="\$\(version_since "\$\{BASE_SHA\}" ')
        self.assertEqual(self.step_env('Find the comparison targets')['BASE_SHA'],'${{ github.event.pull_request.base.sha }}')
    def test_only_add_ons_whose_version_changed_are_compared(self):
        # Multi-add-on repositories: an add-on whose version is unchanged is listed as unchanged and never compared.
        detect=self.step('Find add-ons whose version changed')
        self.assertIn('if [ "${current}" != "${before}" ]; then',detect)
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
    def run_step(self,ident,*,policy='release',extra=None,releases=('v1.0.0',),old_config=True,new_config=True,skip='',sbom='',version='1.1.0',old=None,old_path='',
            new_path='addon/config.yaml',new=None,files=None,raw_version=None,history=None,changed=1,gh_fail=''):
        """ident: one step, or a tuple run in order until one fails. new_path: where the PR has the config; new: changes to it;
        files: more files of the PR checkout; raw_version: {'old'/'new': the version line's YAML as written, e.g. 1.10 unquoted}.
        history: the PR base's history, newest first, [(sha, {path: changes to the config, or None for no file})]; the first
        sha must be 'b' (BASE_SHA). Without it, every ref has `old` (at old_path when given) and 'b' is its only commit.
        changed: how many registry add-ons the detect step reports as changed. gh_fail: any gh call containing it fails.
        self.tmp is the job's directory (also RUNNER_TEMP); self.plans is every line of plan.jsonl."""
        import os,subprocess
        tmp=self.tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'tooling/.addon-sync').mkdir(parents=True);(tmp/'source').mkdir();(tmp/'bin').mkdir()
        for f in (self.STORE/'.addon-sync').iterdir():
            if f.suffix in ('.py','.sh'):shutil.copy(f,tmp/'tooling/.addon-sync'/f.name)
        (tmp/'tooling/.addon-sync/registry.json').write_text(json.dumps({'providers':{'WOOWTECH/t':{'ref_policy':policy,'components':[
            {'id':'t','source_path':'addon','config_file':'config.yaml'}],**(extra or {})}}}))
        cfg=dict(BASE,image='ghcr.io/da-anda/addon-{arch}')
        def dump(c,side):
            text=yaml.safe_dump(c)
            return re.sub(r'(?m)^version: .*$','version: '+raw_version[side],text) if side in (raw_version or {}) else text
        if new_config:
            # The checkout, and what the detect step leaves for the later steps.
            text=dump(dict(cfg,version=version,**(new or {})),'new');(tmp/'source'/new_path).parent.mkdir(parents=True,exist_ok=True)
            (tmp/'source'/new_path).write_text(text);(tmp/'t.new.yaml').write_text(text)
        for name,text in (files or {}).items():(tmp/'source'/name).parent.mkdir(parents=True,exist_ok=True);(tmp/'source'/name).write_text(text)
        (tmp/'old.yaml').write_text(dump(dict(cfg,**(old or {})),'old') if old_config else '')
        with contextlib.redirect_stdout(io.StringIO()) as provider:
            self.assertEqual(u.main(['components','--registry',str(tmp/'tooling/.addon-sync/registry.json'),'--repo','WOOWTECH/t']),0)
        (tmp/'provider.json').write_text(provider.getvalue())
        (tmp/'changed.jsonl').write_text(''.join(json.dumps(dict(c,version=version,new=str(tmp/'t.new.yaml')))+'\n' for c in json.loads(provider.getvalue())['components'][:changed]))
        if history is not None:
            (tmp/'history.json').write_text(json.dumps([{'sha':sha,'date':f'2026-01-01T00:{59-i:02d}:00Z','files':{p:dump(dict(cfg,**c),'old')
                for p,c in at.items() if c is not None}} for i,(sha,at) in enumerate(history)]))
        gh=tmp/'bin/gh';gh.write_text(GH_STUB);gh.chmod(0o755)
        # What `gh api --paginate .../releases --jq '.[]'` prints: one Release object per line; a bare tag is a stable Release.
        releases='\n'.join(json.dumps(r if isinstance(r,dict) else {'tag_name':r,'draft':False,'prerelease':False}) for r in releases)
        env=dict(os.environ,PATH=f"{tmp/'bin'}{os.pathsep}{os.environ['PATH']}",OLD=str(tmp/'old.yaml'),OLD_PATH=old_path,RELEASES=releases,REPO='WOOWTECH/t',BASE_SHA='b',
            GH_TOKEN='x',DB_MAX_AGE_HOURS='120',SBOM_ARTIFACT=sbom,SKIP_VULNERABILITY_SCAN=skip,RUNNER_TEMP=str(tmp),RUN_ATTEMPT='1',
            GITHUB_OUTPUT=str(tmp/'out'),GITHUB_STEP_SUMMARY=str(tmp/'summary'),HISTORY=str(tmp/'history.json') if history is not None else '',GH_FAIL=gh_fail)
        for one in (ident if isinstance(ident,tuple) else (ident,)):
            (tmp/'step.sh').write_text(self.step(one)['run'])
            r=subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=env,capture_output=True,text=True)
            if r.returncode:break
        self.plans=[json.loads(l) for l in (tmp/'plan.jsonl').read_text().splitlines()] if (tmp/'plan.jsonl').exists() else []
        return r,(self.plans[0] if self.plans else {}),(tmp/'out').read_text() if (tmp/'out').exists() else ''

# The fake GitHub API of StepHarness: Releases, raw files at a ref and the commits that changed a path (with --jq through jq).
GH_STUB=r'''#!/usr/bin/env python3
import json,os,re,subprocess,sys
args=sys.argv[1:];url=next(a for a in args if a.startswith('repos/'))
def out(data):
    if '--jq' not in args:print(json.dumps(data));sys.exit(0)
    r=subprocess.run(['jq','-r',args[args.index('--jq')+1]],input=json.dumps(data),text=True);sys.exit(r.returncode)
if os.environ.get('GH_FAIL') and os.environ['GH_FAIL'] in url:print('gh: Server Error (HTTP 502)',file=sys.stderr);sys.exit(1)
history=json.load(open(os.environ['HISTORY'])) if os.environ.get('HISTORY') else None
old=open(os.environ['OLD']).read();old_path=os.environ.get('OLD_PATH','')
def legacy(path):return old if old and (not old_path or path==old_path) else None
def at(ref,path):
    for c in history or []:
        if c['sha']==ref:return c['files'].get(path)
    return legacy(path)
if '/releases' in url:
    if os.environ['RELEASES']:print(os.environ['RELEASES'])
elif '/contents/' in url:
    path,ref=re.fullmatch(r'repos/[^/]+/[^/]+/contents/(.*)\?ref=(.*)',url).groups();text=at(ref,path)
    if text is None:print('gh: Not Found (HTTP 404)',file=sys.stderr);sys.exit(1)
    sys.stdout.write(text)
elif '/commits?' in url:
    q=dict(p.split('=',1) for p in url.split('?',1)[1].split('&'))
    commits=history if history is not None else [{'sha':'b','date':'2026-01-01T00:00:00Z','files':{q['path']:legacy(q['path'])}}]
    start=next(i for i,c in enumerate(commits) if c['sha']==q['sha'])
    def changed(i):return commits[i]['files'].get(q['path'])!=(commits[i+1]['files'].get(q['path']) if i+1<len(commits) else None)
    out([{'sha':c['sha'],'commit':{'committer':{'date':c['date']}}} for i,c in enumerate(commits) if i>=start and changed(i)])
else:sys.exit(1)
'''

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
    """"No comparison target" only when there is no stable Release (or, for ref_policy main, no config at the PR base)."""
    @needs_shell
    def test_release_whose_config_cannot_be_read_fails(self):
        r,plan,_=self.run_step('plan',old_config=False,skip='x')
        self.assertEqual(r.returncode,1);self.assertIn('v1.0.0 has no addon/config.yaml',r.stdout+r.stderr);self.assertEqual(plan,{})
    @needs_shell
    def test_no_stable_release_has_no_comparison_target(self):
        r,plan,_=self.run_step('plan',releases=(),old_config=False)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual([plan['target'],plan['ref'],plan['note']],['','','no comparison target'])
    @needs_shell
    def test_config_deleted_or_moved_by_the_pr_fails(self):
        # Spec: a tool error fails the check; a registry add-on whose config the PR removes is not "unchanged".
        r,_,_=self.run_step('detect',new_config=False)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('this PR deletes or moves addon/config.yaml',r.stdout)
    @needs_shell
    def test_registry_path_absent_in_the_pr_and_its_base_fails(self):
        # Spec: a tool error fails the check; a wrong registry path is one, not "nothing to compare".
        r,_,_=self.run_step('detect',new_config=False,old_config=False)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('neither this PR nor its base has it',r.stdout)
    MOVED={'components':[{'id':'t','source_path':'addon','config_file':'config.yaml','previous_config':'old/config.yaml'}]}
    @needs_shell
    def test_a_move_without_a_version_bump_is_unchanged(self):
        # The registry lists the new path and previous_config the old one; the PR base still has only the old path.
        for policy in ('release','main'):
            with self.subTest(policy):
                r,_,out=self.run_step('detect',policy=policy,extra=self.MOVED,version='1.0.0',old_path='old/config.yaml')
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('changed=false',out)
    @needs_shell
    def test_a_target_from_before_the_move_is_read_at_the_previous_path(self):
        # The move PR with a bump, or the next bump PR while the latest Release (or, for main, the PR base) predates the move.
        for policy in ('release','main'):
            with self.subTest(policy):
                r,plan,_=self.run_step('plan',policy=policy,extra=self.MOVED,sbom='*',old_path='old/config.yaml')
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('t: comparing 1.1.0 with',r.stdout)
                self.assertEqual(plan['ref'],'ghcr.io/da-anda/addon-amd64:1.0.0')
    @needs_shell
    def test_a_pr_from_before_the_move_reads_the_previous_path(self):
        # The Store PR comes first: until the move merges, PRs and their base have the config only at previous_config.
        for policy in ('release','main'):
            with self.subTest(policy):
                r,_,out=self.run_step('detect',policy=policy,extra=self.MOVED,version='1.0.0',old_path='old/config.yaml',new_path='old/config.yaml')
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('changed=false',out)
                r,_,out=self.run_step('detect',policy=policy,extra=self.MOVED,old_path='old/config.yaml',new_path='old/config.yaml')
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('changed=true',out)
                # Its upgrade-notes.yaml is next to the config it has.
                self.assertEqual(json.loads((self.tmp/'changed.jsonl').read_text())['notes'],'old/upgrade-notes.yaml')
                r,plan,_=self.run_step('plan',policy=policy,extra=self.MOVED,sbom='*',old_path='old/config.yaml',new_path='old/config.yaml')
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['ref'],'ghcr.io/da-anda/addon-amd64:1.0.0')
    @needs_shell
    def test_a_pr_from_before_the_move_is_judged_with_the_notes_next_to_its_config(self):
        steps=('detect','plan','Compare with the comparison target')
        extra={**self.MOVED,'upgrade_comparison':{'skip_vulnerability_scan':'x'}}
        removed=dict(new={'ports':{'8069/tcp':8069}},extra=extra,skip='x',old_path='old/config.yaml',new_path='old/config.yaml')
        notes={'old/upgrade-notes.yaml':'"1.1.0":\n  breaking:\n    - {change: port-removed, key: 8072/tcp, migration: Use 8069.}\n'}
        r,_,_=self.run_step(steps,**removed,files=notes)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('t 1.0.0 → 1.1.0',r.stdout)
        r,_,_=self.run_step(steps,**removed)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('Undeclared breaking change::port-removed 8072/tcp',r.stdout)
    @needs_shell
    def test_a_target_after_the_move_is_read_at_the_new_path(self):
        r,plan,_=self.run_step('plan',extra=self.MOVED,sbom='*',old_path='addon/config.yaml')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['ref'],'ghcr.io/da-anda/addon-amd64:1.0.0')
    @needs_shell
    def test_a_moved_config_without_previous_config_points_to_the_readme(self):
        r,_,_=self.run_step('plan',sbom='*',old_path='old/config.yaml')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('has no addon/config.yaml, so there is nothing to compare with; if the config moved, see moving a config in the Store README',r.stdout)
        r,_,_=self.run_step('detect',new_config=False)
        self.assertIn('to move it, first merge a Store PR that lists the new path with previous_config: addon/config.yaml',r.stdout)
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
    def test_a_version_not_newer_than_the_latest_release_fails(self):
        # The Release notes' rule (addon_sync.comparison_target): 1.2.5 after 1.3.0 is a downgrade; 1.3.0 again is no upgrade.
        for version in ('1.2.5','1.3.0'):
            with self.subTest(version):
                r,plan,_=self.run_step('plan',releases=('v1.3.0','v1.2.4','v1.2.0'),version=version,skip='x')
                self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn(f'version {version} is not newer than 1.3.0',r.stdout);self.assertEqual(plan,{})
    @needs_shell
    def test_ref_policy_main_fails_a_version_not_newer_than_the_pr_base_before_scanning(self):
        # As for ref_policy release: in the plan step, not after the Grype DB update and the SBOM wait (compare()).
        sbom='upgrade-comparison-sbom-*'
        r,plan,out=self.run_step('plan',policy='main',old={'version':'1.2.0'},version='1.3.0',sbom=sbom)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('scan=true',out)
        r,plan,out=self.run_step('plan',policy='main',old={'version':'1.2.0'},version='1.1.0',sbom=sbom)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan,{});self.assertNotIn('scan=true',out)
        self.assertIn('t: version 1.1.0 is not newer than 1.2.0, the version users run now',r.stdout)
    @needs_shell
    def test_the_same_version_written_differently_fails_as_not_newer(self):
        # Detection compares the strings, so 1.3 -> 1.3.0 is a change; treated as unchanged, release() would later try to
        # release v1.3.0 and be blocked on main. It fails here instead, saying why.
        for policy,steps in [('release',('detect','plan')),('main',('detect','plan','Compare with the comparison target'))]:
            with self.subTest(policy):
                r,_,_=self.run_step(steps,policy=policy,releases=('v1.3',),old={'version':1.3},version='1.3.0',skip='x',
                    extra={'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
                self.assertEqual(r.returncode,1,r.stdout+r.stderr)
                self.assertIn('changed=true',(self.tmp/'out').read_text())
                self.assertIn('version 1.3.0 is not newer than 1.3 (the same version, written differently)',r.stdout)
    @needs_shell
    def test_a_target_whose_config_disagrees_with_its_tag_fails(self):
        # The target's version comes from its tag (comparison-target) and from its config (compare); one must not silently win.
        r,plan,_=self.run_step('plan',old={'version':'0.9.0'},skip='x')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan,{})
        self.assertIn('t: the comparison target v1.0.0 is version 1.0.0 by its tag but 0.9.0 by addon/config.yaml',r.stdout)
        # The same version written differently agrees (version_cmp, not the strings); a different one does not.
        r,plan,_=self.run_step('plan',releases=('v1.3',),old={'version':'1.3.0'},version='1.4.0',skip='x')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'v1.3')
        r,plan,_=self.run_step('plan',releases=('v1.3',),old={'version':'1.4'},version='1.5.0',skip='x')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan,{})
        self.assertIn('t: the comparison target v1.3 is version 1.3 by its tag but 1.4 by addon/config.yaml; correct that Release',r.stdout)
        # Under ref_policy main the target is the PR base: its config is the only source.
        r,plan,_=self.run_step('plan',policy='main',old={'version':'0.9.0'},skip='x')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'b')
    @needs_shell
    def test_a_target_config_without_a_version_names_the_target(self):
        # Not "1.1.0 cannot be ordered against null ...; use a newer version": the PR's version is not the problem.
        for policy,target,fix in [('release','v1.0.0','correct that Release'),('main','b','add a version to that config on the default branch')]:
            with self.subTest(policy):
                r,plan,_=self.run_step('plan',policy=policy,raw_version={'old':'null'},skip='x')
                self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan,{});self.assertNotIn('null',r.stdout)
                self.assertIn(f't: the comparison target {target} has no version in addon/config.yaml; {fix}, then re-run this check',r.stdout)
    @needs_shell
    def test_a_normal_bump_compares_with_the_latest_release(self):
        r,plan,_=self.run_step('plan',releases=('v1.0.0','v0.9.0','v1.1.0-foo'),version='1.1.0',skip='x')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'v1.0.0')
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
    def test_the_prs_config_path_is_spelled_once(self):
        # The detect step names where it leaves the PR's config; later steps read that path from the JSON lines it wrote.
        text=self.WF.read_text(encoding='utf-8')
        self.assertEqual(text.count('.new.yaml'),1)
        for ident,field in (('detect','new: $new'),('plan','new=new'),('Compare with the comparison target','new=new')):
            with self.subTest(ident):self.assertIn(field,self.step(ident)['run'])
    def test_each_step_sources_exactly_the_helpers_it_uses(self):
        import re
        for step in self.wf['jobs']['compare']['steps']:
            run=step.get('run','')
            for helper,use in [('gh_raw.sh',r'\b(fetch|config_at) '),('log.sh',r'\b(esc|fail|fail_output|no_cntrl) "'),('fields.sh',r'\bfields "')]:
                with self.subTest(step=step.get('name'),helper=helper):
                    self.assertEqual('source tooling/.addon-sync/'+helper in run,bool(re.search(use,run)))

class MainFirstVersion(StepHarness):
    """ref_policy main (#129): users run the PR base's version as it first appeared on the default branch, so the target is
    the commit where that version first appeared, not the PR base: a later same-version commit is in the comparison."""
    SKIP=dict(skip='x',extra={'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
    STEPS=('plan','Compare with the comparison target')
    NO_WORKERS={'options':{k:v for k,v in BASE['options'].items() if k!='workers'},'schema':{k:v for k,v in BASE['schema'].items() if k!='workers'}}
    P='addon/config.yaml'
    @needs_shell
    def test_a_breaking_change_merged_without_a_bump_blocks_the_next_bump(self):
        # PR A removed workers at 2.0 without a bump (passed: no version change); PR B bumps to 2.1 on top of it.
        history=[('b',{self.P:{'version':'2.0',**self.NO_WORKERS}}),('c',{self.P:{'version':'2.0'}}),('o',{self.P:{'version':'1.9'}})]
        r,plan,_=self.run_step(self.STEPS,policy='main',history=history,version='2.1',new=self.NO_WORKERS,**self.SKIP)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan['target'],'c')
        self.assertIn('Undeclared breaking change::option-removed workers',r.stdout);self.assertIn('t 2.0 → 2.1',r.stdout)
    @needs_shell
    def test_a_normal_bump_compares_with_the_commit_that_bumped_the_base(self):
        # No PR in between: the PR base is the commit where its version first appeared, as before #129.
        history=[('b',{self.P:{'version':'2.0'}}),('o',{self.P:{'version':'1.9'}})]
        r,plan,_=self.run_step('plan',policy='main',history=history,version='2.1',**self.SKIP)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'b')
        self.assertIn('t: comparing 2.1 with b, where version 2.0 first appeared on the PR base',r.stdout)
        r,_,_=self.run_step(self.STEPS,policy='main',history=history,version='2.1',**self.SKIP)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('t 2.0 → 2.1',r.stdout)
    @needs_shell
    def test_a_version_unchanged_since_the_config_was_created_uses_the_creating_commit(self):
        history=[('b',{self.P:{'version':'2.0',**self.NO_WORKERS}}),('c',{self.P:{'version':'2.0'}}),('a',{self.P:None})]
        r,plan,_=self.run_step(self.STEPS,policy='main',history=history,version='2.1',new=self.NO_WORKERS,**self.SKIP)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan['target'],'c')
        self.assertIn('Undeclared breaking change::option-removed workers',r.stdout)
    @needs_shell
    def test_a_config_recreated_after_a_deletion_starts_its_history_again(self):
        # Before the deletion it was another life of the add-on; its commits are not looked at.
        history=[('b',{self.P:{'version':'2.0'}}),('d',{self.P:None}),('o',{self.P:{'version':'2.0'}})]
        r,plan,_=self.run_step('plan',policy='main',history=history,version='2.1',**self.SKIP)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'b')
    @needs_shell
    def test_a_move_in_progress_follows_the_version_back_through_the_previous_path(self):
        moved=ComparisonTarget.MOVED;old='old/config.yaml'
        history=[('b',{self.P:{'version':'2.0',**self.NO_WORKERS},old:None}),('k',{old:{'version':'2.0','log_level':'warn'}}),
            ('f',{old:{'version':'2.0'}}),('o',{old:{'version':'1.9'}})]
        r,plan,_=self.run_step(self.STEPS,policy='main',history=history,version='2.1',new=self.NO_WORKERS,skip='x',
            extra={**moved,'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan['target'],'f')
        self.assertIn('Undeclared breaking change::option-removed workers',r.stdout)
    @needs_shell
    def test_each_add_on_of_a_multi_add_on_repository_has_its_own_target(self):
        comps=[{'id':'t','source_path':'addon','config_file':'config.yaml'},{'id':'t_2','source_path':'addon2','config_file':'config.yaml'}]
        two='addon2/config.yaml'
        history=[('b',{self.P:{'version':'2.0'},two:{'version':'3.0','log_level':'warn'}}),('c',{self.P:{'version':'2.0'},two:{'version':'3.0'}}),
            ('d',{self.P:{'version':'1.9'},two:{'version':'3.0'}}),('e',{self.P:{'version':'1.9'},two:{'version':'2.9'}})]
        r,_,_=self.run_step('plan',policy='main',history=history,version='9.0',changed=2,skip='x',extra={'components':comps,'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual({p['id']:p['target'] for p in self.plans},{'t':'c','t_2':'d'})
    @needs_shell
    def test_the_old_image_is_the_one_of_the_commit_where_the_version_first_appeared(self):
        history=[('b',{self.P:{'version':'2.0','image':'ghcr.io/da-anda/new-{arch}'}}),('c',{self.P:{'version':'2.0'}}),('o',{self.P:{'version':'1.9'}})]
        r,plan,_=self.run_step('plan',policy='main',history=history,version='2.1',sbom='*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual([plan['target'],plan['ref']],['c','ghcr.io/da-anda/addon-amd64:2.0'])
    @needs_shell
    def test_an_api_error_fails_and_never_falls_back_to_the_pr_base(self):
        history=[('b',{self.P:{'version':'2.0'}}),('c',{self.P:{'version':'2.0'}}),('o',{self.P:{'version':'1.9'}})]
        for gh_fail,reason in [('/commits?','cannot list the commits that changed addon/config.yaml on the PR base (GitHub API)'),
                ('?ref=c','cannot read addon/config.yaml at c (GitHub API)')]:
            with self.subTest(gh_fail):
                r,plan,_=self.run_step('plan',policy='main',history=history,version='2.1',gh_fail=gh_fail,**self.SKIP)
                self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan,{})
                self.assertIn('::error title=Upgrade comparison failed::t: '+reason,r.stdout)
                self.assertIn('the commit where version 2.0 first appeared is unknown; re-run this check',r.stdout)

class VersionReading(StepHarness):
    """One reader of a config's version (addon_sync.config_version) for the workflow's steps, compare() and release():
    Home Assistant Supervisor's (YAML, then str), so an unquoted 1.10 is 1.1. The PR's version must read as written."""
    SKIP=dict(skip='x',extra={'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
    STEPS=('detect','plan','Compare with the comparison target')
    def cli(self,text,*args):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d);(d/'config.yaml').write_text(text)
        with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(['version','--file',str(d/'config.yaml'),'--path','addon/config.yaml','--name','t',*args])
        return code,out.getvalue()
    def test_version_command_reads_as_supervisor_does(self):
        self.assertEqual(self.cli('slug: t\nversion: 1.10\n'),(0,'1.1\n'))
        self.assertEqual(self.cli('slug: t\nversion: "1.10"\n','--as-written'),(0,'1.10\n'))
        self.assertEqual(self.cli('slug: t\nversion: 2\n','--as-written'),(0,'2\n'))
        self.assertEqual(self.cli('slug: t\n'),(0,'\n'))
        code,out=self.cli('slug: t\nversion: 1.10\n','--as-written')
        self.assertEqual(code,2)
        self.assertEqual(out,'::error title=Upgrade comparison failed::t: addon/config.yaml: version 1.10 is read by YAML, and by Home Assistant Supervisor, as 1.1; quote it: version: "1.10"\n')
    @needs_shell
    def test_an_unquoted_pr_version_fails_the_same_in_the_workflow_and_compare(self):
        # Base 1.2, PR unquoted 1.10: yq read 1.10 (newer), compare() 1.1 (not newer), so the plan passed and compare failed.
        quote='version 1.10 is read by YAML, and by Home Assistant Supervisor, as 1.1; quote it: version: "1.10"'
        for policy in ('release','main'):
            with self.subTest(policy):
                r,plan,_=self.run_step(self.STEPS,policy=policy,releases=('v1.2',),old={'version':'1.2'},raw_version={'new':'1.10'},**self.SKIP)
                self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn(quote,r.stdout);self.assertEqual(plan,{})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code=u.main(['compare','--old',str(self.tmp/'old.yaml'),'--new',str(self.tmp/'t.new.yaml'),'--summary',str(self.tmp/'s.md')])
        self.assertEqual(code,2);self.assertIn(quote,out.getvalue())
    @needs_shell
    def test_a_pr_config_without_a_version_fails(self):
        r,_,out=self.run_step('detect',raw_version={'new':'null'})
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('t: addon/config.yaml has no version',r.stdout);self.assertNotIn('changed=true',out)
    @needs_shell
    def test_a_quoted_version_is_read_as_written(self):
        for policy in ('release','main'):
            with self.subTest(policy):
                r,_,_=self.run_step(self.STEPS,policy=policy,releases=('v1.2',),old={'version':'1.2'},raw_version={'new':'"1.10"'},**self.SKIP)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('t 1.2 → 1.10',r.stdout)
    @needs_shell
    def test_an_unquoted_target_version_is_what_users_run(self):
        # Users of a base with unquoted 1.10 run 1.1 (Supervisor's reading); a PR quoting "1.2" is newer, in every step.
        r,_,_=self.run_step(self.STEPS,policy='main',old={'version':'x'},raw_version={'old':'1.10'},version='1.2',**self.SKIP)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('t 1.1 → 1.2',r.stdout)

class ConfigAt(StepHarness):
    """config_at (gh_raw.sh) and addon_sync.locate read a config the same way: a missing or empty file is skipped."""
    def bash(self,script,files,remote=None):
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp);(tmp/'bin').mkdir()
        for name,text in files.items():(tmp/'source'/name).parent.mkdir(parents=True,exist_ok=True);(tmp/'source'/name).write_text(text)
        gh=tmp/'bin/gh';gh.write_text('#!/bin/bash\nfor p in $REMOTE; do [[ "$*" == *"contents/${p%%=*}?"* ]] && { printf "%s" "${p#*=}"; exit 0; }; done\necho "gh: Not Found (HTTP 404)" >&2; exit 1\n');gh.chmod(0o755)
        env=dict(os.environ,PATH=f"{tmp/'bin'}{os.pathsep}{os.environ['PATH']}",REPO='WOOWTECH/t',REMOTE=' '.join(f'{k}={v}' for k,v in (remote or {}).items()))
        return subprocess.run([shutil.which('bash'),'-c','set -euo pipefail; source "$1"; shift; '+script,'-',(self.STORE/'.addon-sync/gh_raw.sh').as_posix()],cwd=tmp,env=env,capture_output=True,text=True)
    @needs_shell
    def test_a_missing_or_empty_config_falls_back_to_previous_config(self):
        for name,files,remote,ref in [('checkout: empty',{'addon/config.yaml':'','old/config.yaml':'v: 1'},None,''),
                ('checkout: missing',{'old/config.yaml':'v: 1'},None,''),
                ('ref: empty',{},{'addon/config.yaml':'','old/config.yaml':'v:1'},'b'),('ref: missing',{},{'old/config.yaml':'v:1'},'b')]:
            with self.subTest(name):
                r=self.bash(f'config_at "{ref}" addon/config.yaml old/config.yaml out.yaml',files,remote)
                self.assertEqual((r.returncode,r.stdout),(0,'old/config.yaml\n'),r.stderr)
    @needs_shell
    def test_neither_location_prints_nothing_and_leaves_an_empty_file(self):
        for ref,files in [('',{'addon/config.yaml':''}),('b',{})]:
            with self.subTest(ref=ref):
                r=self.bash(f'config_at "{ref}" addon/config.yaml old/config.yaml out.yaml; [ ! -s out.yaml ] && echo empty',files)
                self.assertEqual((r.returncode,r.stdout),(0,'empty\n'),r.stderr)

class Fields(StepHarness):
    """fields (fields.sh) reads one JSON line into shell variables for every step."""
    def bash(self,script,*args):
        import subprocess
        return subprocess.run([shutil.which('bash'),'-c','set -euo pipefail; source "$1"; shift; '+script,'-',(self.STORE/'.addon-sync/fields.sh').as_posix(),*args],capture_output=True,text=True)
    @needs_shell
    def test_values_are_quoted_for_eval(self):
        value='a b\'"$(touch x)";`id`\n::warning::x'
        r=self.bash('fields "$1" id=id path=config; printf "%s|%s" "${id}" "${path}"',json.dumps({'id':value,'config':'c/config.yaml'}))
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,value+'|c/config.yaml')
    @needs_shell
    def test_a_bad_line_stops_the_step(self):
        # eval of jq's empty output returned 0 and kept the previous line's values.
        r=self.bash('id=previous; fields "$1" id=id; echo "reached ${id}"','not json')
        self.assertNotEqual(r.returncode,0);self.assertNotIn('reached',r.stdout)
        # The step fails with the check's annotation, not only jq's stderr.
        self.assertTrue(r.stdout.startswith('::error title=Upgrade comparison failed::fields: jq cannot read not json'),r.stdout)
    @needs_shell
    def test_a_name_that_is_not_a_plain_variable_or_is_a_local_is_refused(self):
        # The name goes into jq's @sh output that is eval'd; the helper's own locals (all _f_...) would be overwritten before eval.
        for name in ('Id','1x','x-y','x;touch pwned','_f_json','_f_code','_f_anything'):
            with self.subTest(name):
                r=self.bash(f'fields "$1" "{name}=id"; echo reached',json.dumps({'id':'v'}))
                self.assertNotEqual(r.returncode,0);self.assertNotIn('reached',r.stdout)
                self.assertTrue(r.stdout.startswith('::error title=Upgrade comparison failed::fields: '),r.stdout)
        # Any other name is the caller's, including ones a helper might plausibly use.
        r=self.bash('fields "$1" json=id spec=id pair=id code=id; echo "${json}${spec}${pair}${code}"',json.dumps({'id':'v'}))
        self.assertEqual((r.returncode,r.stdout),(0,'vvvv\n'),r.stderr)
    def test_no_step_evals_jq_output_itself(self):
        self.assertNotIn('eval "$(jq',self.WF.read_text(encoding='utf-8'))

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
