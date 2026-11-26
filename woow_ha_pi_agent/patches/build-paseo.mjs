// Build-time only: install the immutable, public Paseo daemon runtime before
// creating the HA image. No model accounts or live daemon are required here.
// The plugin carries no web client (every connection target opens its official
// site), so nothing but the runtime is prepared.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
const bundle = process.argv[2] || '/opt/woow/pi-paseo-plugin';
const runtimeDir = process.argv[3] || '/opt/woow/paseo-runtime';
// What the vendored archive must be. The Dockerfile reads both values from
// cli-runtime/versions.json (agentConnect); they are never repeated here.
const expectedVersion = process.env.PI_PASEO_EXPECTED_VERSION;
const expectedRuntimeRevision = process.env.PI_PASEO_EXPECTED_RUNTIME_REVISION;
if (!expectedVersion || !expectedRuntimeRevision) throw new Error('PI_PASEO_EXPECTED_VERSION and PI_PASEO_EXPECTED_RUNTIME_REVISION are required');
const pkg = JSON.parse(fs.readFileSync(path.join(bundle, 'package.json')));
if (pkg.name !== '@woowtech/pi-paseo' || pkg.version !== expectedVersion) throw new Error('Unsupported Paseo package');
const layout = await import(pathToFileURL(path.join(bundle, 'src/runtime-layout.mjs')).href);
if (layout.RUNTIME_REVISION !== expectedRuntimeRevision) throw new Error('Unsupported Paseo runtime revision');
const loc = { runtimeDir };
const target = layout.prepareRuntimeManifest(loc);
execFileSync('npm', ['ci', '--omit=dev', '--no-audit', '--no-fund', '--prefix', target], { stdio: 'inherit', timeout: 600000 });
// npm's optional OS/CPU matching also installs the musl Claude SDK executable
// on Debian. Keep its glibc sibling; the unused musl binary adds ~230 MiB.
if (process.platform !== 'linux' || !process.report.getReport().header.glibcVersionRuntime) throw new Error('HA runtime requires Linux glibc');
const nativeSdk = path.join(target, 'node_modules/@anthropic-ai');
if (!fs.existsSync(path.join(nativeSdk, `claude-agent-sdk-linux-${process.arch}`))) throw new Error('Missing native Claude SDK');
fs.rmSync(path.join(nativeSdk, `claude-agent-sdk-linux-${process.arch}-musl`), { recursive: true, force: true });
layout.markRuntimeReady(loc);
if (!layout.runtimeReady(loc)) throw new Error('Paseo image preparation failed');
console.log(JSON.stringify({ plugin: pkg.version, runtime: layout.RUNTIME_REVISION }));
