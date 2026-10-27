// Build-time only: install both immutable, public release artifacts before
// creating the HA image. No model accounts or live daemon are required here.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
const bundle = process.argv[2] || '/opt/woow/pi-paseo-plugin';
const runtimeDir = process.argv[3] || '/opt/woow/paseo-runtime';
const stateDir = process.argv[4] || '/opt/woow/paseo-web';
const pkg = JSON.parse(fs.readFileSync(path.join(bundle, 'package.json')));
if (pkg.name !== '@woowtech/pi-paseo' || pkg.version !== '0.1.12') throw new Error('Unsupported Paseo package');
const layout = await import(pathToFileURL(path.join(bundle, 'src/runtime-layout.mjs')).href);
const web = await import(pathToFileURL(path.join(bundle, 'src/web-client.mjs')).href);
const loc = { runtimeDir, stateDir };
const target = layout.prepareRuntimeManifest(loc);
execFileSync('npm', ['ci', '--omit=dev', '--no-audit', '--no-fund', '--prefix', target], { stdio: 'inherit', timeout: 600000 });
// npm's optional OS/CPU matching also installs the musl Claude SDK executable
// on Debian. Keep its glibc sibling; the unused musl binary adds ~230 MiB.
if (process.platform !== 'linux' || !process.report.getReport().header.glibcVersionRuntime) throw new Error('HA runtime requires Linux glibc');
const nativeSdk = path.join(target, 'node_modules/@anthropic-ai');
if (!fs.existsSync(path.join(nativeSdk, `claude-agent-sdk-linux-${process.arch}`))) throw new Error('Missing native Claude SDK');
fs.rmSync(path.join(nativeSdk, `claude-agent-sdk-linux-${process.arch}-musl`), { recursive: true, force: true });
layout.markRuntimeReady(loc);
if (layout.RUNTIME_REVISION !== '0.11.2-r3-6d8dbe515479') throw new Error('Unsupported Paseo runtime revision');
await web.ensureWebClient(loc);
if (!layout.runtimeReady(loc) || !web.webClientStatus(loc).ready) throw new Error('Paseo image preparation failed');
console.log(JSON.stringify({ plugin: pkg.version, runtime: layout.RUNTIME_REVISION, web: web.webClientStatus(loc) }));
