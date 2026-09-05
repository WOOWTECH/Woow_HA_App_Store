import assert from 'node:assert/strict';

export function inspectZipMembers(bytes) {
  const eocdSignature = 0x06054b50;
  const centralSignature = 0x02014b50;
  const minimumEocdOffset = Math.max(0, bytes.length - 65_557);
  let eocdOffset = -1;
  for (let offset = bytes.length - 22; offset >= minimumEocdOffset; offset -= 1) {
    if (bytes.readUInt32LE(offset) === eocdSignature) {
      eocdOffset = offset;
      break;
    }
  }
  assert.notEqual(eocdOffset, -1, 'ZIP end-of-central-directory record is required');

  const entryCount = bytes.readUInt16LE(eocdOffset + 10);
  let offset = bytes.readUInt32LE(eocdOffset + 16);
  const members = [];
  for (let index = 0; index < entryCount; index += 1) {
    assert.equal(bytes.readUInt32LE(offset), centralSignature, 'ZIP central-directory entry is required');
    const nameLength = bytes.readUInt16LE(offset + 28);
    const extraLength = bytes.readUInt16LE(offset + 30);
    const commentLength = bytes.readUInt16LE(offset + 32);
    const name = bytes.subarray(offset + 46, offset + 46 + nameLength).toString('utf8');
    const madeBy = bytes.readUInt16LE(offset + 4);
    const externalAttributes = bytes.readUInt32LE(offset + 38);
    const hostOs = madeBy >>> 8;
    const unixMode = externalAttributes >>> 16;
    if (hostOs === 3 && (unixMode & 0o170000) === 0o120000) {
      assert.fail(`ZIP member must not be a Unix symbolic link: ${name}`);
    }
    members.push({ name, madeBy, externalAttributes });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return members;
}
