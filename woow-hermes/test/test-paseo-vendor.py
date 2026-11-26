"""Verify the reviewed host adapter is complete, pinned and untampered."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
vendor=root/'vendor/paseo'
pin=json.loads((vendor/'PROVENANCE.json').read_text())
assert pin['repository']=='https://github.com/WOOWTECH/hermes-paseo-plugin'
assert pin['commit']=='7b9c88d032672f688c88df222e384ce3bc1af2f2'
assert pin['version']=='0.1.5-rc.3'
assert set(pin['sha256'])=={'dashboard_control.py','profile_lifecycle.py','resource_limits.py','hermes'}
for name,digest in pin['sha256'].items():
 data=(vendor/name).read_bytes()
 assert hashlib.sha256(data).hexdigest()==digest,name+' differs from reviewed source'
 if name.endswith('.py'):ast.parse(data)
assert 'MIT License' in (vendor/'LICENSE').read_text()
dockerfile=(root/'Dockerfile').read_text()
assert 'COPY --chmod=0555 vendor/paseo/hermes /opt/hermes/.venv/bin/hermes' in dockerfile
assert 'vendor/paseo/dashboard_control.py vendor/paseo/profile_lifecycle.py vendor/paseo/resource_limits.py /opt/hermes-paseo-dashboard-control/' in dockerfile
assert 'HERMES_PASEO_INGRESS_ORIGIN' in (vendor/'dashboard_control.py').read_text()
with tempfile.TemporaryDirectory() as td:
 work=Path(td);source=work/'source';remote=work/'remote.git';checkout=work/'checkout'
 subprocess.run(['git','init','-q',str(source)],check=True)
 subprocess.run(['git','-C',str(source),'config','user.name','test'],check=True)
 subprocess.run(['git','-C',str(source),'config','user.email','test@example.invalid'],check=True)
 (source/'plugin.yaml').write_text('version: old\n')
 subprocess.run(['git','-C',str(source),'add','plugin.yaml'],check=True)
 subprocess.run(['git','-C',str(source),'commit','-qm','old'],check=True)
 subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
 subprocess.run(['git','-C',str(source),'remote','add','origin',str(remote)],check=True)
 subprocess.run(['git','-C',str(source),'push','-q','-u','origin','HEAD:main'],check=True)
 subprocess.run(['git','clone','-q','--branch','main',str(remote),str(checkout)],check=True)
 marker=checkout/'.omnigent-installation.json';marker.write_text('{"id":"preserved"}\n')
 config=checkout/'.git/config';config_before=config.read_bytes();config_mtime=config.stat().st_mtime_ns
 checkout_inode=checkout.stat().st_ino
 (source/'plugin.yaml').write_text('version: new\n')
 subprocess.run(['git','-C',str(source),'commit','-qam','new'],check=True)
 new_sha=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
 subprocess.run(['git','-C',str(source),'push','-q','origin','HEAD:main'],check=True)
 assert subprocess.check_output(['git','-C',str(checkout),'status','--porcelain','--untracked-files=no'],text=True)==''
 subprocess.run(['git','-C',str(checkout),'fetch','-q','origin',new_sha],check=True)
 subprocess.run(['git','-C',str(checkout),'merge','-q','--ff-only','FETCH_HEAD'],check=True)
 assert subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()==new_sha
 assert checkout.stat().st_ino==checkout_inode
 assert marker.read_text()=='{"id":"preserved"}\n'
 assert config.read_bytes()==config_before and config.stat().st_mtime_ns==config_mtime
print('Paseo host provenance and packaging: ok')
