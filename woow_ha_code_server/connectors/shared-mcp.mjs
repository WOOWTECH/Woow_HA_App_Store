import { spawn } from 'node:child_process';

// Synchronization is independent of provider lifecycle. Never print registry values.
export function synchronizeMcp(env = process.env) {
  return new Promise((resolve, reject) => {
    const fail = () => reject(Object.assign(new Error('MCP_SYNC_FAILED'), {code: 'MCP_SYNC_FAILED'}));
    const child = spawn('/usr/local/bin/woow-agent-sync', [], { env, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '', bytes = 0;
    const timer = setTimeout(() => { child.kill(); fail(); }, 30000);
    child.stderr.resume();
    child.on('error', () => {clearTimeout(timer); fail();});
    child.stdout.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 65536) child.kill(); else output += chunk;
    });
    child.on('close', code => {
      clearTimeout(timer);
      try {
        const parsed = JSON.parse(output);
        if (code !== 0 || bytes > 65536 || !/^[a-f0-9]{64}$/.test(parsed.configurationHash)) throw Error();
        resolve({configurationHash: parsed.configurationHash});
      } catch { fail(); }
    });
  });
}
