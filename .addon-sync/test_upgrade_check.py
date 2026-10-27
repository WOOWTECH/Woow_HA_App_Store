import contextlib,copy,io,pathlib,shutil,tempfile,unittest
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
    def test_nonstandard_versions_order_by_their_leading_number(self):
        old=copy.deepcopy(BASE);old['version']='2.12.4-v2'
        cfg=self.REMOVED();cfg['version']='2.12.5-v1'
        for version,blocked in [('2.12.5-v1',False),('2.12.4-v2',True)]:
            with self.subTest(version):self.assertEqual(run(cfg,self.notes(version),old=old,old_version='2.12.4-v2')['blocked'],blocked)
        with self.assertRaises(ValueError):run(cfg,self.notes('2.12.4-v3'),old=old,old_version='2.12.4-v2')
    def test_scan_results_are_not_accepted_until_category_4_exists(self):
        with self.assertRaises(ValueError):u.compare(BASE,new(),'1.0.0','1.1.0',old_scan={'matches':[]},new_scan={'matches':[]})
        self.assertIn('Vulnerability comparison: not run',run(new())['report'])

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
class ReusableWorkflow(unittest.TestCase):
    """Shape that callers and the ruleset depend on; the shell itself is verified on pilot PRs (#89 Testing Decisions)."""
    def setUp(self):
        path=pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/woow-addon-upgrade-check.yml'
        self.text=path.read_text(encoding='utf-8');self.wf=yaml.safe_load(self.text)
    def test_single_compare_job_reports_on_every_event(self):
        # The required check is "Upgrade comparison / compare": caller job name / this job's name.
        self.assertIn('workflow_call',self.wf['on']);self.assertEqual(list(self.wf['jobs']),['compare'])
        job=self.wf['jobs']['compare'];self.assertEqual(job['name'],'compare');self.assertNotIn('if',job)
        self.assertEqual(self.wf['permissions'],{'contents':'read'})
    def test_tests_run_before_the_comparison_with_store_tooling(self):
        steps=self.wf['jobs']['compare']['steps'];runs=[s.get('run','') for s in steps]
        tooling=[s for s in steps if s.get('with',{}).get('repository')=='WOOWTECH/Woow_HA_App_Store'][0]['with']
        self.assertEqual((tooling['ref'],tooling['persist-credentials']),('${{ inputs.tooling_ref }}',False))
        test=next(i for i,r in enumerate(runs) if 'test_upgrade_check.py' in r);compare=next(i for i,r in enumerate(runs) if 'upgrade_check.py compare' in r)
        self.assertLess(test,compare)
    def test_no_secrets_beyond_the_job_token(self):
        self.assertNotIn('secrets.',self.text)

if __name__=='__main__':unittest.main()
