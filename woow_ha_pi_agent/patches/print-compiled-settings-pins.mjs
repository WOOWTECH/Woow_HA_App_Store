// Diagnostic only: never writes. Reports every build-derived value that
// patch-omnigent-settings.mjs pins, measured on the UNPATCHED compiled tree.
//
// Next.js module IDs embed the absolute app directory, so the compiled client
// chunk, SSR page, flight references and the chunk file name all change with the
// build root. After any Pi Web, lockfile or build-root change, run this on a
// fresh build at the canonical root (/opt/piweb-source/package) and copy the
// reported values into patch-omnigent-settings.mjs. Exit status is 0 even when
// values differ; the strict patch and its tests stay the fail-closed gate.
//
//   node patches/print-compiled-settings-pins.mjs /opt/piweb-source/package
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { COMPILED_PIN_TABLE } from './patch-omnigent-settings.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
if (!process.argv[2]) {
  console.error('Usage: node print-compiled-settings-pins.mjs /path/to/@agegr/pi-web');
  process.exit(2);
}
const root = path.resolve(process.argv[2]);
const { specs, oldName, references } = COMPILED_PIN_TABLE;
const read = file => fs.readFileSync(path.join(root, file));
const exists = file => fs.existsSync(path.join(root, file));

const chunks = '.next/static/chunks';
const clientFiles = fs.readdirSync(path.join(root, chunks), { recursive: true })
  .filter(file => file.endsWith('.js'))
  .map(file => path.join(chunks, file))
  .filter(file => read(file).toString('utf8').includes('className:"settings-section-tabs"'));
const serverFile = '.next/server/app/page.js';

const report = {
  root,
  note: 'sha256 values are of the unpatched compiled files; matches=false means that pin must be updated',
  client: clientFiles.map(file => {
    const sha256 = hash(read(file));
    return { file, name: path.basename(file), sha256, pinned: specs.client.sha256, matches: sha256 === specs.client.sha256 };
  }),
  server: exists(serverFile)
    ? { file: serverFile, sha256: hash(read(serverFile)), pinned: specs.server.sha256, matches: hash(read(serverFile)) === specs.server.sha256 }
    : null,
  chunkName: { actual: clientFiles.length === 1 ? path.basename(clientFiles[0]) : null, pinned: oldName },
  references: references.map(([relative, pinned]) => {
    const file = path.join('.next/server/app', relative);
    const sha256 = exists(file) ? hash(read(file)) : null;
    return { relative, sha256, pinned, matches: sha256 === pinned };
  }),
  anchors: [],
};

for (const [label, spec, file] of [['client', specs.client, clientFiles[0]], ['server', specs.server, serverFile]]) {
  if (!file || !exists(file)) continue;
  const text = read(file).toString('utf8');
  for (const [from] of spec.replacements) {
    const occurrences = text.split(from).length - 1;
    const entry = { spec: label, anchor: from.length > 64 ? `${from.slice(0, 61)}...` : from, occurrences };
    if (occurrences !== 1) {
      // Show the neighbouring compiled text so a renamed minified identifier is easy to spot.
      const at = text.indexOf(from.slice(0, 18));
      entry.nearbyText = at >= 0 ? text.slice(at, at + Math.min(from.length + 40, 220)) : null;
    }
    report.anchors.push(entry);
  }
}
// Optional localisation aids for build-environment differences (never gate anything):
//   PIN_BLOCK_SIZE=2048          -> sha256[0:8] of every block of the SSR page
//   PIN_DUMP=<offset>:<length>   -> the SSR page text of that byte range
const blockSize = Number(process.env.PIN_BLOCK_SIZE || 0);
if (blockSize > 0 && exists(serverFile)) {
  const bytes = read(serverFile);
  const sha8 = [];
  for (let at = 0; at < bytes.length; at += blockSize) sha8.push(hash(bytes.subarray(at, at + blockSize)).slice(0, 8));
  report.serverBlocks = { blockSize, length: bytes.length, sha8 };
}
if (process.env.PIN_DUMP && exists(serverFile)) {
  const [offset, length] = process.env.PIN_DUMP.split(':').map(Number);
  report.serverDump = { offset, length, text: read(serverFile).subarray(offset, offset + length).toString('utf8') };
}
console.log(JSON.stringify(report, null, 2));
