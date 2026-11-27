// Pi Web 0.12.0 is published as compiled Next.js output, not TSX sources.
// Source mapping: npm gitHead e8d91efdcedf2a37a2ca0a31c2a6df9c30a4eb93,
// components/SettingsPanel.tsx and lib/settings-navigation.ts.
// Patch React's section list/renderer in BOTH client and SSR bundles. Never
// mutate React-owned DOM or guess a hashed filename. Unknown builds fail closed
// before either file is written, even if the npm version is unchanged.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const marker = '\n/* woow-ha-omnigent-agent-connect-settings-v4 */\n';
const sections = '["general","models","skills","agents","plugins","mcp"]';
const expanded = '["general","models","skills","agents","plugins","mcp","omnigent","paseo"]';
const prefix = '(typeof window==="undefined"?"":window.__INGRESS_PATH__||"")';
// nginx also rewrites quoted "/icons/" in JavaScript. Keep this literal split
// so the compiled client does not receive the ingress prefix twice.
const iconBase = prefix + '+"/icon"+"s/catppuccin"';
const frame = '(0,r.jsx)("iframe",{title:"Omnigent",src:' + prefix + '+"/omnigent?embedded=1",style:{display:"block",width:"100%",height:"100%",border:0},referrerPolicy:"no-referrer"})';
const paseoFrame = frame.replaceAll("Omnigent", "Agent Connect").replace("/omnigent?", "/paseo/setup?");
const specs = {
  client: {
    sha256: 'ac18c04848bead1a116f08abbd88b705e42bc6680e1b44af6b070bb865eed560',
    replacements: [
      ['"/icons/catppuccin"', iconBase],
      [sections, expanded],
      ['{id:"mcp",label:h("settings.mcp")}', '{id:"mcp",label:h("settings.mcp")},{id:"omnigent",label:"Omnigent"},{id:"paseo",label:"Agent Connect"}'],
      ['k("mcp",(0,r.jsx)(mb,{embedded:!0,cwd:t,trust:d,onTrustProject:u,onProjectTrustChanged:p,onClose:s},t??""))',
        'k("mcp",(0,r.jsx)(mb,{embedded:!0,cwd:t,trust:d,onTrustProject:u,onProjectTrustChanged:p,onClose:s},t??"")),f==="omnigent"&&k("omnigent",' + frame + '),f==="paseo"&&k("paseo",' + paseoFrame + ')'],
    ],
  },
  server: {
    sha256: '20af3728b46f5a2af6cc895dba58819f6f01a36a32489a64e42214e20b4b8a2a',
    replacements: [
      ['"/icons/catppuccin"', iconBase],
      [sections, expanded],
      ['{id:"mcp",label:k("settings.mcp")}', '{id:"mcp",label:k("settings.mcp")},{id:"omnigent",label:"Omnigent"},{id:"paseo",label:"Agent Connect"}'],
      ['u("mcp",(0,r.jsx)(zH,{embedded:!0,cwd:a,trust:h,onTrustProject:i,onProjectTrustChanged:j,onClose:d},a??""))',
        'u("mcp",(0,r.jsx)(zH,{embedded:!0,cwd:a,trust:h,onTrustProject:i,onProjectTrustChanged:j,onClose:d},a??"")),l==="omnigent"&&u("omnigent",' + frame + '),l==="paseo"&&u("paseo",' + paseoFrame + ')'],
    ],
  },
};
// References include the pre-rendered HTML and RSC, not just the JS manifest.
// Keep the hash width unchanged so length-prefixed flight content stays valid.
const oldName = 'page-5309ff419b280c46.js';
const references = [
  ['index.html', 'af51784f4d2752c9088169eb337bbc8e3afac89dd30edeaf548f813318519ffd'],
  ['_global-error/page_client-reference-manifest.js', '0df7ac2048acb2116d1f8bc8541eecfcafa2ac0acc98f38ffafdfacceb08ce76'],
  ['_not-found/page_client-reference-manifest.js', 'd149504ff56c736d011c487426527694232b601afa2c4d6acaaa1d7876773acb'],
  ['login/page_client-reference-manifest.js', 'e3a1676790674436a0a366032bf2527d871205c29a82c20f22f5b66f28d1b232'],
  ['page_client-reference-manifest.js', '6143099aaa16ea3c5ff772f08da6170dac54f3b3c9fe2ae5b439d58be98a087a'],
  ['index.segments/__PAGE__.segment.rsc', '6c53201a6a69dd49a1d35ffee2fec6fe5ec2c2c9299ad5e3aebf3c1a6e72c4b9'],
  ['index.segments/_full.segment.rsc', '286087d203e99851eca115d11a91843e1dc1f540e387afb5f70f1e3ec25c532a'],
  ['index.rsc', '286087d203e99851eca115d11a91843e1dc1f540e387afb5f70f1e3ec25c532a'],
];
// Read-only view for patches/print-compiled-settings-pins.mjs, which reports every
// build-derived value above after a Pi Web, lockfile or build-root change.
export const COMPILED_PIN_TABLE = Object.freeze({ specs, oldName, references });
const hash = text => createHash('sha256').update(text).digest('hex');
function replaceOnce(text, from, to) {
  if (text.split(from).length !== 2) throw new Error('Omnigent settings: expected exactly one source anchor');
  return text.replace(from, to);
}
function transform(source, spec) {
  if (source.endsWith(marker)) {
    let original = source.slice(0, -marker.length);
    for (const [from, to] of [...spec.replacements].reverse()) original = replaceOnce(original, to, from);
    if (hash(original) !== spec.sha256) throw new Error('Omnigent settings: patched artifact has changed');
    return source;
  }
  const actualHash = hash(source);
  if (actualHash !== spec.sha256) throw new Error(`Omnigent settings: unsupported compiled artifact (expected ${spec.sha256}, got ${actualHash}); revalidate the Pi Web build`);
  for (const [from, to] of spec.replacements) source = replaceOnce(source, from, to);
  return source + marker;
}

export function patchSettings(root) {
  const meta = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  if (meta.name !== '@agegr/pi-web' || meta.version !== '0.12.0') throw new Error('Omnigent settings requires @agegr/pi-web 0.12.0');
  const chunks = path.join(root, '.next/static/chunks');
  const candidates = fs.readdirSync(chunks, { recursive: true })
    .filter(file => file.endsWith('.js'))
    .map(file => path.join(chunks, file))
    .filter(file => fs.readFileSync(file, 'utf8').includes('className:"settings-section-tabs"'));
  if (candidates.length !== 1) throw new Error('Omnigent settings: expected one client SettingsPanel');
  const targets = [[candidates[0], specs.client], [path.join(root, '.next/server/app/page.js'), specs.server]];
  const planned = targets.map(([file, spec]) => {
    if (!fs.lstatSync(file).isFile()) throw new Error('Omnigent settings: target must be a regular file');
    const before = fs.readFileSync(file, 'utf8');
    return { file, before, after: transform(before, spec) };
  });
  const newName = `page-${hash(planned[0].after).slice(0, 16)}.js`;
  const alreadyPatched = path.basename(planned[0].file) === newName;
  if (!alreadyPatched && path.basename(planned[0].file) !== oldName) throw new Error('Unexpected client artifact name');
  for (const [relative, checksum] of references) {
    const file = path.join(root, '.next/server/app', relative);
    if (!fs.lstatSync(file).isFile()) throw new Error('Settings reference must be a regular file');
    const before = fs.readFileSync(file, 'utf8');
    const original = alreadyPatched ? before.replaceAll(newName, oldName) : before;
    const actualHash = hash(original);
    if (actualHash !== checksum) throw new Error(`Omnigent settings: incompatible asset reference ${relative} (expected ${checksum}, got ${actualHash})`);
    planned.push({ file, before, after: original.replaceAll(oldName, newName) });
  }
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-settings-syntax-'));
  try {
    for (const [index, item] of planned.entries()) {
      if (!item.file.endsWith('.js')) continue;
      const file = path.join(temporary, `${index}.js`); fs.writeFileSync(file, item.after);
      const check = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
      if (check.status !== 0) throw new Error(`Omnigent settings syntax preflight failed: ${check.stderr}`);
    }
  } finally { fs.rmSync(temporary, { recursive: true, force: true }); }
  // Both compatibility and syntax preflights succeeded. This runs only while
  // building the image, before Next.js starts; partial output is never served.
  for (const { file, before, after } of planned) if (before !== after) fs.writeFileSync(file, after);
  const newFile = path.join(path.dirname(planned[0].file), newName);
  if (!alreadyPatched) fs.renameSync(planned[0].file, newFile);
  planned[0].file = newFile;
  return planned.map(({ file, before, after }) => ({ file: path.relative(root, file), changed: before !== after, sha256: hash(after) }));
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  if (!process.argv[2]) throw new Error('Usage: node patch-omnigent-settings.mjs /path/to/@agegr/pi-web');
  console.log(JSON.stringify(patchSettings(path.resolve(process.argv[2])), null, 2));
}
