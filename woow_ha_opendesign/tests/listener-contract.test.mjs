import test from 'node:test';
import assert from 'node:assert/strict';
import {assertListeners, baseListeners, parseListeners, readProcessTcpListeners, withoutDockerResolver} from './listener-contract.mjs';
import {createServer} from 'node:net';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
const auxiliary='127.0.0.1:35295';
const managed = port => ({running:true, state:{port}, config:{daemon:{listen:`127.0.0.1:${port}`}}, workerListeners:[`127.0.0.1:${port}`,auxiliary]});
test('settled Paseo worker owns exactly its recorded daemon port and internal OpenCode bridge', () => {
  for (const port of [6769, 6770, 24680]) assertListeners([...baseListeners,`127.0.0.1:${port}`,auxiliary],managed(port));
  assertListeners(baseListeners, {running:false});
});
test('rejects public, IPv6, unowned, duplicate, missing and additional worker listeners', () => {
  const good=[...baseListeners,'127.0.0.1:6769',auxiliary];
  for(const extra of ['0.0.0.0:6769',':::6769','127.0.0.1:7460','127.0.0.1:6769'])
    assert.throws(()=>assertListeners([...good,extra],managed(6769)));
  assert.throws(()=>assertListeners(baseListeners,managed(6769)));
  assert.throws(()=>assertListeners(good,{running:false}));
  assert.throws(()=>assertListeners(good,managed(6770)));
  assert.throws(()=>assertListeners(good,{...managed(6769),config:{daemon:{listen:'0.0.0.0:6769'}}}));
  assert.throws(()=>assertListeners(good,{...managed(6769),state:{port:'6769'}}));
  assert.throws(()=>assertListeners(baseListeners,managed(7456)));
  for(const workerListeners of [undefined,[],['127.0.0.1:6769'],[auxiliary],['127.0.0.1:6769','0.0.0.0:35295'],['127.0.0.1:6769',':::35295'],['127.0.0.1:6769','127.0.0.1:7456'],['127.0.0.1:6769',auxiliary,auxiliary]])
    assert.throws(()=>assertListeners(good,{...managed(6769),workerListeners}));
});
test('parses BusyBox netstat TCP4 and TCP6 without discarding unexpected listeners', () => {
  assert.deepEqual(parseListeners('Active Internet connections (only servers)\nProto Recv-Q Send-Q Local Address Foreign Address State\ntcp 0 0 127.0.0.1:6769 0.0.0.0:* LISTEN\ntcp6 0 0 :::1234 :::* LISTEN\n'),['127.0.0.1:6769',':::1234']);
});
test('a user-defined Docker network adds exactly one embedded DNS listener on 127.0.0.11 and nothing else is forgiven', () => {
  const resolver = '127.0.0.11:41753';
  assert.deepEqual(parseListeners(`tcp 0 0 ${resolver} 0.0.0.0:* LISTEN\ntcp 0 0 0.0.0.0:8099 0.0.0.0:* LISTEN\n`), [resolver, '0.0.0.0:8099']);
  assertListeners(withoutDockerResolver([...baseListeners, resolver]), {running: false});
  assertListeners(withoutDockerResolver(baseListeners), {running: false}); // default bridge: no resolver, still exact
  for (const extra of ['127.0.0.11:41754', '127.0.0.2:41753', '127.0.0.110:41753', '127.0.0.11:0', '0.0.0.0:41753', ':::41753'])
    assert.throws(() => assertListeners(withoutDockerResolver([...baseListeners, resolver, extra]), {running: false}), undefined, extra);
  assert.throws(() => assertListeners(withoutDockerResolver([...baseListeners, '127.0.0.12:41753']), {running: false}));
});
test('kernel socket ownership excludes another process in the same network namespace', async () => {
  const own=createServer();own.listen(0,'127.0.0.1');await once(own,'listening');
  const child=spawn(process.execPath,['--input-type=module','-e',`import net from 'node:net';const s=net.createServer();s.listen(0,'127.0.0.1',()=>console.log(s.address().port));`],{stdio:['ignore','pipe','inherit']});
  try {
    const [data]=await once(child.stdout,'data');const childAddress=`127.0.0.1:${Number(String(data).trim())}`;
    const ownAddress=`127.0.0.1:${own.address().port}`;
    assert.deepEqual(readProcessTcpListeners(child.pid),[childAddress]);
    assert.ok(readProcessTcpListeners(process.pid).includes(ownAddress));
    assert.ok(!readProcessTcpListeners(process.pid).includes(childAddress));
  } finally {child.kill();await once(child,'exit');await new Promise(resolve=>own.close(resolve));}
});
