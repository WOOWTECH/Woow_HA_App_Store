import contextlib,copy,datetime,io,json,pathlib,re,shutil,tempfile,unittest,unittest.mock
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
        # nginxpm bumps only its -v<N> suffix while upstream stays put: 2.12.4-v2 -> 2.12.4-v3.
        old=copy.deepcopy(BASE);old['version']='2.12.4-v2'
        cfg=self.REMOVED();cfg['version']='2.12.4-v3'
        for version,blocked in [('2.12.4-v3',False),('2.12.4-v2',True),('2.12.4-v10',True),('2.12.4',True),('2.12.3-v9',True)]:
            with self.subTest(version):self.assertEqual(run(cfg,self.notes(version),old=old,old_version='2.12.4-v2')['blocked'],blocked)
    def test_haos_core_dash_revision_versions(self):
        # Woow_haos_ha_core versions as <HA release>-<revision>: 2026.9.1-1 -> 2026.9.1-2, then 2026.9.2.
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
        r=u.compare(BASE,new(),'1.0.0','1.1.0',scan_note='skipped as approved in the Store registry: a reason')
        self.assertFalse(r['blocked']);self.assertIsNone(r['vulnerabilities'])
        self.assertIn('Vulnerability comparison: not run (skipped as approved in the Store registry: a reason).',r['report'])
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
        self.main('--old',self.write('old.yaml',BASE),'--new',self.write('new.yaml',new()),'--scan-note','skipped as approved in the Store registry: a reason')
        self.assertIn('not run (skipped as approved in the Store registry: a reason)',self.summary.read_text(encoding='utf-8'))
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
    def main(self,releases,component,components=('t',),version='99.0.0',on_base=False,catalog=None):
        """catalog: the Store catalog.json's content (passed as --catalog), or None for no --catalog."""
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d)
        (d/'registry.json').write_text(json.dumps({'providers':{'WOOWTECH/r':{'components':[{'id':c} for c in components]}}}))
        if catalog is not None:(d/'catalog.json').write_text(catalog if isinstance(catalog,str) else json.dumps(catalog),encoding='utf-8')
        stdin=releases if isinstance(releases,str) else json.dumps([r if isinstance(r,dict) else {'tag_name':r,'draft':False,'prerelease':False} for r in releases])
        with contextlib.redirect_stdout(io.StringIO()) as out,unittest.mock.patch('sys.stdin',io.StringIO(stdin)):
            code=u.main(['comparison-target','--registry',str(d/'registry.json'),'--repo','WOOWTECH/r','--component',component,'--version',version,
                *(['--on-base'] if on_base else []),*(['--catalog',str(d/'catalog.json')] if catalog is not None else [])])
        return code,out.getvalue()
    def seed(self,why,tag='v<version>'):
        return (f'::error title=Upgrade comparison failed::t is not a new add-on ({why}) but has no stable Release, so version 99.0.0 has nothing to be '
            f'compared with; publish a seed Release first ({tag}, the version on the default branch: from its merged release job, or for a Mirror source '
            'by hand with addon_sync.py release --apply; Store README, seed Release), then re-run this check\n')
    def test_an_add_on_on_the_pr_base_without_a_stable_release_fails(self):
        # #135: with a stable Release it is compared; without one only a new add-on (no config on the PR base) passes uncompared.
        self.assertEqual(self.main(['v1.2.0'],'t',on_base=True),(0,'v1.2.0\t1.2.0\n'))
        self.assertEqual(self.main([],'t'),(0,''))
        for releases,tag in [([],'v<version>'),(['nightly',{'tag_name':'v2.0.0','draft':False,'prerelease':True}],'v<version>'),(['t_2-v1.0.0'],'t-v<version>')]:
            with self.subTest(releases):
                code,out=self.main(releases,'t',('t','t_2'),on_base=True) if tag.startswith('t-') else self.main(releases,'t',on_base=True)
                self.assertEqual((code,out),(2,self.seed('its config is on the PR base',tag)))
    CATALOG={'schema':1,'components':{'t':{'repository':'WOOWTECH/r','version':'1.0.0'},'u':{'repository':'WOOWTECH/other','version':'2.0.0'}}}
    def test_an_add_on_in_the_store_catalog_without_a_stable_release_fails(self):
        # #135: users run what the Store catalog has, PR base or not (sha mode has none); with a stable Release it is compared.
        self.assertEqual(self.main([],'t',catalog=self.CATALOG),(2,self.seed('users run version 1.0.0 from the Store catalog')))
        self.assertEqual(self.main([],'t',on_base=True,catalog=self.CATALOG),
            (2,self.seed('its config is on the PR base; users run version 1.0.0 from the Store catalog')))
        self.assertEqual(self.main(['v1.2.0'],'t',catalog=self.CATALOG),(0,'v1.2.0\t1.2.0\n'))
    def test_a_catalog_entry_of_another_repository_is_ignored(self):
        # The same id shipped from another repository is not this add-on; an id the catalog lacks is a new add-on.
        self.assertEqual(self.main([],'u',('u',),catalog=self.CATALOG),(0,''))
        self.assertEqual(self.main([],'n',('n',),catalog=self.CATALOG),(0,''))
    def test_without_catalog_only_on_base_counts(self):
        self.assertEqual(self.main([],'t'),(0,''))
    def test_a_catalog_that_cannot_be_read_fails(self):
        # Never looser: a catalog the check cannot read is a tool error, not "a new add-on". Only needed with no stable Release.
        for catalog in ('{',[],{'schema':1}):
            with self.subTest(catalog):
                code,out=self.main([],'t',catalog=catalog);self.assertEqual(code,2);self.assertIn('::error title=Upgrade comparison failed::',out)
        self.assertEqual(self.main(['v1.2.0'],'t',catalog='{'),(0,'v1.2.0\t1.2.0\n'))
    def test_catalog_entry(self):
        self.assertEqual(u.catalog_entry(self.CATALOG,'WOOWTECH/r','t'),{'repository':'WOOWTECH/r','version':'1.0.0'})
        for repo,cid in (('WOOWTECH/r','u'),('WOOWTECH/r','n'),('woowtech/r','t')):
            with self.subTest(repo=repo,cid=cid):self.assertIsNone(u.catalog_entry(self.CATALOG,repo,cid))
        with self.assertRaisesRegex(ValueError,'no components object'):u.catalog_entry({'schema':1},'WOOWTECH/r','t')
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
        self.assertEqual(code,0);self.assertEqual(json.loads(out),{'ref_policy':'main','skip_vulnerability_scan':'#1: why','scan_published_image':'','components':[
            {'id':'a','config':'config.yaml','notes':'upgrade-notes.yaml','previous_config':'','previous_notes':'','ha_core':False},
            {'id':'b','config':'addons/b/config.yml','notes':'addons/b/upgrade-notes.yaml','previous_config':'','previous_notes':'','ha_core':False}]})
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps}}})
        self.assertEqual(json.loads(out)['skip_vulnerability_scan'],'')
    def test_approved_published_image_scan(self):
        # #147: the reason the registry approves scanning the image config.yaml names (image:version) on both sides.
        comps=[{'id':'a','source_path':'.','config_file':'config.yaml'}]
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps,'upgrade_comparison':{'scan_published_image':'#147: why'}}}})
        self.assertEqual((code,json.loads(out)['scan_published_image']),(0,'#147: why'))
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps}}})
        self.assertEqual(json.loads(out)['scan_published_image'],'')
    def test_skip_and_published_image_scan_together_fail(self):
        # Both name what category 4 scans; the registry must pick one.
        comps=[{'id':'a','source_path':'.','config_file':'config.yaml'}]
        code,out=self.main({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':comps,
            'upgrade_comparison':{'scan_published_image':'x','skip_vulnerability_scan':'y'}}}})
        self.assertEqual(code,2);self.assertIn('both skip_vulnerability_scan and scan_published_image',out)
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
# A step that also runs after an earlier one failed in sha mode (#167); on a PR the prefix is success(), as before.
SHA_GOES_ON="(success() || (inputs.sha != '' && !cancelled())) && "
ALWAYS_ON_PR_OR_SHA="always() && (github.event_name == 'pull_request' || inputs.sha != '')"
class ReusableWorkflow(unittest.TestCase):
    """Shape that callers and the ruleset depend on; the shell itself is verified on pilot PRs (#89 Testing Decisions)."""
    def setUp(self):
        path=pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/woow-addon-upgrade-check.yml'
        self.text=path.read_text(encoding='utf-8');self.wf=yaml.safe_load(self.text)
    def test_compare_job_reports_on_every_event_after_runtime(self):
        # The required check is "Upgrade comparison / compare": caller job name / this job's name. It waits for the
        # upgrade test (runtime, #137) and runs whatever runtime's result: a skipped required check counts as passed.
        self.assertIn('workflow_call',self.wf['on']);self.assertEqual(sorted(self.wf['jobs']),['compare','runtime'])
        job=self.wf['jobs']['compare'];self.assertEqual(job['name'],'compare')
        self.assertEqual((job['needs'],job['if']),('runtime','${{ always() }}'))
        self.assertNotIn('if',self.wf['jobs']['runtime']);self.assertNotIn('needs',self.wf['jobs']['runtime'])
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
        self.assertIn('wait_artifacts.sh wanted-sboms.tsv artifacts.tsv',steps[wait]['run'])
        self.assertEqual(self.wf['on']['workflow_call']['inputs']['sbom_wait_minutes']['default'],40)
        self.assertGreater(self.wf['jobs']['compare']['timeout-minutes'],40)
    def test_ref_policy_main_compares_with_where_the_base_version_first_appeared(self):
        # Under ref_policy main the Store follows main (#121), and the
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
    def test_device_built_add_ons_get_category_4_from_the_runtime_jobs_rebuilt_images(self):
        # #146: no step says category 4 of these add-ons is another ticket's; their SBOMs come from runtime, after it (needs).
        self.assertNotIn('#90',self.text.split('jobs:',1)[1])
        self.assertNotIn('has no prebuilt image',self.text)
        steps=self.wf['jobs']['compare']['steps'];names=[s.get('name') for s in steps]
        download=steps[names.index("Download the rebuilt images' SBOMs")]
        self.assertEqual(download['if'],SHA_GOES_ON+"steps.plan.outputs.rebuilt == 'true'")
        self.assertIn('upgrade-comparison-rebuilt-sboms-attempt-${RUN_ATTEMPT}',download['run'])
        self.assertLess(names.index("Download the rebuilt images' SBOMs"),names.index('Compare with the comparison target'))
        runtime=self.wf['jobs']['runtime']['steps'];rnames=[s.get('name') for s in runtime]
        upload=runtime[rnames.index("Upload the rebuilt images' SBOMs")]
        self.assertEqual((upload['if'],upload['with']['name'],upload['with']['path'],upload['with']['retention-days']),
            (ALWAYS_ON_PR_OR_SHA,'upgrade-comparison-rebuilt-sboms-attempt-${{ github.run_attempt }}','rebuilt-sboms/',7))
        # The same pinned Syft and config as compare's own SBOMs (#89).
        install=runtime[rnames.index('Install pinned Syft')]
        self.assertEqual(install['run'],'bash tooling/.github/actions/addon-sbom/install-scanners.sh "$RUNNER_TEMP/scanners" syft')
        self.assertLess(rnames.index('Install pinned Syft'),rnames.index('Build the images of add-ons built on the device'))
        build=runtime[rnames.index('Build the images of add-ons built on the device')]['run']
        self.assertIn('scan "docker:upgrade-comparison/$1:$2" --config tooling/.github/actions/addon-sbom/syft.yaml',build)
        self.assertIn('scan "docker:${image}" --config tooling/.github/actions/addon-sbom/syft.yaml',self.step("SBOMs of the comparison targets' images"))
    def test_runtime_plans_with_the_same_steps_as_compare(self):
        # Both jobs judge the same add-ons and comparison targets: runtime repeats compare's steps up to the plan.
        compare,runtime=self.wf['jobs']['compare']['steps'],self.wf['jobs']['runtime']['steps']
        plan=[s.get('name') for s in compare].index('Find the comparison targets')
        self.assertEqual(runtime[:plan+1],compare[:plan+1])
    def test_upgrade_test_result_fails_compare_with_the_reason(self):
        step=next(s for s in self.wf['jobs']['compare']['steps'] if s.get('name')=='Upgrade test result')
        self.assertEqual(step['if'],ALWAYS_ON_PR_OR_SHA)
        self.assertEqual(step['env']['RUNTIME_RESULT'],'${{ needs.runtime.result }}')
        self.assertIn('upgrade-comparison-runtime-attempt-${RUN_ATTEMPT}',step['run'])
        self.assertIn("upgrade test failed: $(jq -r '.reason'",step['run'])
        self.assertIn('if [ "${RUNTIME_RESULT}" != success ]',step['run'])
        self.assertIn('只檢查啟動，沒有檢查資料',step['run'])
        names=[s.get('name') for s in self.wf['jobs']['runtime']['steps']];steps=self.wf['jobs']['runtime']['steps']
        upload=steps[names.index('Upload the upgrade test results')]
        self.assertEqual(upload['with']['name'],'upgrade-comparison-runtime-attempt-${{ github.run_attempt }}')
        self.assertTrue(upload['if'].startswith('always()'))
        # A runtime step that fails before any add-on result (plan, pull, wait, load) still hands compare its reasons.
        record=steps[names.index('Record why the runtime job failed')]
        self.assertLess(names.index('Record why the runtime job failed'),names.index('Upload the upgrade test results'))
        self.assertTrue(record['if'].startswith('failure()'));self.assertIn('${FAIL_LOG}',record['run'])
        self.assertEqual(self.wf['jobs']['runtime']['env']['FAIL_LOG'],'${{ github.workspace }}/runtime-failures.txt')
    def test_new_image_comes_from_this_attempts_build_not_a_rebuild_or_ghcr(self):
        steps={s.get('name'):s for s in self.wf['jobs']['runtime']['steps']}
        self.assertIn('artifact="upgrade-comparison-image-${id}-attempt-${RUN_ATTEMPT}"',steps['Plan the upgrade tests']['run'])
        self.assertIn('wait_artifacts.sh wanted-images.tsv images.tsv',steps['Wait for the new images']['run'])
        self.assertIn('docker load -i',steps['Load the new images']['run'])
        self.assertIn('new_image="upgrade-comparison/${id}:new"',steps['Run the upgrade tests']['run'])
        self.assertIn('--new-image "${new_image}"',steps['Run the upgrade tests']['run'])
        # Only add-ons built on the device are built here (#144): an add-on with a prebuilt image is never rebuilt.
        builds=[n for n,s in steps.items() if 'docker build' in s.get('run','')]
        self.assertEqual(builds,['Build the images of add-ons built on the device'])
        self.assertIn('[ "${want}" = true ] && [ -n "${old_src}" ]',steps[builds[0]]['run'])
        self.assertIn('[ "${want}" = true ] && [ "${new_src}" = pr ]',steps[builds[0]]['run'])
        for name in ('Wait for the new images','Load the new images'):
            with self.subTest(name):self.assertEqual(steps[name]['if'],SHA_GOES_ON+"steps.upgrade.outputs.wait == 'true'")
        self.assertIn('select(.test and .new_src == "artifact")',steps['Wait for the new images']['run'])
        runtime=yaml.safe_dump(self.wf['jobs']['runtime'])
        for absent in ('docker push','buildx'):
            with self.subTest(absent):self.assertNotIn(absent,runtime)
        action=yaml.safe_load((pathlib.Path(__file__).resolve().parent.parent/'.github/actions/addon-image/action.yml').read_text(encoding='utf-8'))
        upload=next(s for s in action['runs']['steps'] if s.get('uses','').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['with']['name'],'upgrade-comparison-image-${{ inputs.component }}-attempt-${{ github.run_attempt }}')
        save=action['runs']['steps'][0]['run'];self.assertIn('docker save',save);self.assertIn('upgrade-comparison/${COMPONENT}:new',save)
    def test_add_ons_without_a_test_yet_are_named_with_their_ticket(self):
        plan=next(s for s in self.wf['jobs']['runtime']['steps'] if s.get('name')=='Plan the upgrade tests')['run']
        self.assertIn('the caller passes no image_artifact; the upgrade test is being rolled out in #143',plan)
        # Add-ons built on the device are tested (#144), and their rebuilt images get category 4 (#146).
        self.assertNotIn('the upgrade test for these add-ons is #144',plan)
    def step(self,name):return next(s for s in self.wf['jobs']['compare']['steps'] if s.get('name')==name)['run']
    def step_env(self,name):return next(s for s in self.wf['jobs']['compare']['steps'] if s.get('name')==name)['env']
SHELL_TOOLS=all(shutil.which(t) for t in ('bash','jq','yq'))
needs_shell=unittest.skipUnless(SHELL_TOOLS,'needs bash, jq and yq (present on GitHub runners)')
class StepHarness(unittest.TestCase):
    """Runs a real step script of the reusable workflow against a fake repository, gh stubbed (bash, jq, yq: CI runners)."""
    STORE=pathlib.Path(__file__).resolve().parent.parent
    WF=STORE/'.github/workflows/woow-addon-upgrade-check.yml'
    def setUp(self):self.wf=yaml.safe_load(self.WF.read_text(encoding='utf-8'))
    def step(self,ident):return next(s for j in ('compare','runtime') for s in self.wf['jobs'][j]['steps'] if ident in (s.get('id'),s.get('name')))
    def run_step(self,ident,*,policy='release',extra=None,releases=('v1.0.0',),old_config=True,new_config=True,skip='',sbom='',version='1.1.0',old=None,old_path='',
            new_path='addon/config.yaml',new=None,files=None,raw_version=None,history=None,changed=1,gh_fail='',images=(),vulnerable='',image_artifact='',
            tarball=None,build_fail='',news=None,syft_fail='',sha='',keep_going=False,results=None,runtime='success',on_base=None,catalog=None):
        """ident: one step, or a tuple run in order until one fails. new_path: where the PR has the config; new: changes to it;
        files: more files of the PR checkout; raw_version: {'old'/'new': the version line's YAML as written, e.g. 1.10 unquoted}.
        history: the PR base's history, newest first, [(sha, {path: changes to the config, or None for no file})]; the first
        sha must be 'b' (BASE_SHA). Without it, every ref has `old` (at old_path when given) and 'b' is its only commit.
        changed: how many registry add-ons the detect step reports as changed. gh_fail: any gh call containing it fails.
        images: the image references the registry has; `docker pull` of any other fails, and the stub Syft writes
        {"source": "<what it scanned>"} as the SBOM. vulnerable: the image whose SBOM the stub Grype finds a High fixable
        vulnerability in (CVE-2026-0001 openssl, fixed in 3.0.9); every scan reports the same DB.
        image_artifact: the caller's image_artifact (the runtime job's plan, #137).
        tarball: {path: text} in GitHub's archive of every ref besides its configs (#144); build_fail: the tag whose
        `docker build` fails. self.builds is every `docker build` (DOCKER_STUB); gh.log in self.tmp has every tarball URL asked for,
        rm.log every `docker image rm`. syft_fail: the image the stub Syft cannot read.
        news: {add-on id: changes to its PR config} for a changed add-on of a multi-add-on provider whose PR config is not t's.
        sha: the workflow input sha (sha mode, #167); keep_going: run every step of a tuple even after one fails, as sha mode
        does (self.runs has each step's CompletedProcess); results: {id: the runtime job's runtime-reports/<id>.json};
        runtime: the runtime job's result (RUNTIME_RESULT). on_base: what the detect step reports in changed.jsonl (#135);
        default: the PR base has the config (old_config), never in sha mode. catalog: the Store catalog's components
        ({id: entry}, tooling/.addon-sync/catalog.json; default none: every add-on is new to the Store, #135).
        self.tmp is the job's directory (also RUNNER_TEMP); self.plans is every line of plan.jsonl."""
        import os,subprocess
        tmp=self.tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'tooling/.addon-sync').mkdir(parents=True);(tmp/'source').mkdir();(tmp/'bin').mkdir()
        for f in (self.STORE/'.addon-sync').iterdir():
            if f.suffix in ('.py','.sh'):shutil.copy(f,tmp/'tooling/.addon-sync'/f.name)
        (tmp/'tooling/.addon-sync/registry.json').write_text(json.dumps({'providers':{'WOOWTECH/t':{'ref_policy':policy,'components':[
            {'id':'t','source_path':'addon','config_file':'config.yaml'}],**(extra or {})}}}))
        (tmp/'tooling/.addon-sync/catalog.json').write_text(json.dumps({'schema':1,'components':catalog or {}}))
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
        for cid,changes in (news or {}).items():(tmp/f'{cid}.new.yaml').write_text(dump(dict(cfg,version=version,**changes),'new'))
        def new_of(cid):return str(tmp/(f'{cid}.new.yaml' if cid in (news or {}) else 't.new.yaml'))
        (tmp/'changed.jsonl').write_text(''.join(json.dumps(dict(c,version=version,new=new_of(c['id']),on_base=bool(old_config) and not sha if on_base is None else on_base))+'\n' for c in json.loads(provider.getvalue())['components'][:changed]))
        if history is not None:
            (tmp/'history.json').write_text(json.dumps([{'sha':sha,'date':f'2026-01-01T00:{59-i:02d}:00Z','files':{p:dump(dict(cfg,**c),'old')
                for p,c in at.items() if c is not None}} for i,(sha,at) in enumerate(history)]))
        gh=tmp/'bin/gh';gh.write_text(GH_STUB);gh.chmod(0o755)
        (tmp/'scanners').mkdir()
        for path,stub in ((tmp/'bin/docker',DOCKER_STUB),(tmp/'scanners/syft',SYFT_STUB),(tmp/'scanners/grype',GRYPE_STUB)):path.write_text(stub);path.chmod(0o755)
        # What `gh api --paginate .../releases --jq '.[]'` prints: one Release object per line; a bare tag is a stable Release.
        releases='\n'.join(json.dumps(r if isinstance(r,dict) else {'tag_name':r,'draft':False,'prerelease':False}) for r in releases)
        env=dict(os.environ,PATH=f"{tmp/'bin'}{os.pathsep}{os.environ['PATH']}",OLD=str(tmp/'old.yaml'),OLD_PATH=old_path,RELEASES=releases,REPO='WOOWTECH/t',BASE_SHA='b',
            GH_TOKEN='x',DB_MAX_AGE_HOURS='120',IMAGES='\n'.join(images),VULNERABLE=vulnerable,SBOM_ARTIFACT=sbom,IMAGE_ARTIFACT=image_artifact,SKIP_VULNERABILITY_SCAN=skip,RUNNER_TEMP=str(tmp),RUN_ATTEMPT='1',
            GITHUB_OUTPUT=str(tmp/'out'),GITHUB_STEP_SUMMARY=str(tmp/'summary'),HISTORY=str(tmp/'history.json') if history is not None else '',GH_FAIL=gh_fail,
            TMPDIR=str(tmp/'mktemp'),TARBALL=json.dumps(tarball or {}),BUILD_FAIL=build_fail,DOCKER_LOG=str(tmp/'docker.log'),GH_LOG=str(tmp/'gh.log'),
            DOCKER_RM_LOG=str(tmp/'rm.log'),SYFT_FAIL=syft_fail,SHA=sha,RUN_ID='1',RUNTIME_RESULT=runtime)
        if results is not None:
            (tmp/'runtime-reports').mkdir(exist_ok=True)
            for cid,result in results.items():(tmp/'runtime-reports'/f'{cid}.json').write_text(json.dumps(result))
        (tmp/'mktemp').mkdir(exist_ok=True)
        self.runs=[]
        for one in (ident if isinstance(ident,tuple) else (ident,)):
            (tmp/'step.sh').write_text(self.step(one)['run'])
            r=subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=env,capture_output=True,text=True);self.runs.append(r)
            if r.returncode and not keep_going:break
        self.plans=[json.loads(l) for l in (tmp/'plan.jsonl').read_text().splitlines()] if (tmp/'plan.jsonl').exists() else []
        self.builds=[json.loads(l) for l in (tmp/'docker.log').read_text().splitlines()] if (tmp/'docker.log').exists() else []
        return r,(self.plans[0] if self.plans else {}),(tmp/'out').read_text() if (tmp/'out').exists() else ''
    def run_runtime_steps(self,tmp,steps,**env):
        """Runtime-job steps run in order in tmp (the job's directory, also RUNNER_TEMP), every one even after a failure;
        tmp/bin first on PATH. upgrade_runtime.py is stood in for: it passes and records the images it was given.
        env: more variables (e.g. IMAGES for DOCKER_STUB). Returns each step's CompletedProcess."""
        import os,subprocess
        (tmp/'tooling/.addon-sync/upgrade_runtime.py').write_text('import argparse,json,pathlib\np=argparse.ArgumentParser()\n'
            "for o in ('--name','--addon-dir','--old-image','--old-config','--new-image','--new-config','--report-dir','--summary'):p.add_argument(o)\n"
            "p.add_argument('--ha-core',action='store_true')\n"
            "a=p.parse_args();pathlib.Path(a.report_dir,a.name+'.json').write_text(json.dumps({'name':a.name,'passed':True,'old_image':a.old_image,'new_image':a.new_image,"
            "**({'ha_core':True} if a.ha_core else {})}))\n")
        env=dict(os.environ,PATH=f"{tmp/'bin'}{os.pathsep}{os.environ['PATH']}",RUNNER_TEMP=str(tmp),GITHUB_STEP_SUMMARY=str(tmp/'summary'),**env)
        runs=[]
        for step in steps:
            (tmp/'step.sh').write_text(self.step(step)['run'],newline='\n')
            runs.append(subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=env,capture_output=True,text=True))
        return runs

# The fake GitHub API of StepHarness: Releases, raw files at a ref and the commits that changed a path (with --jq through jq).
GH_STUB=r'''#!/usr/bin/env python3
import json,os,re,subprocess,sys,urllib.parse
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
    q={k:urllib.parse.unquote(v) for k,v in (p.split('=',1) for p in url.split('?',1)[1].split('&'))}
    commits=history if history is not None else [{'sha':'b','date':'2026-01-01T00:00:00Z','files':{q['path']:legacy(q['path'])}}]
    start=next(i for i,c in enumerate(commits) if c['sha']==q['sha'])
    def changed(i):return commits[i]['files'].get(q['path'])!=(commits[i+1]['files'].get(q['path']) if i+1<len(commits) else None)
    out([{'sha':c['sha'],'commit':{'committer':{'date':c['date']}}} for i,c in enumerate(commits) if i>=start and changed(i)])
elif '/actions/runs/' in url:
    out({'artifacts':[]})  # no artifact: the runtime job's results are already in runtime-reports/ (results)
elif '/tarball/' in url:
    # The repository at a ref as GitHub archives it: one top directory, the configs at that ref and $TARBALL's files.
    import io,tarfile
    ref=urllib.parse.unquote(url.split('/tarball/',1)[1])
    with open(os.environ['GH_LOG'],'a') as f:f.write(url+'\n')
    files={c['sha']:c['files'] for c in history}.get(ref,{}) if history is not None else {old_path or 'addon/config.yaml':legacy(old_path or 'addon/config.yaml')}
    files={**{p:t for p,t in files.items() if t is not None},**json.loads(os.environ.get('TARBALL') or '{}')}
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:gz') as tar:
        for path,text in files.items():
            data=text.encode();info=tarfile.TarInfo(f'WOOWTECH-t-{ref}/{path}');info.size=len(data);tar.addfile(info,io.BytesIO(data))
    sys.stdout.buffer.write(buf.getvalue())
else:sys.exit(1)
'''

# StepHarness's image registry: `docker pull` succeeds only for a reference in $IMAGES; `docker image rm` always does (and
# appends the image to $DOCKER_RM_LOG when set).
# `docker build` appends {args, files: the context's files and their text} to $DOCKER_LOG and fails for the tag $BUILD_FAIL.
DOCKER_STUB=r'''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
if args[:1]==['pull']:
    if args[-1] in os.environ.get('IMAGES','').split('\n'):sys.exit(0)
    print(f'Error response from daemon: manifest unknown: {args[-1]}',file=sys.stderr);sys.exit(1)
if args[:1]==['build']:
    context=pathlib.Path(args[-1]);tag=args[args.index('-t')+1]
    files={p.relative_to(context).as_posix():p.read_text() for p in context.rglob('*') if p.is_file()}
    with open(os.environ['DOCKER_LOG'],'a') as f:f.write(json.dumps({'args':args,'files':files})+'\n')
    if tag==os.environ.get('BUILD_FAIL'):print('ERROR: failed to solve: process "/bin/sh -c false" did not complete successfully',file=sys.stderr);sys.exit(1)
    sys.exit(0)
if args[:2]==['image','rm']:
    if os.environ.get('DOCKER_RM_LOG'):
        with open(os.environ['DOCKER_RM_LOG'],'a') as f:f.write(args[-1]+'\n')
    sys.exit(0)
sys.exit(1)
'''
# Stub Syft: `syft scan <source> --config ... -o syft-json=<file>` writes {"source": <source>} to <file>; it fails for
# the source docker:$SYFT_FAIL.
SYFT_STUB=r'''#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:];out=next(a for a in args if a.startswith('syft-json=')).split('=',1)[1]
if args[1]=='docker:'+os.environ.get('SYFT_FAIL','-'):print('syft: cannot read the image',file=sys.stderr);sys.exit(1)
json.dump({'source':args[1]},open(out,'w'))
'''
# Stub Grype: `grype sbom:<file> -o json --file <out>`; one High fixable match when the SBOM is of $VULNERABLE.
GRYPE_STUB=r'''#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:];source=json.load(open(args[0].split(':',1)[1]))['source']
match={'vulnerability':{'id':'CVE-2026-0001','severity':'High','fix':{'state':'fixed','versions':['3.0.9']}},'artifact':{'name':'openssl'}}
scan={'matches':[match] if source=='docker:'+os.environ.get('VULNERABLE','') else [],
    'descriptor':{'db':{'status':{'built':'2026-11-01T00:00:00Z','from':'https://grype.anchore.io/db'}}}}
json.dump(scan,open(args[args.index('--file')+1],'w'))
'''

def registry_approvals(key):
    """{repository: approved reason} of the Store registry's upgrade_comparison.<key>."""
    registry=json.loads((StepHarness.STORE/'.addon-sync/registry.json').read_text(encoding='utf-8'))
    return {repo:p['upgrade_comparison'][key] for repo,p in registry['providers'].items() if key in (p.get('upgrade_comparison') or {})}

class UpgradeTestPlan(StepHarness):
    """The runtime job's plan (#137): which add-ons get the upgrade test, with which old image and new-image artifact."""
    def plan(self,**kw):
        kw.setdefault('sbom','upgrade-comparison-sbom-*')
        r,_,out=self.run_step(('plan','upgrade'),**kw)
        rows=[json.loads(l) for l in (self.tmp/'upgrade.jsonl').read_text().splitlines()] if (self.tmp/'upgrade.jsonl').exists() else []
        return r,rows,out
    def note(self):return json.loads((self.tmp/'runtime-reports/t.json').read_text())
    @needs_shell
    def test_prebuilt_add_on_is_tested_with_the_targets_ghcr_image_and_this_attempts_artifact(self):
        r,(row,),out=self.plan(image_artifact='upgrade-comparison-image-*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('run=true',out)
        self.assertEqual((row['old_ref'],row['artifact'],row['addon_dir']),('ghcr.io/da-anda/addon-amd64:1.0.0','upgrade-comparison-image-t-attempt-1','source/addon'))
        self.assertFalse((self.tmp/'runtime-reports/t.json').exists())
    @needs_shell
    def test_caller_without_image_artifact_is_reported_as_not_rolled_out(self):
        r,(row,),out=self.plan()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('run=false',out);self.assertEqual(row['old_ref'],'')
        self.assertEqual(self.note(),{'name':'t','passed':None,'not_run':'no_image_artifact','note':'the caller passes no image_artifact; the upgrade test is being rolled out in #143'})
    @needs_shell
    def test_device_built_add_on_rebuilds_the_release_and_builds_the_pr_without_an_artifact(self):
        # #144: no image to pull or hand over, so the caller needs no image_artifact; the old image is rebuilt from the Release tag.
        r,(row,),out=self.plan(new={'image':None},old={'image':None},sbom='')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((row['test'],row['old_ref'],row['old_src'],row['new_src']),(True,'','v1.0.0','pr'))
        for output in ('run=true','build=true','wait=false'):
            with self.subTest(output):self.assertIn(output,out)
        self.assertFalse((self.tmp/'runtime-reports/t.json').exists())
    @needs_shell
    def test_ref_policy_main_rebuilds_the_commit_where_the_base_version_first_appeared(self):
        p='addon/config.yaml';history=[('b',{p:{'version':'2.0','image':None,'log_level':'warn'}}),('c',{p:{'version':'2.0','image':None}}),('o',{p:{'version':'1.9','image':None}})]
        r,(row,),out=self.plan(policy='main',history=history,version='2.1',new={'image':None},sbom='')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual((row['old_src'],row['new_src']),('c','pr'))
    @needs_shell
    def test_a_move_between_prebuilt_and_built_on_the_device_takes_each_side_from_where_it_is(self):
        # The comparison target was built on the device, the PR ships a prebuilt image: rebuild the old one, await the new one.
        r,(row,),out=self.plan(old={'image':None},image_artifact='upgrade-comparison-image-*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((row['old_ref'],row['old_src'],row['new_src']),('','v1.0.0','artifact'));self.assertIn('wait=true',out)
        # And back: the target's image is pulled, the PR's is built here.
        r,(row,),out=self.plan(new={'image':None},sbom='')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((row['old_ref'],row['old_src'],row['new_src']),('ghcr.io/da-anda/addon-amd64:1.0.0','','pr'));self.assertIn('wait=false',out)
    @needs_shell
    def test_device_built_add_on_without_a_comparison_target_is_not_tested(self):
        r,(row,),out=self.plan(new={'image':None},old={'image':None},sbom='',releases=(),old_config=False)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertFalse(row['test']);self.assertIn('run=false',out)
        self.assertEqual((self.note()['note'],self.note()['not_run']),('no comparison target','no_target'))
    @needs_shell
    def test_image_artifact_that_does_not_match_fails(self):
        r,rows,out=self.plan(image_artifact='other-*')
        self.assertNotEqual(r.returncode,0);self.assertIn("image_artifact 'other-*' does not match upgrade-comparison-image-t-attempt-1",r.stdout)

class DeviceBuiltImages(StepHarness):
    """'Build the images of add-ons built on the device' (#144): both images built for amd64 as Supervisor builds them,
    the comparison target's from GitHub's archive of the target, the new one from the PR checkout."""
    STEPS=('plan','Skip the upgrade tests the registry approves','upgrade','Build the images of add-ons built on the device')
    DEVICE=dict(new={'image':None},old={'image':None},sbom='')
    BUILD='build_from:\n  amd64: ghcr.io/woowtech/base:{v}\nargs:\n  EXTRA: "{v}"\n'
    def build(self,**kw):
        kw.setdefault('files',{'addon/Dockerfile':'FROM new','addon/build.yaml':self.BUILD.format(v='new')})
        kw.setdefault('tarball',{'addon/Dockerfile':'FROM old','addon/build.yaml':self.BUILD.format(v='old')})
        return self.run_step(self.STEPS,**{**self.DEVICE,**kw})[0]
    @staticmethod
    def build_args(b):return [a for i,a in enumerate(b['args']) if i and b['args'][i-1]=='--build-arg']
    @needs_shell
    def test_old_from_the_targets_source_and_new_from_the_pr_as_supervisor_builds_them(self):
        r=self.build()
        # The PR's image first, so a PR that does not build is the PR's fault whatever its target does.
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);new,old=self.builds
        for b,side,version in ((old,'old','1.0.0'),(new,'new','1.1.0')):
            with self.subTest(side):
                self.assertEqual(b['args'][b['args'].index('-t')+1],f'upgrade-comparison/t:{side}')
                self.assertEqual(b['args'][b['args'].index('--platform')+1],'linux/amd64')
                self.assertEqual(b['files']['Dockerfile'],f'FROM {side}')
                self.assertEqual(self.build_args(b),[f'BUILD_FROM=ghcr.io/woowtech/base:{side}',f'BUILD_VERSION={version}','BUILD_ARCH=amd64',f'EXTRA={side}'])
        # The target's tree comes from GitHub's archive of the Release tag; the PR's is the checkout.
        self.assertTrue(old['args'][-1].endswith('old-src-0/addon'));self.assertEqual(new['args'][-1],'source/addon')
        self.assertEqual((self.tmp/'gh.log').read_text(),'repos/WOOWTECH/t/tarball/v1.0.0\n')
        # The archive and its tree are gone once the images are built.
        self.assertEqual(list(self.tmp.glob('old-src-*')),[])
    @needs_shell
    def test_ref_policy_main_builds_the_commit_where_the_base_version_first_appeared(self):
        p='addon/config.yaml';history=[('b',{p:{'version':'2.0','image':None,'log_level':'warn'}}),('c',{p:{'version':'2.0','image':None}}),('o',{p:{'version':'1.9','image':None}})]
        r=self.build(policy='main',history=history,version='2.1')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);old=self.builds[1]
        self.assertTrue(old['args'][-1].endswith('old-src-0/addon'));self.assertIn('BUILD_VERSION=2.0',self.build_args(old))
        self.assertNotIn('log_level',yaml.safe_load(old['files']['config.yaml']))  # c's tree, not the PR base b's
    @needs_shell
    def test_add_ons_sharing_a_comparison_target_download_it_once(self):
        # A multi-add-on repository under ref_policy main: each add-on's target is the same commit here.
        comps=[{'id':i,'source_path':'addon','config_file':'config.yaml'} for i in ('t','u')]
        p='addon/config.yaml';history=[('b',{p:{'version':'2.0','image':None}}),('o',{p:{'version':'1.9','image':None}})]
        r=self.build(policy='main',history=history,version='2.1',extra={'components':comps},changed=2)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((self.tmp/'gh.log').read_text(),'repos/WOOWTECH/t/tarball/b\n')
        self.assertEqual([b['args'][b['args'].index('-t')+1] for b in self.builds],
            ['upgrade-comparison/t:new','upgrade-comparison/t:old','upgrade-comparison/u:new','upgrade-comparison/u:old'])
    def test_the_tarball_ref_is_percent_encoded(self):
        build=self.step('Build the images of add-ons built on the device')['run']
        self.assertIn('''tarball/$(jq -rn --arg ref "${old_src}" '$ref | @uri')''',build)
    @needs_shell
    def failed(self,r,reason,exact=True):
        """Like a pull (#140): the step goes on, the add-on leaves the test with its result, and "Run the upgrade tests"
        fails the job for it (ComparisonTargetFailure). exact False: `reason` is the start of the reason."""
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn(f'::error title=Upgrade comparison failed::t: {reason}',r.stdout)
        result=json.loads((self.tmp/'runtime-reports/t.json').read_text())
        if not exact:self.assertTrue(result['reason'].startswith(reason),result['reason']);reason=result['reason']
        self.assertEqual(result,{'name':'t','passed':False,'reason':reason,'hooks':[],'data_checked':False,'phases':[]})
        self.assertEqual([json.loads(l)['test'] for l in (self.tmp/'upgrade.jsonl').read_text().splitlines()],[False])
        return reason
    DOCKER_FAILED="docker build exited with code 1; its log is in the step 'Build the images of add-ons built on the device'"
    @needs_shell
    def test_a_comparison_target_that_cannot_be_rebuilt_is_a_target_failure(self):
        r=self.build(build_fail='upgrade-comparison/t:old')
        self.failed(r,f'the comparison target v1.0.0 could not be rebuilt for amd64, so the upgrade cannot be tested: {self.DOCKER_FAILED}')
        self.assertEqual(len(self.builds),2)
    @needs_shell
    def test_a_target_whose_source_cannot_be_downloaded_is_a_target_failure(self):
        r=self.build(gh_fail='/tarball/')
        self.failed(r,'cannot download the source of the comparison target v1.0.0 to rebuild its image, so the upgrade cannot be tested; re-run the check')
        self.assertEqual(len(self.builds),1)  # the PR's image was built first
    @needs_shell
    def test_a_pr_that_cannot_be_built_fails_as_the_prs_fault_before_its_target_is_built(self):
        r=self.build(build_fail='upgrade-comparison/t:new',gh_fail='/tarball/')
        self.failed(r,f'the new version could not be built for amd64 from this PR: {self.DOCKER_FAILED}')
        self.assertFalse((self.tmp/'gh.log').exists())
    @needs_shell
    def test_the_tools_error_is_the_reason(self):
        # A target without a Dockerfile: build-args' own message is in the report, not only "see the log".
        reason=self.failed(self.build(tarball={}),'the comparison target v1.0.0 could not be rebuilt for amd64, so the upgrade cannot be tested: t: ',exact=False)
        self.assertIn('no Dockerfile (or Dockerfile.amd64)',reason)
        reason=self.failed(self.build(files={'addon/Dockerfile':'FROM new','addon/build.yaml':'args:\n  "A B": x\n'}),
            'the new version could not be built for amd64 from this PR: t: ',exact=False)
        self.assertIn("build argument name 'A B' must be non-empty, without = or whitespace",reason)
    SKIPPED={'components':[{'id':'t','source_path':'addon','config_file':'config.yaml','upgrade_comparison':{'skip_upgrade_test':'#158: needs a physical enp2s0'}}]}
    SKIP_NOTE='categories 2 and 3 skipped as approved in the Store registry: #158: needs a physical enp2s0'
    def rows(self):return [json.loads(l) for l in (self.tmp/'upgrade.jsonl').read_text().splitlines()]
    def sbom(self,side):
        p=self.tmp/f'rebuilt-sboms/t.{side}.syft.json';return json.loads(p.read_text()) if p.exists() else None
    def removed(self):return (self.tmp/'rm.log').read_text().splitlines() if (self.tmp/'rm.log').exists() else []
    @needs_shell
    def test_tested_add_on_gets_sboms_of_both_rebuilt_images_right_after_each_build(self):
        # #146: category 4 of an add-on built on the device uses the images built here for the upgrade test.
        r=self.build()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((self.sbom('old'),self.sbom('new')),({'source':'docker:upgrade-comparison/t:old'},{'source':'docker:upgrade-comparison/t:new'}))
        self.assertFalse((self.tmp/'rebuilt-sboms/t.json').exists())
        # Kept for the upgrade test ("Run the upgrade tests" removes them).
        self.assertEqual(self.removed(),[]);self.assertEqual([x['test'] for x in self.rows()],[True])
    @needs_shell
    def test_an_approved_skip_is_built_for_its_sboms_but_not_tested(self):
        # woow_lan_gateway (#158, permanent): skip_upgrade_test skips categories 2 and 3 only (owner, #146): both images are
        # still rebuilt and get SBOMs, then removed; it is never started, and its result stays the registry's reason.
        r,_,out=self.run_step(self.STEPS[:3],extra=self.SKIPPED,**self.DEVICE)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        for output in ('run=false','build=true','sbom=true'):
            with self.subTest(output):self.assertIn(output,out)
        (row,)=self.rows();self.assertEqual((row['test'],row['sbom'],row['old_src'],row['new_src']),(False,True,'v1.0.0','pr'))
        r=self.build(extra=self.SKIPPED)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual([b['args'][b['args'].index('-t')+1] for b in self.builds],['upgrade-comparison/t:new','upgrade-comparison/t:old'])
        self.assertEqual((self.sbom('old'),self.sbom('new')),({'source':'docker:upgrade-comparison/t:old'},{'source':'docker:upgrade-comparison/t:new'}))
        self.assertEqual(self.removed(),['upgrade-comparison/t:new','upgrade-comparison/t:old'])
        self.assertEqual(json.loads((self.tmp/'runtime-reports/t.json').read_text()),
            {'name':'t','passed':None,'skipped':True,'not_run':'approved_skip','note':self.SKIP_NOTE})
        self.assertEqual([x['test'] for x in self.rows()],[False])
    @needs_shell
    def test_a_skipped_prebuilt_add_on_is_not_built(self):
        r,_,out=self.run_step(self.STEPS[:3],extra=self.SKIPPED,sbom='upgrade-comparison-sbom-*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(self.rows(),[])
        for output in ('run=false','build=false','sbom=false'):
            with self.subTest(output):self.assertIn(output,out)
    @needs_shell
    def test_an_sbom_only_build_failure_is_recorded_for_category_4_not_as_a_test_result(self):
        for name,kw,reason in (('target',dict(build_fail='upgrade-comparison/t:old'),f'the comparison target v1.0.0 could not be rebuilt for amd64: {self.DOCKER_FAILED}'),
                ('download',dict(gh_fail='/tarball/'),'cannot download the source of the comparison target v1.0.0 to rebuild its image; re-run the check'),
                ('pr',dict(build_fail='upgrade-comparison/t:new'),f'the new version could not be built for amd64 from this PR: {self.DOCKER_FAILED}'),
                ('syft',dict(syft_fail='upgrade-comparison/t:new'),'Syft could not read the rebuilt new image upgrade-comparison/t:new')):
            with self.subTest(name):
                r=self.build(extra=self.SKIPPED,**kw)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                self.assertEqual(json.loads((self.tmp/'rebuilt-sboms/t.json').read_text()),{'reasons':[reason]})
                self.assertIn(f'::error title=Upgrade comparison failed::t: {reason}',r.stdout)
                self.assertEqual(json.loads((self.tmp/'runtime-reports/t.json').read_text())['not_run'],'approved_skip')
                # "Run the upgrade tests" does not fail the job for it: only category 4 fails.
                (run,)=self.run_runtime_steps(self.tmp,('Run the upgrade tests',));self.assertEqual(run.returncode,0,run.stdout+run.stderr)
    @needs_shell
    def test_a_tested_add_ons_build_failure_also_leaves_its_reason_for_category_4(self):
        reason=self.failed(self.build(build_fail='upgrade-comparison/t:old'),
            f'the comparison target v1.0.0 could not be rebuilt for amd64, so the upgrade cannot be tested: {self.DOCKER_FAILED}')
        self.assertEqual(json.loads((self.tmp/'rebuilt-sboms/t.json').read_text()),
            {'reasons':[f'the comparison target v1.0.0 could not be rebuilt for amd64: {self.DOCKER_FAILED}']})
        self.assertIn('so the upgrade cannot be tested',reason)
    @needs_shell
    def test_a_tested_add_on_whose_syft_fails_is_still_tested(self):
        r=self.build(syft_fail='upgrade-comparison/t:old')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual([x['test'] for x in self.rows()],[True])
        self.assertFalse((self.tmp/'runtime-reports/t.json').exists());self.assertIsNone(self.sbom('old'))
        self.assertEqual(json.loads((self.tmp/'rebuilt-sboms/t.json').read_text()),{'reasons':['Syft could not read the rebuilt old image upgrade-comparison/t:old']})
    @needs_shell
    def test_without_category_4_no_sbom_is_made(self):
        # skip_vulnerability_scan: still built and tested, no SBOM.
        r=self.build(skip='a reason',extra={'upgrade_comparison':{'skip_vulnerability_scan':'#x: approved'}})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(len(self.builds),2)
        self.assertEqual(list((self.tmp/'rebuilt-sboms').glob('*')),[]);self.assertEqual([x['sbom'] for x in self.rows()],[False])

class DeviceBuiltVulnerabilityComparison(StepHarness):
    """Category 4 of add-ons built on the device (#146): the plan marks each rebuilt side, the runtime job hands over the
    SBOMs of the images it rebuilds, and compare scans them with its one Grype DB, as it scans prebuilt images (#89)."""
    RUNTIME=('plan','Skip the upgrade tests the registry approves','upgrade','Build the images of add-ons built on the device')
    DEVICE=DeviceBuiltImages.DEVICE
    FILES={'addon/Dockerfile':'FROM new','addon/build.yaml':DeviceBuiltImages.BUILD.format(v='new')}
    TARBALL={'addon/Dockerfile':'FROM old','addon/build.yaml':DeviceBuiltImages.BUILD.format(v='old')}
    OLD='ghcr.io/da-anda/addon-amd64:1.0.0'
    def runtime(self,**kw):
        kw.setdefault('files',self.FILES);kw.setdefault('tarball',self.TARBALL)
        return self.run_step(self.RUNTIME,**{**self.DEVICE,**kw})
    def compare(self,**env):
        """compare's 'Compare with the comparison target' in the job's directory, after the runtime steps (the harness
        stands in for the download: rebuilt-sboms/ is where it would unzip the artifact)."""
        (r,)=self.run_runtime_steps(self.tmp,('Compare with the comparison target',),DB_MAX_AGE_HOURS='120',**env)
        return r
    @needs_shell
    def test_both_sides_rebuilt_plan_a_scan_without_waiting(self):
        r,plan,out=self.run_step('plan',**self.DEVICE)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((plan['ref'],plan['new_ref'],plan['rebuilt_old'],plan['rebuilt_new'],plan['note']),('','',True,True,''))
        for output in ('scan=true','wait=false','rebuilt=true'):
            with self.subTest(output):self.assertIn(output,out)
    @needs_shell
    def test_without_a_comparison_target_there_is_nothing_to_scan(self):
        r,plan,out=self.run_step('plan',releases=(),old_config=False,**self.DEVICE)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((plan['note'],plan['rebuilt_old'],plan['rebuilt_new']),('no comparison target',False,False))
        for output in ('scan=false','rebuilt=false'):
            with self.subTest(output):self.assertIn(output,out)
    @needs_shell
    def test_a_new_fixable_vulnerability_in_the_rebuilt_pr_image_blocks(self):
        r,_,_=self.runtime();self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        r=self.compare(VULNERABLE='upgrade-comparison/t:new')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('::error title=New fixable vulnerability::CVE-2026-0001 openssl (High, fixed in 3.0.9)',r.stdout)
        self.assertIn('t: scanned v1.0.0 rebuilt and the PR image rebuilt with the same DB',r.stdout)
        # Only in the old image: reported, not blocking.
        r=self.compare(VULNERABLE='upgrade-comparison/t:old')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('No new fixable vulnerabilities.',r.stdout)
        self.assertNotIn('#90',r.stdout)
    @needs_shell
    def test_an_approved_skip_still_gets_category_4(self):
        # woow_lan_gateway: categories 2 and 3 skipped, category 4 judged on its rebuilt images.
        r,_,_=self.runtime(extra=DeviceBuiltImages.SKIPPED);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        r=self.compare(VULNERABLE='upgrade-comparison/t:new')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('CVE-2026-0001 openssl',r.stdout)
    @needs_shell
    def test_an_sbom_only_rebuild_failure_fails_category_4_with_its_reason(self):
        r,_,_=self.runtime(extra=DeviceBuiltImages.SKIPPED,build_fail='upgrade-comparison/t:old');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        r=self.compare()
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('::error title=Upgrade comparison failed::t: the vulnerability comparison cannot run without the SBOMs of both images: '
            f'the comparison target v1.0.0 could not be rebuilt for amd64: {DeviceBuiltImages.DOCKER_FAILED}',r.stdout)
    @needs_shell
    def test_a_missing_artifact_fails_saying_so(self):
        r,_,_=self.run_step('plan',**self.DEVICE);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        r=self.compare()
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('::error title=Upgrade comparison failed::t: the runtime job handed over no SBOMs of the rebuilt images; its log has the reason',r.stdout)
    @needs_shell
    def test_an_artifact_without_this_add_ons_sbom_fails(self):
        r,_,_=self.run_step('plan',**self.DEVICE);(self.tmp/'rebuilt-sboms').mkdir()
        r=self.compare()
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn("t: the runtime job handed over no SBOM of this add-on's rebuilt image; its log has the reason",r.stdout)
    @needs_shell
    def test_a_rebuilt_target_and_a_prebuilt_pr_image_are_compared_per_side(self):
        # The target was built on the device, the PR ships a prebuilt image: old from the runtime job, new from the caller's SBOM.
        kw=dict(old={'image':None},sbom='upgrade-comparison-sbom-*',image_artifact='upgrade-comparison-image-*')
        r,plan,out=self.run_step('plan',**kw)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((plan['ref'],plan['rebuilt_old'],plan['rebuilt_new'],plan['note']),('',True,False,''))
        for output in ('scan=true','wait=true','rebuilt=true'):
            with self.subTest(output):self.assertIn(output,out)
        r,_,_=self.run_step(self.RUNTIME,files=self.FILES,tarball=self.TARBALL,**kw);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual([b['args'][b['args'].index('-t')+1] for b in self.builds],['upgrade-comparison/t:old'])
        (self.tmp/'sboms').mkdir();(self.tmp/'sboms/t.syft.json').write_text(json.dumps({'source':'docker:the caller build'}))
        r=self.compare(VULNERABLE='the caller build')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('t: scanned v1.0.0 rebuilt and the PR image with the same DB',r.stdout)
        self.assertNotIn('has no prebuilt image',r.stdout)
    @needs_shell
    def test_a_rebuilt_target_is_built_for_its_sbom_when_the_test_does_not_run(self):
        # The caller passes no image_artifact (#143), so the upgrade test does not run; category 4 still gets the target's SBOM.
        r,_,out=self.run_step(self.RUNTIME,files=self.FILES,tarball=self.TARBALL,old={'image':None},sbom='upgrade-comparison-sbom-*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('build=true',out)
        self.assertEqual([b['args'][b['args'].index('-t')+1] for b in self.builds],['upgrade-comparison/t:old'])
        self.assertEqual(json.loads((self.tmp/'rebuilt-sboms/t.old.syft.json').read_text()),{'source':'docker:upgrade-comparison/t:old'})
        self.assertEqual(json.loads((self.tmp/'runtime-reports/t.json').read_text())['not_run'],'no_image_artifact')
        self.assertEqual((self.tmp/'rm.log').read_text().splitlines(),['upgrade-comparison/t:old'])
    @needs_shell
    def test_a_prebuilt_target_and_a_rebuilt_pr_image_are_compared_per_side(self):
        # The target's image is pulled from GHCR (its SBOM made in compare), the PR's is rebuilt in the runtime job.
        kw=dict(new={'image':None},images=(self.OLD,))
        r,plan,out=self.run_step('plan',**kw)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((plan['ref'],plan['rebuilt_old'],plan['rebuilt_new']),(self.OLD,False,True))
        for output in ('scan=true','wait=false','rebuilt=true'):
            with self.subTest(output):self.assertIn(output,out)
        r,_,_=self.run_step(self.RUNTIME[:3]+("SBOMs of the comparison targets' images",self.RUNTIME[3]),files=self.FILES,**kw)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual([b['args'][b['args'].index('-t')+1] for b in self.builds],['upgrade-comparison/t:new'])
        r=self.compare(VULNERABLE='upgrade-comparison/t:new')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn(f't: scanned {self.OLD} (v1.0.0) and the PR image rebuilt with the same DB',r.stdout)
    @needs_shell
    def test_a_rebuilt_target_and_a_published_pr_image_are_compared_per_side(self):
        # The target was built on the device, the PR names a published image (scan_published_image): old from the runtime
        # job, new pulled and given its SBOM in compare.
        new=PublishedImageScan.NEW
        kw=dict(old={'image':None},extra=PublishedImageScan.APPROVED,images=(new,))
        r,plan,out=self.run_step('plan',**kw)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((plan['ref'],plan['new_ref'],plan['rebuilt_old'],plan['rebuilt_new']),('',new,True,False))
        for output in ('scan=true','wait=false','rebuilt=true'):
            with self.subTest(output):self.assertIn(output,out)
        r,_,_=self.run_step(self.RUNTIME[:3]+("SBOMs of the comparison targets' images",self.RUNTIME[3]),
            files=self.FILES,tarball=self.TARBALL,**kw)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(json.loads((self.tmp/'sboms/t.syft.json').read_text()),{'source':'docker:'+new})
        self.assertEqual(json.loads((self.tmp/'rebuilt-sboms/t.old.syft.json').read_text()),{'source':'docker:upgrade-comparison/t:old'})
        r=self.compare(VULNERABLE=new)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('::error title=New fixable vulnerability::CVE-2026-0001 openssl',r.stdout)
        self.assertIn(f't: scanned v1.0.0 rebuilt and {new} with the same DB',r.stdout)
        self.assertNotIn('holds no t.syft.json',r.stdout)

class BuildArgs(unittest.TestCase):
    """upgrade_check.build_args (#144): how Supervisor builds an add-on built on the device (supervisor/addons/build.py)."""
    def addon(self,files):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d)
        for name,text in {'Dockerfile':'FROM x',**files}.items():
            if text is not None:(d/name).write_text(text)
        return d
    def test_without_a_build_file_the_base_is_home_assistants(self):
        d=self.addon({})
        self.assertEqual(u.build_args(d,'1.2.3'),{'dockerfile':(d/'Dockerfile').as_posix(),
            'args':{'BUILD_FROM':'ghcr.io/home-assistant/amd64-base:latest','BUILD_VERSION':'1.2.3','BUILD_ARCH':'amd64'}})
    def test_build_from_per_arch_or_one_for_all_and_args(self):
        for name,text in (('build.yaml','build_from:\n  amd64: a/b:1\n  aarch64: c/d:1\nargs:\n  X: 1\n'),('build.yml','build_from: a/b:1\nargs:\n  X: "1"\n'),
                ('build.json','{"build_from": {"amd64": "a/b:1"}, "args": {"X": 1}}')):
            with self.subTest(name):self.assertEqual(u.build_args(self.addon({name:text}),'2')['args'],{'BUILD_FROM':'a/b:1','BUILD_VERSION':'2','BUILD_ARCH':'amd64','X':'1'})
    def test_arch_dockerfile_wins(self):
        d=self.addon({'Dockerfile.amd64':'FROM y'});self.assertEqual(u.build_args(d,'1')['dockerfile'],(d/'Dockerfile.amd64').as_posix())
    def test_what_supervisor_could_not_build_is_an_error(self):
        for name,files,error in (('no amd64 base',{'build.yaml':'build_from:\n  aarch64: a/b:1\n'},'no base image for amd64'),
                ('no Dockerfile',{'Dockerfile':None},'no Dockerfile'),('args not a mapping',{'build.yaml':'args: [1]\n'},'args is not a mapping'),
                ('multi-line arg',{'build.yaml':'args:\n  X: "a\\nb"\n'},'must be one line'),
                ('empty arg name',{'build.yaml':'args:\n  "": x\n'},"build argument name '' must be non-empty, without = or whitespace"),
                ('= in arg name',{'build.yaml':'args:\n  "A=B": x\n'},"build argument name 'A=B' must be non-empty"),
                ('space in arg name',{'build.yaml':'args:\n  "A B": x\n'},"build argument name 'A B' must be non-empty"),
                ('tab in arg name',{'build.yaml':'args:\n  "A\\tB": x\n'},'without = or whitespace'),('not a mapping',{'build.yaml':'- 1\n'},'is not a mapping')):
            with self.subTest(name),self.assertRaisesRegex(ValueError,error):u.build_args(self.addon(files),'1')
    def test_command_prints_json_and_names_the_add_on_on_error(self):
        d=self.addon({})
        with contextlib.redirect_stdout(io.StringIO()) as out:self.assertEqual(u.main(['build-args','--addon-dir',str(d),'--version','1','--name','t']),0)
        self.assertEqual(json.loads(out.getvalue())['args']['BUILD_VERSION'],'1')
        with contextlib.redirect_stdout(io.StringIO()) as out:self.assertEqual(u.main(['build-args','--addon-dir',str(d/'missing'),'--version','1','--name','t']),2)
        self.assertIn('::error title=Upgrade comparison failed::t: ',out.getvalue())

class RuntimeFailureRecord(StepHarness):
    """'Record why the runtime job failed': compare gets each reason once, and no reason-less entry next to a real one."""
    def record(self,*,fail_log='',results=()):
        """fail_log: what earlier steps wrote to FAIL_LOG. results: the runtime-reports/*.json already written.
        Returns the reports compare would read, by file name."""
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'runtime-reports').mkdir()
        for r in results:(tmp/'runtime-reports'/f"{r['name']}.json").write_text(json.dumps(r))
        (tmp/'failures.txt').write_text(fail_log);(tmp/'step.sh').write_text(self.step('Record why the runtime job failed')['run'])
        r=subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=dict(os.environ,FAIL_LOG=str(tmp/'failures.txt')),capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        return {p.name:json.loads(p.read_text()) for p in (tmp/'runtime-reports').iterdir()}
    @needs_shell
    def test_failed_upgrade_test_is_the_only_reason(self):
        failed={'name':'t','passed':False,'reason':'the new version (1.1.0) did not start: the container exited with code 3','phases':[]}
        self.assertEqual(self.record(results=(failed,)),{'t.json':failed})
    @needs_shell
    def test_step_that_failed_before_the_test_hands_compare_its_reasons(self):
        reports=self.record(fail_log='t: cannot pull the comparison target\'s image\n',results=({'name':'t','passed':None,'note':'n'},))
        self.assertEqual(reports['runtime-job.json'],{'name':'runtime job','passed':False,'reason':"t: cannot pull the comparison target's image"})
    @needs_shell
    def test_failure_with_no_reason_anywhere_still_fails_compare(self):
        self.assertEqual(self.record()['runtime-job.json']['reason'],"a step failed without a reason; the runtime job's log has it")
        passed={'name':'t','passed':True,'reason':'','phases':[]}
        self.assertEqual(self.record(results=(passed,))['runtime-job.json']['passed'],False)

class UpgradeTestResult(StepHarness):
    """compare's 'Upgrade test result' (#138): each add-on's verdict, whether its data was checked, and its report with every check."""
    def result(self,results,reports=None,runtime='success'):
        """results: the runtime-reports/*.json; reports: name -> the .md upgrade_runtime.py wrote. (exit code, stdout, step summary)."""
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'runtime-reports').mkdir();(tmp/'bin').mkdir();(tmp/'tooling/.addon-sync').mkdir(parents=True)
        shutil.copy(self.STORE/'.addon-sync/log.sh',tmp/'tooling/.addon-sync/log.sh')
        # #141: each add-on with a result is in this job's plan and the registry, with no data-check due date.
        for f in (self.STORE/'.addon-sync').glob('*.py'):shutil.copy(f,tmp/'tooling/.addon-sync'/f.name)
        names=[r['name'] for r in results if r['name']!='runtime job']
        (tmp/'tooling/.addon-sync/registry.json').write_text(json.dumps({'providers':{'o/r':{'ref_policy':'release','components':[
            {'id':n,'source_path':n,'config_file':'config.yaml'} for n in names]}}}))
        (tmp/'plan.jsonl').write_text(''.join(json.dumps({'id':n,'notes':f'{n}/upgrade-notes.yaml'})+'\n' for n in names))
        # No artifact to download: the results are already in runtime-reports/.
        (tmp/'bin/gh').write_text('#!/bin/sh\nexit 0\n',newline='\n');(tmp/'bin/gh').chmod(0o755)
        for r in results:(tmp/'runtime-reports'/f"{r['name']}.json").write_text(json.dumps(r))
        for name,text in (reports or {}).items():(tmp/'runtime-reports'/f'{name}.md').write_text(text,encoding='utf-8')
        (tmp/'step.sh').write_text(self.step('Upgrade test result')['run'],newline='\n');(tmp/'summary.md').write_text('')
        env=dict(os.environ,PATH=f"{tmp/'bin'}{os.pathsep}{os.environ['PATH']}",GITHUB_STEP_SUMMARY=str(tmp/'summary.md'),RUNNER_TEMP=str(tmp),
            REPO='o/r',RUN_ID='1',RUN_ATTEMPT='1',RUNTIME_RESULT=runtime)
        r=subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=env,capture_output=True,text=True)
        return r.returncode,r.stdout,(tmp/'summary.md').read_text(encoding='utf-8')
    @needs_shell
    def test_add_on_with_verify_is_reported_as_data_checked_with_its_checks(self):
        code,out,summary=self.result([{'name':'t','passed':True,'reason':'','hooks':['seed','verify'],'data_checked':True,'phases':[]}],
            {'t':'#### Upgrade test: t\n\n| the new version 1.1.0 | verify | item kept | pass | hello |\n'})
        self.assertEqual(code,0,out);self.assertIn('- t: passed, data checked by seed and verify (已檢查資料)',summary)
        self.assertIn('| verify | item kept | pass | hello |',summary)
    @needs_shell
    def test_add_on_without_verify_is_reported_as_startup_only(self):
        # Also a result written before #138 (no hooks field).
        for r in ({'name':'t','passed':True,'reason':'','hooks':['seed'],'phases':[]},{'name':'t','passed':True,'reason':'','phases':[]}):
            with self.subTest(r):
                code,out,summary=self.result([r])
                self.assertEqual(code,0,out);self.assertIn('- t: passed, startup only: data was not checked (只檢查啟動，沒有檢查資料)',summary)
    @needs_shell
    def test_data_counts_as_checked_only_when_verify_ran(self):
        # A failing seed (or comparison target) stops the test before verify: an add-on that has verify was not checked.
        failed={'name':'t','passed':False,'reason':'seed failed on the comparison target (1.0.0): exited with code 2',
            'hooks':['seed','verify'],'data_checked':False,'phases':[]}
        code,out,summary=self.result([failed],runtime='failure')
        self.assertEqual(code,1);self.assertIn('- t: **failed**, data was not checked: the test failed before verify ran (沒有檢查資料)',summary)
        self.assertNotIn('已檢查資料',summary)
        code,out,summary=self.result([{'name':'t','passed':True,'reason':'','hooks':['verify'],'data_checked':True,'phases':[]}])
        self.assertEqual(code,0,out);self.assertIn('- t: passed, data checked by verify, no seed (已檢查資料)',summary)
    @needs_shell
    def test_failed_verify_fails_compare_with_the_reason(self):
        failed={'name':'t','passed':False,'reason':'verify failed on the new version (1.1.0): exited with code 1; failing checks: item kept',
            'hooks':['seed','verify'],'data_checked':True,'phases':[]}
        code,out,summary=self.result([failed],{'t':'#### Upgrade test: t\n\n| the new version 1.1.0 | verify | item kept | **fail** | HTTP 404 |\n'},runtime='failure')
        self.assertEqual(code,1);self.assertIn('t: upgrade test failed: verify failed on the new version (1.1.0)',out)
        self.assertIn('- t: **failed**, data checked by seed and verify',summary);self.assertIn('| item kept | **fail** | HTTP 404 |',summary)

class DataCheckDueStep(StepHarness):
    """compare's 'Upgrade test result' applies the data-check deadline (#141) to each add-on whose upgrade test ran."""
    TODAY='2026-11-10'  # DATA_CHECK_TODAY: fixed, so no test races UTC midnight
    def result(self,result,due='2026-11-17',verify=False,in_plan=True,crash=False,smoke=False):
        """result: t's runtime-reports/t.json. due: t's data_check_due in the registry (None: none). verify: the PR's
        upgrade-check/ has verify. crash: upgrade_check.py dies with exit 1 and no output. (exit code, stdout, step summary)."""
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'runtime-reports').mkdir();(tmp/'bin').mkdir();(tmp/'tooling/.addon-sync').mkdir(parents=True);(tmp/'source/addon/upgrade-check').mkdir(parents=True)
        for f in (self.STORE/'.addon-sync').iterdir():
            if f.suffix in ('.py','.sh'):shutil.copy(f,tmp/'tooling/.addon-sync'/f.name)
        comp={'id':'t','source_path':'addon','config_file':'config.yaml'}
        if due is not None:comp['upgrade_comparison']={'data_check_due':due}
        (tmp/'tooling/.addon-sync/registry.json').write_text(json.dumps({'providers':{'o/r':{'ref_policy':'release','components':[comp]}}}))
        if in_plan:(tmp/'plan.jsonl').write_text(json.dumps({'id':'t','notes':'addon/upgrade-notes.yaml'})+'\n')
        if verify:(tmp/'source/addon/upgrade-check/verify').write_text('#!/bin/sh\nexit 0\n',newline='\n')
        if smoke:(tmp/'source/addon/upgrade-check/smoke').write_text('#!/bin/sh\nexit 0\n',newline='\n')
        if crash:(tmp/'tooling/.addon-sync/upgrade_check.py').write_text('import sys\nsys.exit(1)\n')
        (tmp/'bin/gh').write_text('#!/bin/sh\nexit 0\n',newline='\n');(tmp/'bin/gh').chmod(0o755)
        (tmp/'runtime-reports/t.json').write_text(json.dumps(result))
        (tmp/'step.sh').write_text(self.step('Upgrade test result')['run'],newline='\n');(tmp/'summary.md').write_text('')
        env=dict(os.environ,PATH=f"{tmp/'bin'}{os.pathsep}{os.environ['PATH']}",GITHUB_STEP_SUMMARY=str(tmp/'summary.md'),RUNNER_TEMP=str(tmp),
            REPO='o/r',RUN_ID='1',RUN_ATTEMPT='1',RUNTIME_RESULT='success' if result.get('passed') is not False else 'failure',DATA_CHECK_TODAY=self.TODAY)
        r=subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=env,capture_output=True,text=True)
        return r.returncode,r.stdout,(tmp/'summary.md').read_text(encoding='utf-8')
    PASSED={'name':'t','passed':True,'reason':'','hooks':[],'data_checked':False,'phases':[]}
    def day(self,offset):return (datetime.date.fromisoformat(self.TODAY)+datetime.timedelta(days=offset)).isoformat()
    @needs_shell
    def test_before_the_due_date_startup_only_passes_with_the_days_left(self):
        due=self.day(3);code,out,summary=self.result(self.PASSED,due)
        self.assertEqual(code,0,out);self.assertIn(f'- t: 資料檢查期限 {due}，剩 3 天',summary)
    @needs_shell
    def test_on_the_due_date_passes_with_0_days_left(self):
        code,out,summary=self.result(self.PASSED,self.TODAY);self.assertEqual(code,0,out);self.assertIn(f'- t: 資料檢查期限 {self.TODAY}，剩 0 天',summary)
    @needs_shell
    def test_after_the_due_date_startup_only_fails_compare(self):
        due=self.day(-1);code,out,summary=self.result(self.PASSED,due)
        self.assertEqual(code,1);self.assertIn(f'::error title=Upgrade comparison failed::t: 資料檢查期限 {due} 已過，要補資料檢查',out)
        self.assertIn(f'- t: **資料檢查期限 {due} 已過',summary)
    @needs_shell
    def test_with_verify_the_due_date_is_not_looked_at(self):
        result=dict(self.PASSED,hooks=['seed','verify'],data_checked=True)
        code,out,summary=self.result(result,self.day(-30),verify=True)
        self.assertEqual(code,0,out);self.assertNotIn('資料檢查期限',summary+out)
    @needs_shell
    def test_smoke_is_not_a_data_check(self):
        # #139: smoke (category 3) appears in hooks and phases[].hooks with reported/report_error, and the new phase may
        # carry smoke_not_run; none of it is read here. Only upgrade-check/verify in the PR counts as the data check.
        smoke={'hook':'smoke','phase':'new','passed':True,'reported':True,'report_error':'','checks':[]}
        result=dict(self.PASSED,hooks=['seed','smoke'],phases=[{'phase':'new','started':True,'hooks':[smoke]}])
        code,out,summary=self.result(result,self.day(-1),smoke=True)
        self.assertEqual(code,1);self.assertIn(f'- t: **資料檢查期限 {self.day(-1)} 已過',summary)
        not_run=dict(self.PASSED,hooks=['seed','verify','smoke'],data_checked=True,phases=[{'phase':'new','started':True,'hooks':[],'smoke_not_run':'verify failed'}])
        code,out,summary=self.result(not_run,self.day(-1),verify=True,smoke=True)
        self.assertEqual(code,0,out);self.assertNotIn('資料檢查期限',summary+out)
    @needs_shell
    def test_target_that_failed_before_verify_ran_is_not_also_failed_for_the_deadline(self):
        # target_failed (#140) writes hooks [] whatever upgrade-check/ has: verify is read from the PR's upgrade-check/.
        failed={'name':'t','passed':False,'reason':"cannot pull the comparison target's image",'hooks':[],'data_checked':False,'phases':[]}
        code,out,_=self.result(failed,self.day(-1),verify=True)
        self.assertEqual(code,1);self.assertNotIn('資料檢查期限',out)
        code,out,_=self.result(failed,self.day(-1))
        self.assertEqual(code,1);self.assertIn('資料檢查期限',out)
    # The runtime job's not-run records ("Skip the upgrade tests the registry approves", "Plan the upgrade tests").
    NO_TARGET={'name':'t','passed':None,'not_run':'no_target','note':'no comparison target'}
    APPROVED_SKIP={'name':'t','passed':None,'skipped':True,'not_run':'approved_skip','note':'categories 2 and 3 skipped as approved in the Store registry: #158: x'}
    NO_IMAGE_ARTIFACT={'name':'t','passed':None,'not_run':'no_image_artifact','note':'the caller passes no image_artifact; the upgrade test is being rolled out in #143'}
    @needs_shell
    def test_no_comparison_target_and_approved_skip_are_not_judged(self):
        # Nothing to upgrade from (a first release), or the registry's owner decision (#140): no deadline either.
        for result in (self.NO_TARGET,self.APPROVED_SKIP):
            with self.subTest(result['not_run']):
                code,out,summary=self.result(result,self.day(-1))
                self.assertEqual(code,0,out);self.assertNotIn('資料檢查期限',summary+out)
    @needs_shell
    def test_caller_without_image_artifact_is_judged_after_the_due_date(self):
        # image_artifact is the caller's input: dropping it must not waive the deadline (only the registry decides).
        due=self.day(-1);code,out,summary=self.result(self.NO_IMAGE_ARTIFACT,due)
        self.assertEqual(code,1);self.assertIn(f'::error title=Upgrade comparison failed::t: 資料檢查期限 {due} 已過，要補資料檢查',out)
        self.assertIn('升級測試沒跑 (the upgrade test did not run: the caller passes no image_artifact',out)
        self.assertIn('add verify, and pass image_artifact (the addon-image action, #143) so the test runs',out)
        self.assertIn(f'- t: **資料檢查期限 {due} 已過',summary);self.assertIn('- t: not run (the caller passes no image_artifact',summary)
    @needs_shell
    def test_caller_without_image_artifact_passes_before_the_due_date_with_the_days_left(self):
        due=self.day(3);code,out,summary=self.result(self.NO_IMAGE_ARTIFACT,due)
        self.assertEqual(code,0,out);self.assertIn(f'- t: 資料檢查期限 {due}，剩 3 天',summary)
    @needs_shell
    def test_caller_without_image_artifact_with_verify_passes(self):
        code,out,summary=self.result(self.NO_IMAGE_ARTIFACT,self.day(-30),verify=True)
        self.assertEqual(code,0,out);self.assertNotIn('資料檢查期限',summary+out)
    @needs_shell
    def test_unknown_not_run_reason_is_judged(self):
        # Fail closed: a not-run record without a known code (or any not_run code) is judged like a test that ran.
        for result in ({'name':'t','passed':None,'note':'some new reason'},dict(self.NO_TARGET,not_run='something_else'),{'name':'t'}):
            with self.subTest(result):
                code,out,summary=self.result(result,self.day(-1))
                self.assertEqual(code,1);self.assertIn(f'- t: **資料檢查期限 {self.day(-1)} 已過',summary)
                self.assertIn('升級測試沒跑 (the upgrade test did not run:',out);self.assertNotIn('#143) so the test runs',out)
    @needs_shell
    def test_without_a_due_date_nothing_is_added(self):
        code,out,summary=self.result(self.PASSED,None);self.assertEqual(code,0,out);self.assertNotIn('資料檢查期限',summary)
    @needs_shell
    def test_malformed_due_date_fails_with_the_reason(self):
        code,out,summary=self.result(self.PASSED,'2026-13-01')
        self.assertEqual(code,1);self.assertIn("upgrade_comparison.data_check_due '2026-13-01'; it must be a date, YYYY-MM-DD (UTC)",out)
        self.assertIn('- t: **data-check deadline could not be judged (upgrade_check.py data-check-due exited 2)',summary)
    @needs_shell
    def test_crash_is_never_read_as_an_overdue_check(self):
        code,out,summary=self.result(self.PASSED,crash=True)
        self.assertEqual(code,1);self.assertIn('::error title=Upgrade comparison failed::t: the data-check deadline could not be judged: upgrade_check.py data-check-due exited 1',out)
        self.assertNotIn('已過',out+summary);self.assertIn('- t: **data-check deadline could not be judged',summary)
    @needs_shell
    def test_add_on_that_ran_but_is_not_in_the_plan_fails(self):
        code,out,summary=self.result(self.PASSED,in_plan=False)
        self.assertEqual(code,1);self.assertIn("t: the upgrade test has a result for this add-on, but this job's plan does not list it",out)
        self.assertIn("- t: **data-check deadline not judged: not in this job's plan**",summary)
    @needs_shell
    def test_runtime_job_record_is_not_an_add_on(self):
        code,out,summary=self.result({'name':'runtime job','passed':False,'reason':'a step failed'},in_plan=False)
        self.assertEqual(code,1);self.assertIn('runtime job: upgrade test failed: a step failed',out)
        self.assertNotIn('data-check',out+summary)

class SkipVulnerabilityScan(StepHarness):
    """skip_vulnerability_scan: a caller whose category 4 cannot run opts out with a reason; category 1 still runs and
    the report says why. No provider is approved now (mcp_addons' #123 became scan_published_image, #148); the
    mechanism stays.
    Only a provider the Store registry approves may skip (upgrade_comparison.skip_vulnerability_scan, with the reason)."""
    REASON='the shipped image is third-party; category 4 for it is out of scope'
    APPROVED={'upgrade_comparison':{'skip_vulnerability_scan':'#122: third-party image; category 4 for it is out of scope'}}
    def test_optional_string_input_that_defaults_to_scanning(self):
        inp=self.wf['on']['workflow_call']['inputs']['skip_vulnerability_scan']
        self.assertEqual((inp['type'],inp['default']),('string',''))
        for ident in ('detect','plan'):
            with self.subTest(ident):self.assertEqual(self.step(ident)['env']['SKIP_VULNERABILITY_SCAN'],'${{ inputs.skip_vulnerability_scan }}')
    def test_registry_approves_the_skip_for_no_provider(self):
        # knxd (#147) and mcp_addons (#148, formerly skipped under #123) scan their published images instead.
        self.assertEqual(registry_approvals('skip_vulnerability_scan'),{})
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

class PublishedImageScan(StepHarness):
    """scan_published_image: the shipped image is the published one its config.yaml names, not one the caller's PR builds
    (knxd's third-party image, #147; mcp_addons' images built only on woow-disposable-builder, #148), so category 4 scans
    that image at the comparison target's version and at the PR's version (the version is the tag), not an SBOM of the
    PR's build."""
    APPROVED={'upgrade_comparison':{'scan_published_image':'#147: knxd ships the third-party image config.yaml names'}}
    SBOMS=('plan',"SBOMs of the comparison targets' images")
    OLD,NEW='ghcr.io/da-anda/addon-amd64:1.0.0','ghcr.io/da-anda/addon-amd64:1.1.0'
    def test_registry_approves_it_for_knxd_mcp_addons_and_the_mirrors(self):
        approved=registry_approvals('scan_published_image')
        # Mirror 來源 (branch_rules.exempt "mirror: ...", pipeline #91) ship the GHCR copy their config.yaml names.
        providers=json.loads((StepHarness.STORE/'.addon-sync/registry.json').read_text(encoding='utf-8'))['providers']
        mirrors={repo for repo in approved if providers[repo].get('branch_rules',{}).get('exempt','').startswith('mirror:')}
        self.assertEqual(sorted(set(approved)-mirrors),['WOOWTECH/Woow_ha_knxd_add_on','WOOWTECH/Woow_ha_mcp_addons'])
        self.assertIn('WOOWTECH/Woow_ha_music_assistant_add_on',mirrors)
        self.assertIn('WOOWTECH/Woow_ha_jellyfin_add_on',mirrors)
        self.assertIn('WOOWTECH/Woow_ha_frigate_add_on',mirrors)
        self.assertIn('WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on',mirrors)
        self.assertIn('WOOWTECH/Woow_ha_matter_hub_add_on',mirrors)
        self.assertIn('#147',approved['WOOWTECH/Woow_ha_knxd_add_on']);self.assertIn('#148',approved['WOOWTECH/Woow_ha_mcp_addons'])
        for repo in mirrors:self.assertIn('#91',approved[repo],repo)
    @needs_shell
    def test_both_sides_are_the_published_image_at_their_version(self):
        r,plan,out=self.run_step('plan',extra=self.APPROVED)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual([plan['ref'],plan['new_ref'],plan['note']],['ghcr.io/da-anda/addon-amd64:1.0.0','ghcr.io/da-anda/addon-amd64:1.1.0',''])
        # No SBOM artifact of the caller's build is needed or awaited.
        self.assertIn('scan=true',out);self.assertIn('wait=false',out)
    @needs_shell
    def test_the_new_image_is_the_one_the_pr_names(self):
        # A changed image is category 1's image-changed; category 4 still scans what users would install.
        r,plan,_=self.run_step('plan',extra=self.APPROVED,new={'image':'ghcr.io/da-anda/other-{arch}'})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['new_ref'],'ghcr.io/da-anda/other-amd64:1.1.0')
    @needs_shell
    def test_a_prebuilt_image_without_the_approval_still_awaits_its_sbom(self):
        r,plan,out=self.run_step('plan',sbom='upgrade-comparison-sbom-*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['new_ref'],'');self.assertIn('wait=true',out)
    @needs_shell
    def test_both_published_images_get_an_sbom_for_the_compare_step(self):
        r,_,_=self.run_step(self.SBOMS,extra=self.APPROVED,images=(self.OLD,self.NEW))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        # Where the compare step reads them: the old one in RUNNER_TEMP, the new one where a downloaded artifact would be.
        self.assertEqual(json.loads((self.tmp/'t.old.syft.json').read_text()),{'source':'docker:'+self.OLD})
        self.assertEqual(json.loads((self.tmp/'sboms/t.syft.json').read_text()),{'source':'docker:'+self.NEW})
    @needs_shell
    def test_an_unpublished_version_fails_saying_its_image_is_not_published(self):
        r,_,_=self.run_step(self.SBOMS,extra=self.APPROVED,images=(self.OLD,))
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        # #148: not only an upstream publishes these images (mcp_addons' are the WOOW builder's), so the message names neither alone.
        self.assertIn(f'::error title=Upgrade comparison failed::t: cannot pull {self.NEW}, the image users would install with this PR: '
            'tag 1.1.0 of ghcr.io/da-anda/addon-amd64 is not published yet (or the registry is unreachable); publish it first '
            "(its upstream's release for a third-party image, the repository's own image publication otherwise)",r.stdout)
        self.assertNotIn('the upstream has not published',r.stdout)
        self.assertFalse((self.tmp/'sboms/t.syft.json').exists())
    def multi(self,images):
        """mcp_addons' shape (#148): three add-ons with their own WOOW image; the PR changes the first two's versions."""
        comps=[{'id':i,'source_path':'addons/'+i,'config_file':'config.yaml'} for i in ('n8n','hermes','odoo')]
        image={i:f'ghcr.io/woowtech/{{arch}}-mcp-{i}' for i in ('n8n','hermes','odoo')}
        history=[('b',{})]+[(f'{i}-v1.0.0',{f'addons/{i}/config.yaml':{'image':image[i]}}) for i in image]
        return self.run_step(self.SBOMS,extra={'components':comps,**self.APPROVED},releases=tuple(f'{i}-v1.0.0' for i in image),
            history=history,changed=2,news={i:{'image':image[i]} for i in ('n8n','hermes')},images=images)
    @needs_shell
    def test_each_changed_add_on_of_a_multi_add_on_repository_scans_its_own_published_images(self):
        refs={i:(f'ghcr.io/woowtech/amd64-mcp-{i}:1.0.0',f'ghcr.io/woowtech/amd64-mcp-{i}:1.1.0') for i in ('n8n','hermes')}
        r,_,out=self.multi([x for pair in refs.values() for x in pair])
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        # The unchanged add-on (odoo) is not compared; each changed one gets its own old and new image, nothing is awaited.
        self.assertEqual({p['id']:(p['ref'],p['new_ref']) for p in self.plans},refs)
        self.assertIn('wait=false',out)
        for i,(old,new) in refs.items():
            with self.subTest(i):
                self.assertEqual(json.loads((self.tmp/f'{i}.old.syft.json').read_text()),{'source':'docker:'+old})
                self.assertEqual(json.loads((self.tmp/f'sboms/{i}.syft.json').read_text()),{'source':'docker:'+new})
        self.assertFalse((self.tmp/'sboms/odoo.syft.json').exists())
    @needs_shell
    def test_an_unpublished_version_of_one_add_on_fails_naming_it(self):
        # hermes' new version has no image on GHCR yet (for mcp_addons: the builder has not published it).
        r,_,_=self.multi(['ghcr.io/woowtech/amd64-mcp-n8n:1.0.0','ghcr.io/woowtech/amd64-mcp-n8n:1.1.0','ghcr.io/woowtech/amd64-mcp-hermes:1.0.0'])
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('::error title=Upgrade comparison failed::hermes: cannot pull ghcr.io/woowtech/amd64-mcp-hermes:1.1.0, the image users would '
            'install with this PR: tag 1.1.0 of ghcr.io/woowtech/amd64-mcp-hermes is not published yet',r.stdout)
    def test_a_published_new_image_is_not_awaited_or_downloaded(self):
        # The harness runs a step whatever its `if:`; in the workflow these two must not run for a pulled new image.
        for name in ("Wait for the new images' SBOMs","Download the new images' SBOMs"):
            with self.subTest(name):self.assertIn("steps.plan.outputs.wait == 'true'",self.step(name)['if'])
    @needs_shell
    def test_a_new_fixable_vulnerability_in_the_published_image_blocks(self):
        steps=self.SBOMS+('Compare with the comparison target',)
        r,_,_=self.run_step(steps,extra=self.APPROVED,images=(self.OLD,self.NEW),vulnerable=self.NEW)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('::error title=New fixable vulnerability::CVE-2026-0001 openssl (High, fixed in 3.0.9)',r.stdout)
        self.assertIn(f't: scanned {self.OLD} (v1.0.0) and {self.NEW} with the same DB',r.stdout)
        r,_,_=self.run_step(steps,extra=self.APPROVED,images=(self.OLD,self.NEW),vulnerable=self.OLD)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('No new fixable vulnerabilities.',r.stdout)
    @needs_shell
    def test_a_new_image_with_a_newline_is_rejected(self):
        r,plan,_=self.run_step('plan',extra=self.APPROVED,new={'image':'ghcr.io/x/a-{arch}\n::warning title=Injected::boom'})
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn('control character',r.stdout);self.assertEqual(plan,{})

class ShaMode(StepHarness):
    """sha mode (#167, pipeline #91): a source with no PR (a Mirror 來源's mirror-sync) is compared at one commit before its
    Releases are cut. Given the registry, the Releases and the configs at the commit, the compare job's steps run as they
    do in sha mode (each one also after an earlier one failed); the runtime job's results (categories 2 and 3) are given
    as its runtime-reports. A Mirror 來源 has scan_published_image: both sides are its GHCR copy at their version."""
    SHA='0123456789abcdef0123456789abcdef01234567'
    APPROVED={'upgrade_comparison':{'scan_published_image':'#91: mirror; the image is the GHCR copy config.yaml names'}}
    STEPS=('detect','plan',"SBOMs of the comparison targets' images",'Compare with the comparison target','Upgrade test result','passed')
    OLD,NEW='ghcr.io/da-anda/addon-amd64:1.0.0','ghcr.io/da-anda/addon-amd64:1.1.0'
    # The runtime job's result of an add-on with no hooks: it started; there is no data to check (#91 writes no hooks).
    STARTED={'passed':True,'reason':'','hooks':[],'data_checked':False,'phases':[]}
    NO_WORKERS={'schema':{k:v for k,v in BASE['schema'].items() if k!='workers'},'options':{k:v for k,v in BASE['options'].items() if k!='workers'}}
    DECLARED='"1.1.0":\n  breaking:\n    - change: option-removed\n      key: workers\n      migration: Set workers again in the new options.\n'
    def sha(self,steps=STEPS,started=('t',),**kw):
        """(exit code of the last step, the output passed as a list or None when unset, every step's log, step summary).
        started: the add-ons whose upgrade test passed (results), unless results is given."""
        kw.setdefault('extra',self.APPROVED);kw.setdefault('images',(self.OLD,self.NEW))
        kw.setdefault('results',{i:dict(self.STARTED,name=i) for i in started})
        _,_,out=self.run_step(steps,sha=self.SHA,keep_going=True,**kw)
        passed=[l.split('=',1)[1] for l in out.splitlines() if l.startswith('passed=')]
        summary=(self.tmp/'summary').read_text(encoding='utf-8') if (self.tmp/'summary').exists() else ''
        return self.runs[-1].returncode,json.loads(passed[-1]) if passed else None,''.join(r.stdout+r.stderr for r in self.runs),summary
    def test_workflow_passes_sha_to_the_cli_and_outputs_passed(self):
        inp=self.wf['on']['workflow_call']['inputs']['sha'];self.assertEqual((inp['type'],inp['default']),('string',''))
        detect=self.step('detect')
        self.assertEqual(detect['env']['SHA'],'${{ inputs.sha }}');self.assertIn('release-change --registry',detect['run']);self.assertIn('--sha "${SHA}"',detect['run'])
        self.assertEqual(self.step('Check out the pull request')['with']['ref'],'${{ inputs.sha }}')
        passed=self.step('passed');self.assertEqual(passed['if'],"always() && inputs.sha != ''");self.assertIn('upgrade_check.py sha-verdicts',passed['run'])
        self.assertEqual(self.wf['jobs']['compare']['outputs'],{'passed':'${{ steps.passed.outputs.passed }}'})
        # Without sha, "" as before #167; with sha never "", even when the compare job ended before its last step.
        self.assertEqual(self.wf['on']['workflow_call']['outputs']['passed']['value'],"${{ jobs.compare.outputs.passed || (inputs.sha != '' && '[]' || '') }}")
        # The required check keeps its name, and nothing on a PR depends on sha.
        self.assertEqual((sorted(self.wf['jobs']),self.wf['jobs']['compare']['name']),(['compare','runtime'],'compare'))
    @needs_shell
    def test_a_compatible_version_change_passes(self):
        code,passed,log,summary=self.sha()
        self.assertEqual((code,passed),(0,['t']),log)
        # Category 4 on the GHCR copies at both versions; categories 2 and 3 start-up only, and the report says so.
        self.assertIn(f't: scanned {self.OLD} (v1.0.0) and {self.NEW} with the same DB',log)
        self.assertIn('- t: passed, startup only: data was not checked (只檢查啟動，沒有檢查資料)',summary)
        self.assertIn('- t: passed\n',summary)
    @needs_shell
    def test_an_add_on_in_the_store_catalog_without_a_stable_release_fails(self):
        # #135: sha mode has no PR base, so the Store catalog tells an add-on users run from a new one; the Release job
        # must not cut its next version uncompared. The fix for a Mirror 來源 is a seed Release by hand.
        self.run_step(('detect','plan'),sha=self.SHA,extra=self.APPROVED,releases=(),keep_going=True,catalog={'t':{'repository':'WOOWTECH/t','version':'1.0.0'}})
        log=''.join(r.stdout+r.stderr for r in self.runs)
        self.assertEqual([r.returncode for r in self.runs],[0,1],log);self.assertEqual(json.loads((self.tmp/'changed.jsonl').read_text())['on_base'],False)
        self.assertIn('::error title=Upgrade comparison failed::t is not a new add-on (users run version 1.0.0 from the Store catalog) but has no stable Release, '
            'so version 1.1.0 has nothing to be compared with; publish a seed Release first (v<version>',self.runs[1].stdout)
        self.assertIn('for a Mirror source by hand with addon_sync.py release --apply',self.runs[1].stdout);self.assertEqual(self.plans,[])
    @needs_shell
    def test_a_new_add_on_without_a_stable_release_has_no_comparison_target(self):
        # Not in the Store catalog (an add-on of another repository by that id is not this one): its first Release is not compared.
        self.run_step(('detect','plan'),sha=self.SHA,extra=self.APPROVED,releases=(),catalog={'t':{'repository':'WOOWTECH/other','version':'1.0.0'}})
        self.assertEqual([r.returncode for r in self.runs],[0,0],''.join(r.stdout+r.stderr for r in self.runs))
        self.assertEqual(json.loads((self.tmp/'changed.jsonl').read_text())['on_base'],False)
        self.assertEqual(self.plans[0]['note'],'no comparison target');self.assertNotIn('seed Release',self.runs[1].stdout)
    @needs_shell
    def test_an_undeclared_breaking_change_fails(self):
        code,passed,log,summary=self.sha(new=self.NO_WORKERS)
        self.assertEqual((code,passed),(1,[]),log)
        self.assertIn('::error title=Undeclared breaking change::option-removed workers — declare it in addon/upgrade-notes.yaml',log)
        self.assertIn('- t: **failed**',summary)
    @needs_shell
    def test_a_declared_breaking_change_passes(self):
        # The owner's declaration in the overlay (#91), at the commit: a re-run at the same commit passes.
        code,passed,log,_=self.sha(new=self.NO_WORKERS,files={'addon/upgrade-notes.yaml':self.DECLARED})
        self.assertEqual((code,passed),(0,['t']),log)
    @needs_shell
    def test_a_version_not_newer_than_the_comparison_target_fails(self):
        # The runtime job's plan fails it the same way, so it has no result there.
        for version in ('0.9.0','1.0'):
            with self.subTest(version):
                code,passed,log,summary=self.sha(version=version,results={},runtime='failure')
                self.assertEqual((code,passed),(1,[]),log)
                self.assertIn(f'version {version} is not newer than 1.0.0',log);self.assertIn('- t: **failed**',summary)
    @needs_shell
    def test_no_version_change_is_not_compared_and_passes_at_once(self):
        # Only detect runs (every later step's `if` needs a change), then the verdicts.
        code,passed,log,summary=self.sha(('detect','passed'),version='1.0.0',results={})
        self.assertEqual((code,passed),(0,[]),log)
        self.assertIn('changed=false',(self.tmp/'out').read_text());self.assertIn('- t: version unchanged, not compared',summary)
    @needs_shell
    def test_an_unpublished_new_image_fails(self):
        result={'name':'t','passed':False,'reason':'cannot pull '+self.NEW,'hooks':[],'data_checked':False,'phases':[]}
        code,passed,log,_=self.sha(images=(self.OLD,),results={'t':result},runtime='failure')
        self.assertEqual((code,passed),(1,[]),log)
        self.assertIn(f'::error title=Upgrade comparison failed::t: cannot pull {self.NEW}',log)
    @needs_shell
    def test_a_failed_upgrade_test_fails(self):
        result={'name':'t','passed':False,'reason':'the new version (1.1.0) did not start','hooks':[],'data_checked':False,'phases':[]}
        code,passed,log,_=self.sha(results={'t':result},runtime='failure')
        self.assertEqual((code,passed),(1,[]),log);self.assertIn('t: upgrade test failed: the new version (1.1.0) did not start',log)
    @needs_shell
    def test_ref_policy_main_is_refused(self):
        code,passed,log,_=self.sha(policy='main',results={})
        self.assertEqual((code,passed),(1,[]),log);self.assertIn('switch the provider to ref_policy release first',log)
    def multi(self,two=None,images=None,**kw):
        """music_assistant's shape: two add-ons with their own image; both bump to 1.1.0; two's config gets `two`."""
        comps=[{'id':i,'source_path':i,'config_file':'config.yaml'} for i in ('one','two')]
        image={i:f'ghcr.io/woowtech/ha-mirror-{i}-{{arch}}' for i in ('one','two')}
        files={f'{i}/config.yaml':yaml.safe_dump(dict(BASE,image=image[i],version='1.1.0',**(two if i=='two' else {}) or {})) for i in image}
        history=[('b',{})]+[(f'{i}-v1.0.0',{f'{i}/config.yaml':{'image':image[i]}}) for i in image]
        refs=[f'ghcr.io/woowtech/ha-mirror-{i}-amd64:{v}' for i in image for v in ('1.0.0','1.1.0')]
        return self.sha(extra={'components':comps,**self.APPROVED},releases=('one-v1.0.0','two-v1.0.0'),history=history,
            files=files,images=refs if images is None else images,started=('one','two'),**kw)
    @needs_shell
    def test_one_add_on_failing_leaves_only_the_other_in_passed(self):
        code,passed,log,summary=self.multi(two=self.NO_WORKERS)
        self.assertEqual((code,passed),(1,['one']),log)
        self.assertIn('- one: passed\n',summary);self.assertIn('- two: **failed**',summary)
    @needs_shell
    def test_an_image_one_add_on_cannot_pull_does_not_stop_the_others(self):
        # On a PR the step ends at the first image it cannot pull; in sha mode the other add-on is still scanned and compared.
        refs=['ghcr.io/woowtech/ha-mirror-one-amd64:1.0.0','ghcr.io/woowtech/ha-mirror-two-amd64:1.0.0','ghcr.io/woowtech/ha-mirror-two-amd64:1.1.0']
        code,passed,log,summary=self.multi(images=refs)
        self.assertEqual((code,passed),(1,['two']),log)
        self.assertIn('one: cannot pull ghcr.io/woowtech/ha-mirror-one-amd64:1.1.0',log)
        self.assertIn('two: scanned ghcr.io/woowtech/ha-mirror-two-amd64:1.0.0 (two-v1.0.0)',log);self.assertIn('- one: **failed**',summary)
    @needs_shell
    def test_without_sha_the_image_step_still_ends_at_the_first_failure(self):
        r,_,_=self.run_step(('plan',"SBOMs of the comparison targets' images"),extra=self.APPROVED,images=())
        self.assertEqual(r.returncode,1);self.assertFalse((self.tmp/'unscanned.txt').exists())

class ShaCommands(unittest.TestCase):
    """The two rules sha mode adds (#167): what changed at a commit (release-change) and what passed (sha-verdicts)."""
    SHA='0123456789abcdef0123456789abcdef01234567'
    def change(self,releases,version,policy='release',sha=SHA):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d)
        (d/'registry.json').write_text(json.dumps({'providers':{'WOOWTECH/r':{'ref_policy':policy,'components':[{'id':'t'}]}}}))
        stdin=json.dumps([r if isinstance(r,dict) else {'tag_name':r,'draft':False,'prerelease':False} for r in releases])
        with contextlib.redirect_stdout(io.StringIO()) as out,unittest.mock.patch('sys.stdin',io.StringIO(stdin)):
            code=u.main(['release-change','--registry',str(d/'registry.json'),'--repo','WOOWTECH/r','--component','t','--version',version,'--sha',sha])
        return code,out.getvalue()
    def test_unchanged_only_at_the_latest_stable_releases_version(self):
        releases=['v1.0.0','v1.1.0',{'tag_name':'v1.2.0','draft':False,'prerelease':True},'nightly']
        self.assertEqual(self.change(releases,'1.1.0'),(0,'unchanged\n'))
        # Newer is compared; a downgrade, the same version written differently and no Release are compared too (the plan fails the first two).
        for version in ('1.2.0','1.0.0','1.1'):
            with self.subTest(version):self.assertEqual(self.change(releases,version),(0,'changed\n'))
        self.assertEqual(self.change([],'1.0.0'),(0,'changed\n'))
    def test_sha_must_be_a_full_commit_and_the_provider_ref_policy_release(self):
        for kw,why in (({'sha':'main'},'sha must be a full commit id'),({'sha':''},'sha must be a full commit id'),({'policy':'main'},'switch the provider to ref_policy release first')):
            with self.subTest(kw):
                code,out=self.change(['v1.0.0'],'1.1.0',**kw)
                self.assertEqual(code,2);self.assertIn(why,out);self.assertTrue(out.startswith('::error title=Upgrade comparison failed::'))
    def verdicts(self,plan=('a','b','c'),compared=('a','b','c'),results=None,unchanged=(),runtime_failed=(),components=('a','b','c','d')):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d);(d/'reports').mkdir()
        (d/'provider.json').write_text(json.dumps({'components':[{'id':i} for i in components]}))
        (d/'plan.jsonl').write_text(''.join(json.dumps({'id':i})+'\n' for i in plan))
        for name,lines in (('compared.txt',compared),('unchanged.txt',unchanged),('failed.txt',runtime_failed)):(d/name).write_text(''.join(i+'\n' for i in lines))
        for i,passed in (results if results is not None else {'a':True,'b':True,'c':True}).items():(d/'reports'/f'{i}.json').write_text(json.dumps({'name':i,'passed':passed}))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code=u.main(['sha-verdicts','--provider',str(d/'provider.json'),'--unchanged',str(d/'unchanged.txt'),'--plan',str(d/'plan.jsonl'),
                '--compared',str(d/'compared.txt'),'--runtime-reports',str(d/'reports'),'--runtime-failed',str(d/'failed.txt')])
        return code,json.loads(out.getvalue())
    def test_passed_needs_both_jobs_evidence(self):
        code,v=self.verdicts(unchanged=('d',))
        self.assertEqual((code,v['passed']),(0,['a','b','c']))
        self.assertEqual(v['verdicts'],[{'id':i,'verdict':'passed'} for i in 'abc']+[{'id':'d','verdict':'unchanged'}])
        # A test that did not run (no comparison target, an approved skip) is not a failure, as on a PR.
        self.assertEqual(self.verdicts(results={'a':None,'b':True,'c':True},unchanged=('d',))[1]['passed'],['a','b','c'])
    def test_any_missing_or_failed_evidence_fails_that_add_on_only(self):
        for kw,failed in (({'compared':('b','c')},'a'),({'results':{'b':True,'c':True}},'a'),({'results':{'a':False,'b':True,'c':True}},'a'),
                ({'runtime_failed':('a',)},'a'),({'plan':('b','c')},'a')):
            with self.subTest(kw):
                code,v=self.verdicts(unchanged=('d',),**kw)
                self.assertEqual((code,v['passed']),(1,['b','c']));self.assertEqual(v['verdicts'][0],{'id':failed,'verdict':'failed'})
        # An add-on no step reached (d: neither unchanged nor planned) failed too.
        code,v=self.verdicts();self.assertEqual((code,v['passed'],v['verdicts'][3]),(1,['a','b','c'],{'id':'d','verdict':'failed'}))
    def test_missing_files_mean_not_judged_and_an_unknown_provider_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code=u.main(['sha-verdicts','--provider',f'{d}/provider.json','--unchanged',f'{d}/x','--plan',f'{d}/x','--compared',f'{d}/x','--runtime-reports',f'{d}/x','--runtime-failed',f'{d}/x'])
            self.assertEqual(code,2);self.assertTrue(out.getvalue().startswith('::error title=Upgrade comparison failed::'))
            pathlib.Path(d,'provider.json').write_text(json.dumps({'components':[{'id':'a'}]}))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code=u.main(['sha-verdicts','--provider',f'{d}/provider.json','--unchanged',f'{d}/x','--plan',f'{d}/x','--compared',f'{d}/x','--runtime-reports',f'{d}/x','--runtime-failed',f'{d}/x'])
            self.assertEqual((code,json.loads(out.getvalue())['passed']),(1,[]))

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
        self.assertIn('t: no stable Release yet, a new add-on',r.stdout)
    SEED=('t is not a new add-on (its config is on the PR base) but has no stable Release, so version 1.1.0 has nothing to be compared with; '
        'publish a seed Release first (v<version>')
    @needs_shell
    def test_an_add_on_on_the_pr_base_without_a_stable_release_fails(self):
        # #135: e.g. the registry switched to ref_policy release before the seed Release; it must not pass uncompared.
        r,plan,out=self.run_step(('detect','plan'),releases=(),skip='x',extra={'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan,{});self.assertNotIn('scan=',out)
        self.assertEqual(json.loads((self.tmp/'changed.jsonl').read_text())['on_base'],True)
        self.assertIn('::error title=Upgrade comparison failed::'+self.SEED,r.stdout)
        # A draft or a prerelease is no stable Release either.
        r,plan,_=self.run_step('plan',releases=({'tag_name':'v1.0.0','draft':False,'prerelease':True},),skip='x')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertIn(self.SEED,r.stdout)
    @needs_shell
    def test_with_a_stable_release_an_add_on_on_the_pr_base_is_compared(self):
        r,plan,_=self.run_step(('detect','plan'),skip='x',extra={'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'v1.0.0');self.assertIn('t: comparing 1.1.0 with v1.0.0',r.stdout)
    @needs_shell
    def test_a_new_add_on_without_a_stable_release_passes(self):
        # No config on the PR base (the detect step's on_base false): a new add-on, nothing to compare, as before #135.
        r,plan,_=self.run_step(('detect','plan'),releases=(),old_config=False)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(json.loads((self.tmp/'changed.jsonl').read_text())['on_base'],False)
        self.assertEqual([plan['target'],plan['note']],['','no comparison target']);self.assertIn('t: no stable Release yet, a new add-on',r.stdout)
    @needs_shell
    def test_an_add_on_in_the_store_catalog_without_a_stable_release_fails(self):
        # #135: no config on the PR base, but the Store ships it from this repository (e.g. a config moved without
        # previous_config): users run it, so it is not new; the same id from another repository is not this add-on.
        r,plan,_=self.run_step(('detect','plan'),releases=(),old_config=False,catalog={'t':{'repository':'WOOWTECH/t','version':'1.0.0'}})
        self.assertEqual(r.returncode,1,r.stdout+r.stderr);self.assertEqual(plan,{})
        self.assertIn('::error title=Upgrade comparison failed::t is not a new add-on (users run version 1.0.0 from the Store catalog) but has no stable Release',r.stdout)
        r,plan,_=self.run_step(('detect','plan'),releases=(),old_config=False,catalog={'t':{'repository':'WOOWTECH/other','version':'1.0.0'}})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['note'],'no comparison target')
    @needs_shell
    def test_ref_policy_main_does_not_look_for_a_stable_release(self):
        # Unchanged by #135: the target is the commit on the PR base where its version first appeared, Releases or none.
        r,plan,_=self.run_step(('detect','plan'),policy='main',releases=(),skip='x',extra={'upgrade_comparison':{'skip_vulnerability_scan':'x'}})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'b');self.assertNotIn('seed Release',r.stdout)
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
            for helper,use in [('gh_raw.sh',r'\b(fetch|config_at|version_since) '),('log.sh',r'\b(esc|fail|fail_output|no_cntrl) "'),('fields.sh',r'\bfields "')]:
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
        self.assertEqual(list((self.tmp/'mktemp').iterdir()),[])
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
                self.assertIn('so the commit where the version first appeared is unknown; re-run this check',r.stdout)
                self.assertEqual(list((self.tmp/'mktemp').iterdir()),[])
    @needs_shell
    def test_no_config_at_the_pr_base_is_a_new_add_on(self):
        # Nothing to look up: the PR base itself, with no config there (ComparisonTarget: no comparison target).
        r,plan,_=self.run_step('plan',policy='main',history=[('b',{self.P:None})],version='2.1',**self.SKIP)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(plan['target'],'b')
        self.assertIn('t: no config at the PR base, a new add-on',r.stdout)

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
    def test_fail_also_writes_its_reason_to_fail_log(self):
        # The runtime job sets FAIL_LOG, so compare can quote why it failed before any add-on result (#137).
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        script='source "$1"; fail "a: no image"; (fail_output "::error title=Upgrade comparison failed::b: bad tag") || true'
        r=subprocess.run([shutil.which('bash'),'-c',script,'-',(self.STORE/'.addon-sync/log.sh').as_posix()],capture_output=True,
            env=dict(os.environ,FAIL_LOG=(tmp/'f.txt').as_posix()))
        self.assertIn(b'::error title=Upgrade comparison failed::a: no image',r.stdout,r.stderr)
        self.assertEqual((tmp/'f.txt').read_bytes().replace(b'\r',b''),b'a: no image\nb: bad tag\n')
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

class DataCheckDueCommand(unittest.TestCase):
    """#141: an add-on with a database has until upgrade_comparison.data_check_due (a UTC date) to add verify. Through the
    due date itself (0 days left) startup only passes with the days left; from the day after it fails."""
    DUE='2026-11-17'
    def setUp(self):
        self.dir=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.dir);(self.dir/'addon/upgrade-check').mkdir(parents=True)
    def main(self,today,due=DUE,verify=False,component='a',given=None):
        """given: a's upgrade_comparison as written (default: {data_check_due: due}, none when due is None)."""
        comp={'id':'a','source_path':'addon','config_file':'config.yaml'}
        if due is not None:comp['upgrade_comparison']={'data_check_due':due}
        if given is not None:comp['upgrade_comparison']=given
        (self.dir/'registry.json').write_text(json.dumps({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':[comp,{'id':'b','source_path':'b','config_file':'config.yaml'}]}}}))
        if verify:(self.dir/'addon/upgrade-check/verify').write_text('#!/bin/sh\n')
        args=['data-check-due','--registry',str(self.dir/'registry.json'),'--repo','WOOWTECH/r','--component',component,'--addon-dir',str(self.dir/'addon')]
        if today is not None:args+=['--today',today]
        with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(args)
        return code,out.getvalue()
    def test_before_the_due_date_passes_with_the_days_left(self):
        code,out=self.main('2026-11-04');self.assertEqual(code,0);self.assertTrue(out.startswith('資料檢查期限 2026-11-17，剩 13 天'),out)
    def test_on_the_due_date_passes_with_0_days_left(self):
        code,out=self.main('2026-11-17');self.assertEqual(code,0);self.assertTrue(out.startswith('資料檢查期限 2026-11-17，剩 0 天'),out)
    def test_the_day_after_the_due_date_fails_and_says_to_add_the_data_check(self):
        code,out=self.main('2026-11-18');self.assertEqual(code,u.OVERDUE);self.assertEqual(u.OVERDUE,3)  # not 1, Python's code for a crash
        self.assertTrue(out.startswith('資料檢查期限 2026-11-17 已過，要補資料檢查'),out);self.assertIn('1 days ago, and upgrade-check/ still has no verify',out)
        self.assertIn('add the verify hook',out);self.assertNotIn('::error',out)  # the workflow gives it as the add-on's ::error
    def test_with_verify_the_due_date_is_ignored(self):
        for today in ('2026-11-04','2026-11-17','2027-01-01'):
            with self.subTest(today):self.assertEqual(self.main(today,verify=True),(0,''))
    def test_verify_must_be_a_file(self):
        (self.dir/'addon/upgrade-check/verify').mkdir();self.assertEqual(self.main('2026-11-18')[0],u.OVERDUE)
    def test_without_a_due_date_nothing_is_judged(self):
        self.assertEqual(self.main('2030-01-01',due=None),(0,''));self.assertEqual(self.main('2030-01-01',component='b'),(0,''))
    def test_malformed_due_date_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError,'it must be a date'):u.data_check_due({'id':'a','upgrade_comparison':{'data_check_due':None}},True,datetime.date(2026,11,4))
        for due in ('2026-11-31','17-11-2026','2026-1-7','',' 2026-11-17',20261117,True):
            with self.subTest(due=due):
                for verify in (False,True):
                    code,out=self.main('2026-11-04',due=due,verify=verify);self.assertEqual(code,2)
                    self.assertIn(f'::error title=Upgrade comparison failed::a: the Store registry gives upgrade_comparison.data_check_due {due!r}; it must be a date, YYYY-MM-DD (UTC)',out)
    def test_upgrade_comparison_must_be_a_mapping(self):
        for given in ('2026-11-17',['data_check_due'],True):
            with self.subTest(given=given):
                for verify in (False,True):
                    code,out=self.main('2026-11-04',verify=verify,given=given);self.assertEqual(code,2)
                    self.assertIn(f'the Store registry entry for a is malformed: upgrade_comparison must be a mapping, not {given!r}',out)
    def test_unexpected_error_is_a_tool_error_not_an_overdue_check(self):
        with unittest.mock.patch.object(u,'data_check_due',side_effect=RuntimeError('boom')):code,out=self.main('2026-11-18')
        self.assertEqual(code,2);self.assertIn('::error title=Upgrade comparison failed::boom',out)
        with unittest.mock.patch.object(u,'find_component',side_effect=AttributeError('x')):self.assertEqual(self.main('2026-11-18')[0],2)
    def test_malformed_today_and_unknown_add_on_fail(self):
        code,out=self.main('04/11/2026');self.assertEqual(code,2);self.assertIn('::error title=Upgrade comparison failed::a: --today: ',out)
        code,out=self.main('2026-11-04',component='zz');self.assertEqual(code,2);self.assertIn('zz',out)
    def test_today_defaults_to_the_utc_date(self):
        real=datetime.datetime
        class Fixed(real):
            @classmethod
            def now(cls,tz=None):return real(2026,11,17,23,30,tzinfo=datetime.timezone.utc).astimezone(tz)
        with unittest.mock.patch.object(u.datetime,'datetime',Fixed):code,out=self.main(None)
        self.assertEqual(code,0);self.assertTrue(out.startswith('資料檢查期限 2026-11-17，剩 0 天'),out)
    def test_pure_rule(self):
        comp={'id':'a','upgrade_comparison':{'data_check_due':'2026-12-08'}}
        self.assertEqual(u.data_check_due(comp,False,datetime.date(2026,12,7))[0],True)
        self.assertEqual(u.data_check_due(comp,False,datetime.date(2026,12,9))[0],False)
        self.assertIsNone(u.data_check_due(comp,True,datetime.date(2026,12,9)));self.assertIsNone(u.data_check_due({'id':'a'},False,datetime.date(2026,12,9)))
    def test_registry_due_dates_are_the_owners(self):
        # Owner, pipeline #90 (#141; the mirrors: pipeline #176-#180): the add-ons with a database and their deadlines; none at provider level.
        registry=json.loads((StepHarness.STORE/'.addon-sync/registry.json').read_text(encoding='utf-8'))
        due={c['id']:c['upgrade_comparison']['data_check_due'] for p in registry['providers'].values() for c in p['components'] if u.DUE_KEY in (c.get('upgrade_comparison') or {})}
        self.assertEqual(due,{'woow-n8n':'2026-11-17','odoo18ce':'2026-12-08','woow-nextcloud-office':'2026-12-08','woow-immich':'2026-12-29','woow-headscale':'2026-12-29',
                             'jellyfin':'2026-12-08','frigate':'2026-12-29','music_assistant':'2026-12-29','hamh':'2026-12-29','dnsmasq-dhcp':'2027-01-19'})
        for comp in (c for p in registry['providers'].values() for c in p['components']):
            with self.subTest(comp['id']):u.data_check_due(comp,False,datetime.date(2026,11,4))  # every date parses
        for p in registry['providers'].values():self.assertNotIn(u.DUE_KEY,p.get('upgrade_comparison') or {})
    def test_components_checks_every_add_ons_due_date_on_every_pr(self):
        # A bad date fails any PR of the repository, also for an add-on whose upgrade test does not run (or is retired).
        def components(*comps):
            reg={'providers':{'WOOWTECH/r':{'ref_policy':'release','components':[{'id':'a','source_path':'a','config_file':'config.yaml'},*comps]}}}
            return u.components(reg,'WOOWTECH/r')
        ok={'id':'b','source_path':'b','config_file':'config.yaml','upgrade_comparison':{'data_check_due':'2026-12-08'}}
        self.assertEqual([c['id'] for c in components(ok)['components']],['a','b'])
        for upgrade,message in (({'data_check_due':'2026-02-30'},"WOOWTECH/r b: the Store registry gives upgrade_comparison.data_check_due '2026-02-30'; it must be a date"),
                ('soon',"the Store registry entry for WOOWTECH/r b is malformed: upgrade_comparison must be a mapping, not 'soon'")):
            for extra in ({},{'enabled':False}):
                with self.subTest(upgrade=upgrade,extra=extra):
                    with self.assertRaises(ValueError) as e:components(dict(ok,upgrade_comparison=upgrade,**extra))
                    self.assertIn(message,str(e.exception))

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
        for path in [self.ACTION/'action.yml',self.ACTION.parent/'addon-image/action.yml',self.ACTION.parent.parent/'workflows/woow-addon-upgrade-check.yml']:
            for ref in re.findall(r'uses: *([^\s#]+)',path.read_text(encoding='utf-8')):
                with self.subTest(ref):
                    if not ref.startswith('WOOWTECH/'):self.assertRegex(ref,r'@[0-9a-f]{40}$')

class RuntimeRulesCommand(unittest.TestCase):
    """The upgrade test's pure rules (#137): where each data directory is mounted, and how "it starts" is judged."""
    def setUp(self):
        self.dir=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.dir)
    def run_cmd(self,*args):
        with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(list(args))
        return code,out.getvalue()
    def config(self,**cfg):
        path=self.dir/'config.yaml';path.write_text(yaml.safe_dump(dict(BASE,**cfg)),encoding='utf-8');return str(path)
    def mounts(self,**cfg):
        code,out=self.run_cmd('mounts','--config',self.config(**cfg),'--root','/w')
        self.assertEqual(code,0,out);return [(m['source'],m['target'],m['read_only']) for m in json.loads(out)]
    def test_data_is_always_mounted_and_shared_by_type(self):
        self.assertEqual(self.mounts(),[('/w/data','/data',False)])
    def test_map_entries_mount_at_supervisor_default_paths(self):
        # n8n's map: its data is in /config (addon_config); a dict entry is read-only unless read_only: false.
        got=self.mounts(map=[{'type':'addon_config','read_only':False},{'type':'share'},'media:rw','ssl','homeassistant_config'])
        self.assertEqual(got,[('/w/data','/data',False),('/w/all_app_configs/test','/config',False),('/w/share','/share',True),
            ('/w/media','/media',False),('/w/ssl','/ssl',True),('/w/homeassistant_config','/homeassistant',True)])
    def test_every_supervisor_type_has_its_default_path(self):
        # home-assistant/supervisor@bde7fb7 docker/const.py PATH_*; aliases share their new name's directory.
        expected={'config':('homeassistant_config','/config'),'homeassistant_config':('homeassistant_config','/homeassistant'),
            'app_config':('all_app_configs/test','/config'),'addon_config':('all_app_configs/test','/config'),
            'all_app_configs':('all_app_configs','/app_configs'),'all_addon_configs':('all_app_configs','/addon_configs'),
            'local_apps':('local_apps','/local_apps'),'addons':('local_apps','/addons'),'ssl':('ssl','/ssl'),
            'backup':('backup','/backup'),'share':('share','/share'),'media':('media','/media')}
        self.assertEqual(set(expected)|{'data'},set(u.MAP_PATHS))
        for kind,(source,target) in expected.items():
            with self.subTest(kind):
                self.assertEqual(self.mounts(map=[kind]),[('/w/data','/data',False),(f'/w/{source}',target,True)])
                self.assertEqual(self.mounts(map=[{'type':kind,'path':'/custom','read_only':False}]),
                    [('/w/data','/data',False),(f'/w/{source}','/custom',False)])
    def test_odoo_app_config_shares_the_addon_config_directory(self):
        # odoo #330 renames addon_config:rw to app_config:rw; both versions see the same directory at /config.
        self.assertEqual(self.mounts(map=['app_config:rw']),self.mounts(map=['addon_config:rw']))
        self.assertEqual(self.mounts(map=['app_config:rw']),[('/w/data','/data',False),('/w/all_app_configs/test','/config',False)])
    def test_data_entry_is_the_one_data_directory(self):
        # nextcloud #12 lists data itself; Supervisor mounts the add-on's data once, read-write, at its path or /data.
        self.assertEqual(self.mounts(map=[{'type':'data','read_only':False}]),[('/w/data','/data',False)])
        self.assertEqual(self.mounts(map=['data']),[('/w/data','/data',False)])
        self.assertEqual(self.mounts(map=[{'type':'data','path':'/var/lib/app'},'share']),
            [('/w/data','/var/lib/app',False),('/w/share','/share',True)])
    def test_custom_path_is_where_the_directory_is_mounted(self):
        # headscale's map (Woow_ha_vpn_headscale_package headscale/config.yaml): its database in /var/lib/headscale
        # (data), its config in /etc/headscale (addon_config).
        got=self.mounts(map=[{'type':'addon_config','path':'/etc/headscale','read_only':False},{'type':'data','path':'/var/lib/headscale'}])
        self.assertEqual(got,[('/w/data','/var/lib/headscale',False),('/w/all_app_configs/test','/etc/headscale',False)])
    def test_each_mount_names_its_type_as_written(self):
        # 'data' for the data mount wherever it is; otherwise the map type as config.yaml writes it.
        def types(m):
            code,out=self.run_cmd('mounts','--config',self.config(map=m),'--root','/w')
            self.assertEqual(code,0,out);return [(x['type'],x['source'],x['target']) for x in json.loads(out)]
        self.assertEqual(types([{'type':'addon_config','path':'/etc/headscale','read_only':False},{'type':'data','path':'/var/lib/headscale'}]),
            [('data','/w/data','/var/lib/headscale'),('addon_config','/w/all_app_configs/test','/etc/headscale')])
        self.assertEqual(types(['addon_config:rw','share']),
            [('data','/w/data','/data'),('addon_config','/w/all_app_configs/test','/config'),('share','/w/share','/share')])
        self.assertEqual([t for t,_,_ in types(['app_config','config:rw'])],['data','config'])
    def test_own_config_folder_is_inside_all_app_configs(self):
        # Supervisor's app_config is <app_configs>/<slug>, the folder all_app_configs shows as a whole.
        self.assertEqual(self.mounts(map=['app_config:rw','all_app_configs']),
            [('/w/data','/data',False),('/w/all_app_configs/test','/config',False),('/w/all_app_configs','/app_configs',True)])
        code,out=self.run_cmd('mounts','--config',self.config(slug='',map=['app_config']),'--root','/w')
        self.assertEqual(code,2);self.assertIn("map entry 'app_config' needs the add-on slug",out)
    def test_legacy_config_is_home_assistant_config_at_config(self):
        self.assertEqual(self.mounts(map=['config:rw']),[('/w/data','/data',False),('/w/homeassistant_config','/config',False)])
    def test_superseded_types_are_dropped_as_supervisor_does(self):
        # config drops app_config/addon_config/homeassistant_config; a new name drops its legacy one, in either order.
        self.assertEqual(self.mounts(map=['config:rw','addon_config:rw','homeassistant_config']),
            [('/w/data','/data',False),('/w/homeassistant_config','/config',False)])
        self.assertEqual(self.mounts(map=['addon_config','app_config:rw','addons','local_apps','all_addon_configs','all_app_configs']),
            [('/w/data','/data',False),('/w/all_app_configs/test','/config',False),('/w/local_apps','/local_apps',True),('/w/all_app_configs','/app_configs',True)])
        self.assertEqual(self.mounts(map=['app_config:rw','addon_config','local_apps','addons','all_app_configs','all_addon_configs']),
            [('/w/data','/data',False),('/w/all_app_configs/test','/config',False),('/w/local_apps','/local_apps',True),('/w/all_app_configs','/app_configs',True)])
        # A repeated type keeps its last entry.
        self.assertEqual(self.mounts(map=['share','share:rw']),[('/w/data','/data',False),('/w/share','/share',False)])
    def test_ignored_entries_are_reported(self):
        self.assertEqual(u.map_warnings({'map':['config:rw','addon_config','homeassistant_config']}),
            ["map entry 'addon_config' is ignored because 'config' is present (as Supervisor does)",
             "map entry 'homeassistant_config' is ignored because 'config' is present (as Supervisor does)"])
        self.assertEqual(u.map_warnings({'map':['addon_config','app_config']}),
            ["map entry 'addon_config' is ignored because 'app_config' is present (as Supervisor does)"])
        self.assertEqual(u.map_warnings({'map':['app_config:rw','share']}),[])
    def test_entries_supervisor_skips_are_skipped_and_reported(self):
        # apps/validate.py skips (and logs) a string that is not <known type>[:rw|:ro], a mapping without `type`,
        # and anything else; the add-on still loads, so the upgrade test still runs it.
        for entry in ['nope','media:rx','media:','share:rw:ro',{'path':'/x'},{'read_only':False},5,['share'],None]:
            with self.subTest(entry=entry):
                self.assertEqual(self.mounts(map=[entry,'share']),[('/w/data','/data',False),('/w/share','/share',True)])
                self.assertEqual(len(u.map_warnings({'map':[entry,'share']})),1)
                self.assertIn('is skipped because',u.map_warnings({'map':[entry]})[0])
    def test_map_entries_supervisor_rejects_fail_with_the_reason(self):
        # Supervisor's map schema: a known type, a boolean read_only (no coercion), a string path, no other key.
        for entry in [{'type':'nope'},{'type':['share']},{'type':{'a':1}},{'type':5},{'type':'share','read_only':'false'},
                {'type':'share','read_only':0},{'type':'share','path':5},{'type':'share','mode':'rw'}]:
            with self.subTest(entry=entry):
                code,out=self.run_cmd('mounts','--config',self.config(map=[entry]),'--root','/w')
                self.assertEqual(code,2,out);self.assertIn('invalid map entry',out)
        self.assertEqual(self.mounts(map=['share:ro']),[('/w/data','/data',False),('/w/share','/share',True)])
        code,out=self.run_cmd('mounts','--config',self.config(map=['app_config:rw',{'type':'share','path':'/config'}]),'--root','/w')
        self.assertEqual(code,2);self.assertIn('two data directories are mounted at /config',out)
    def probe(self,settings=None,**cfg):
        args=['startup-probe','--config',self.config(**cfg)]
        if settings is not None:
            path=self.dir/'settings.yaml';path.write_text(yaml.safe_dump(settings),encoding='utf-8');args+=['--settings',str(path)]
        code,out=self.run_cmd(*args);self.assertEqual(code,0,out);return json.loads(out)
    def test_startup_is_judged_by_watchdog_first(self):
        # n8n: watchdog, ingress and webui all present; the watchdog wins, at its container port.
        p=self.probe(watchdog='http://[HOST]:[PORT:5690]/_woow/watchdog',ingress=True,ingress_port=5690,webui='http://[HOST]:[PORT:5678]')
        self.assertEqual((p['method'],p['url']),('watchdog','http://[HOST]:5690/_woow/watchdog'))
        self.assertEqual(self.probe(watchdog='tcp://[HOST]:[PORT:1883]')['url'],'tcp://[HOST]:1883')
    def test_then_ingress_port_then_webui_then_staying_up(self):
        self.assertEqual(self.probe(ingress=True,ingress_port=5690,webui='http://[HOST]:[PORT:5678]/x')['url'],'http://[HOST]:5690/')
        self.assertEqual(self.probe(ingress=True)['url'],'http://[HOST]:8099/')  # Supervisor's default ingress_port
        self.assertEqual(self.probe(webui='http://[HOST]:[PORT:5678]/admin')['url'],'http://[HOST]:5678/admin')
        p=self.probe(webui='[PROTO:ssl]://[HOST]:[PORT:443]/',options={'ssl':True})
        self.assertEqual((p['method'],p['url']),('webui','https://[HOST]:443/'))
        p=self.probe();self.assertEqual((p['method'],p['url'],p['stable_seconds']),('stays-up','',60))
        # ingress_port 0 is a port Supervisor picks at install: still ingress, at the port the upgrade test assigns.
        p=self.probe(ingress=True,ingress_port=0,webui='http://[HOST]:[PORT:5678]')
        self.assertEqual((p['method'],p['url']),('ingress',f'http://[HOST]:{u.ASSIGNED_INGRESS_PORT}/'))
    def test_watchdog_needs_success_ingress_and_webui_any_answer_short_of_a_server_error(self):
        self.assertEqual(self.probe(watchdog='http://[HOST]:[PORT:1]/')['below'],300)
        self.assertIsNone(self.probe(watchdog='tcp://[HOST]:[PORT:1]')['below'])
        self.assertEqual(self.probe(ingress=True)['below'],500);self.assertEqual(self.probe(webui='http://[HOST]:[PORT:1]')['below'],500)
    def test_time_limits_have_defaults_and_can_be_overridden(self):
        p=self.probe(watchdog='tcp://[HOST]:[PORT:1]')
        self.assertEqual((p['timeout'],p['stable_seconds']),(300,60))
        p=self.probe({'startup_timeout':900,'stable_seconds':90},watchdog='tcp://[HOST]:[PORT:1]')
        self.assertEqual((p['timeout'],p['stable_seconds']),(900,90))
    def test_the_hooks_time_limit_is_a_known_setting_but_not_part_of_the_probe(self):
        # hook_timeout (#138) is upgrade_runtime.py's; the same settings.yaml holds it.
        p=self.probe({'hook_timeout':1200},watchdog='tcp://[HOST]:[PORT:1]')
        self.assertEqual((p['timeout'],p['stable_seconds'],'hook_timeout' in p),(300,60,False))
        # One loader validates every setting, the hooks' too.
        self.assertEqual(u.upgrade_settings(None),{'startup_timeout':300,'stable_seconds':60,'hook_timeout':600})
        self.assertEqual(u.upgrade_settings({'hook_timeout':1200})['hook_timeout'],1200)
    def test_webui_endpoint_is_its_scheme_and_port_as_supervisor_reads_it(self):
        self.assertEqual(u.webui_endpoint({'webui':'http://[HOST]:[PORT:5678]'}),('http',5678))
        self.assertEqual(u.webui_endpoint({'webui':'[PROTO:ssl]://[HOST]:[PORT:8443]/admin','options':{'ssl':True}}),('https',8443))
        self.assertEqual(u.webui_endpoint({'webui':'[PROTO:ssl]://[HOST]:[PORT:8443]/','options':{'ssl':False}}),('http',8443))
        self.assertIsNone(u.webui_endpoint({'ingress':True}))
        with self.assertRaisesRegex(ValueError,'as Supervisor does'):u.webui_endpoint({'webui':'http://localhost:1'})
    def test_bad_settings_fail_with_the_reason(self):
        path=self.dir/'settings.yaml'
        for text,reason in [('startup_timeout: 0\n','startup_timeout'),('startup_timeout: soon\n','startup_timeout'),('wait: 5\n',"unknown setting 'wait'"),
                ('hook_timeout: 0\n','hook_timeout must be a whole number of seconds above 0'),
                ('- 5\n','settings must be a mapping'),('stable_seconds: 300\n','stable_seconds (300) must be below startup_timeout (300)')]:
            with self.subTest(text):
                path.write_text(text,encoding='utf-8')
                code,out=self.run_cmd('startup-probe','--config',self.config(),'--settings',str(path))
                self.assertEqual(code,2);self.assertIn(reason,out)
    def test_absent_settings_file_uses_the_defaults(self):
        code,out=self.run_cmd('startup-probe','--config',self.config(),'--settings',str(self.dir/'absent.yaml'))
        self.assertEqual((code,json.loads(out)['timeout']),(0,300))
    def test_skip_upgrade_test_in_settings_is_not_a_time_limit(self):
        # #140: upgrade-test-skip judges it; the time limits ignore it.
        self.assertEqual(u.upgrade_settings({'skip_upgrade_test':'please','hook_timeout':5})['hook_timeout'],5)

class UpgradeTestSkipCommand(unittest.TestCase):
    """#140: skipping the upgrade test (categories 2 and 3) is approved per add-on in the Store registry
    (upgrade_comparison.skip_upgrade_test, the reason and its ticket), like skip_vulnerability_scan per provider."""
    REASON='#158: needs a physical enp2s0'
    def setUp(self):
        self.dir=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.dir)
    def main(self,approval=None,settings=None,component='a',given=None):
        # given: the whole upgrade_comparison value, for a malformed one.
        comp={'id':'a','source_path':'.','config_file':'config.yaml'}
        if approval is not None:comp['upgrade_comparison']={'skip_upgrade_test':approval}
        if given is not None:comp['upgrade_comparison']=given
        (self.dir/'registry.json').write_text(json.dumps({'providers':{'WOOWTECH/r':{'ref_policy':'release','components':[comp,{'id':'b','source_path':'b','config_file':'config.yaml'}]}}}))
        args=['upgrade-test-skip','--registry',str(self.dir/'registry.json'),'--repo','WOOWTECH/r','--component',component,'--settings',str(self.dir/'settings.yaml')]
        if settings is not None:(self.dir/'settings.yaml').write_text(settings,encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(args)
        return code,out.getvalue()
    def test_approved_add_on_prints_the_registry_reason(self):
        self.assertEqual(self.main(self.REASON),(0,self.REASON+'\n'))
    def test_approval_is_per_add_on(self):
        self.assertEqual(self.main(self.REASON,component='b'),(0,'\n'))
    def test_without_approval_nothing_is_skipped(self):
        self.assertEqual(self.main(),(0,'\n'));self.assertEqual(self.main(settings='hook_timeout: 5\n'),(0,'\n'))
    def test_asking_for_the_skip_without_approval_fails_and_says_to_get_it_approved(self):
        code,out=self.main(settings='skip_upgrade_test: "my add-on cannot start on a runner"\n')
        self.assertEqual(code,2)
        self.assertIn('::error title=Upgrade comparison failed::a: upgrade-check/settings.yaml asks for skip_upgrade_test, but skipping the upgrade test is not approved for a',out)
        self.assertIn('needs upgrade_comparison.skip_upgrade_test with the reason',out);self.assertIn('get the skip approved in the registry',out)
    def test_with_approval_the_report_gives_the_registrys_reason_not_the_repositorys(self):
        self.assertEqual(self.main(self.REASON,settings='skip_upgrade_test: "my text"\n'),(0,self.REASON+'\n'))
    def test_malformed_registry_entry_fails_with_a_clear_reason(self):
        for value in ('',' ',True,['#1: why'],{'why':1}):
            with self.subTest(value):
                code,out=self.main(value);self.assertEqual(code,2)
                self.assertIn('the Store registry entry for a is malformed: upgrade_comparison.skip_upgrade_test must be the approved reason and its ticket',out)
        for given in (['skip_upgrade_test'],'#158: why',3):
            with self.subTest(given):
                code,out=self.main(given=given);self.assertEqual(code,2)
                self.assertIn('the Store registry entry for a is malformed: upgrade_comparison must be a mapping',out);self.assertNotIn('Traceback',out)
        self.assertEqual(self.main(given={}),(0,'\n'))
    def test_only_a_non_empty_string_in_settings_asks_for_the_skip(self):
        for text in ('skip_upgrade_test: false\n','skip_upgrade_test: null\n','skip_upgrade_test: ""\n','skip_upgrade_test: "  "\n',
                'skip_upgrade_test: 1\n','- skip_upgrade_test\n'):
            with self.subTest(text):self.assertEqual(self.main(settings=text),(0,'\n'))
    def test_with_approval_a_malformed_settings_file_is_not_read(self):
        # The registry decides; the repository's text is ignored, even when it is not YAML.
        self.assertEqual(self.main(self.REASON,settings='skip_upgrade_test: [unclosed\n'),(0,self.REASON+'\n'))
        code,out=self.main(settings='skip_upgrade_test: [unclosed\n');self.assertEqual(code,2)
    def test_unknown_add_on_fails(self):
        code,out=self.main(component='zz');self.assertEqual(code,2);self.assertIn('zz',out)
    def test_registry_approves_exactly_the_add_ons_the_owner_did(self):
        # Owner, 2026-11-04 (pipeline #140): each skip names its ticket. 2026-11-05 (#158): pi_agent runs (host_network);
        # woow_lan_gateway's skip is permanent (pipeline .out-of-scope/lan-gateway-upgrade-test-on-runner.md).
        # 2026-11-06 (#164): woow-tailscale's temporary skip is removed; 0.1.4 is its Stable Release and rebuilds.
        # 2026-11-06 (#170): music_assistant's skip is temporary, until the mock Supervisor gives it the HA Core API (#174).
        # 2026-11-09 (#171): hamh's skip is temporary, until #174 too; dnsmasq-dhcp's is temporary, until the runtime applies privileged (#175).
        # 2026-11-09 (#175): dnsmasq-dhcp's skip is removed; the runtime applies privileged as --cap-add.
        # 2026-11-09 (#174): music_assistant's and hamh's skips are removed; they are flagged ha_core instead (HaCoreFlag).
        registry=json.loads((StepHarness.STORE/'.addon-sync/registry.json').read_text(encoding='utf-8'))
        approved={(repo,c['id']):u.upgrade_test_skip(c) for repo,p in registry['providers'].items() for c in p['components'] if u.upgrade_test_skip(c)}
        expected={('WOOWTECH/woow-lan-gateway','woow_lan_gateway'):('#158','permanent')}
        self.assertEqual({k:re.match(r'#\d+',v).group() for k,v in approved.items()},{k:ticket for k,(ticket,_) in expected.items()})
        for k,(_,kind) in expected.items():
            with self.subTest(k):
                self.assertIn(kind,approved[k])
                # Only a temporary approval says when it comes out; a permanent one names no removal.
                if kind=='permanent':self.assertNotIn('remove',approved[k].lower())
        for p in registry['providers'].values():
            with self.subTest('provider level'):self.assertNotIn('skip_upgrade_test',p.get('upgrade_comparison') or {})

class HaCoreFlag(StepHarness):
    """#174: upgrade_comparison.ha_core (a boolean, false when absent) in a component's Store registry entry makes its
    upgrade test start a real HA Core behind the mock Supervisor (upgrade_runtime.py --ha-core); homeassistant_api in
    config.yaml alone never does. components() checks it on every add-on and hands it to the workflow."""
    def test_the_flag_is_true_or_false(self):
        self.assertIs(u.ha_core({'id':'a'}),False);self.assertIs(u.ha_core({'id':'a','upgrade_comparison':{}}),False)
        self.assertIs(u.ha_core({'id':'a','upgrade_comparison':{'ha_core':True}}),True)
        self.assertIs(u.ha_core({'id':'a','upgrade_comparison':{'ha_core':False}}),False)
        for bad in ('true',1,None,[True]):
            with self.subTest(bad),self.assertRaisesRegex(ValueError,'the Store registry entry for a is malformed: upgrade_comparison.ha_core must be true or false'):
                u.ha_core({'id':'a','upgrade_comparison':{'ha_core':bad}})
        with self.assertRaisesRegex(ValueError,'upgrade_comparison must be a mapping'):u.ha_core({'id':'a','upgrade_comparison':True})
    def test_components_hands_the_flag_over_and_checks_every_add_on(self):
        comp=lambda i,**kw:{'id':i,'source_path':i,'config_file':'config.yaml',**kw}
        registry=lambda c:{'providers':{'WOOWTECH/r':{'ref_policy':'release','components':[comp('a',upgrade_comparison={'ha_core':True}),comp('b'),c]}}}
        out=u.components(registry(comp('c')),'WOOWTECH/r')
        self.assertEqual([(c['id'],c['ha_core']) for c in out['components']],[('a',True),('b',False),('c',False)])
        # Like data_check_due, a malformed flag fails every PR of the repository, even on an add-on that is not compared.
        bad=comp('c',channel='prerelease',upgrade_comparison={'ha_core':'yes'})
        with self.assertRaisesRegex(ValueError,'the Store registry entry for WOOWTECH/r c is malformed: upgrade_comparison.ha_core'):u.components(registry(bad),'WOOWTECH/r')
    def test_registry_flags_exactly_the_add_ons_the_owner_did(self):
        # Owner, 2026-11-09 (#174): music_assistant and hamh need HA Core; frigate (homeassistant_api too) does not.
        registry=json.loads((self.STORE/'.addon-sync/registry.json').read_text(encoding='utf-8'))
        flagged={(repo,c['id']) for repo,p in registry['providers'].items() for c in p['components'] if u.ha_core(c)}
        self.assertEqual(flagged,{('WOOWTECH/Woow_ha_music_assistant_add_on','music_assistant'),('WOOWTECH/Woow_ha_matter_hub_add_on','hamh')})
        for p in registry['providers'].values():
            with self.subTest('provider level'):self.assertNotIn('ha_core',p.get('upgrade_comparison') or {})
    @needs_shell
    def test_the_plan_and_run_steps_pass_ha_core_only_for_flagged_add_ons(self):
        comps=[{'id':'t','source_path':'addon','config_file':'config.yaml','upgrade_comparison':{'ha_core':True}}]
        for extra,flag in (({'components':comps},True),(None,False)):
            with self.subTest(flag):
                r,_,_=self.run_step(('plan','upgrade'),sbom='upgrade-comparison-sbom-*',image_artifact='upgrade-comparison-image-*',extra=extra)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                (row,)=[json.loads(l) for l in (self.tmp/'upgrade.jsonl').read_text().splitlines()];self.assertIs(row['ha_core'],flag)
        # A row without the key (an older plan) is unflagged.
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'tooling/.addon-sync').mkdir(parents=True);(tmp/'runtime-reports').mkdir()
        for name in ('log.sh','fields.sh'):shutil.copy(self.STORE/'.addon-sync'/name,tmp/'tooling/.addon-sync'/name)
        rows=[{'id':i,'addon_dir':f'source/{i}','new':f'{i}.yaml','old_ref':f'ghcr.io/o/{i}-amd64:1.0.0','artifact':'x','test':True,**extra}
            for i,extra in (('a',{'ha_core':True}),('b',{'ha_core':False}),('c',{}))]
        (tmp/'upgrade.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (run,)=self.run_runtime_steps(tmp,('Run the upgrade tests',))
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual({p.stem:json.loads(p.read_text()).get('ha_core',False) for p in (tmp/'runtime-reports').iterdir()},{'a':True,'b':False,'c':False})

class UpgradeTestSkipStep(StepHarness):
    """The runtime job's 'Skip the upgrade tests the registry approves' (#140): an approved add-on gets a result with the
    registry's reason and stays in the job's plan marked skipped, so one built on the device is still rebuilt for its
    SBOMs (#146) but not tested; asking for the skip without the approval fails the job, so compare fails."""
    STEP='Skip the upgrade tests the registry approves'
    def approved(self,reason='#158: needs a physical enp2s0'):
        return {'components':[{'id':'t','source_path':'addon','config_file':'config.yaml','upgrade_comparison':{'skip_upgrade_test':reason}}]}
    def plan(self,**kw):
        kw.setdefault('sbom','upgrade-comparison-sbom-*');kw.setdefault('image_artifact','upgrade-comparison-image-*')
        return self.run_step(('plan',self.STEP,'upgrade'),**kw)
    def test_no_caller_input(self):
        # The registry alone decides: a caller cannot ask for the skip, and a caller of a repository that has one need not change.
        self.assertNotIn('skip_upgrade_test',self.wf['on']['workflow_call']['inputs'])
        names=[s.get('name') for s in self.wf['jobs']['runtime']['steps']]
        self.assertEqual(names.index(self.STEP),names.index('Find the comparison targets')+1)
        self.assertEqual(names.index('Plan the upgrade tests'),names.index(self.STEP)+1)
        self.assertNotIn(self.STEP,[s.get('name') for s in self.wf['jobs']['compare']['steps']])
    @needs_shell
    def test_approved_add_on_is_skipped_with_the_registrys_reason(self):
        r,_,out=self.plan(extra=self.approved(),files={'addon/upgrade-check/settings.yaml':'skip_upgrade_test: "my text"\n'})
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('run=false',out)
        # It stays in the plan marked skipped (#146: one built on the device is still rebuilt for category 4); a prebuilt
        # one has nothing to build, so it is not in upgrade.jsonl.
        self.assertEqual([(p['id'],p.get('skipped')) for p in self.plans],[('t',True)]);self.assertEqual((self.tmp/'upgrade.jsonl').read_text(),'')
        note='categories 2 and 3 skipped as approved in the Store registry: #158: needs a physical enp2s0'
        self.assertEqual(json.loads((self.tmp/'runtime-reports/t.json').read_text()),{'name':'t','passed':None,'skipped':True,'not_run':'approved_skip','note':note})
        self.assertIn(f'- t: upgrade test not run ({note})',(self.tmp/'summary').read_text())
    @needs_shell
    def test_add_on_without_approval_is_tested(self):
        r,_,out=self.plan()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('run=true',out);self.assertEqual([p['id'] for p in self.plans],['t'])
        self.assertFalse((self.tmp/'runtime-reports/t.json').exists())
    @needs_shell
    def test_asking_for_the_skip_without_approval_fails(self):
        r,_,_=self.plan(files={'addon/upgrade-check/settings.yaml':'skip_upgrade_test: "cannot start on a runner"\n'})
        self.assertEqual(r.returncode,1)
        self.assertIn('skipping the upgrade test is not approved for t',r.stdout);self.assertIn('get the skip approved in the registry',r.stdout)
        self.assertFalse((self.tmp/'upgrade.jsonl').exists())
    @needs_shell
    def test_skipped_add_on_is_reported_with_the_reason_by_compare(self):
        note='categories 2 and 3 skipped as approved in the Store registry: #157: admin_password has no default'
        code,out,summary=UpgradeTestResult.result(self,[{'name':'t','passed':None,'skipped':True,'note':note}])
        self.assertEqual(code,0,out);self.assertIn(f'- t: not run ({note})',summary)

class ComparisonTargetFailure(StepHarness):
    """#140: a comparison target that cannot be tested fails the upgrade comparison for that add-on, with the reason.
    Pulling its image is the workflow's (target_failed, log.sh; #144 also calls it when a rebuild fails); a target that
    does not start or whose seed fails is upgrade_runtime.py's (test_upgrade_runtime.py)."""
    @needs_shell
    def test_image_that_cannot_be_pulled_is_the_add_ons_failure_with_the_reason(self):
        r,_,_=self.run_step(('plan','upgrade','Pull the images'),sbom='upgrade-comparison-sbom-*',image_artifact='upgrade-comparison-image-*')
        # The step goes on (other add-ons are still tested); the add-on leaves the test and "Run the upgrade tests" fails the job.
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual([json.loads(l)['test'] for l in (self.tmp/'upgrade.jsonl').read_text().splitlines()],[False])
        reason="cannot pull the comparison target's image ghcr.io/da-anda/addon-amd64:1.0.0 from the registry, so the upgrade cannot be tested; re-run, or check that the image exists"
        self.assertIn(f'::error title=Upgrade comparison failed::t: {reason}',r.stdout)
        result=json.loads((self.tmp/'runtime-reports/t.json').read_text())
        self.assertEqual(result,{'name':'t','passed':False,'reason':reason,'hooks':[],'data_checked':False,'phases':[]})
        # It is the only reason compare gets (no reason-less runtime-job entry next to it), and compare fails with it.
        self.assertEqual(RuntimeFailureRecord.record(self,results=(result,)),{'t.json':result})
        code,out,summary=UpgradeTestResult.result(self,[result],runtime='failure')
        self.assertEqual(code,1);self.assertIn(f't: upgrade test failed: {reason}',out);self.assertIn('- t: **failed**',summary)
    @needs_shell
    def test_one_unpullable_target_does_not_stop_the_others(self):
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'tooling/.addon-sync').mkdir(parents=True);(tmp/'bin').mkdir();(tmp/'runtime-reports').mkdir()
        for name in ('log.sh','fields.sh','images.sh'):shutil.copy(self.STORE/'.addon-sync'/name,tmp/'tooling/.addon-sync'/name)
        (tmp/'bin/docker').write_text(DOCKER_STUB);(tmp/'bin/docker').chmod(0o755)
        rows=[{'id':i,'addon_dir':f'source/{i}','new':f'{i}.yaml','old_ref':f'ghcr.io/o/{i}-amd64:1.0.0','artifact':'x','test':True} for i in ('a','b','c')]
        (tmp/'upgrade.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        runs=self.run_runtime_steps(tmp,('Pull the images','Run the upgrade tests'),IMAGES='ghcr.io/o/a-amd64:1.0.0\nghcr.io/o/c-amd64:1.0.0')
        # b fails with its reason, a and c are still tested, and the job fails at the end.
        self.assertEqual([r.returncode for r in runs],[0,1],runs[-1].stdout+runs[-1].stderr)
        results={p.stem:json.loads(p.read_text()) for p in (tmp/'runtime-reports').iterdir()}
        self.assertEqual({k:v['passed'] for k,v in results.items()},{'a':True,'b':False,'c':True})
        self.assertIn("cannot pull the comparison target's image ghcr.io/o/b-amd64:1.0.0",results['b']['reason'])
        self.assertEqual(results['c']['old_image'],'ghcr.io/o/c-amd64:1.0.0')
    @needs_shell
    def test_run_step_passes_when_nothing_failed(self):
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        (tmp/'tooling/.addon-sync').mkdir(parents=True);(tmp/'runtime-reports').mkdir()
        shutil.copy(self.STORE/'.addon-sync/fields.sh',tmp/'tooling/.addon-sync');shutil.copy(self.STORE/'.addon-sync/log.sh',tmp/'tooling/.addon-sync')
        (tmp/'upgrade.jsonl').write_text(json.dumps({'id':'t','old_ref':'','test':False})+'\n')
        (tmp/'runtime-reports/t.json').write_text(json.dumps({'name':'t','passed':None,'note':'n'}))
        (tmp/'step.sh').write_text(self.step('Run the upgrade tests')['run'],newline='\n')
        r=subprocess.run(['bash',str(tmp/'step.sh')],cwd=tmp,env=dict(os.environ,GITHUB_STEP_SUMMARY=str(tmp/'summary')),capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    @needs_shell
    def test_target_failed_escapes_and_leaves_fail_log_alone(self):
        import os,subprocess
        tmp=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,tmp)
        script=f'source "{(self.STORE/".addon-sync/log.sh").as_posix()}"\ntarget_failed t "$1"\n'
        r=subprocess.run(['bash','-c',script,'bash','bad\n::error::x'],cwd=tmp,env=dict(os.environ,FAIL_LOG=str(tmp/'fail.txt')),capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,'::error title=Upgrade comparison failed::t: bad%0A::error::x\n')
        self.assertFalse((tmp/'fail.txt').exists());self.assertEqual(json.loads((tmp/'runtime-reports/t.json').read_text())['reason'],'bad\n::error::x')

class PublishedImageUpgradeTest(StepHarness):
    """#154: with the provider's scan_published_image approval (#147, #148) the upgrade test's new image is the published one
    the PR's config names (image with {arch} -> amd64, tag = the PR's version), pulled in the runtime job like the comparison
    target's: no image_artifact is awaited or checked. An unpublished tag is the PR's fault (addon_failed); an unpullable
    comparison target is still target_failed (#140)."""
    APPROVED=PublishedImageScan.APPROVED
    OLD,NEW=PublishedImageScan.OLD,PublishedImageScan.NEW
    STEPS=('plan','Skip the upgrade tests the registry approves','upgrade','Pull the images')
    UNPUBLISHED_REASON=("cannot pull ghcr.io/da-anda/addon-amd64:1.1.0, the image users would install with this PR: tag 1.1.0 of ghcr.io/da-anda/addon-amd64 "
        "is not published yet (or the registry is unreachable); publish it first (its upstream's release for a third-party image, the repository's "
        "own image publication otherwise) or bump to a version whose image is published, then re-run")
    def rows(self):return [json.loads(l) for l in (self.tmp/'upgrade.jsonl').read_text().splitlines()]
    def run_tests(self):
        """'Run the upgrade tests' in the job's directory (run_runtime_steps)."""
        (r,)=self.run_runtime_steps(self.tmp,('Run the upgrade tests',))
        return r,{p.stem:json.loads(p.read_text()) for p in (self.tmp/'runtime-reports').glob('*.json')}
    @needs_shell
    def test_published_provider_without_image_artifact_is_tested_with_the_pulled_new_image(self):
        r,_,out=self.run_step(self.STEPS,extra=self.APPROVED,images=(self.OLD,self.NEW))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        (row,)=self.rows()
        self.assertEqual((row['test'],row['old_ref'],row['new_src'],row['new_ref']),(True,self.OLD,'published',self.NEW))
        # Nothing to wait for, load or build; no "not run" note (the #143 one is for callers whose own build ships).
        for output in ('run=true','wait=false','build=false'):
            with self.subTest(output):self.assertIn(output,out)
        self.assertFalse((self.tmp/'runtime-reports/t.json').exists())
        r,results=self.run_tests()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(results['t'],{'name':'t','passed':True,'old_image':self.OLD,'new_image':self.NEW})
    @needs_shell
    def test_the_callers_image_artifact_glob_is_not_checked(self):
        r,_,_=self.run_step(self.STEPS[:3],extra=self.APPROVED,image_artifact='other-*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(self.rows()[0]['new_src'],'published')
    def test_category_4_and_the_upgrade_test_give_one_unpublished_reason(self):
        # One text (images.sh), so the README's "the same message as category 4" cannot drift.
        for name in ("SBOMs of the comparison targets' images",'Pull the images'):
            with self.subTest(name):
                run=self.step(name)['run'];self.assertIn('source tooling/.addon-sync/images.sh',run);self.assertIn('$(unpublished_reason "${new_ref}")',run)
    @needs_shell
    def test_an_unpublished_new_tag_is_the_prs_fault_with_the_category_4_message(self):
        r,_,_=self.run_step(self.STEPS,extra=self.APPROVED,images=(self.OLD,))
        # Like a target that cannot be pulled, the step goes on and the add-on leaves the test with its result.
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual([x['test'] for x in self.rows()],[False])
        self.assertIn(f'::error title=Upgrade comparison failed::t: {self.UNPUBLISHED_REASON}',r.stdout)
        result=json.loads((self.tmp/'runtime-reports/t.json').read_text())
        self.assertEqual(result,{'name':'t','passed':False,'reason':self.UNPUBLISHED_REASON,'hooks':[],'data_checked':False,'phases':[]})
        self.assertNotIn('comparison target',result['reason'])
        # compare quotes it, once.
        self.assertEqual(RuntimeFailureRecord.record(self,results=(result,)),{'t.json':result})
        code,out,_=UpgradeTestResult.result(self,[result],runtime='failure')
        self.assertEqual(code,1);self.assertIn(f't: upgrade test failed: {self.UNPUBLISHED_REASON}',out)
        r,_=self.run_tests();self.assertEqual(r.returncode,1,r.stdout+r.stderr)
    @needs_shell
    def test_an_unpullable_comparison_target_is_still_a_target_failure(self):
        r,_,_=self.run_step(self.STEPS,extra=self.APPROVED,images=(self.NEW,))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(json.loads((self.tmp/'runtime-reports/t.json').read_text())['reason'],
            f"cannot pull the comparison target's image {self.OLD} from the registry, so the upgrade cannot be tested; re-run, or check that the image exists")
    @needs_shell
    def test_one_unpublished_add_on_of_a_multi_add_on_repository_does_not_stop_the_others(self):
        # mcp_addons' shape (#155 reuses this): each changed add-on pulls its own published image; hermes' is not published.
        comps=[{'id':i,'source_path':'addons/'+i,'config_file':'config.yaml'} for i in ('n8n','hermes','odoo')]
        image={i:f'ghcr.io/woowtech/{{arch}}-mcp-{i}' for i in ('n8n','hermes','odoo')}
        history=[('b',{})]+[(f'{i}-v1.0.0',{f'addons/{i}/config.yaml':{'image':image[i]}}) for i in image]
        images=('ghcr.io/woowtech/amd64-mcp-n8n:1.0.0','ghcr.io/woowtech/amd64-mcp-n8n:1.1.0','ghcr.io/woowtech/amd64-mcp-hermes:1.0.0')
        r,_,_=self.run_step(self.STEPS,extra={'components':comps,**self.APPROVED},releases=tuple(f'{i}-v1.0.0' for i in image),
            history=history,changed=2,news={i:{'image':image[i]} for i in ('n8n','hermes')},images=images)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual({x['id']:(x['test'],x['new_ref']) for x in self.rows()},
            {'n8n':(True,'ghcr.io/woowtech/amd64-mcp-n8n:1.1.0'),'hermes':(False,'ghcr.io/woowtech/amd64-mcp-hermes:1.1.0')})
        self.assertIn('hermes: cannot pull ghcr.io/woowtech/amd64-mcp-hermes:1.1.0, the image users would install with this PR: tag 1.1.0 of '
            'ghcr.io/woowtech/amd64-mcp-hermes is not published yet',r.stdout)
        r,results=self.run_tests()
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertEqual((results['n8n']['passed'],results['n8n']['new_image'],results['hermes']['passed']),(True,'ghcr.io/woowtech/amd64-mcp-n8n:1.1.0',False))
    @needs_shell
    def test_two_changed_add_ons_of_one_provider_each_get_their_own_pulled_new_image(self):
        # release-gating/155: mcp_addons bumps several add-ons in one PR; each is tested on its own published image, and an
        # add-on whose version did not change (odoo) is not in the plan.
        ids=('n8n','hermes','odoo')
        comps=[{'id':i,'source_path':'addons/'+i,'config_file':'config.yaml'} for i in ids]
        image={i:f'ghcr.io/woowtech/{{arch}}-mcp-{i}' for i in ids}
        history=[('b',{})]+[(f'{i}-v1.0.0',{f'addons/{i}/config.yaml':{'image':image[i]}}) for i in ids]
        images=tuple(f'ghcr.io/woowtech/amd64-mcp-{i}:{v}' for i in ('n8n','hermes') for v in ('1.0.0','1.1.0'))
        r,_,out=self.run_step(self.STEPS,extra={'components':comps,**self.APPROVED},releases=tuple(f'{i}-v1.0.0' for i in ids),
            history=history,changed=2,news={i:{'image':image[i]} for i in ('n8n','hermes')},images=images)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual({x['id']:(x['test'],x['old_ref'],x['new_src'],x['new_ref']) for x in self.rows()},
            {i:(True,f'ghcr.io/woowtech/amd64-mcp-{i}:1.0.0','published',f'ghcr.io/woowtech/amd64-mcp-{i}:1.1.0') for i in ('n8n','hermes')})
        for output in ('run=true','wait=false','build=false'):
            with self.subTest(output):self.assertIn(output,out)
        r,results=self.run_tests()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(results,{i:{'name':i,'passed':True,'old_image':f'ghcr.io/woowtech/amd64-mcp-{i}:1.0.0',
            'new_image':f'ghcr.io/woowtech/amd64-mcp-{i}:1.1.0'} for i in ('n8n','hermes')})
    @needs_shell
    def test_a_provider_without_the_approval_is_unchanged(self):
        # Still the caller's artifact, its glob checked, and the #143 note without one.
        r,_,out=self.run_step(self.STEPS[:3],sbom='upgrade-comparison-sbom-*',image_artifact='upgrade-comparison-image-*',images=(self.OLD,self.NEW))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual((self.rows()[0]['new_src'],self.rows()[0]['new_ref']),('artifact',''));self.assertIn('wait=true',out)
        r,_,_=self.run_step(self.STEPS[:3],sbom='upgrade-comparison-sbom-*',image_artifact='other-*')
        self.assertNotEqual(r.returncode,0);self.assertIn("image_artifact 'other-*' does not match",r.stdout)
        r,_,out=self.run_step(self.STEPS[:3],sbom='upgrade-comparison-sbom-*')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('run=false',out)
        self.assertEqual(json.loads((self.tmp/'runtime-reports/t.json').read_text())['not_run'],'no_image_artifact')

def smoke_run(phase,exit_code=0,checks=None,report_error=''):
    """A smoke run as upgrade_runtime.py records it; checks: {name: result}, or None when the hook wrote no report."""
    return {'hook':'smoke','phase':phase,'passed':exit_code==0 and not report_error and 'fail' not in (checks or {}).values(),'exit_code':exit_code,
        'detail':f'exited with code {exit_code}','checks':[{'name':n,'result':r,'detail':f'{n} {r}'} for n,r in (checks or {}).items()],'output':'','report_error':report_error,'reported':checks is not None or bool(report_error)}

class RegressionCommand(unittest.TestCase):
    """Category 3 (#139): `regression` compares the smoke checks of an upgrade test result by name."""
    def setUp(self):
        self.dir=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.dir)
    def compare(self,old,new,hooks=('seed','verify','smoke'),started=(True,True),not_run=None):
        """old/new: the smoke run of each version (None: smoke did not run there; 'absent': that version did not run).
        not_run: the new version's smoke_not_run."""
        phases=[{'phase':phase,'version':version,'started':up,'detail':f'{phase} detail','hooks':[run] if run else []}
            for phase,version,up,run in (('old','1.0.0',started[0],old),('new','1.1.0',started[1],new)) if run!='absent']
        if not_run:phases[-1]['smoke_not_run']=not_run
        path=self.dir/'t.json';path.write_text(json.dumps({'name':'t','passed':True,'reason':'','hooks':list(hooks),'phases':phases}),encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(['regression','--result',str(path)])
        r=json.loads(out.getvalue());self.assertEqual(code,0 if r['passed'] else 1)
        return r
    def verdicts(self,r):return {row['name']:row['verdict'] for row in r['rows']}
    def test_check_that_passes_on_the_target_must_pass_on_the_new_version(self):
        for new in ('fail','skip'):
            with self.subTest(new):
                r=self.compare(smoke_run('old',0,{'api':'pass','ui':'pass'}),smoke_run('new',0,{'api':new,'ui':'pass'}))
                self.assertFalse(r['passed']);self.assertEqual(self.verdicts(r),{'(the hook)':'pass','api':'fail','ui':'pass'})
                self.assertEqual(r['reason'],f'regression (category 3): api passes on the comparison target but is {new} on the new version')
        # A check the new version no longer reports is not passing either.
        r=self.compare(smoke_run('old',0,{'api':'pass'}),smoke_run('new',0,{}))
        self.assertEqual(self.verdicts(r)['api'],'fail');self.assertIn('api passes on the comparison target but is absent from its report',r['reason'])
        row=r['rows'][1];self.assertEqual((row['old'],row['new'],row['old_detail'],row['new_detail']),('pass',None,'api pass',''))
    def test_check_that_does_not_pass_on_the_target_is_only_reported(self):
        r=self.compare(smoke_run('old',1,{'api':'fail','ui':'skip','db':'pass'}),smoke_run('new',1,{'api':'fail','ui':'fail','db':'pass'}))
        self.assertTrue(r['passed']);self.assertEqual(r['reason'],'')
        self.assertEqual(self.verdicts(r),{'(the hook)':'not compared','api':'not compared','ui':'not compared','db':'pass'})
    def test_check_only_in_the_new_version_must_pass(self):
        r=self.compare(smoke_run('old',0,{'api':'pass'}),smoke_run('new',0,{'api':'pass','new':'pass'}))
        self.assertTrue(r['passed']);self.assertEqual(self.verdicts(r)['new'],'pass')
        for result in ('fail','skip'):
            with self.subTest(result):
                r=self.compare(smoke_run('old',0,{'api':'pass'}),smoke_run('new',0,{'api':'pass','new':result}))
                self.assertFalse(r['passed']);self.assertEqual(self.verdicts(r)['new'],'fail')
                self.assertIn(f'new is only in the new version and is {result}, not pass',r['reason'])
    def test_without_a_report_the_exit_codes_are_compared(self):
        r=self.compare(smoke_run('old',0),smoke_run('new',3))
        self.assertFalse(r['passed']);self.assertEqual([(row['name'],row['old'],row['new'],row['verdict']) for row in r['rows']],[('(the hook)','pass','fail','fail')])
        self.assertIn('(the hook) passes on the comparison target but is fail on the new version',r['reason'])
        # The target's smoke exits non-zero: not compared (未比對), whatever the new version does.
        for new in (0,3):
            with self.subTest(new):
                r=self.compare(smoke_run('old',2),smoke_run('new',new))
                self.assertTrue(r['passed']);self.assertEqual(self.verdicts(r),{'(the hook)':'not compared'})
        self.assertTrue(self.compare(smoke_run('old',0),smoke_run('new',0))['passed'])
    def test_hook_that_fails_after_writing_passing_checks_or_breaks_its_report_regresses(self):
        r=self.compare(smoke_run('old',0,{'api':'pass'}),smoke_run('new',1,{'api':'pass'}))
        self.assertEqual(self.verdicts(r),{'(the hook)':'fail','api':'pass'})
        r=self.compare(smoke_run('old',0,{'api':'pass'}),smoke_run('new',0,{'api':'pass'},report_error='its report smoke.json is not JSON'))
        self.assertEqual(self.verdicts(r)['(the hook)'],'fail')
        # A target report that cannot be read has no checks to go by: a check is not "only in the new version".
        r=self.compare(smoke_run('old',0,report_error='its report smoke.json is not JSON'),smoke_run('new',0,{'api':'fail'}))
        self.assertTrue(r['passed']);self.assertEqual(self.verdicts(r),{'(the hook)':'not compared','api':'not compared'})
    def test_smoke_not_run_on_the_new_version_is_not_compared(self):
        # Category 2 failed first (the new version did not start, verify failed): category 3 is not judged.
        r=self.compare(smoke_run('old',0,{'api':'pass'}),None,not_run='verify failed on the new version (1.1.0): exited with code 1')
        self.assertEqual((r['compared'],r['passed'],r['rows'],r['reason']),(False,True,[],''))
        self.assertEqual(r['not_run'],'verify failed on the new version (1.1.0): exited with code 1')
        r=self.compare(smoke_run('old',0,{'api':'pass'}),'absent')
        self.assertEqual((r['compared'],r['not_run']),(False,'the upgrade test ended before the new version ran'))
        r=self.compare(None,smoke_run('new',0,{'api':'fail'}))
        self.assertTrue(r['passed']);self.assertTrue(r['compared']);self.assertEqual(self.verdicts(r),{'(the hook)':'not compared','api':'not compared'})
    def test_target_smoke_without_a_readable_report_makes_no_check_only_in_the_new_version(self):
        # Timed out (exit_code None), crashed or exited non-zero before writing smoke.json, or exited 0 without one:
        # the comparison target has no checks to go by, so the new version's checks are 未比對.
        for old in (smoke_run('old',None),smoke_run('old',2),smoke_run('old',0)):
            with self.subTest(old):
                r=self.compare(old,smoke_run('new',0,{'new':'fail'}))
                self.assertTrue(r['passed'],r['reason']);self.assertEqual(self.verdicts(r)['new'],'not compared')
    def test_target_smoke_that_exits_non_zero_with_a_report_still_makes_new_checks_count(self):
        # One check already fails on the comparison target, so its smoke exits 1; its report still lists every
        # check, so a check only the new version has must pass (an empty report counts too).
        for old in (smoke_run('old',1,{'api':'pass','old bug':'fail'}),smoke_run('old',1,{})):
            with self.subTest(old):
                r=self.compare(old,smoke_run('new',1,{'api':'pass','old bug':'fail','new':'fail'}))
                self.assertFalse(r['passed']);self.assertEqual(self.verdicts(r)['new'],'fail')
                self.assertIn('new is only in the new version and is fail, not pass',r['reason'])
                self.assertEqual(self.verdicts(r)['(the hook)'],'not compared')
        r=self.compare(smoke_run('old',1,{'old bug':'fail'}),smoke_run('new',1,{'old bug':'fail','new':'pass'}))
        self.assertTrue(r['passed'],r['reason']);self.assertEqual(self.verdicts(r),{'(the hook)':'not compared','old bug':'not compared','new':'pass'})
        # A check that passes on a target whose hook exited non-zero is still compared.
        self.assertEqual(self.verdicts(self.compare(smoke_run('old',1,{'api':'pass'}),smoke_run('new',1,{'api':'fail'})))['api'],'fail')
    def test_without_smoke_only_startup_is_compared(self):
        r=self.compare(None,None,hooks=('seed','verify'))
        self.assertTrue(r['passed']);self.assertFalse(r['smoke']);self.assertTrue(r['compared'])
        self.assertEqual(r['rows'],[{'name':'starts','old':'pass','new':'pass','verdict':'pass','old_detail':'old detail','new_detail':'new detail'}])
        r=self.compare(None,None,hooks=(),started=(True,False))
        self.assertFalse(r['passed']);self.assertEqual(r['reason'],'regression (category 3): starts passes on the comparison target but is fail on the new version')
        self.assertTrue(self.compare(None,None,hooks=(),started=(False,True))['passed'])
    def test_input_that_is_not_a_result_exits_2(self):
        for text in ('{','[]','{"phases": 3}'):
            with self.subTest(text):
                path=self.dir/'bad.json';path.write_text(text,encoding='utf-8')
                with contextlib.redirect_stdout(io.StringIO()) as out:code=u.main(['regression','--result',str(path)])
                self.assertEqual(code,2);self.assertIn('::error',out.getvalue())

if __name__=='__main__':unittest.main()
