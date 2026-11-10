import json,os,pathlib,subprocess,tempfile
root=pathlib.Path(tempfile.mkdtemp(prefix='woow-sandbox-proof-'))
workspace=root/'workspace';workspace.mkdir()
(workspace/'input.txt').write_text('fixture')
outside=root/'outside';outside.write_text('unchanged')
env=dict(os.environ)
if env.get('CODEX_HOME'):pathlib.Path(env['CODEX_HOME']).mkdir(parents=True,exist_ok=True)
base=['codex','sandbox','-c','sandbox_mode="workspace-write"','-c','sandbox_workspace_write.network_access=false','-c','sandbox_workspace_write.exclude_tmpdir_env_var=true','-c','sandbox_workspace_write.exclude_slash_tmp=true','--']
cases=[('read-workspace',['/bin/cat',str(workspace/'input.txt')],True),
 ('write-workspace',['/bin/sh','-c','printf allowed > inside.txt'],True),
 ('deny-outside-write',['/bin/sh','-c','printf forbidden > "$1"','probe',str(outside)],False),
 ('deny-network',['python3','-c','import socket; socket.create_connection(("1.1.1.1",443),timeout=2)'],False)]
rows=[]
try:
 for name,command,expected in cases:
  r=subprocess.run(base+command,cwd=workspace,env=env,capture_output=True,text=True,timeout=30)
  passed=(r.returncode==0)==expected
  if name=='deny-outside-write':passed=passed and 'Read-only file system' in r.stderr
  if name=='deny-network':passed=passed and 'PermissionError' in r.stderr
  if name=='read-workspace':passed=passed and r.stdout=='fixture'
  rows.append({'test':name,'exit':r.returncode,'expectedSuccess':expected,'pass':passed,'detail':(r.stdout+r.stderr)[-350:]})
 summary={'cases':rows,'workspaceWritten':(workspace/'inside.txt').read_text() if (workspace/'inside.txt').exists() else None,'outsideUnchanged':outside.read_text()=='unchanged'}
 summary['pass']=all(r['pass'] for r in rows) and summary['outsideUnchanged'] and summary['workspaceWritten']=='allowed'
 print(json.dumps(summary))
 if not summary['pass']:raise SystemExit(1)
finally:
 import shutil;shutil.rmtree(root)
