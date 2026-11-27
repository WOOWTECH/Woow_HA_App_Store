import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { assertSafePath, RuntimeError } from './state.mjs';

// Frozen @getpaseo/server 0.17.5. The hello response is serialized as built, so the
// status envelope keeps extra fields; branded clients require this optional brand
// identity during hello. Releases built for 0.11.2 are never patched again: offline
// control of their daemons does not load this module.
export const ORIGINAL_BRAND_SERVER_SHA256 = 'a11dd0366089d25c57c71929c3d56d47dfef3d40cc272c010c4e08bc74d9ac19';
export const PATCHED_BRAND_SERVER_SHA256 = '4abdd2bc4f72d5865521b0d5adfca0743b6bd3a7cb8729df42f9b0baa635c523';
const helper = fs.readFileSync(new URL('./brand-identity.mjs', import.meta.url));
const sha = value => createHash('sha256').update(value).digest('hex');
export const BRAND_IDENTITY_PATCH_ID = sha(Buffer.concat([helper, Buffer.from(PATCHED_BRAND_SERVER_SHA256)]));
export const BRAND_SERVER_PATH = 'node_modules/@getpaseo/server/dist/server/server/websocket-server.js';
const CURRENT = Object.freeze({ original: ORIGINAL_BRAND_SERVER_SHA256, patched: PATCHED_BRAND_SERVER_SHA256, helperSha256: sha(helper) });
// Frozen @getpaseo/server 0.11.2 server as Agent Connect 0.1.18-0.1.23 left it in release 0.11.2-r4 (the
// same transformation; receipt patch ID and helper bytes below). Literal values: they only verify that
// release for control of a daemon it already runs, and must not follow later edits to the helper.
export const BRAND_0112 = Object.freeze({
  original: 'ba8122d01dd17533231a573097ec4e9f91f4fd12caada107adb9f6706f5f8950',
  patched: '8315add9226617d4c2c09d1481c750eff7a34fa83670725914c69892f1cd1561',
  patchId: 'd1f27c35db3eb9f456085893a6ca46ecc8aa353eb9dc3b3f9f8b833fd30e4d81',
  helperSha256: '036471982ccbbb5a7c3418631518025b245ac50e1c0b1a29c3824d16ba069733',
});
export function patchBrandIdentitySource(source, release = CURRENT) {
  if (sha(source) === release.patched) return source;
  if (sha(source) !== release.original) throw new RuntimeError('BRAND_IDENTITY_SOURCE_MISMATCH');
  const result = 'import {agentConnectBrand} from "./pi-paseo-brand-identity.mjs";\n' + source.replace(
    '            status: "server_info",', '            status: "server_info",\n            brand: agentConnectBrand,');
  if (sha(result) !== release.patched) throw new RuntimeError('BRAND_IDENTITY_PATCH_MISMATCH');
  return result;
}
export function applyBrandIdentityPatch(root) {
  const file = path.join(root, BRAND_SERVER_PATH), target = path.join(path.dirname(file), 'pi-paseo-brand-identity.mjs');
  assertSafePath(file); assertSafePath(target);
  const before = fs.readFileSync(file, 'utf8'), after = patchBrandIdentitySource(before);
  if (!fs.existsSync(target) || !fs.readFileSync(target).equals(helper)) fs.writeFileSync(target, helper, { mode: 0o644 });
  if (before !== after) fs.writeFileSync(file, after);
}
/** The given release's patched server beside its brand helper. */
export function brandIdentityPatchReady(root, release = CURRENT) {
  try {
    const file = path.join(root, BRAND_SERVER_PATH), target = path.join(path.dirname(file), 'pi-paseo-brand-identity.mjs');
    assertSafePath(file); assertSafePath(target);
    return sha(fs.readFileSync(file)) === release.patched && sha(fs.readFileSync(target)) === release.helperSha256;
  } catch { return false; }
}
