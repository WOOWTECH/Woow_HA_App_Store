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
    def test_consumer_downgrade_preserves_files(self):
        raw=archive();e=entry(raw)
        class GH:
            def outbox(self,repo):return {'components':{'test':e}}
        registry={'providers':{'WOOWTECH/test':{'components':[{'id':'test','source_path':'pkg','config_file':'config.yaml','store_path':'test'}]}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'validate_entry'):
            target=pathlib.Path(tmp)/'test';target.mkdir();(target/'config.yaml').write_text('slug: test\nversion: 2.0.0\n')
            report,catalog=s.consume(GH(),registry,tmp)
            self.assertEqual(report[0]['state'],'blocked');self.assertEqual(catalog['components'],{});self.assertIn('2.0.0',(target/'config.yaml').read_text())
    def test_consumer_idempotent(self):
        raw=archive();e=entry(raw)
        class GH:
            def outbox(self,repo):return {'components':{'test':e}}
        registry={'providers':{'WOOWTECH/test':{'components':[{'id':'test','source_path':'pkg','config_file':'config.yaml','store_path':'test'}]}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'validate_entry'),patch.object(s,'source_archive',return_value=raw),patch.object(s,'image_ready',return_value=e['images']['amd64']):
            r,first=s.consume(GH(),registry,tmp);r,second=s.consume(GH(),registry,tmp)
            self.assertEqual(first,second);self.assertEqual(r[0]['state'],'unchanged')
    def test_consumer_failed_policy_keeps_previous(self):
        raw=archive();e=entry(raw)
        class GH:
            def outbox(self,repo):return {'components':{'test':e}}
        registry={'providers':{'WOOWTECH/test':{'components':[{'id':'test','source_path':'pkg','config_file':'config.yaml','store_path':'test'}]}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'validate_entry'),patch.object(s,'source_archive',return_value=raw),patch.object(s,'image_ready',return_value=e['images']['amd64']):
            root=pathlib.Path(tmp);target=root/'test';target.mkdir();(target/'config.yaml').write_text('slug: test\nversion: 0.9.0\n')
            policy=root/'.github/scripts/sidebar_titles.py';policy.parent.mkdir(parents=True);policy.write_text('TITLES={"test":"Test"}\ndef normalize(*args):raise ValueError("broken policy")\n')
            report,catalog=s.consume(GH(),registry,tmp);self.assertEqual(report[0]['state'],'blocked');self.assertIn('0.9.0',(target/'config.yaml').read_text());self.assertEqual(catalog['components'],{})

if __name__=='__main__':unittest.main()
