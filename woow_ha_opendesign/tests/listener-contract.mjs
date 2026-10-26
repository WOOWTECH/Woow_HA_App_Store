import assert from 'node:assert/strict';
import fs from 'node:fs';

export const baseListeners = ['0.0.0.0:8081', '0.0.0.0:8099', '127.0.0.1:7456', '127.0.0.1:7681'];
export function assertListeners(actual, {running, state, config, workerListeners} = {running: false}) {
  const expected = [...baseListeners];
  if (running) {
    assert.ok(Number.isInteger(state?.port) && state.port >= 1024 && state.port <= 65535, 'missing managed port');
    const listen = `127.0.0.1:${state.port}`;
    assert.equal(config?.daemon?.listen, listen, 'managed daemon must bind its recorded IPv4 loopback port');
    assert.ok(!expected.includes(listen), 'managed port overlaps a required service');
    // Paseo 0.11.2 eagerly starts OpenCodeBridge in createAgentProviderRuntime.
    // It binds one ephemeral IPv4 loopback port in the same daemon worker.
    // Require kernel-proven ownership; never allow arbitrary loopback sockets.
    assert.equal(workerListeners?.length, 2, 'Paseo worker must own exactly two TCP listeners');
    assert.ok(workerListeners.includes(listen), 'Paseo worker must own its recorded daemon port');
    const auxiliary = workerListeners.filter(address => address !== listen);
    assert.equal(auxiliary.length, 1, 'missing unique internal OpenCode bridge');
    assert.match(auxiliary[0], /^127\.0\.0\.1:[1-9][0-9]*$/, 'internal OpenCode bridge must use IPv4 loopback');
    const port = Number(auxiliary[0].split(':')[1]);
    assert.ok(port >= 1024 && port <= 65535 && !expected.includes(auxiliary[0]), 'invalid internal bridge port');
    expected.push(listen, auxiliary[0]);
  }
  assert.deepEqual([...actual].sort(), expected.sort(), 'unexpected or missing TCP listeners');
}
export function parseListeners(netstat) {
  return netstat.split('\n').filter(line => /\bLISTEN\s*$/.test(line)).map(line => line.trim().split(/\s+/)[3]);
}
export function readProcessTcpListeners(pid) {
  assert.ok(Number.isInteger(pid) && pid > 1, 'invalid worker PID');
  const sockets = new Set();
  for (const fd of fs.readdirSync(`/proc/${pid}/fd`)) {
    try {
      const match = fs.readlinkSync(`/proc/${pid}/fd/${fd}`).match(/^socket:\[([0-9]+)\]$/);
      if (match) sockets.add(match[1]);
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  const listeners = [];
  for (const protocol of ['tcp', 'tcp6']) {
    for (const line of fs.readFileSync(`/proc/${pid}/net/${protocol}`, 'utf8').trim().split('\n').slice(1)) {
      const fields = line.trim().split(/\s+/);
      if (fields[3] !== '0A' || !sockets.has(fields[9])) continue;
      const [host, port] = fields[1].split(':');
      const address = protocol === 'tcp'
        ? host.match(/../g).reverse().map(byte => parseInt(byte, 16)).join('.')
        : `tcp6:${host}`; // Preserve every IPv6 bind so the strict contract rejects it.
      listeners.push(`${address}:${parseInt(port, 16)}`);
    }
  }
  return listeners;
}
