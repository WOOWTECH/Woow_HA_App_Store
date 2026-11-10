import ast
import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT=Path(__file__).parents[1]
SID='original_codex_0123456789'
NID='01234567-89ab-4cde-8f01-23456789abcd'

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

claude=load('codex_test_common','claude_strict_resume.py')
with patch.dict(sys.modules,{'omnigent.runner.native.woow_claude_strict_resume':claude}):
    native=load('codex_test_native','codex_strict_resume.py')
patcher=load('codex_test_patcher','patch-claude-strict-resume.py')
bootstrap=load('codex_test_bootstrap','native_strict_bootstrap.py')


def extract(source,names,ns):
    tree=ast.parse(source);nodes=[]
    for name in names:
        found=[x for x in ast.walk(tree) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and x.name==name]
        if len(found)!=1:raise AssertionError('PINNED_SOURCE_CHANGED:'+name)
        nodes.append(found[0])
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),'actual-pinned-0.16','exec'),ns)


class Fixture:
    def setup_fixture(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'bridges';self.root.mkdir(mode=0o700)
        self.bridge=self.root/hashlib.sha256(SID.encode()).hexdigest()[:32]
        self.home=self.bridge/'codex-home';self.home.mkdir(parents=True,mode=0o700)
        self.workspace=self.base/'workspace';self.workspace.mkdir()
        self.authority=self.base/'authority';self.authority.mkdir();(self.authority/'config.toml').write_text('model="existing-model"\n')
        self.path=self.home/'sessions/2026/11/10'/('rollout-original-'+NID+'.jsonl');self.path.parent.mkdir(parents=True)
        self.raw=('\n'.join(json.dumps(x) for x in [
            {'type':'session_meta','payload':{'id':NID,'cwd':str(self.workspace),'timestamp':'2026-11-10T00:00:00Z','cli_version':'0.162.1','model_provider':'openai'}},
            {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'native-only original history'}]}}
        ])+'\n').encode();self.path.write_bytes(self.raw);self.path.chmod(0o600)
        self.info=dict(id=SID,harness='codex-native',permission_level=4,status='idle',workspace=str(self.workspace),external_session_id=NID,labels={})
        self.req=dict(engine='codex',sessionId=SID,nativeSessionId=NID,workspace=str(self.workspace),originalBytes=len(self.raw),originalSHA256=hashlib.sha256(self.raw).hexdigest())
        self.busy=False;self.epoch=2
        self.registry=types.SimpleNamespace(session_turn_is_active=lambda _:self.busy,session_activity_epoch=lambda _:self.epoch)
        self.ctx=types.SimpleNamespace(session_id=SID,resource_registry=self.registry)
        self.config=types.SimpleNamespace(external_session_id=NID,workspace=self.workspace,fork_source_id=None,fork_source_external_id=None)
        self.orch=types.SimpleNamespace(_AUTO_CODEX_APP_SERVERS={},_AUTO_FORWARDER_TASKS={})
        self.emptyproc=self.base/'emptyproc';self.emptyproc.mkdir()
        actual=native.assert_no_writer
        self.patches=[patch.object(native,'assert_no_writer',side_effect=lambda plan,**kw:actual(plan,proc_root=kw.get('proc_root',self.emptyproc))),
          patch.dict(sys.modules,{'omnigent.harnesses.codex_native':types.SimpleNamespace(bridge=object()),
            'omnigent.runner.native':types.SimpleNamespace(orchestration=self.orch),
            'omnigent.runner.native.woow_claude_strict_resume':claude})]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def plan(self):return native.prepare_plan(self.ctx,self.req,self.info,bridge_root=self.root,authority_root=self.authority)
    def expect(self,code,fn):
        with self.assertRaisesRegex(claude.StrictResumeError,'^'+code+'$'):fn()


class Validation(Fixture,unittest.TestCase):
    def setUp(self):self.setup_fixture()
    def test_exact_local_native_bytes_and_authority_unchanged(self):
        p=self.plan();p.before_prepare(self.config);self.assertEqual(p.resume_existing(self.config,self.home),self.path)
        self.assertEqual(self.path.read_bytes(),self.raw);self.assertEqual((self.authority/'config.toml').read_text(),'model="existing-model"\n')
    def test_wrong_native_workspace_owner_harness_refused(self):
        for field,value,code in [('external_session_id','different','STRICT_NATIVE_ID_INVALID'),('workspace','/different','STRICT_WORKSPACE_MISMATCH'),('permission_level',2,'STRICT_SESSION_INVALID'),('harness','pi-native','STRICT_SESSION_INVALID')]:
            old=self.info[field];self.info[field]=value;self.expect(code,self.plan);self.info[field]=old
    def test_missing_duplicate_truncated_malformed_and_wrong_header(self):
        self.path.unlink();self.expect('STRICT_NATIVE_FILE_UNAVAILABLE',self.plan);self.path.write_bytes(self.raw);self.path.chmod(0o600)
        other=self.path.with_name('rollout-duplicate-'+NID+'.jsonl');other.write_bytes(self.raw);self.expect('STRICT_NATIVE_FILE_UNAVAILABLE',self.plan);other.unlink()
        self.path.write_bytes(self.raw[:-1]);self.expect('STRICT_NATIVE_FILE_INVALID',self.plan)
        self.path.write_bytes(self.raw.replace(NID.encode(),b'wrong'));self.expect('STRICT_NATIVE_ID_CHANGED',self.plan)
    def test_hash_file_replacement_and_prefix_mutation_refused(self):
        self.req['originalSHA256']='0'*64;self.expect('STRICT_NATIVE_FILE_CHANGED',self.plan)
        self.req['originalSHA256']=hashlib.sha256(self.raw).hexdigest();p=self.plan()
        self.path.rename(self.path.with_suffix('.saved'));self.path.write_bytes(self.raw);self.expect('STRICT_NATIVE_FILE_CHANGED',p.check_cold)
    def test_symlink_hardlink_writable_file_refused(self):
        saved=self.path.with_suffix('.saved');self.path.rename(saved);self.path.symlink_to(saved)
        self.expect('STRICT_NATIVE_FILE_UNAVAILABLE',self.plan);self.path.unlink();os.link(saved,self.path)
        self.expect('STRICT_NATIVE_FILE_UNSAFE',self.plan);saved.unlink();self.path.chmod(0o666);self.expect('STRICT_NATIVE_FILE_UNSAFE',self.plan)
    def test_original_bridge_selection_cannot_fall_back_to_default(self):
        self.info['labels']['omnigent.codex_native.bridge_id']=SID+'-other';self.expect('STRICT_BRIDGE_ID_CHANGED',self.plan)
    def test_busy_pending_and_changed_epoch(self):
        p=self.plan();self.busy=True;self.expect('SESSION_BUSY',p.check_cold);self.busy=False;self.epoch+=1;self.expect('SESSION_BUSY',p.check_cold)
        for key in ['pending_inputs','pending_elicitations','active_response_id','background_task_count']:
            self.info[key]=1;self.expect('SESSION_BUSY',self.plan);self.info.pop(key)
    def test_canonical_settings_change_is_detected_without_replacing_them(self):
        p=self.plan();(self.authority/'config.toml').write_text('model="changed"\n');self.expect('STRICT_AUTHORITY_CHANGED',p.check_cold)
        self.assertEqual((self.authority/'config.toml').read_text(),'model="changed"\n')
    def test_append_allowed_only_after_launch_and_no_reconstruction(self):
        p=self.plan();self.path.write_bytes(self.raw+b'{"type":"event_msg","payload":{}}\n');self.expect('STRICT_NATIVE_FILE_CHANGED',p.check_cold);p.check_prefix(allow_append=True)
        self.path.write_bytes(b'changed'+self.raw[7:]);self.expect('STRICT_NATIVE_FILE_CHANGED',lambda:p.check_prefix(allow_append=True))
    def test_fork_or_existing_registered_server_refused_before_prepare(self):
        p=self.plan();self.config.fork_source_id='different';self.expect('STRICT_NATIVE_ID_CHANGED',lambda:p.before_prepare(self.config));self.config.fork_source_id=None
        self.orch._AUTO_CODEX_APP_SERVERS[SID]=object();self.expect('STRICT_NATIVE_ALREADY_RUNNING',lambda:p.before_prepare(self.config))
    def test_no_model_reset_or_new_trust_grants(self):
        p=self.plan();server=types.SimpleNamespace(codex_home=self.home,cwd=self.workspace,trust_project=False,trust_all_hooks=False)
        p.before_server(server,self.config,None);self.assertIs(p.app_server,server);self.assertIsNotNone(p.launch_ticks)
        for key in ('trust_project','trust_all_hooks'):
            setattr(server,key,True);self.expect('STRICT_LAUNCH_CONFIG_CHANGED',lambda:p.before_server(server,self.config,None));setattr(server,key,False)
        self.expect('STRICT_LAUNCH_CONFIG_CHANGED',lambda:p.before_server(server,self.config,'new-model'))
    def test_duplicate_native_reservation(self):
        p=self.plan()
        with native.reserve_native(p):
            with self.assertRaisesRegex(claude.StrictResumeError,'SESSION_BUSY'):
                with native.reserve_native(p):self.fail('second admitted')


class Pinned(Fixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_fixture();fixture=Path(os.environ.get('OMNIGENT_TEST_SITE_PACKAGES',ROOT/'tests/vendor-fixture'))
        self.site=self.base/'vendor'
        for name in patcher.HASHES:
            target=self.site/'omnigent'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(fixture/'omnigent'/name,target)
        meta=self.site/'omnigent-0.16.0.dist-info/METADATA';meta.parent.mkdir();meta.write_text('Name: omnigent\nVersion: 0.16.0\n')
        patcher.patch(self.site);self.source=(self.site/'omnigent/runner/native/orchestration.py').read_text()
    async def test_actual_context_adapter_and_original_build_retain_plan(self):
        ns={'dataclasses':dataclasses,'_auto_create_codex_terminal':AsyncMock(return_value='terminal')};extract(self.source,['NativeLaunchContext','_launch_codex'],ns)
        p=self.plan();ctx=ns['NativeLaunchContext'](SID,self.registry,Mock(),woow_strict_resume=p)
        built=dataclasses.replace(ctx,bundle_dir=self.base)
        await ns['_launch_codex'](built);self.assertIs(ns['_auto_create_codex_terminal'].call_args.kwargs['woow_strict_resume'],p)
        await ns['_launch_codex'](ns['NativeLaunchContext'](SID,self.registry,Mock()));self.assertIsNone(ns['_auto_create_codex_terminal'].call_args.kwargs['woow_strict_resume'])
    async def test_actual_original_branch_strict_skips_adversarial_synthesis_normal_still_calls(self):
        fn=next(x for x in ast.walk(ast.parse(self.source)) if isinstance(x,ast.AsyncFunctionDef) and x.name=='_auto_create_codex_terminal')
        branch=next(x for x in fn.body if isinstance(x,ast.If) and 'woow_strict_resume.resume_existing' in ast.unparse(x) and 'elif' in ast.unparse(x))
        wrapper=ast.parse('async def branch():\n pass').body[0];wrapper.body=[branch]
        ns=dict(woow_strict_resume=self.plan(),launch_config=self.config,codex_home=self.home,original_external_session_id=NID,server_client=object(),session_id=SID,workspace=str(self.workspace),Path=Path,_session_meta_provider='openai',_codex_cli_path='codex')
        self.config.terminal_launch_args=[]
        synth=AsyncMock(side_effect=RuntimeError('SYNTHESIS_WOULD_REPLACE_HISTORY'))
        with patch.dict(sys.modules,{'omnigent.harnesses.codex_native.main':types.SimpleNamespace(_ensure_local_codex_resume_rollout=synth)}):
            exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),'actual-original-branch','exec'),ns)
            await ns['branch']();synth.assert_not_called();self.assertEqual(self.path.read_bytes(),self.raw)
            ns['woow_strict_resume']=None
            with self.assertRaisesRegex(RuntimeError,'SYNTHESIS_WOULD_REPLACE_HISTORY'):await ns['branch']()
            synth.assert_awaited_once()
    async def test_failed_armed_request_cannot_trigger_ordinary_reaper_or_ensure(self):
        ns={'os':os};extract(self.source,['_auto_create_codex_terminal'],ns)
        with patch.dict(os.environ,{bootstrap.ENV:'/private/request.json'}),self.assertRaisesRegex(claude.StrictResumeError,'STRICT_BOOTSTRAP_REQUIRED'):
            await ns['_auto_create_codex_terminal'](SID,self.registry,Mock())
    async def test_actual_unreadable_native_error_refuses_fresh_fallback_and_closes_owned_child(self):
        fn=next(x for x in ast.walk(ast.parse(self.source)) if isinstance(x,ast.AsyncFunctionDef) and x.name=='_auto_create_codex_terminal')
        handler=next(x for x in ast.walk(fn) if isinstance(x,ast.ExceptHandler) and any(isinstance(y,ast.If) and 'is_unreadable_thread_error' in ast.unparse(y.test) for y in x.body))
        branch=handler.body[0];wrapper=ast.parse('async def branch():\n pass').body[0];wrapper.body=[ast.Try(body=[ast.Raise(exc=ast.Name(id='original_error',ctx=ast.Load()))],handlers=[ast.ExceptHandler(type=ast.Name(id='BaseException',ctx=ast.Load()),name='exc',body=[branch])],orelse=[],finalbody=[])]
        import contextlib
        server=types.SimpleNamespace(close=AsyncMock());ns={'woow_strict_resume':self.plan(),'original_error':RuntimeError('unreadable original'),'is_unreadable_thread_error':lambda _:True,'contextlib':contextlib,'app_server':server,'_AUTO_CODEX_APP_SERVERS':{SID:server},'session_id':SID}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),'actual-resume-failure','exec'),ns)
        with self.assertRaisesRegex(RuntimeError,'unreadable original'):await ns['branch']()
        server.close.assert_awaited_once();self.assertNotIn(SID,ns['_AUTO_CODEX_APP_SERVERS'])
    def test_actual_creator_skips_target_reap_and_automatic_model_reset_only_when_strict(self):
        fn=next(x for x in ast.walk(ast.parse(self.source)) if isinstance(x,ast.AsyncFunctionDef) and x.name=='_auto_create_codex_terminal')
        guards=[ast.unparse(x.test) for x in fn.body if isinstance(x,ast.If)]
        self.assertIn('woow_strict_resume is None and launch_config.external_session_id is not None',guards)
        self.assertTrue(any(x.startswith('woow_strict_resume is None and codex_binding') for x in guards))
        self.assertIn('trust_project=woow_strict_resume is None',ast.unparse(fn));self.assertIn('trust_all_hooks=woow_strict_resume is None',ast.unparse(fn))
    def test_actual_previous_strict_transform_receipt_upgrades_idempotently(self):
        # Reconstruct the exact previous transform from its still-present
        # Claude/Pi operations, then assert the REVIEWED legacy byte hashes.
        # No git history dependency in mirrored repositories or CI.
        tree=ast.parse((ROOT/'patch-claude-strict-resume.py').read_text())
        transform=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='transform')
        branch=transform.body[0].orelse
        start=next(i for i,x in enumerate(branch) if isinstance(x,ast.FunctionDef) and x.name=='codex_creator')
        del branch[start:]
        ns={'once':patcher.once,'scoped':patcher.scoped}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[transform],type_ignores=[])),'previous-verified-transform','exec'),ns)
        legacy=self.base/'legacy';targets={}
        import base64,zlib
        fixture=Path(os.environ.get('OMNIGENT_TEST_SITE_PACKAGES',ROOT/'tests/vendor-fixture'))
        for name,sha in patcher.HASHES.items():
            original=(fixture/'omnigent'/name).read_bytes();old=ns['transform'](name,original.decode()).encode()
            self.assertEqual(hashlib.sha256(old).hexdigest(),patcher.LEGACY_TARGETS[name])
            dest=legacy/'omnigent'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(old)
            targets[name]={'original':sha,'patched':hashlib.sha256(old).hexdigest(),'sourceZlib':base64.b64encode(zlib.compress(original)).decode()}
        helpers={}
        for target,source in patcher.HELPERS.items():
            if target.endswith('woow_codex_strict_resume.py'):continue
            raw=(ROOT/source).read_bytes()
            dest=legacy/'omnigent'/target;dest.write_bytes(raw);helpers[target]=hashlib.sha256(raw).hexdigest()
        meta=legacy/'omnigent-0.16.0.dist-info/METADATA';meta.parent.mkdir();meta.write_text('Name: omnigent\nVersion: 0.16.0\n')
        (legacy/'omnigent'/patcher.RECEIPT).write_text(json.dumps({'version':1,'targets':targets,'helpers':helpers}))
        self.assertEqual(patcher.patch(legacy)['state'],'upgraded')
        self.assertEqual(patcher.patch(legacy)['state'],'already-applied')
        self.assertEqual((legacy/'omnigent/runner/native/orchestration.py').read_text(),self.source)

    def test_patch_idempotent_and_new_helper_installed(self):
        self.assertEqual(patcher.patch(self.site)['state'],'already-applied')
        self.assertEqual((self.site/'omnigent/runner/native/woow_codex_strict_resume.py').read_bytes(),(ROOT/'codex_strict_resume.py').read_bytes())




class Attachment(Fixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_fixture();self.plan_value=self.plan();self.plan_value.launch_ticks=500;self.plan_value.launch_started_at=time.time()
        self.proc=self.base/'proc';self.proc.mkdir();(self.proc/'net').mkdir()
        (self.proc/'net/tcp').write_text('header\n0: 0100007F:3039 00000000:0000 0A 0:0 00:0 0 1000 0 55555\n')
        binary=self.base/'codex';binary.touch();self.binary=binary
        self.endpoint='ws://127.0.0.1:12345'
        self.make_process(101,[b'codex',b'app-server',b'--listen',self.endpoint.encode()])
        self.make_process(202,[b'codex',b'--remote',self.endpoint.encode(),b'resume',NID.encode()])
        (self.proc/'101/fd/3').symlink_to('socket:[55555]')
        self.server=types.SimpleNamespace(proc=types.SimpleNamespace(pid=101,returncode=None),listen_url=self.endpoint)
        self.plan_value.app_server=self.server;self.orch._AUTO_CODEX_APP_SERVERS[SID]=self.server
        self.terminal=types.SimpleNamespace(pane_pid_sync=Mock(return_value=202))
        self.registry.get_terminal_resource=AsyncMock(return_value={'id':'terminal_codex_main'})
        self.registry.terminal_registry=types.SimpleNamespace(get=lambda *args:self.terminal)
        self.thread={'id':NID,'cwd':str(self.workspace),'path':str(self.path),'status':{'type':'idle'}}
        self.client=types.SimpleNamespace(connect=AsyncMock(),close=AsyncMock(),request=AsyncMock(side_effect=self.rpc))
        self.state=types.SimpleNamespace(session_id=SID,thread_id=NID,codex_home=str(self.home),socket_path=self.endpoint,active_turn_id=None)
        modules={'omnigent.harnesses.codex_native.bridge':types.SimpleNamespace(read_bridge_state=lambda _:self.state),
            'omnigent.harnesses.codex_native.app_server':types.SimpleNamespace(client_for_transport=lambda *a,**k:self.client),
            'omnigent.entities.session_resources':types.SimpleNamespace(terminal_resource_id=lambda *a:'terminal_codex_main')}
        actual=native.verify_processes
        for p in [patch.dict(sys.modules,modules),patch.object(native,'verify_processes',side_effect=lambda *a,**k:actual(*a,proc_root=self.proc))]:
            p.start();self.addCleanup(p.stop)
    def make_process(self,pid,args):
        p=self.proc/str(pid);p.mkdir();(p/'fd').mkdir();(p/'task'/str(pid)).mkdir(parents=True);(p/'task'/str(pid)/'children').write_text('')
        (p/'stat').write_text(str(pid)+' (codex) '+' '.join(['S']+['0']*18+['501']))
        (p/'exe').symlink_to(self.binary);(p/'cwd').symlink_to(self.workspace)
        (p/'cmdline').write_bytes(b'\0'.join(args)+b'\0');(p/'environ').write_bytes(b'CODEX_HOME='+str(self.home).encode()+b'\0')
    async def rpc(self,method,params):
        if method=='thread/loaded/list':return {'result':{'data':[NID]}}
        if method=='thread/read':
            self.assertFalse(params['includeTurns']);return {'result':{'thread':self.thread}}
        self.fail('unexpected mutating RPC '+method)
    async def test_current_new_socket_process_loaded_thread_prefix_and_tui_confirm(self):
        result=await native.confirm_attachment(self.plan_value,self.registry)
        self.assertTrue(result['currentNativeVerified']);self.assertTrue(result['threadReadVerified']);self.assertFalse(result['toolsVerified'])
        self.assertEqual((result['nativePid'],result['panePid']),(101,202));self.assertEqual(self.path.read_bytes(),self.raw)
        self.client.close.assert_awaited_once()
    async def test_dead_process_or_foreign_socket_cannot_confirm_registry_alone(self):
        self.server.proc.returncode=0
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_PROCESS_UNAVAILABLE'):await native.confirm_attachment(self.plan_value,self.registry)
        self.server.proc.returncode=None;(self.proc/'101/fd/3').unlink();(self.proc/'101/fd/3').symlink_to('socket:[99999]')
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_PROCESS_UNAVAILABLE'):await native.confirm_attachment(self.plan_value,self.registry)
    async def test_previous_generation_and_foreign_home_refused(self):
        self.plan_value.launch_ticks=502
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_GENERATION_CHANGED'):await native.confirm_attachment(self.plan_value,self.registry)
        self.plan_value.launch_ticks=500;(self.proc/'101/environ').write_bytes(b'CODEX_HOME=/foreign\0')
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_GENERATION_CHANGED'):await native.confirm_attachment(self.plan_value,self.registry)
    async def test_disk_read_without_native_loaded_is_not_attachment(self):
        async def missing(method,params):
            return {'result':{'data':[]}} if method=='thread/loaded/list' else {'result':{'thread':self.thread}}
        self.client.request.side_effect=missing
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_ID_CHANGED'):await native.confirm_attachment(self.plan_value,self.registry)
    async def test_active_thread_and_wrong_native_id_refused(self):
        self.thread['status']={'type':'active','activeFlags':['waitingOnApproval']}
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_ID_CHANGED'):await native.confirm_attachment(self.plan_value,self.registry)
        self.thread['status']={'type':'idle'};self.thread['id']='different'
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_ID_CHANGED'):await native.confirm_attachment(self.plan_value,self.registry)
    async def test_foreign_tui_resume_and_pane_race_refused(self):
        p=self.proc/'202/cmdline';original=p.read_bytes();p.write_bytes(original.replace(NID.encode(),b'other'))
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_GENERATION_CHANGED'):await native.confirm_attachment(self.plan_value,self.registry)
        p.write_bytes(original);self.terminal.pane_pid_sync.side_effect=[202,999]
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_GENERATION_CHANGED'):await native.confirm_attachment(self.plan_value,self.registry)
    async def test_registry_detach_during_rpc_refuses_alive_cached_pane(self):
        async def detach(method,params):
            result=await self.rpc(method,params)
            if method=='thread/read':self.registry.get_terminal_resource.return_value=None
            return result
        self.client.request.side_effect=detach
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_ATTACH_UNCONFIRMED'):await native.confirm_attachment(self.plan_value,self.registry)
        self.assertTrue((self.proc/'202').exists())
    async def test_registry_detach_during_rpc_client_close_cannot_mint_receipt(self):
        async def detach():self.registry.terminal_registry.get=lambda *a:None
        self.client.close.side_effect=detach
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_ATTACH_UNCONFIRMED'):await native.confirm_attachment(self.plan_value,self.registry)
        self.client.close.assert_awaited_once()
    async def test_terminal_server_and_bridge_replacement_during_rpc_refused(self):
        for field in ['terminal','server','bridge']:
            oldterminal=self.terminal;oldserver=self.server;oldstate=self.state
            async def replace_binding(method,params):
                result=await self.rpc(method,params)
                if method=='thread/read':
                    if field=='terminal':self.registry.terminal_registry.get=lambda *a:object()
                    elif field=='server':self.orch._AUTO_CODEX_APP_SERVERS[SID]=object()
                    else:self.state=types.SimpleNamespace(**{**vars(oldstate),'thread_id':'different'})
                return result
            self.client.request.side_effect=replace_binding
            with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_ATTACH_UNCONFIRMED'):await native.confirm_attachment(self.plan_value,self.registry)
            self.registry.terminal_registry.get=lambda *a:oldterminal
            self.orch._AUTO_CODEX_APP_SERVERS[SID]=oldserver;self.state=oldstate
    async def test_unrelated_fd_close_is_tolerated_but_listening_socket_loss_is_not(self):
        extra=self.proc/'101/fd/4';extra.symlink_to('pipe:[123]');actual=os.readlink
        def closing(fd,*a,**kw):
            if Path(fd)==extra:raise FileNotFoundError('descriptor closed')
            return actual(fd,*a,**kw)
        with patch.object(os,'readlink',side_effect=closing):
            result=await native.confirm_attachment(self.plan_value,self.registry)
            self.assertTrue(result['currentNativeVerified'])
            (self.proc/'101/fd/3').unlink()
            with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_PROCESS_UNAVAILABLE'):await native.confirm_attachment(self.plan_value,self.registry)
    def test_matching_native_process_is_refused_without_kill(self):
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_NATIVE_ALREADY_RUNNING'):native.assert_no_writer(self.plan_value,proc_root=self.proc)
        self.assertTrue((self.proc/'101').exists())



class ColdDispatch(Fixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_fixture()
        self.private=self.base/'request';self.private.mkdir(mode=0o700);self.request_path=self.private/'original.json'
        self.req.update(version=1,requestId='a'*32,issuedAt=time.time()-5,expiresAt=time.time()+120)
        self.write_request()
    def write_request(self):
        self.request_path.write_text(json.dumps(self.req));self.request_path.chmod(0o600)
    async def invoke(self):
        @dataclasses.dataclass(frozen=True)
        class Context:
            session_id:str
            resource_registry:object
            server_client:object
            woow_strict_resume:object=None
        response=types.SimpleNamespace(status_code=200,json=lambda:self.info)
        self.get=AsyncMock(return_value=response)
        ctx=Context(SID,self.registry,types.SimpleNamespace(get=self.get))
        self.launch=AsyncMock(return_value=True)
        self.confirm=AsyncMock(return_value=dict(state='attached',sessionId=SID,nativeSessionId=NID,historyPrefixPreserved=True,toolsVerified=False))
        actual_prepare=native.prepare_plan
        modules={'omnigent.runner.native.orchestration':types.SimpleNamespace(_launch_native_terminal=self.launch),
            'omnigent.runner.native.woow_codex_strict_resume':native}
        with patch.dict(sys.modules,modules),patch.dict(os.environ,{bootstrap.ENV:str(self.request_path)}), \
            patch.object(native,'prepare_plan',side_effect=lambda c,r,i:actual_prepare(c,r,i,bridge_root=self.root,authority_root=self.authority)), \
            patch.object(native,'confirm_attachment',self.confirm):
            return await bootstrap.strict_cold_launch('codex-native',ctx,ensure_locks={},pre_launch=Mock())
    async def test_private_original_dispatch_metadata_only_and_one_shot_receipt(self):
        self.assertTrue(await self.invoke());args,kwargs=self.launch.call_args
        self.assertEqual(args[0],'codex-native');self.assertIsInstance(args[1].woow_strict_resume,native.StrictCodexPlan)
        self.assertIsNone(kwargs['pre_launch']);self.assertTrue(kwargs['reraise'])
        self.assertEqual(self.get.call_args.kwargs['params']['include_items'],'false')
        receipt=json.loads(self.request_path.with_name('original.json.attached.json').read_text())
        self.assertEqual(receipt['nativeSessionId'],NID);self.assertEqual(self.path.read_bytes(),self.raw)
        with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_REQUEST_ALREADY_USED'):await self.invoke()
        self.launch.assert_not_awaited()
    async def test_invalid_hash_busy_owner_fail_before_native_launch(self):
        for where,field,value in [(self.req,'originalSHA256','0'*64),(self.info,'pending_inputs',[{}]),(self.info,'permission_level',2)]:
            old=where.get(field);where[field]=value;self.write_request()
            with self.assertRaises(claude.StrictResumeError):await self.invoke()
            self.launch.assert_not_awaited();where[field]=old
        self.assertFalse(self.request_path.with_name('original.json.attached.json').exists())
    async def test_no_success_receipt_when_actual_attachment_confirmation_fails(self):
        with patch.object(native,'cold_resume',AsyncMock(side_effect=claude.StrictResumeError('STRICT_ATTACH_UNCONFIRMED'))):
            with self.assertRaisesRegex(claude.StrictResumeError,'STRICT_ATTACH_UNCONFIRMED'):await self.invoke()
        self.assertFalse(self.request_path.with_name('original.json.attached.json').exists())

if __name__=='__main__':unittest.main()
