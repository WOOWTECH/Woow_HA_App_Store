export const meta = {
  id: 'p46', title: 'Backup manifest integrity verifier', category: 'Data integrity',
  description: 'Compare supplied file sizes and SHA-256 digests for missing, changed, and extra files.',
  version: '1.1.0',
  example: {
    expected: [{ path: 'notes.txt', size: 3, sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' }],
    actual: [{ path: 'notes.txt', size: 3, sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' }],
    allowExtra: false
  }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
function check(ok, message) { if (!ok) throw new Error(message); }
function manifest(value, name) {
  check(Array.isArray(value) && value.length <= 1000, name + ' must be an array of at most 1000 files');
  const files = new Map();
  for (const f of value) {
    check(object(f) && typeof f.path === 'string' && f.path.length <= 240 && /^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(f.path) && f.path.split('/').every(p => p !== '.' && p !== '..'), name + ' contains an unsafe relative path');
    check(!files.has(f.path), name + ' contains duplicate path: ' + f.path);
    check(Number.isSafeInteger(f.size) && f.size >= 0 && f.size <= 1000000000000, name + ' file size must be an integer from 0 to 1e12');
    check(typeof f.sha256 === 'string' && /^[0-9a-fA-F]{64}$/.test(f.sha256), name + ' sha256 must contain exactly 64 hexadecimal digits');
    files.set(f.path, { size: f.size, sha256: f.sha256.toLowerCase() });
  }
  return files;
}
export function run(input) {
  check(object(input), 'Input must be an object');
  const expected = manifest(input.expected, 'expected');
  const actual = manifest(input.actual, 'actual');
  const allowExtra = input.allowExtra ?? false;
  check(typeof allowExtra === 'boolean', 'allowExtra must be boolean');
  const summary = { expected: expected.size, actual: actual.size, matched: 0, missing: 0, changed: 0, extra: 0 };
  const files = [...new Set([...expected.keys(), ...actual.keys()])].sort().map(path => {
    const e = expected.get(path), a = actual.get(path);
    let status;
    const issues = [];
    if (!e) status = 'extra';
    else if (!a) status = 'missing';
    else {
      if (e.size !== a.size) issues.push('size');
      if (e.sha256 !== a.sha256) issues.push('sha256');
      status = issues.length ? 'changed' : 'matched';
    }
    summary[status]++;
    return { path, status, issues };
  });
  return { valid: summary.missing === 0 && summary.changed === 0 && (allowExtra || summary.extra === 0), summary, files };
}
