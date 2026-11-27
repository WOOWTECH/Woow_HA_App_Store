import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
const root=path.resolve(import.meta.dirname,'..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');
const manifest=JSON.parse(read('paseo-runtime/VENDOR.json'));

test('shared runtime archive and separately retained npm lock match the reviewed source pin',()=>{
 for(const [name,expected] of [['package.tgz',manifest.archive_sha256],['package-lock.json',manifest.lock_sha256]]){
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'paseo-runtime',name))).digest('hex'),expected);
  assert.ok(read('paseo-runtime/checksums.sha256').includes(`${expected}  ${name}`));
 }
 assert.match(manifest.commit,/^[0-9a-f]{40}$/);assert.equal(manifest.version,'0.3.0');assert.equal(manifest.paseo_cli_version,'0.17.5');
 const archive=spawnSync('tar',['-xOzf',path.join(root,'paseo-runtime/package.tgz'),'package/package.json'],{encoding:'utf8'});
 assert.equal(archive.status,0,archive.stderr);const pkg=JSON.parse(archive.stdout);
 const launcher=spawnSync('tar',['-xOzf',path.join(root,'paseo-runtime/package.tgz'),'package/launcher/open-design.json'],{encoding:'utf8'});
 assert.equal(launcher.status,0,launcher.stderr);const launcherManifest=JSON.parse(launcher.stdout);
 const lock=JSON.parse(read('paseo-runtime/package-lock.json'));
 assert.equal(pkg.version,manifest.version);assert.equal(lock.packages[''].version,pkg.version);
 assert.equal(launcherManifest.title,'Agent Connect');assert.equal(launcherManifest.version,pkg.version);
 assert.deepEqual(lock.packages[''].dependencies,pkg.dependencies);
 const listed=spawnSync('tar',['-tzf',path.join(root,'paseo-runtime/package.tgz')],{encoding:'utf8'});
 assert.equal(listed.status,0);
 for(const file of ['host/ha-ingress.mjs','host/standalone.mjs','bin/serve.mjs','bin/supervise.mjs','bin/mcp.mjs','src/flock-helper.py','scripts/prepare-managed-runtime.mjs','scripts/smoke-managed-runtime.mjs','vendor/pi-paseo/runtime/package-lock.json'])assert.ok(listed.stdout.split('\n').includes('package/'+file));
 const preparer=spawnSync('tar',['-xOzf',path.join(root,'paseo-runtime/package.tgz'),'package/scripts/prepare-managed-runtime.mjs'],{encoding:'utf8'});
 assert.equal(preparer.status,0,preparer.stderr);
 for(const fragment of ["['ci', '--prefix', root, '--omit=dev', '--ignore-scripts'","['rebuild', '--prefix', root, 'node-pty', '--ignore-scripts=false'","npm_config_build_from_source: 'true'","pty.spawn('/bin/sh",'markRuntimeReady(loc)'])assert.ok(preparer.stdout.includes(fragment),fragment);
 assert.ok(preparer.stdout.indexOf('pty.spawn')<preparer.stdout.indexOf('markRuntimeReady(loc)'));
 assert.doesNotMatch(listed.stdout,/node_modules|browser-auth|\.private|\/preload\.mjs/);
});

test('HA installation aligns native launch metadata, verifies core capabilities and keeps runtime code immutable',()=>{
 const install=read('paseo-runtime/install.sh');
 for(const fragment of ['sha256sum -c','npm ci --omit=dev --ignore-scripts','scripts/prepare-managed-runtime.mjs','managed-runtime','verifyBundledInstallation','/app/apps/daemon/dist/routes/mcp-servers.js','registerMcpServerRoutes','chown -R root:root'])assert.ok(install.includes(fragment),fragment);
 assert.doesNotMatch(install,/cp .*\/app\//);
 assert.ok(install.includes('install -m 0644 /opt/opendesign-paseo/launcher/open-design.json /opt/opendesign-paseo/launcher/SKILL.md /app/plugins/_official/woow/woow-paseo/'));
 assert.ok(read('Dockerfile').includes('sh /tmp/paseo-runtime/install.sh'));
 for(const fragment of ['.agent-connect-build build-base python3','apk del .agent-connect-build'])assert.ok(read('Dockerfile').includes(fragment),fragment);
});

test('bridge is a required same-container child with persistent state and a private nginx socket',()=>{
 const launcher=read('rootfs/usr/local/bin/ha-opendesign');
 for(const fragment of ['"$DATA_DIR/paseo"','chmod 0700 "$DATA_DIR/paseo"','prepare_owned_dir /run/ha-opendesign-paseo open-design:ha-ingress','chmod 2750 /run/ha-opendesign-paseo','start_child paseo','su-exec open-design:open-design /usr/bin/env','OPENDESIGN_PASEO_TRANSPORT=ha-ingress','OPENDESIGN_PASEO_NATIVE_PORT=7456 OPENDESIGN_PASEO_AUTO_ENABLE=1','/opt/opendesign-paseo/bin/serve.mjs'])assert.ok(launcher.includes(fragment),fragment);
 assert.match(fs.readFileSync('paseo-runtime/install.sh','utf8'),/chmod -R a\+rX,go-w \/opt\/opendesign-paseo\/managed-runtime/,
   'root-built managed runtime and its 0600 receipt must be readable by UID 1001 without becoming writable');
 const outer = Number(read('config.yaml').match(/^timeout: (\d+)$/m)?.[1]);
 const inner = Number(launcher.match(/readonly SHUTDOWN_GRACE_SECONDS=(\d+)/)?.[1]);
 assert.ok(inner >= 25 && outer >= inner + 5, 'Supervisor must allow native cleanup plus a stop margin');
 assert.doesNotMatch(read('config.yaml'),/7460|host_pid|host_network/);
 const proxy=read('rootfs/etc/nginx/paseo-proxy.conf');
 assert.match(proxy,/allow 172\.30\.32\.2;\ndeny all;/);
 assert.match(proxy,/proxy_pass_request_headers off;/);
 assert.match(proxy,/proxy_set_header X-OD-HA-Peer \$remote_addr;/);
 assert.match(proxy,/proxy_set_header Host \$http_host;/);
 assert.doesNotMatch(proxy,/^(?:proxy_set_header (?:Forwarded|X-Forwarded)|real_ip_header)/m);
});
