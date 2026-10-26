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

const marker = '\n/* woow-ha-omnigent-paseo-settings-v2 */\n';
const sections = '["general","models","skills","agents","plugins","mcp"]';
const expanded = '["general","models","skills","agents","plugins","mcp","omnigent","paseo"]';
const prefix = '(typeof window==="undefined"?"":window.__INGRESS_PATH__||"")';
const frame = '(0,r.jsx)("iframe",{title:"Omnigent",src:' + prefix + '+"/omnigent?embedded=1",style:{display:"block",width:"100%",height:"100%",border:0},referrerPolicy:"no-referrer"})';
const paseoFrame = frame.replaceAll("Omnigent", "Paseo").replace("/omnigent?", "/paseo/setup?");
const specs = {
  client: {
    sha256: 'f273303c76f7ab856768e315526cdc7cd485fba7f930e649337c57289d96093f',
    replacements: [
      [sections, expanded],
      ['{id:"mcp",label:h("settings.mcp")}', '{id:"mcp",label:h("settings.mcp")},{id:"omnigent",label:"Omnigent"},{id:"paseo",label:"Paseo"}'],
      ['k("mcp",(0,r.jsx)(mb,{embedded:!0,cwd:t,trust:d,onTrustProject:u,onProjectTrustChanged:p,onClose:s},t??""))',
        'k("mcp",(0,r.jsx)(mb,{embedded:!0,cwd:t,trust:d,onTrustProject:u,onProjectTrustChanged:p,onClose:s},t??"")),f==="omnigent"&&k("omnigent",' + frame + '),f==="paseo"&&k("paseo",' + paseoFrame + ')'],
    ],
  },
  server: {
    sha256: 'a1205fad45252a602e50e13a3c5c2fd21c7968b002d54ad939984052953a2d71',
    replacements: [
      [sections, expanded],
      ['{id:"mcp",label:k("settings.mcp")}', '{id:"mcp",label:k("settings.mcp")},{id:"omnigent",label:"Omnigent"},{id:"paseo",label:"Paseo"}'],
      ['u("mcp",(0,r.jsx)(zG,{embedded:!0,cwd:a,trust:h,onTrustProject:i,onProjectTrustChanged:j,onClose:d},a??""))',
        'u("mcp",(0,r.jsx)(zG,{embedded:!0,cwd:a,trust:h,onTrustProject:i,onProjectTrustChanged:j,onClose:d},a??"")),l==="omnigent"&&u("omnigent",' + frame + '),l==="paseo"&&u("paseo",' + paseoFrame + ')'],
    ],
  },
};
// References include the pre-rendered HTML and RSC, not just the JS manifest.
// Keep the hash width unchanged so length-prefixed flight content stays valid.
const oldName = 'page-b3286479e7c79f5d.js';
const references = [
  ['index.html', 'f3586c304ad4853a5d844ca82babc0daf3b0eb32508188cd1c3515543d1de264'],
  ['_global-error/page_client-reference-manifest.js', '287a194231a779c5e5afe692a224e3bf9f88249d70a9dea8612a6386ad2d3567'],
  ['_not-found/page_client-reference-manifest.js', '69c95b97255eea379a7f74b69bf8fc37af377ba72fd267f65176f2de32cadf5c'],
  ['login/page_client-reference-manifest.js', '528a8132af338691169ca3fd425054debc3a60ee5b2405edee0f1ef5684165d7'],
  ['page_client-reference-manifest.js', '2f99858d8655e7a67e138c40a8d5d376d3daed6e9d99b920777fd6e5b1c2e8e1'],
  ['index.segments/__PAGE__.segment.rsc', '69b2c5407307b0e2b00d3cc8e020ffb52eed6854960319bea38536071d79a2b1'],
  ['index.segments/_full.segment.rsc', '05dc21b7d3c4185d7e88c19b4f3fa8eaf359d17f90338bf3c9fec6c108597f1a'],
  ['index.rsc', '05dc21b7d3c4185d7e88c19b4f3fa8eaf359d17f90338bf3c9fec6c108597f1a'],
];
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
  if (hash(source) !== spec.sha256) throw new Error('Omnigent settings: unsupported compiled artifact; revalidate the Pi Web build');
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
    if (hash(original) !== checksum) throw new Error(`Omnigent settings: incompatible asset reference ${relative}`);
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
