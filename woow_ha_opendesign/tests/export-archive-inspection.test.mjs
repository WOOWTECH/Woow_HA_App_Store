import assert from 'node:assert/strict';
import test from 'node:test';
import { inspectZipMembers } from './export-archive-inspection.mjs';

function centralDirectoryOnlyArchive(name, unixMode) {
  const encodedName = Buffer.from(name, 'utf8');
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt16LE(0x0314, 4); // Unix host, ZIP specification 2.0
  central.writeUInt16LE(20, 6);
  central.writeUInt16LE(encodedName.length, 28);
  central.writeUInt32LE((unixMode << 16) >>> 0, 38);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(1, 8);
  end.writeUInt16LE(1, 10);
  end.writeUInt32LE(central.length + encodedName.length, 12);
  return Buffer.concat([central, encodedName, end]);
}

test('central-directory inspection reads normal Unix file attributes', () => {
  assert.deepEqual(
    inspectZipMembers(centralDirectoryOnlyArchive('export-deck.html', 0o100644)).map(({ name }) => name),
    ['export-deck.html'],
  );
});

test('central-directory inspection rejects Unix symbolic-link members', () => {
  assert.throws(
    () => inspectZipMembers(centralDirectoryOnlyArchive('linked-deck.html', 0o120777)),
    /symbolic link/i,
  );
});
