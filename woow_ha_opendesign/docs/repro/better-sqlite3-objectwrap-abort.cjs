// Repro (core image, no HA layer): Node 24 ObjectWrap cleanup-hook abort in better-sqlite3 built against 24.19+ headers.
// Statements are prepared and dropped; an allocation-driven GC reclaims their ObjectWrap -> ~ObjectWrap()
// -> node::RemoveEnvironmentCleanupHook(isolate) with no current Environment -> CHECK abort (exit 134).
const path = require('path');
const fs = require('fs');
const root = '/app/apps/daemon/node_modules/.pnpm';
const dir = fs.readdirSync(root).find((d) => d.startsWith('better-sqlite3@'));
const Database = require(path.join(root, dir, 'node_modules/better-sqlite3'));
console.log(`node ${process.version}, ${dir}`);
const db = new Database(':memory:');
const n = Number(process.argv[2] || 2e6);
let junk = [];
for (let i = 0; i < n; i += 1) {
  db.prepare('select ? as v').get(i);
  junk.push(new Array(16).fill(i));
  if (junk.length > 1000) junk = [];
  if (i % 200000 === 0) console.log(`prepared ${i}`);
}
console.log(`survived ${n} prepared statements`);
