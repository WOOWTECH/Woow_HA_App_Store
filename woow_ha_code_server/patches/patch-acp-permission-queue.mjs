import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

// VS Code has one QuickPick surface. Concurrent ACP permission requests replace
// that surface and resolve the earlier request as cancelled. Keep each request's
// original approval handling, but wait until the preceding prompt has settled.
export const original = 'n.PermissionHandler=class{async requestPermission(e){';
export const patched = 'n.PermissionHandler=class{permissionQueue=Promise.resolve();requestPermission(e){const run=this.permissionQueue.then(()=>this.requestPermissionSerial(e));this.permissionQueue=run.then(()=>undefined,()=>undefined);return run}async requestPermissionSerial(e){';

export function patch(source) {
  const originals = source.split(original).length - 1;
  const patches = source.split(patched).length - 1;
  if (patches === 1 && originals === 0) return source;
  if (originals !== 1 || patches !== 0) {
    throw new Error('Expected exactly one ACP 0.2.0 PermissionHandler; source unchanged');
  }
  return source.replace(original, patched);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const path = process.argv[2];
  if (!path) throw new Error('Pass the built-in ACP dist/extension.js path');
  const source = fs.readFileSync(path, 'utf8');
  const result = patch(source);
  if (source !== result) fs.writeFileSync(path, result);
  console.log('ACP permission prompts serialized; approval choices unchanged');
}
