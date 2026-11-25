"""Tests for the daily apk pin check (#228) and the shared base-image resolution (addon_build)."""
import json,os,pathlib,shutil,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import addon_build as b
import apk_pin_check as c

HERE=pathlib.Path(__file__).resolve().parent
STORE=HERE.parent
# The Store registry and add-on directories; an add-on release job checks out only .addon-sync, so tests reading them skip
# there. The Store's own CI sets STORE_FULL_CHECKOUT=1, so a missing Store stops the run instead.
HAS_STORE=(STORE/'repository.yaml').is_file()
if not HAS_STORE and os.environ.get('STORE_FULL_CHECKOUT'):
    sys.exit('STORE_FULL_CHECKOUT is set, but this checkout has no Store add-on directories')
needs_store=unittest.skipUnless(HAS_STORE,'needs the Store add-on directories (sparse checkout of .addon-sync)')

class Addon(unittest.TestCase):
    def addon(self,files,config=None):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d)
        files={'config.yaml':json.dumps(config or {'slug':'t','version':'1.0.0','arch':['amd64','aarch64']}),**files}
        for name,text in files.items():
            p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        return d

class BaseImage(Addon):
    """addon_build.base_image: build_from, else the Dockerfile's BUILD_FROM default, else the FROM written out."""
    def test_build_from_wins_over_the_dockerfile_default(self):
        d=self.addon({'build.yaml':'build_from:\n  amd64: a/amd64:1\n  aarch64: a/aarch64:1\n','Dockerfile':'ARG BUILD_FROM=x/y:9\nFROM ${BUILD_FROM}\n'})
        self.assertEqual(b.base_image(d,'amd64')[1],'a/amd64:1');self.assertEqual(b.base_image(d,'aarch64')[1],'a/aarch64:1')
    def test_without_a_build_file_the_build_from_default_counts(self):
        # Current Supervisor passes BUILD_FROM only with a build file (supervisor/apps/build.py).
        d=self.addon({'Dockerfile':'ARG BUILD_FROM=ghcr.io/hassio-addons/base:21.0.2\nFROM ${BUILD_FROM}\n'})
        self.assertEqual(b.base_image(d,'aarch64')[1],'ghcr.io/hassio-addons/base:21.0.2')
    def test_a_build_file_without_build_from_passes_home_assistants_base(self):
        d=self.addon({'build.yaml':'args:\n  X: "1"\n','Dockerfile':'ARG BUILD_FROM=x/y:9\nFROM ${BUILD_FROM}\n'})
        self.assertEqual(b.base_image(d,'amd64')[1],'ghcr.io/home-assistant/base:latest')
    def test_a_written_from_and_build_arch(self):
        d=self.addon({'Dockerfile':'ARG BUILD_ARCH\nARG TAG="bookworm-1"\nFROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:${TAG}\n'})
        self.assertEqual(b.base_image(d,'aarch64')[1],'ghcr.io/home-assistant/aarch64-base-debian:bookworm-1')
    def test_the_last_stage_and_the_stages_it_starts_from(self):
        d=self.addon({'Dockerfile':'FROM node:22-alpine AS ui\nRUN true\nFROM a/b:1 AS base\nFROM base AS final\n'})
        _,image,chain,stages,_=b.base_image(d,'amd64')
        self.assertEqual(image,'a/b:1');self.assertEqual(chain,[1,2]);self.assertEqual(stages[0]['image'],'node:22-alpine')
    def test_an_unresolved_from_is_an_error(self):
        with self.assertRaisesRegex(ValueError,r'\$NOPE has no value'):b.base_image(self.addon({'Dockerfile':'FROM ${NOPE}\n'}),'amd64')
    def test_build_args_is_the_same_function_upgrade_check_uses(self):
        import upgrade_check
        self.assertIs(upgrade_check.build_args,b.build_args)

class Specs(unittest.TestCase):
    def test_package_arguments(self):
        self.assertEqual(c.parse_spec('nginx=1.30.6-r0'),{'name':'nginx','op':'=','version':'1.30.6-r0','tag':'','spec':'nginx=1.30.6-r0'})
        self.assertEqual(c.parse_spec('python3~3.14')['op'],'~')
        self.assertEqual(c.parse_spec('yq-go')['op'],'')
        self.assertEqual(c.parse_spec('foo>=2@edge')['tag'],'edge')
        self.assertIsNone(c.parse_spec('a b'))
    def test_comparison(self):
        self.assertFalse(c.satisfies('1.30.7-r0','=','1.30.6-r0'));self.assertTrue(c.satisfies('1.30.7-r0','=','1.30.7-r0'))
        self.assertTrue(c.satisfies('3.14.10-r2','~','3.14'));self.assertFalse(c.satisfies('3.140.1-r0','~','3.14'))
        self.assertTrue(c.satisfies('4.53.3-r2','~','4.53'));self.assertIsNone(c.satisfies('2','>=','1'))

class Collect(Addon):
    def test_run_packages_with_arg_values_virtual_repositories_and_upgrade(self):
        d=self.addon({'Dockerfile':'FROM a/b:1\nARG PG=16\nRUN set -x && apk add --no-cache --upgrade musl \\\n  && apk add --no-cache --virtual .deps \\\n'
            '    -X https://example.org/repo postgresql${PG} "nginx=1.30.6-r0" \\\n    && apk del .deps\n'})
        got=c.collect(d,'amd64')
        self.assertEqual([[p['spec'] for p in a['packages']] for a in got['adds']],[['musl'],['postgresql16','nginx=1.30.6-r0']])
        self.assertTrue(got['adds'][0]['upgrade']);self.assertEqual(got['adds'][1]['repositories'],['https://example.org/repo'])
        self.assertEqual((got['adds'][1]['file'],got['adds'][1]['line']),('Dockerfile',3));self.assertEqual(got['unchecked'],[])
    def test_build_script_pin_is_collected(self):
        # cloudflared: RUN ["/build.sh"] runs rootfs/build.sh, which pins yq-go from the Dockerfile's ARG.
        d=self.addon({'Dockerfile':'FROM node:22-alpine AS ui\nRUN npm ci\nFROM ghcr.io/hassio-addons/base:21.0.1\nARG YQ_VERSION="4.53.3-r2"\nCOPY rootfs /\nRUN ["/build.sh"]\n',
            'rootfs/build.sh':'#!/bin/sh\nset -eux\n# yq\napk add --no-cache yq-go="${YQ_VERSION}"\ncase "${BUILD_ARCH}" in\n"aarch64")\n    a="arm64"\n    ;;\nesac\n',
            # A script the build only copies or chmods (a start-up script) is not read.
            'rootfs/etc/run.sh':'apk add --no-cache never=1-r0\n'})
        (d/'Dockerfile').write_text((d/'Dockerfile').read_text()+'RUN chmod +x /etc/run.sh\n')
        got=c.collect(d,'amd64')
        self.assertEqual(got['scripts'],['rootfs/build.sh'])
        self.assertEqual([(a['file'],a['line'],[p['spec'] for p in a['packages']]) for a in got['adds']],[('rootfs/build.sh',4,['yq-go=4.53.3-r2'])])
    def test_lines_the_check_cannot_read_are_listed_with_their_text(self):
        d=self.addon({'Dockerfile':'FROM a/b:1\nRUN apk add --no-cache "foo=${UNSET}"\nRUN if [ "$BUILD_ARCH" = amd64 ]; then apk add bar=1-r0; fi\n'
            'RUN for p in a b; do apk add "$p"; done\n'})
        got=c.collect(d,'amd64')
        self.assertEqual(got['adds'],[])
        self.assertEqual([(u['line'],u['text'],u['reason']) for u in got['unchecked']],[
            (2,'apk add --no-cache \'foo=${UNSET}\'','$UNSET has no value'),
            (3,'apk add bar=1-r0','inside a conditional or loop'),(4,'apk add \'$p\'','inside a conditional or loop')])
    def test_world_sed_is_replayed_and_other_stage_pins_are_not_checked(self):
        d=self.addon({'Dockerfile':'FROM golang:1-alpine AS builder\nRUN apk add build-base go=1.2-r0\nFROM a/b:1\n'
            "RUN sed -i 's/[<>=~].*$//' /etc/apk/world && apk add nginx\n"})
        got=c.collect(d,'amd64')
        self.assertEqual(got['world_edits'],["sed -i 's/[<>=~].*$//' /etc/apk/world"])
        self.assertEqual([[p['spec'] for p in a['packages']] for a in got['adds']],[['nginx']])
        self.assertEqual(len(got['unchecked']),1);self.assertIn('build stage builder starts from golang:1-alpine',got['unchecked'][0]['reason'])

REGISTRY={'providers':{'WOOWTECH/a':{'components':[
    {'id':'tailscale','store_path':'ts','config_file':'config.yaml','channel':'stable','enabled':True},
    {'id':'beta','store_path':'beta','config_file':'config.yaml','channel':'prerelease','enabled':True},
    {'id':'off','store_path':'off','config_file':'config.yaml','channel':'stable','enabled':False,'reason':'x'},
    {'id':'delisted','store_path':'del','config_file':'config.yaml','channel':'stable','enabled':True,'store_enabled':False},
    {'id':'mirror','store_path':'mirror','config_file':'config.yaml','channel':'stable','enabled':True},
    {'id':'plain','store_path':'plain','config_file':'config.yaml','channel':'stable','enabled':True}]}}}
TAILSCALE_DOCKERFILE='ARG BUILD_FROM=ghcr.io/hassio-addons/base/amd64:21.0.2\nFROM ${BUILD_FROM}\nRUN apk add --no-cache bind-tools nginx=1.30.6-r0 dnsmasq=2.92_p2-r0\n'

def output(world=(),sim='OK: 0 MiB in 30 packages',exit=0,policy='',alpine='3.24.1',apk=True,install=('OK: 0 MiB in 30 packages',0),end=True):
    """container_script()'s output. `install` is the real apk add's (output, exit code); it runs only after a simulate
    that passed."""
    if alpine is None:return '@@ALPINE\n@@NOTALPINE\n'
    if not apk:return f'@@ALPINE\n{alpine}\n@@NOAPK\n'
    text=f'@@ALPINE\n{alpine}\n@@WORLD\n'+''.join(w+'\n' for w in world)+f'@@EDITS\n@@SIMULATE\n{sim}\n@@EXIT {exit}\n@@POLICY\n{policy}@@INSTALL\n'
    if exit==0 and install is not None:text+=f'{install[0]}\n@@INSTALLEXIT {install[1]}\n'
    return text+('@@END\n' if end else '')

HASSIO_WORLD=['bash=5.3.3-r1','curl=8.21.0-r0','musl=1.2.6-r2']
TAILSCALE_FAIL=output(HASSIO_WORLD,'ERROR: unable to select packages:\n  nginx-1.30.7-r0:\n    breaks: world[nginx=1.30.6-r0]',1,
    'bash policy:\n  5.3.3-r1:\n    lib/apk/db/installed\n    https://dl-cdn.alpinelinux.org/alpine/v3.24/main\n'
    'curl policy:\n  8.21.0-r0:\n    lib/apk/db/installed\n  8.23.0-r0:\n    https://dl-cdn.alpinelinux.org/alpine/v3.24/main\n'
    'dnsmasq policy:\n  2.92_p2-r0:\n    https://dl-cdn.alpinelinux.org/alpine/v3.24/main\n'
    'musl policy:\n  1.2.6-r2:\n    lib/apk/db/installed\n  1.2.6-r3:\n    https://dl-cdn.alpinelinux.org/alpine/v3.24/main\n'
    'nginx policy:\n  1.30.7-r0:\n    https://dl-cdn.alpinelinux.org/alpine/v3.24/main\n')

# #241: python3-ndbm from the repository overwrites a file of the base's older python3. apk resolves it (simulate passes)
# and fails only when it unpacks the package. The ERROR line is apk's own (apk-tools 3.0.9, 2.14.13 and 2.12.9 print the
# same: one line per file, then one "N error(s);" line per package).
OPENDESIGN_DOCKERFILE='ARG BUILD_FROM=ghcr.io/woowtech/open-design-core:20261101.2319\nFROM ${BUILD_FROM}\nRUN apk add --no-cache nginx su-exec ttyd=1.7.7-r0\n'
NDBM_SO='usr/lib/python3.14/lib-dynload/_dbm.cpython-314-x86_64-linux-musl.so'
CONFLICT_241=('(1/6) Installing nginx (1.30.7-r0)\n  Executing nginx-1.30.7-r0.pre-install\n  Executing nginx-1.30.7-r0.post-install\n'
    f'(2/6) Installing python3-ndbm (3.14.10-r2)\nERROR: python3-ndbm-3.14.10-r2: trying to overwrite {NDBM_SO} owned by python3-3.14.10-r1.\n'
    '(3/6) Installing su-exec (0.3-r0)\n(4/6) Installing libwebsockets (4.3.5-r2)\n(5/6) Installing libwebsockets-evlib_uv (4.3.5-r2)\n'
    '(6/6) Installing ttyd (1.7.7-r0)\nExecuting busybox-1.37.0-r31.trigger\n1 error; 1037.7 MiB in 324 packages')
TTYD_POLICY='ttyd policy:\n  1.7.7-r0:\n    https://dl-cdn.alpinelinux.org/alpine/v3.24/community\n'

class FakeDocker:
    """Answers docker images / image inspect / pull / run / create / rm / rmi. `outputs` maps an image (or ('rootfs', image)
    for the helper's apk on its exported rootfs) to container_script's output; `local` maps the images already there to
    their IDs; a pulled image's ID is `ids`[image], else sha256:<image>."""
    def __init__(self,outputs,missing=(),local=None,ids=None):
        self.outputs=outputs;self.missing=missing;self.local=dict(local or {});self.ids=ids or {};self.calls=[];self.created=None
    def __call__(self,args,timeout=0,stdin_from=None):
        self.calls.append(args);ok=lambda out='':subprocess.CompletedProcess(args,0,out,'')
        if args[0]=='images':return ok(''.join(i+'\n' for i in self.local.values()))
        if args[0]=='image':return ok(self.local[args[-1]]+'\n') if args[-1] in self.local else subprocess.CompletedProcess(args,1,'','No such image')
        if args[0]=='pull':
            if args[-1] in self.missing:return subprocess.CompletedProcess(args,1,'','no matching manifest for linux/arm64/v8 in the manifest list entries')
            self.local[args[-1]]=self.ids.get(args[-1],'sha256:'+args[-1]);return ok()
        if args[0]=='rmi':self.local.pop(args[1],None);return ok()
        if args[0]=='create':self.created=args[3];return ok('cid1\n')
        if args[0]=='run' and stdin_from:
            assert stdin_from==['export','cid1'] and args[args.index('sh')-1]==c.HELPER;return ok(self.outputs['rootfs',self.created])
        if args[0]=='run':return ok(self.outputs[args[args.index('--entrypoint')+2]])
        return ok()

class Check(Addon):
    def store(self):
        d=self.addon({'ts/config.yaml':json.dumps({'version':'0.1.5','arch':['amd64','aarch64']}),
            'ts/build.yaml':'build_from:\n  amd64: ghcr.io/hassio-addons/base/amd64:21.0.2\n  aarch64: ghcr.io/hassio-addons/base/aarch64:21.0.2\n',
            'ts/Dockerfile':TAILSCALE_DOCKERFILE,
            'mirror/config.yaml':json.dumps({'version':'1','arch':['amd64','aarch64','armv7'],'image':'x/{arch}'}),
            'plain/config.yaml':json.dumps({'version':'1','arch':['amd64']}),'plain/Dockerfile':'FROM debian:12\nRUN apt-get install -y curl\n'})
        return d
    def test_rows_cover_each_shipped_add_on_and_arch(self):
        rows=c.plan(REGISTRY,self.store())
        self.assertEqual([(r['id'],r['arch'],r.get('result')) for r in rows],[('tailscale','amd64',None),('tailscale','aarch64',None),
            ('mirror','amd64',c.SKIPPED),('mirror','aarch64',c.SKIPPED),('plain','amd64',c.SKIPPED)])
        self.assertEqual(rows[2]['reason'],'no Dockerfile (installs the published image)');self.assertEqual(rows[4]['reason'],'no apk add in the build')
    def test_regression_tailscale_nginx_cannot_install_on_both_arches(self):
        # #226: tailscale 0.1.5 pinned nginx=1.30.6-r0 after Alpine replaced it with 1.30.7-r0.
        store=self.store();rows=[]
        for arch in c.ARCHES:
            docker=FakeDocker({f'ghcr.io/hassio-addons/base/{arch}:21.0.2':TAILSCALE_FAIL})
            rows+=c.run_rows(c.plan(REGISTRY,store,(arch,),{'tailscale'}),arch,docker=docker)
            self.assertIn(['rmi',f'ghcr.io/hassio-addons/base/{arch}:21.0.2'],docker.calls)
        for row in rows:
            self.assertEqual(row['result'],c.FAIL)
            nginx=[s for s in row['stale'] if s['spec']=='nginx=1.30.6-r0']
            self.assertEqual(nginx,[{'spec':'nginx=1.30.6-r0','source':'apk add','available':['1.30.7-r0'],'installed':[]}])
            self.assertEqual(row['world_pins'],HASSIO_WORLD)
            self.assertEqual({s['spec'] for s in row['stale'] if s['source']=='base world'},{'curl=8.21.0-r0','musl=1.2.6-r2'})
        text=c.summary(rows)
        self.assertIn('| tailscale | aarch64 | `ghcr.io/hassio-addons/base/aarch64:21.0.2` (Alpine 3.24.1) | 2 + 3 in world | cannot install |',text)
        self.assertIn('nginx=1.30.6-r0 (apk add): repository has 1.30.7-r0',text)
        self.assertIn('world pins checked: 3 (2 older than the repository)',text)
        self.assertIn('breaks: world[nginx=1.30.6-r0]',text);self.assertIn(c.FILE_CONFLICT_NOTE,text)
    def test_script_has_every_package_in_one_simulate_and_policy_for_pins_and_world(self):
        row=c.plan(REGISTRY,self.store(),('amd64',),{'tailscale'})[0]
        script=c.container_script(row)
        self.assertIn('apk add --simulate --no-cache bind-tools nginx=1.30.6-r0 dnsmasq=2.92_p2-r0 2>&1',script)
        self.assertIn('apk policy --no-cache $WORLD_PINS dnsmasq nginx',script)
        rootfs=c.container_script(row,'/r')
        self.assertIn('apk --root /r --arch x86_64 add --simulate',rootfs);self.assertIn('cat /r/etc/apk/world',rootfs)
        # The script runs in sh: its world-pin extraction works on a real world file.
        world=self.addon({'world':'bash=5.3.3-r1\nnginx\ncurl~8.21\n'})/'world'
        line=[l for l in script.splitlines() if l.startswith('WORLD_PINS=')][0].replace('/etc/apk/world',str(world))
        self.assertEqual(subprocess.run(['sh','-c',line+'\necho "$WORLD_PINS"'],capture_output=True,text=True).stdout.split(),['bash','curl'])
    def test_world_pins_the_dockerfile_removes_are_not_reported_or_checked(self):
        # woow-nginxproxymanager strips the base's world pins with sed before installing: the world the build uses has none.
        d=self.addon({'Dockerfile':"FROM a/b:1\nRUN sed -i 's/[<>=~].*$//' /etc/apk/world && apk add --no-cache nginx\n",
            'r/etc/alpine-release':'3.24.1\n','r/lib/apk/db/installed':'','r/etc/apk/world':'bash=5.3.3-r1\ncurl=8.21.0-r0\nmusl\n',
            # A stand-in apk: simulate succeeds, and policy is recorded to see which names the script asks about.
            'bin/apk':'#!/bin/sh\ncase " $* " in *" policy "*) echo "$*" >> "$(dirname "$0")/policy";; *) echo OK;; esac\n'})
        (d/'bin/apk').chmod(0o755)
        row=dict(c.collect(d,'amd64'),id='npm',arch='amd64')
        text=subprocess.run(['sh','-c',c.container_script(row,str(d/'r'))],capture_output=True,text=True,env=dict(os.environ,PATH=f'{d/"bin"}:{os.environ["PATH"]}')).stdout
        got=c.evaluate(row,c.parse_output(text))
        self.assertEqual(got['result'],c.PASS);self.assertEqual(got['world'],['bash','curl','musl'])
        self.assertEqual(got['world_pins'],[]);self.assertEqual(got['stale'],[])
        self.assertNotIn('bash',(d/'bin/policy').read_text().split());self.assertNotIn('curl',(d/'bin/policy').read_text().split())
    def test_pass_not_alpine_no_apk_unchecked_and_missing_platform(self):
        rows=[{'id':'x','arch':'aarch64','base':b,'dockerfile':'Dockerfile','adds':[{'file':'Dockerfile','line':2,'text':'apk add a','packages':[c.parse_spec('a')],'repositories':[],'upgrade':False}],
               'unchecked':[],'world_edits':[],'scripts':[]} for b in ('alpine','debian','noapk','hardened','gone')]
        rows.append(dict(rows[0],id='y',unchecked=[{'file':'Dockerfile','line':3,'text':'apk add $X','reason':'$X has no value'}]))
        docker=FakeDocker({'alpine':output(),'debian':output(alpine=None),'noapk':output(apk=False),('rootfs','noapk'):output(apk=False),
            'hardened':output(apk=False),('rootfs','hardened'):output(alpine='3.24')},missing=('gone',))
        got={(r['id'],r['base']):r for r in c.run_rows(rows,'aarch64',docker=docker)}
        self.assertEqual(got['x','alpine']['result'],c.PASS);self.assertEqual(got['x','debian']['result'],c.SKIPPED)
        self.assertEqual((got['x','noapk']['result'],got['x','noapk']['reason']),(c.UNCHECKED,'the base image has no apk database'))
        # No apk in the base (n8n's Docker Hardened Image): the check's own apk on the exported image.
        self.assertEqual(got['x','hardened']['result'],c.PASS);self.assertIn('exported image',got['x','hardened']['via'])
        self.assertIn(['rm','-f','cid1'],docker.calls)
        self.assertEqual((got['x','gone']['result'],got['x','gone']['reason'],got['x','gone']['error']),(c.UNCHECKED,'the base image has no linux/arm64 variant',False))
        self.assertEqual(got['y','alpine']['result'],c.UNCHECKED)
        self.assertEqual(docker.calls.count(['pull','--quiet','--platform','linux/arm64','alpine']),1)
        self.assertEqual(docker.local,{})  # every image this run pulled is removed again
        text=c.summary(list(got.values()))
        self.assertIn('not checked, Dockerfile:3: `apk add $X` ($X has no value)',text)
        for r in got.values():self.assertIn(r['result'],c.RESULTS)
    def test_a_base_image_that_cannot_be_resolved_is_a_tool_error(self):
        d=self.addon({'x/config.yaml':json.dumps({'version':'1','arch':['amd64']}),'x/Dockerfile':'FROM ${NOPE}\nRUN apk add nginx\n'})
        registry={'providers':{'o/a':{'components':[{'id':'x','store_path':'x','config_file':'config.yaml','channel':'stable','enabled':True}]}}}
        row=c.plan(registry,d)[0]
        self.assertEqual(row['result'],c.UNCHECKED);self.assertIn('base image not resolved',row['reason']);self.assertTrue(row.get('error'))
    def test_apk_that_cannot_read_its_repositories_is_a_tool_error_not_cannot_install(self):
        # apk's own text (apk-tools 3.0.9, 2.14.13, 2.12.9): an index it could not fetch or trust leaves the package
        # "no such package", which is not the add-on's fault; nor is a database apk could not open.
        row=c.plan(REGISTRY,self.store(),('amd64',),{'tailscale'})[0]
        missing='ERROR: unable to select packages:\n  bind-tools (no such package):\n    required by: world[bind-tools]'
        for sim,code in (('WARNING: fetching https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/APKINDEX.tar.gz: DNS: name does not exist\n'+missing,1),
                ('fetch https://dl-cdn.alpinelinux.org/alpine/v3.21/main/x86_64/APKINDEX.tar.gz\nWARNING: fetching https://dl-cdn.alpinelinux.org/alpine/v3.21/main: UNTRUSTED signature\n'+missing,1),
                ('WARNING: Ignoring https://dl-cdn.alpinelinux.org/alpine/v3.16/main: DNS lookup error\n'+missing,1),
                ('ERROR: Unable to read database state: Permission denied\nERROR: Failed to open apk database: Permission denied',99),
                ('Segmentation fault',139)):
            got=c.evaluate(row,c.parse_output(output(HASSIO_WORLD,sim,code)))
            self.assertNotEqual(got['result'],c.FAIL,sim);self.assertTrue(got.get('error'),sim)
        # A version the repository no longer has is still cannot install, also with apk 2's plain "fetch" progress lines.
        for sim in (TAILSCALE_FAIL,output(HASSIO_WORLD,'fetch https://dl-cdn.alpinelinux.org/alpine/v3.21/main/x86_64/APKINDEX.tar.gz\n'
                'ERROR: unable to select packages:\n  nginx-1.30.7-r0:\n    breaks: world[nginx=1.30.6-r0]',1)):
            got=c.evaluate(row,c.parse_output(sim))
            self.assertEqual(got['result'],c.FAIL);self.assertFalse(got.get('error'))
    def test_images_that_were_there_before_are_kept(self):
        # By tag, or as a digest-only copy with the ID the pulled tag turns out to have.
        row=c.plan(REGISTRY,self.store(),('amd64',),{'tailscale'})[0]
        for local,ids in (({row['base']:'sha256:1'},{row['base']:'sha256:1'}),({'x/y@sha256:1':'sha256:1'},{row['base']:'sha256:1'})):
            docker=FakeDocker({row['base']:output()},local=local,ids=ids)
            self.assertEqual(c.run_rows([row],'amd64',docker=docker)[0]['result'],c.PASS)
            self.assertFalse([a for a in docker.calls if a[0]=='rmi'])
    def test_report_fails_only_on_cannot_install_or_a_tool_error(self):
        d=self.addon({})
        def report(rows):
            (d/'r.json').write_text(json.dumps(rows))
            with unittest.mock.patch('sys.stdout'):return c.main(['report',str(d/'r.json')])
        base={'id':'x','arch':'amd64','base':'a','adds':[],'unchecked':[],'world_edits':[]}
        self.assertEqual(report([dict(base,result=c.PASS),dict(base,result=c.UNCHECKED,reason='r'),dict(base,result=c.SKIPPED,reason='r')]),0)
        self.assertEqual(report([dict(base,result=c.FAIL,reason='r',stale=[],apk_output='E')]),1)
        self.assertEqual(report([dict(base,result=c.UNCHECKED,reason='cannot pull',error=True)]),1)
    def test_only_an_add_on_without_this_arch_is_an_empty_result_and_an_unknown_id_an_error(self):
        # The aarch64 job of a manual run for an amd64-only add-on succeeds with no rows; the report then has amd64's.
        d=self.store();(d/'registry.json').write_text(json.dumps(REGISTRY))
        def check(only,arch):
            with unittest.mock.patch('sys.stdout'):
                return c.main(['check','--registry',str(d/'registry.json'),'--store',str(d),'--arch',arch,'--only',only,'--out',str(d/f'{arch}.json')])
        self.assertEqual(check('plain','aarch64'),0);self.assertEqual(json.loads((d/'aarch64.json').read_text()),[])
        self.assertEqual(check('plain','amd64'),0)
        with unittest.mock.patch('sys.stdout'):self.assertEqual(c.main(['report',str(d/'amd64.json'),str(d/'aarch64.json')]),0)
        for arch in c.ARCHES:self.assertEqual(check('nope',arch),2);self.assertEqual(check('beta',arch),2)
    def test_a_bad_registry_is_a_tool_error(self):
        d=self.addon({'registry.json':'{"providers": []}'})
        with unittest.mock.patch('sys.stdout'):self.assertEqual(c.main(['check','--registry',str(d/'registry.json'),'--store',str(d),'--arch','amd64','--out',str(d/'o.json')]),2)

OPENDESIGN_REGISTRY={'providers':{'o/od':{'components':[{'id':'opendesign','store_path':'od','config_file':'config.yaml','channel':'stable','enabled':True}]}}}

class Install(Addon):
    """After a simulate that passes, the same packages are installed once for real: a file conflict is cannot install (#246)."""
    def row(self,dockerfile=OPENDESIGN_DOCKERFILE,arch='amd64'):
        d=self.addon({'od/config.yaml':json.dumps({'version':'1.0.0','arch':['amd64','aarch64']}),'od/Dockerfile':dockerfile})
        return c.plan(OPENDESIGN_REGISTRY,d,(arch,))[0]
    def test_regression_241_a_file_conflict_cannot_install(self):
        row=self.row()
        docker=FakeDocker({row['base']:output(sim='OK: 1037.7 MiB in 324 packages',policy=TTYD_POLICY,install=(CONFLICT_241,1))})
        got=c.run_rows([row],'amd64',docker=docker)[0]
        self.assertEqual(got['result'],c.FAIL);self.assertFalse(got.get('error'));self.assertEqual(got['exit'],0)
        self.assertEqual(got['conflicts'],[{'package':'python3-ndbm-3.14.10-r2','path':NDBM_SO,'owner':'python3-3.14.10-r1'}])
        self.assertIn('file conflict',got['reason']);self.assertIn('python3-ndbm-3.14.10-r2',got['reason']);self.assertIn(NDBM_SO,got['reason'])
        self.assertEqual((got['install_exit'],got['install_output']),(1,CONFLICT_241));self.assertNotIn('approximate',got)
        text=c.summary([got])
        self.assertIn('| opendesign | amd64 |',text);self.assertIn('| cannot install |',text)
        self.assertIn(f'ERROR: python3-ndbm-3.14.10-r2: trying to overwrite {NDBM_SO} owned by python3-3.14.10-r1.',text)
        body=c.issue_body('opendesign',[got])
        for want in ('file conflict','`apk add --simulate` passed','`python3-ndbm-3.14.10-r2`',f'`{NDBM_SO}`','`python3-3.14.10-r1`',
                f'ERROR: python3-ndbm-3.14.10-r2: trying to overwrite {NDBM_SO}','`apk add` output:'):self.assertIn(want,body)
        for bad in ('/home/','/tmp/','runner','.addon-sync'):self.assertNotIn(bad,body)
        gh=FakeGitHub();self.assertEqual(c.sync_issues(gh,'o/r',[got]),[('open','opendesign',None)])
    def test_every_file_of_a_conflict_is_listed(self):
        # apk 2.14.13 and 3.0.9: one ERROR line per file, one "1 error;" line for the package.
        two=('(1/1) Installing multi-b (1.0-r0)\nERROR: multi-b-1.0-r0: trying to overwrite usr/share/multi/one.txt owned by multi-a-1.0-r0.\n'
            'ERROR: multi-b-1.0-r0: trying to overwrite usr/share/multi/two.txt owned by multi-a-1.0-r0.\n1 error; 7 MiB in 17 packages')
        got=c.evaluate(self.row(),c.parse_output(output(install=(two,1))))
        self.assertEqual(got['result'],c.FAIL)
        self.assertEqual([x['path'] for x in got['conflicts']],['usr/share/multi/one.txt','usr/share/multi/two.txt'])
    def test_an_install_that_fails_otherwise_is_a_tool_error(self):
        # apk's own text for a failing install script (apk 3.0.9; 2.14.13 and 2.12.9) and a package gone between the
        # simulate and the install; then, shaped like apk's, a download that failed, a conflict next to another error, no
        # ERROR at all.
        row=self.row()
        conflict=f'ERROR: python3-ndbm-3.14.10-r2: trying to overwrite {NDBM_SO} owned by python3-3.14.10-r1.'
        for text,code in (('(1/1) Installing badscript (1.0-r0)\n  Executing badscript-1.0-r0.post-install\n  * failing on purpose\n'
                    'ERROR: lib/apk/exec/badscript-1.0-r0.post-install: exited with error 1\n1 error; 8212 KiB in 17 packages',1),
                ('Executing badscript-1.0-r0.post-install\nfailing on purpose\nERROR: badscript-1.0-r0.post-install: script exited with error 1\n1 error; 7 MiB in 16 packages',1),
                ('ERROR: unable to select packages:\n  ttyd (no such package):\n    required by: world[ttyd=1.7.7-r0]',1),
                ('ERROR: nginx-1.30.7-r0: network error (check Internet connection and firewall)\n1 error; 7 MiB in 16 packages',1),
                (conflict+'\nERROR: Failed to commit changes: No space left on device\n1 error; 7 MiB in 16 packages',1),
                ('Segmentation fault',139)):
            got=c.evaluate(row,c.parse_output(output(install=(text,code))))
            self.assertEqual(got['result'],c.UNCHECKED,text);self.assertTrue(got.get('error'),text)
            self.assertIn('the install failed without a file conflict',got['reason'])
            self.assertEqual(c.sync_issues(FakeGitHub(),'o/r',[got]),[])
    def test_an_install_that_passes_keeps_the_simulate_result(self):
        row=self.row()
        self.assertEqual(c.evaluate(row,c.parse_output(output()))['result'],c.PASS)
        unread=dict(row,unchecked=[{'file':'Dockerfile','line':3,'text':'apk add $X','reason':'$X has no value'}])
        self.assertEqual(c.evaluate(unread,c.parse_output(output()))['result'],c.UNCHECKED)
        self.assertEqual(c.evaluate(unread,c.parse_output(output(install=(CONFLICT_241,1))))['result'],c.FAIL)
    def test_a_simulate_that_fails_installs_nothing(self):
        # The script itself, in sh, with a stand-in apk: the simulate fails, so no apk add without --simulate runs.
        d=self.addon({'r/etc/alpine-release':'3.24.1\n','r/lib/apk/db/installed':'','r/etc/apk/world':'musl\n',
            'bin/apk':'#!/bin/sh\necho "$*" >> "$(dirname "$0")/calls"\n'
                'case " $* " in *" policy "*) ;; *" --simulate "*) echo "ERROR: unable to select packages:"; echo "  ttyd-1.7.8-r0:"; '
                'echo "    breaks: world[ttyd=1.7.7-r0]"; exit 1;; *) echo INSTALLED;; esac\n'})
        (d/'bin/apk').chmod(0o755)
        row=self.row()
        text=subprocess.run(['sh','-c',c.container_script(row,str(d/'r'))],capture_output=True,text=True,env=dict(os.environ,PATH=f'{d/"bin"}:{os.environ["PATH"]}')).stdout
        calls=(d/'bin/calls').read_text().splitlines()
        self.assertEqual([l for l in calls if ' add ' in f' {l} ' and '--simulate' not in l],[]);self.assertNotIn('INSTALLED',text)
        parsed=c.parse_output(text);self.assertTrue(parsed['complete']);self.assertIsNone(parsed['install_exit'])
        got=c.evaluate(row,parsed)
        self.assertEqual((got['result'],got['reason']),(c.FAIL,'apk add --simulate failed'));self.assertNotIn('conflicts',got)
        self.assertNotIn('approximate',c.evaluate(row,parsed,rootfs=True))
    def test_the_install_runs_after_the_simulate_in_the_same_script(self):
        d=self.addon({'r/etc/alpine-release':'3.24.1\n','r/lib/apk/db/installed':'','r/etc/apk/world':'musl\n',
            'bin/apk':'#!/bin/sh\ncase " $* " in *" policy "*) ;; *" --simulate "*) echo OK;; *) '
                f'echo "ERROR: python3-ndbm-3.14.10-r2: trying to overwrite {NDBM_SO} owned by python3-3.14.10-r1."; echo "1 error; 1 MiB in 2 packages"; exit 1;; esac\n'})
        (d/'bin/apk').chmod(0o755)
        row=self.row()
        text=subprocess.run(['sh','-c',c.container_script(row,str(d/'r'))],capture_output=True,text=True,env=dict(os.environ,PATH=f'{d/"bin"}:{os.environ["PATH"]}')).stdout
        parsed=c.parse_output(text)
        self.assertEqual((parsed['exit'],parsed['install_exit']),(0,1));self.assertEqual(parsed['simulate'],'OK')
        self.assertEqual(c.evaluate(row,parsed)['result'],c.FAIL)
    def test_install_flags_native_and_rootfs(self):
        row=self.row('FROM a/b:1\nRUN apk add --no-cache --upgrade -X https://example.invalid/edge/testing nginx ttyd=1.7.7-r0\n')
        native=c.container_script(row)
        self.assertIn("apk add --simulate --no-cache --upgrade -X https://example.invalid/edge/testing nginx ttyd=1.7.7-r0 2>&1",native)
        self.assertIn("apk add --no-cache --upgrade -X https://example.invalid/edge/testing nginx ttyd=1.7.7-r0 2>&1",native)
        self.assertNotIn('--no-scripts',native)
        # Policy reads the repository and the base before the install changes the base.
        self.assertLess(native.index('@@POLICY'),native.index('@@INSTALL'))
        rootfs=c.container_script(row,'/r')
        self.assertIn('apk --root /r --arch x86_64 add --no-cache --upgrade -X https://example.invalid/edge/testing --no-scripts nginx ttyd=1.7.7-r0 2>&1',rootfs)
        self.assertEqual(rootfs.count('--no-scripts'),1)
    def test_rootfs_mode_is_flagged_approximate(self):
        row=self.row(arch='aarch64')
        for mode,outputs in (('rootfs',{('rootfs',row['base']):output()}),('native',{row['base']:output(apk=False),('rootfs',row['base']):output()})):
            got=c.run_rows([row],'aarch64',mode,docker=FakeDocker(outputs))[0]
            self.assertEqual(got['result'],c.PASS,mode);self.assertIn('--no-scripts',got['approximate'])
            self.assertIn('approximate',c.summary([got]))
        native=c.run_rows([row],'aarch64',docker=FakeDocker({row['base']:output()}))[0]
        self.assertNotIn('approximate',native);self.assertNotIn('--no-scripts',c.summary([native]).split('|---|')[-1])
        conflict=c.run_rows([row],'aarch64','rootfs',docker=FakeDocker({('rootfs',row['base']):output(install=(CONFLICT_241,1))}))[0]
        self.assertEqual(conflict['result'],c.FAIL);self.assertIn('approximate',c.issue_body('opendesign',[conflict]))
    def test_output_cut_off_during_the_install_did_not_finish(self):
        text=output(install=('(1/6) Installing nginx (1.30.7-r0)',0),end=False).replace('@@INSTALLEXIT 0\n','')
        parsed=c.parse_output(text);self.assertFalse(parsed['complete'])
        got=c.evaluate(self.row(),parsed)
        self.assertEqual((got['result'],got['reason'],got['error']),(c.UNCHECKED,'the check did not finish in the base image',True))
        # Complete, but no exit code of the install after a simulate that passed: not a pass either.
        got=c.evaluate(self.row(),c.parse_output(output(install=None)))
        self.assertEqual(got['result'],c.UNCHECKED);self.assertTrue(got['error'])

class FakeGitHub:
    """Issues of one repository, in memory, behind addon_sync.GitHub's api()."""
    def __init__(self,issues=()):self.issues=[dict(i) for i in issues];self.writes=[]
    def api(self,repo,path,data=None,method=None):
        if method is None:
            page=int(path.rsplit('page=',1)[1])
            return [i for i in self.issues if i['state']=='open'][(page-1)*100:page*100]
        self.writes.append((method,path,data))
        if path=='issues':self.issues.append(dict(data,number=len(self.issues)+1,state='open'));return self.issues[-1]
        n=int(path.split('/')[1]);issue=next(i for i in self.issues if i['number']==n)
        if path.endswith('/comments'):return {}
        issue.update(data);return issue

def failing(cid='tailscale',arch='amd64',out='breaks: world[nginx=1.30.6-r0]'):
    return {'id':cid,'arch':arch,'base':'ghcr.io/hassio-addons/base/amd64:21.0.2','alpine':'3.24.1','result':c.FAIL,'apk_output':out,
            'stale':[{'spec':'nginx=1.30.6-r0','source':'apk add','available':['1.30.7-r0'],'installed':[]}]}

class Issues(unittest.TestCase):
    def test_first_failure_opens_second_updates_pass_closes(self):
        gh=FakeGitHub([{'number':1,'title':'unrelated','body':'','state':'open'},{'number':2,'title':'a PR','body':'','state':'open','pull_request':{}}])
        self.assertEqual(c.sync_issues(gh,'o/r',[failing(),dict(failing(),arch='aarch64')]),[('open','tailscale',None)])
        issue=gh.issues[-1];self.assertEqual(issue['title'],'apk pin check: tailscale cannot install its packages')
        for text in ('`nginx=1.30.6-r0`','1.30.7-r0','breaks: world[nginx=1.30.6-r0]','### aarch64'):self.assertIn(text,issue['body'])
        self.assertEqual(c.sync_issues(gh,'o/r',[failing(),dict(failing(),arch='aarch64')]),[('unchanged','tailscale',3)])
        self.assertEqual(c.sync_issues(gh,'o/r',[failing(out='ERROR: other')]),[('update','tailscale',3)])
        self.assertIn('ERROR: other',gh.issues[-1]['body']);self.assertNotIn('### aarch64',gh.issues[-1]['body'])
        self.assertEqual(sum(1 for i in gh.issues if i['title'].startswith('apk pin check')),1)
        self.assertEqual(c.sync_issues(gh,'o/r',[dict(failing(),result=c.PASS)],today='2026-11-25'),[('close','tailscale',3)])
        self.assertEqual(gh.issues[-1]['state'],'closed');self.assertIn(('POST','issues/3/comments',{'body':'The apk pin check passed on 2026-11-25: every package of tailscale installs again. Closing.'}),gh.writes)
        self.assertEqual(c.sync_issues(gh,'o/r',[dict(failing(),result=c.PASS)]),[])
    def test_tool_errors_and_add_ons_not_checked_leave_issues_alone(self):
        gh=FakeGitHub([{'number':5,'title':c.issue_title('a'),'body':'','state':'open'},{'number':6,'title':'x','body':c.issue_body('b',[]),'state':'open'}])
        self.assertEqual(c.sync_issues(gh,'o/r',[{'id':'a','arch':'amd64','result':c.UNCHECKED,'error':True}]),[])
        # Closed only when every row of the add-on passes: one not checked or skipped has not shown it installs again.
        for rows in ([{'id':'b','arch':'amd64','result':c.SKIPPED}],[{'id':'b','arch':'amd64','result':c.UNCHECKED}],
                [{'id':'b','arch':'amd64','result':c.PASS},{'id':'b','arch':'aarch64','result':c.UNCHECKED}]):
            self.assertEqual(c.sync_issues(gh,'o/r',rows),[],rows)
        self.assertEqual(gh.writes,[])
        self.assertEqual(c.sync_issues(gh,'o/r',[{'id':'b','arch':'amd64','result':c.PASS},{'id':'b','arch':'aarch64','result':c.PASS}],dry_run=True),[('close','b',6)])
    def test_issue_text_has_no_runner_paths(self):
        body=c.issue_body('tailscale',[failing()])
        for bad in ('/home/','/tmp/','runner','.addon-sync'):self.assertNotIn(bad,body)

@needs_store
class RealStore(unittest.TestCase):
    """Without docker: the Store registry's shipped add-ons all plan, each arch gets a row."""
    def test_every_shipped_add_on_and_arch_has_a_row(self):
        import yaml
        registry=json.loads((HERE/'registry.json').read_text())
        rows=c.plan(registry,STORE)
        expected=[]
        for _,comp in c.shipped(registry):
            config=yaml.safe_load((STORE/comp['store_path']/comp['config_file']).read_text())
            expected+=[(comp['id'],a) for a in c.ARCHES if a in config['arch']]
        self.assertEqual([(r['id'],r['arch']) for r in rows],expected)
        self.assertNotIn('woow_mcp_opendesign',{r['id'] for r in rows})

import unittest.mock
if __name__=='__main__':unittest.main()
