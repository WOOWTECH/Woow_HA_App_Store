import io,json,pathlib,tarfile,tempfile,unittest
from unittest.mock import patch
import addon_sync as s
import download_addon as d
import rebrand_sync as mirror

def archive(items=None,kind=None):
    b=io.BytesIO()
    with tarfile.open(fileobj=b,mode='w:gz') as t:
        for name,body in (items or {'repo/pkg/config.yaml':b'name: Test\nslug: test\nversion: 1.0.0\narch: [amd64]\nimage: ghcr.io/example/test\nboot: auto\n'}).items():
            m=tarfile.TarInfo(name);m.size=len(body);m.mode=0o755
            if kind:m.type=kind;m.linkname='/outside'
            t.addfile(m,io.BytesIO(body))
    return b.getvalue()

def entry(raw):
    files=s.context_files(raw,'pkg');cfg=s.config_from_files(files,'config.yaml')
    return {'id':'test','name':'Test','repository':'WOOWTECH/test','source_sha':'a'*40,'source_path':'pkg','config_file':'config.yaml','config_sha256':s.digest(files['config.yaml'][0]),'config':cfg,'archive_sha256':s.digest(raw),'architectures':['amd64'],'images':{'amd64':{'reference':'ghcr.io/example/test:1.0.0','digest':'sha256:'+'a'*64}},'version':'1.0.0','channel':'stable','context_fingerprint':'fp','publisher_run_id':'123'}

class Tests(unittest.TestCase):
    def test_rebrand_only_download_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);store=root/'store';target=root/'private';(store/'.addon-sync').mkdir(parents=True);target.mkdir()
            (target/'README.md').write_text('private original')
            catalog={'schema':1,'components':{},'catalog_id':s.digest(s.canonical({}))}
            (store/'.addon-sync/catalog.json').write_text(json.dumps(catalog));(store/'.addon-sync/download_addon.py').write_text('# public downloader\n')
            state=mirror.render(store,target,'a'*40)
            self.assertEqual((target/'README.md').read_text(),'private original');self.assertEqual(state['component_count'],0)
            self.assertEqual({p.name for p in (target/'release/addons').iterdir()},{'catalog.json','download_addon.py','README.md','sync-state.json'})
    def test_rebrand_rejects_bad_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/'.addon-sync').mkdir();(root/'.addon-sync/catalog.json').write_text(json.dumps({'schema':1,'components':{},'catalog_id':'wrong'}))
            with self.assertRaises(ValueError):mirror.render(root,root/'private','a'*40)
    def test_rebrand_rejects_symlink_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/'.addon-sync').mkdir();(root/'.addon-sync/catalog.json').write_text(json.dumps({'schema':1,'components':{},'catalog_id':s.digest(s.canonical({}))}))
            (root/'outside').mkdir();(root/'private').mkdir();(root/'private/release').symlink_to(root/'outside')
            with self.assertRaises(ValueError):mirror.render(root,root/'private','a'*40)
    def test_root_api_has_no_trailing_slash(self):
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(s.urllib.request,'urlopen',return_value=Response(b'{}')) as request:
            s.GitHub('').api('WOOWTECH/test','')
            self.assertEqual(request.call_args[0][0].full_url,'https://api.github.com/repos/WOOWTECH/test')
    def test_source_copy_present(self):
        self.assertTrue(s.source_build_supported({'Dockerfile':(b'FROM test\nCOPY rootfs /\n',0o644),'rootfs/etc/file':(b'x',0o644)}))
    def test_source_copy_missing(self):
        self.assertFalse(s.source_build_supported({'Dockerfile':(b'FROM test\nCOPY pyproject.toml /\n',0o644)}))
    def test_source_copy_other_stage(self):
        self.assertTrue(s.source_build_supported({'Dockerfile':(b'FROM test\nCOPY --from=builder /output /\n',0o644)}))
    def test_source_copy_variable_not_certified(self):
        self.assertFalse(s.source_build_supported({'Dockerfile':(b'FROM test\nCOPY $SOURCE /\n',0o644)}))
    def test_pi_tag_reuse_rejects_changed_runtime(self):
        class GH:
            def fingerprint(self,repo,sha,*args,**kwargs):return sha
        with patch.object(s,'image_ready',return_value={'source_revision':'a'*40}),self.assertRaises(s.Blocked):s.pi_image_reuse(GH(),'b'*40,'amd64','0.14.3')
    def test_pi_tag_reuse_same_runtime(self):
        class GH:
            def fingerprint(self,*args,**kwargs):return 'same'
        with patch.object(s,'image_ready',return_value={'source_revision':'a'*40}):self.assertTrue(s.pi_image_reuse(GH(),'b'*40,'amd64','0.14.3'))
    def test_pi_tag_missing_provenance_refuses_overwrite(self):
        with patch.object(s,'image_ready',return_value={'source_revision':None}),self.assertRaises(s.Blocked):s.pi_image_reuse(None,'b'*40,'amd64','0.14.3')
    def test_semantic_version(self):
        self.assertTrue(s.version_not_older('1.10.0','1.9.0'));self.assertFalse(s.version_not_older('1.9.0','1.10.0'))
    def test_suffix_rejected(self):
        with self.assertRaises(s.Blocked):s.version_not_older('2.12.4-v2','2.12.4-v3')
    def test_pep_prerelease(self):self.assertFalse(s.version_not_older('1.2.0b1','1.2.0'))
    def test_path_traversal(self):
        for p in ['../x','/etc/passwd','x/../../y','x\\y']:
            with self.subTest(p=p),self.assertRaises(s.Blocked):s.safe_path(p)
    def test_foreign_repository(self):
        with self.assertRaises(s.Blocked):s.safe_repo('attacker/repo')
    def test_archive_filters_ci(self):
        raw=archive({'repo/.github/workflows/a':b'bad','repo/repository.yaml':b'bad','repo/config.yaml':b'ok'})
        self.assertEqual(list(s.context_files(raw,'.')),['config.yaml'])
    def test_archive_traversal(self):
        with self.assertRaises(s.Blocked):s.context_files(archive({'repo/pkg/../../evil':b'x'}),'pkg')
    def test_archive_links(self):
        for kind in [tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.FIFOTYPE]:
            with self.subTest(kind=kind),self.assertRaises(s.Blocked):s.context_files(archive({'repo/pkg/link':b''},kind),'pkg')
    def test_archive_multi_roots(self):
        with self.assertRaises(s.Blocked):s.context_files(archive({'repo/pkg/a':b'a','other/pkg/b':b'b'}),'pkg')
    def test_config_invalid(self):
        with self.assertRaises(s.Blocked):s.config_from_files({'config.yaml':(b'slug: test\n',0o644)},'config.yaml')
    def test_config_needs_build_method(self):
        with self.assertRaises(s.Blocked):s.config_from_files({'config.yaml':(b'name: Test\nslug: test\nversion: 1.0.0\narch: [amd64]\n',0o644)},'config.yaml')
    def test_downloader_safe_default(self):
        raw=archive();e=entry(raw)
        with tempfile.TemporaryDirectory() as tmp:
            out=d.stage(e,tmp,'amd64',raw=raw);cfg=json.loads((out/'config.yaml').read_text())
            self.assertEqual(cfg['boot'],'manual');self.assertNotIn('image',cfg)
            self.assertIn('@sha256:',(out/'Dockerfile').read_text());self.assertTrue((out/'.woow-source-lock.json').exists())
    def test_downloader_refuses_existing(self):
        raw=archive();e=entry(raw)
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp)/'test').mkdir();(pathlib.Path(tmp)/'test'/'data').write_text('keep')
            with self.assertRaises(FileExistsError):d.stage(e,tmp,'amd64',raw=raw)
            self.assertEqual((pathlib.Path(tmp)/'test'/'data').read_text(),'keep')
    def test_downloader_wrong_arch(self):
        raw=archive()
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):d.stage(entry(raw),tmp,'aarch64',raw=raw)
    def test_downloader_wrong_hash(self):
        raw=archive()
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):d.stage(entry(raw),tmp,'amd64',raw=raw+b'corrupt')
    def test_downloader_no_source_dockerfile(self):
        raw=archive()
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):d.stage(entry(raw),tmp,'amd64',source_build=True,raw=raw)
    def test_downloader_preserves_original_dockerfile(self):
        raw=archive({'repo/pkg/config.yaml':b'name: Test\nslug: test\nversion: 1.0.0\narch: [amd64]\nimage: ghcr.io/example/test\n','repo/pkg/Dockerfile':b'FROM original:1\n'})
        with tempfile.TemporaryDirectory() as tmp:
            out=d.stage(entry(raw),tmp,'amd64',raw=raw);self.assertEqual((out/'Dockerfile.source').read_text(),'FROM original:1\n')
    def test_notification_needs_receipt(self):
        e=entry(archive());e['publisher_run_id']=None
        with self.assertRaises(s.Blocked):s.validate_entry(None,'WOOWTECH/test',{'id':'test','source_path':'pkg','config_file':'config.yaml'},e)
    def test_notification_identity(self):
        e=entry(archive());e['repository']='attacker/repo'
        with self.assertRaises(s.Blocked):s.validate_entry(None,'WOOWTECH/test',{'id':'test','source_path':'pkg','config_file':'config.yaml'},e)
    def test_notification_incomplete_workflow(self):
        class GH:
            def api(self,*args):return {'conclusion':None,'status':'in_progress'}
        with self.assertRaises(s.Blocked):s.validate_entry(GH(),'WOOWTECH/test',{'id':'test','source_path':'pkg','config_file':'config.yaml'},entry(archive()))
    def test_notification_wrong_workflow(self):
        class GH:
            def api(self,*args):return {'conclusion':'success','status':'completed','path':'.github/workflows/other.yml'}
        with self.assertRaises(s.Blocked):s.validate_entry(GH(),'WOOWTECH/test',{'id':'test','source_path':'pkg','config_file':'config.yaml'},entry(archive()))
    def test_notification_wrong_branch(self):
        class GH:
            def api(self,*args):return {'conclusion':'success','status':'completed','path':'.github/workflows/woow-addon-sync.yml','event':'workflow_dispatch','head_repository':{'full_name':'WOOWTECH/test'},'head_branch':'topic'}
        with self.assertRaisesRegex(s.Blocked,'default branch'):s.validate_entry(GH(),'WOOWTECH/test',{'id':'test','source_path':'pkg','config_file':'config.yaml'},entry(archive()),'main')
    def policy_gh(self,releases=(),tags=None,compare='ahead',runs=None):
        class GH:
            calls=[]
            def api(self,repo,path):
                self.calls.append(path)
                if path.startswith('releases'):return list(releases)
                if path.startswith('commits/'):return {'sha':(tags or {})[path.split('/',1)[1]]}
                if path.startswith('compare/'):return {'status':compare}
                if '/runs' in path:return {'workflow_runs':runs or []}
                raise AssertionError(path)
            def fingerprint(self,*args,**kwargs):return 'material'
        return GH()
    def test_release_policy_accepts_stable_release_commit(self):
        gh=self.policy_gh([{'tag_name':'v1.1','prerelease':True},{'tag_name':'v1.0'}],{'v1.1':'b'*40,'v1.0':'a'*40})
        s.enforce_source_policy(gh,'WOOWTECH/test',{'ref_policy':'release','required_workflows':[]},{'source_path':'pkg'},entry(archive()))
        self.assertNotIn('commits/v1.1',gh.calls)
    def test_release_policy_rejects_unreleased_or_prerelease_commit(self):
        for releases in [[{'tag_name':'v1.0'}],[{'tag_name':'v1.1','prerelease':True}],[{'tag_name':'v1.2','draft':True}],[]]:
            with self.subTest(releases=releases),self.assertRaisesRegex(s.Blocked,'stable Release'):
                s.enforce_source_policy(self.policy_gh(releases,{'v1.0':'b'*40,'v1.1':'a'*40,'v1.2':'a'*40}),'WOOWTECH/test',{'ref_policy':'release'},{'source_path':'pkg'},entry(archive()))
    def test_main_policy_rejects_snapshot_off_default_branch(self):
        for status in ['diverged','behind']:
            with self.subTest(status=status),self.assertRaisesRegex(s.Blocked,'default branch'):
                s.enforce_source_policy(self.policy_gh(compare=status),'WOOWTECH/test',{'ref_policy':'main','default_branch':'main'},{'source_path':'pkg'},entry(archive()))
    def test_store_registry_ci_is_enforced(self):
        failed=[{'id':2,'head_sha':'a'*40,'event':'push','status':'completed','conclusion':'failure'}]
        with self.assertRaisesRegex(s.Blocked,'CI failed'):
            s.enforce_source_policy(self.policy_gh(runs=failed),'WOOWTECH/test',{'default_branch':'main','required_workflows':['.github/workflows/ci.yml']},{'source_path':'pkg'},entry(archive()))
        running=[{'id':3,'head_sha':'a'*40,'event':'push','status':'in_progress','conclusion':None}]
        with self.assertRaises(s.Deferred):
            s.enforce_source_policy(self.policy_gh(runs=running),'WOOWTECH/test',{'default_branch':'main','required_workflows':['.github/workflows/ci.yml']},{'source_path':'pkg'},entry(archive()))
    def test_consumer_ci_running_waits_and_keeps_previous(self):
        raw=archive();e=entry(raw)
        class GH:
            def outbox(self,repo):return {'components':{'test':e}}
        registry={'providers':{'WOOWTECH/test':{'components':[{'id':'test','source_path':'pkg','config_file':'config.yaml','store_path':'test'}]}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'validate_entry'),patch.object(s,'enforce_source_policy',side_effect=s.Deferred('CI still running: ci.yml')):
            target=pathlib.Path(tmp)/'test';target.mkdir();(target/'config.yaml').write_text('slug: test\nversion: 0.9.0\n')
            report,catalog=s.consume(GH(),registry,tmp)
            self.assertEqual(report[0]['state'],'waiting');self.assertIn('0.9.0',(target/'config.yaml').read_text());self.assertEqual(catalog['components'],{})
    def test_summary_annotations_cannot_inject_commands(self):
        out=io.StringIO()
        with patch('sys.stdout',out),patch.dict(s.os.environ,{},clear=False):
            s.os.environ.pop('GITHUB_STEP_SUMMARY',None)
            s.summary([{'id':'test','state':'blocked','reason':'bad\n::error::injected'},{'id':'ok','state':'unchanged'}])
        warnings=[l for l in out.getvalue().splitlines() if l.startswith('::')]
        self.assertEqual(len(warnings),1);self.assertIn('%0A',warnings[0]);self.assertNotIn('ok:',warnings[0])
    def test_rebrand_state_idempotent_for_unrelated_store_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);store=root/'store';target=root/'private';(store/'.addon-sync').mkdir(parents=True);target.mkdir()
            (store/'.addon-sync/catalog.json').write_text(json.dumps({'schema':1,'components':{},'catalog_id':s.digest(s.canonical({}))}));(store/'.addon-sync/download_addon.py').write_text('# v1\n')
            self.assertEqual(mirror.render(store,target,'a'*40)['app_store_commit'],'a'*40)
            self.assertEqual(mirror.render(store,target,'b'*40)['app_store_commit'],'a'*40)
            (store/'.addon-sync/download_addon.py').write_text('# v2\n')
            self.assertEqual(mirror.render(store,target,'c'*40)['app_store_commit'],'c'*40)
    def test_consumer_downgrade_preserves_files(self):
        raw=archive();e=entry(raw)
        class GH:
            def outbox(self,repo):return {'components':{'test':e}}
        registry={'providers':{'WOOWTECH/test':{'components':[{'id':'test','source_path':'pkg','config_file':'config.yaml','store_path':'test'}]}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'validate_entry'),patch.object(s,'enforce_source_policy'):
            target=pathlib.Path(tmp)/'test';target.mkdir();(target/'config.yaml').write_text('slug: test\nversion: 2.0.0\n')
            report,catalog=s.consume(GH(),registry,tmp)
            self.assertEqual(report[0]['state'],'blocked');self.assertEqual(catalog['components'],{});self.assertIn('2.0.0',(target/'config.yaml').read_text())
    def test_consumer_idempotent(self):
        raw=archive();e=entry(raw)
        class GH:
            def outbox(self,repo):return {'components':{'test':e}}
        registry={'providers':{'WOOWTECH/test':{'components':[{'id':'test','source_path':'pkg','config_file':'config.yaml','store_path':'test'}]}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'validate_entry'),patch.object(s,'enforce_source_policy'),patch.object(s,'source_archive',return_value=raw),patch.object(s,'image_ready',return_value=e['images']['amd64']):
            r,first=s.consume(GH(),registry,tmp);r,second=s.consume(GH(),registry,tmp)
            self.assertEqual(first,second);self.assertEqual(r[0]['state'],'unchanged')
    def test_consumer_failed_policy_keeps_previous(self):
        raw=archive();e=entry(raw)
        class GH:
            def outbox(self,repo):return {'components':{'test':e}}
        registry={'providers':{'WOOWTECH/test':{'components':[{'id':'test','source_path':'pkg','config_file':'config.yaml','store_path':'test'}]}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'validate_entry'),patch.object(s,'enforce_source_policy'),patch.object(s,'source_archive',return_value=raw),patch.object(s,'image_ready',return_value=e['images']['amd64']):
            root=pathlib.Path(tmp);target=root/'test';target.mkdir();(target/'config.yaml').write_text('slug: test\nversion: 0.9.0\n')
            policy=root/'.github/scripts/sidebar_titles.py';policy.parent.mkdir(parents=True);policy.write_text('TITLES={"test":"Test"}\ndef normalize(*args):raise ValueError("broken policy")\n')
            report,catalog=s.consume(GH(),registry,tmp);self.assertEqual(report[0]['state'],'blocked');self.assertIn('0.9.0',(target/'config.yaml').read_text());self.assertEqual(catalog['components'],{})
    def publish_gh(self,runs=()):
        class GH:
            def head(self,repo):return 'main','b'*40
            def api(self,repo,path):
                if path=='releases/latest':return {'tag_name':'v1.0.0'}
                if path=='commits/v1.0.0':return {'sha':'a'*40}
                if '/runs' in path:return {'workflow_runs':[r for r in runs if 'head_sha=' not in path or r['head_sha'] in path]}
                raise AssertionError(path)
            def outbox(self,repo):return {'schema':1,'repository':repo,'components':{}}
            def fingerprint(self,repo,sha,*args,**kwargs):return 'fp-'+sha
        return GH()
    def test_publish_follows_the_given_registry_policy(self):
        raw=archive();component={'id':'test','source_path':'pkg','config_file':'config.yaml'}
        with patch.object(s,'source_archive',return_value=raw),patch.object(s,'image_ready',return_value={'digest':'sha256:'+'a'*64}):
            for policy,sha in [('main','b'*40),('release','a'*40)]:
                with self.subTest(policy=policy):
                    registry={'providers':{'WOOWTECH/test':{'ref_policy':policy,'components':[component]}}}
                    report,outbox=s.publish(self.publish_gh(),registry,'WOOWTECH/test')
                    self.assertEqual(report[0]['state'],'ready');self.assertEqual(outbox['components']['test']['source_sha'],sha)
            registry={'providers':{'WOOWTECH/test':{'ref_policy':'main','required_workflows':['.github/workflows/ci.yml'],'components':[component]}}}
            failed=[{'id':1,'head_sha':'b'*40,'event':'push','status':'completed','conclusion':'failure'}]
            report,outbox=s.publish(self.publish_gh(failed),registry,'WOOWTECH/test')
            self.assertEqual(report[0]['state'],'blocked');self.assertEqual(outbox['components'],{})
    def test_publish_moves_unchanged_context_to_the_release_commit(self):
        # Switching a source to ref_policy release must not leave a main snapshot in the outbox just because the files match.
        raw=archive();component={'id':'test','source_path':'pkg','config_file':'config.yaml'}
        gh=self.publish_gh();gh.fingerprint=lambda *args,**kwargs:'same'
        gh.outbox=lambda repo:{'schema':1,'repository':repo,'components':{'test':{**entry(raw),'source_sha':'b'*40,'context_fingerprint':'same','material_fingerprint':'same'}}}
        with patch.object(s,'source_archive',return_value=raw),patch.object(s,'image_ready',return_value={'digest':'sha256:'+'a'*64}):
            report,outbox=s.publish(gh,{'providers':{'WOOWTECH/test':{'ref_policy':'release','components':[component]}}},'WOOWTECH/test')
            self.assertEqual(report[0]['state'],'ready');self.assertEqual(outbox['components']['test']['source_sha'],'a'*40)
            report,outbox=s.publish(gh,{'providers':{'WOOWTECH/test':{'ref_policy':'main','components':[component]}}},'WOOWTECH/test')
            self.assertEqual(report[0]['state'],'unchanged')
    def test_publisher_workflow_reads_current_store_registry(self):
        # Source repos call this workflow at @main, so a registry change reaches every publisher without touching a source repo.
        path=pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/woow-addon-publish.yml'
        workflow=s.yaml.safe_load(path.read_text(encoding='utf-8'))
        self.assertIn('workflow_call',workflow.get('on',workflow.get(True)))
        (job,)=workflow['jobs'].values()
        self.assertEqual(job['permissions'],{'contents':'write','actions':'read'})
        steps=job['steps'];tooling=next(x for x in steps if x.get('with',{}).get('repository')=='WOOWTECH/Woow_HA_App_Store')
        self.assertEqual(tooling['with']['ref'],'main');self.assertIs(tooling['with']['persist-credentials'],False)
        root=tooling['with']['path'];commands='\n'.join(x.get('run','') for x in steps)
        self.assertIn('addon_sync.py publish --registry '+root+'/.addon-sync/registry.json --apply',commands)
        self.assertNotIn('secrets.',path.read_text(encoding='utf-8').replace('secrets.GITHUB_TOKEN',''))
        # The caller's own notify job dispatches to the Store; it reads this output, never a secret passed in here.
        publish=next(x for x in steps if 'addon_sync.py publish' in x.get('run',''))
        self.assertEqual(job['outputs'],{'ready':'${{ steps.'+publish['id']+'.outputs.ready }}'})
        self.assertEqual(workflow['on']['workflow_call']['outputs']['ready']['value'],'${{ jobs.publish.outputs.ready }}')
    def test_publish_reports_ready_only_for_a_new_notification(self):
        for states,expected in [(['ready','unchanged'],'true'),(['unchanged','waiting','blocked','excluded'],'false'),([],'false')]:
            with self.subTest(states=states),tempfile.TemporaryDirectory() as t:
                out=pathlib.Path(t)/'out';registry=pathlib.Path(t)/'registry.json';registry.write_text('{}')
                with patch.object(s,'publish',return_value=([{'id':str(i),'state':x,'reason':'r'} for i,x in enumerate(states)],{})),patch.object(s,'GitHub'),\
                    patch.dict('os.environ',{'GITHUB_OUTPUT':str(out)}),patch('sys.argv',['addon_sync.py','publish','--registry',str(registry)]),patch('builtins.print'):
                    try:s.main()
                    except SystemExit:pass
                self.assertEqual(out.read_text(),'ready='+expected+'\n')
    def test_store_sync_pushes_main_only_with_the_environment_deploy_key(self):
        # Store main requires a reviewed PR; only this deploy key bypasses it, and only main runs can read it from store-sync.
        path=pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/sync-upstreams.yml'
        workflow=s.yaml.safe_load(path.read_text(encoding='utf-8'))
        self.assertEqual(workflow['permissions'],{'contents':'read','actions':'read'})
        (job,)=workflow['jobs'].values()
        self.assertEqual(job['environment'],'store-sync');self.assertNotIn('permissions',job)
        checkout=next(x for x in job['steps'] if x.get('uses','').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['ssh-key'],'${{ secrets.STORE_SYNC_DEPLOY_KEY }}')
    def release_gh(self,configs,released=(),tags=None,compare='ahead'):
        # tags: name -> (object type, commit); an annotated tag object points at the commit.
        tags=tags or {}
        class GH:
            def __init__(self):self.created=[]
            def head(self,repo):return 'main','c'*40
            def content(self,repo,path,ref):
                assert ref=='a'*40
                if path not in configs:raise s.Blocked('GitHub '+repo+'/contents HTTP 404')
                return configs[path].encode()
            def api(self,repo,path,data=None,method=None):
                if data is not None:
                    self.created.append(data);return {'tag_name':data['tag_name']}
                if path.startswith('compare/'):return {'status':compare}
                if path.startswith('releases/tags/'):
                    if path.split('/',2)[2] in released:return {'tag_name':path.split('/',2)[2]}
                    raise s.Blocked('GitHub '+repo+'/'+path+' HTTP 404')
                if path.startswith('git/ref/tags/'):
                    name=path.split('/',3)[3]
                    if name not in tags:raise s.Blocked('GitHub '+repo+'/'+path+' HTTP 404')
                    kind,commit=tags[name]
                    return {'object':{'type':kind,'sha':commit if kind=='commit' else 't'*40}}
                if path=='git/tags/'+'t'*40:return {'object':{'type':'commit','sha':next(c for k,c in tags.values() if k=='tag')}}
                raise AssertionError(path)
        return GH()
    def release_component(self,cid,path,**extra):
        return {'id':cid,'source_path':path,'config_file':'config.yaml','store_path':cid,'channel':'stable','enabled':True,**extra}
    def single(self):return {'providers':{'WOOWTECH/test':{'components':[self.release_component('test','.')]}}}
    def test_release_tags_a_single_addon_with_its_version(self):
        gh=self.release_gh({'config.yaml':'name: Test\nslug: test\nversion: 1.2.0\n'})
        report=s.release(gh,self.single(),'WOOWTECH/test','a'*40,apply=True)
        self.assertEqual(report,[{'id':'test','state':'released','tag':'v1.2.0','version':'1.2.0'}])
        (created,)=gh.created
        self.assertEqual((created['tag_name'],created['target_commitish'],created['make_latest']),('v1.2.0','a'*40,'true'))
        self.assertFalse(created.get('prerelease') or created.get('draft'))
    def test_release_leaves_an_already_released_version_alone(self):
        gh=self.release_gh({'config.yaml':'name: Test\nslug: test\nversion: 1.2.0\n'},released={'v1.2.0'})
        report=s.release(gh,self.single(),'WOOWTECH/test','a'*40,apply=True)
        self.assertEqual(report[0]['state'],'already-released');self.assertEqual(gh.created,[])
    def test_release_tags_each_bumped_addon_of_a_multi_addon_repository(self):
        # Addons with independent versions: one Release per bumped stable addon, all on the same commit.
        gh=self.release_gh({'one/config.yaml':'name: One\nslug: one\nversion: 1.0.0\n','two/config.yaml':'name: Two\nslug: two\nversion: 2.1.0\n'},released={'one-v1.0.0'})
        components=[self.release_component('one','one'),self.release_component('two','two'),
            self.release_component('beta','beta',channel='prerelease'),self.release_component('off','off',enabled=False,reason='retired')]
        report=s.release(gh,{'providers':{'WOOWTECH/test':{'components':components}}},'WOOWTECH/test','a'*40,apply=True)
        self.assertEqual([(r['id'],r['state'],r.get('tag')) for r in report],
            [('one','already-released','one-v1.0.0'),('two','released','two-v2.1.0'),('beta','excluded',None),('off','excluded',None)])
        self.assertEqual([c['tag_name'] for c in gh.created],['two-v2.1.0'])
    def test_release_dry_run_creates_nothing(self):
        gh=self.release_gh({'config.yaml':'name: Test\nslug: test\nversion: 1.2.0\n'})
        report=s.release(gh,self.single(),'WOOWTECH/test','a'*40)
        self.assertEqual(report[0]['state'],'would-release');self.assertEqual(gh.created,[])
    def test_release_refuses_a_commit_off_the_default_branch(self):
        gh=self.release_gh({'config.yaml':'name: Test\nslug: test\nversion: 1.2.0\n'},compare='diverged')
        with self.assertRaisesRegex(s.Blocked,'default branch'):s.release(gh,self.single(),'WOOWTECH/test','a'*40,apply=True)
        self.assertEqual(gh.created,[])
    def test_release_publishes_an_existing_tag_on_the_same_commit(self):
        # A maintainer-pushed tag (OpenDesign publishes its images from the tag run) gets its Release.
        for kind in ['commit','tag']:
            with self.subTest(kind):
                gh=self.release_gh({'config.yaml':'name: Test\nslug: test\nversion: 1.2.0\n'},tags={'v1.2.0':(kind,'a'*40)})
                report=s.release(gh,self.single(),'WOOWTECH/test','a'*40,apply=True)
                self.assertEqual(report[0]['state'],'released');self.assertEqual([c['tag_name'] for c in gh.created],['v1.2.0'])
    def test_release_blocks_a_foreign_slug_or_a_tag_on_another_commit(self):
        for name,gh,reason in [('foreign slug',self.release_gh({'config.yaml':'name: Other\nslug: other\nversion: 1.2.0\n'}),'slug'),
                ('tag elsewhere',self.release_gh({'config.yaml':'name: Test\nslug: test\nversion: 1.2.0\n'},tags={'v1.2.0':('commit','d'*40)}),'another commit'),
                ('annotated tag elsewhere',self.release_gh({'config.yaml':'name: Test\nslug: test\nversion: 1.2.0\n'},tags={'v1.2.0':('tag','d'*40)}),'another commit')]:
            with self.subTest(name):
                report=s.release(gh,self.single(),'WOOWTECH/test','a'*40,apply=True)
                self.assertEqual(report[0]['state'],'blocked');self.assertIn(reason,report[0]['reason']);self.assertEqual(gh.created,[])
    def test_release_workflow_reads_current_store_registry(self):
        # Source repos call it at @main after their own CI; it releases the caller's commit with the caller's token.
        path=pathlib.Path(__file__).resolve().parent.parent/'.github/workflows/woow-addon-release.yml'
        workflow=s.yaml.safe_load(path.read_text(encoding='utf-8'))
        self.assertIn('workflow_call',workflow.get('on',workflow.get(True)))
        (job,)=workflow['jobs'].values()
        self.assertEqual(job['permissions'],{'contents':'write'})
        steps=job['steps'];tooling=next(x for x in steps if x.get('with',{}).get('repository')=='WOOWTECH/Woow_HA_App_Store')
        self.assertEqual(tooling['with']['ref'],'main');self.assertIs(tooling['with']['persist-credentials'],False)
        commands='\n'.join(x.get('run','') for x in steps)
        self.assertIn('addon_sync.py release --registry '+tooling['with']['path']+'/.addon-sync/registry.json',commands)
        self.assertIn('--apply',commands)
        self.assertNotIn('secrets.',path.read_text(encoding='utf-8').replace('secrets.GITHUB_TOKEN',''))

    def test_every_provider_is_gated_by_branch_rules_or_exempt_with_a_reason(self):
        # ADR-0005: a gated provider's release is a merged PR that passed these checks; branch_rules.py checks them daily.
        registry=json.loads((pathlib.Path(__file__).resolve().parent/'registry.json').read_text(encoding='utf-8'))
        for repo,provider in registry['providers'].items():
            with self.subTest(repo):
                rules=provider['branch_rules']
                if 'exempt' in rules:
                    self.assertEqual(set(rules),{'exempt'});self.assertTrue(rules['exempt'].strip())
                else:
                    self.assertEqual(set(rules),{'required_checks'})
                    self.assertTrue(rules['required_checks']);self.assertTrue(all(isinstance(c,str) and c for c in rules['required_checks']))
                    self.assertTrue(provider['required_workflows'])

if __name__=='__main__':unittest.main()
