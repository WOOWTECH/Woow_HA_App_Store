// Optional transport for a read-only inspector in a remote QA deployment.
// The private JSON command file contains a fixed argv array (kubectl exec -i,
// ssh wrapper, etc.), never a shell string or provider token.
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

export async function inspect(request) {
  const file = process.env.WOOW_PASEO_INSPECT_COMMAND_FILE;
  if (!file || !path.isAbsolute(file)) return { ok: false, code: 'INSPECT_COMMAND_REQUIRED' };
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== process.getuid() || (stat.mode & 0o077) || stat.size > 16384) return { ok: false, code: 'INSPECT_COMMAND_UNSAFE' };
  const argv = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!Array.isArray(argv) || !argv.length || argv.some(arg => typeof arg !== 'string' || arg.includes('\0'))) return { ok: false, code: 'INSPECT_COMMAND_INVALID' };
  return new Promise(resolve => {
    const child = spawn(argv[0], argv.slice(1), { shell: false, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', bytes = 0, failed = false;
    const fail = () => { failed = true; child.kill('SIGKILL'); };
    const timer = setTimeout(fail, 40000);
    child.stdout.on('data', chunk => { bytes += chunk.length; if (bytes > 65536) fail(); else output += chunk; });
    child.stderr.on('data', chunk => { bytes += chunk.length; if (bytes > 65536) fail(); });
    child.on('error', () => { failed = true; });
    child.stdin.on('error', () => { failed = true; });
    child.on('close', code => {
      clearTimeout(timer);
      if (failed || code !== 0) return resolve({ ok: false, code: 'REMOTE_INSPECTION_FAILED' });
      try { resolve(JSON.parse(output)); } catch { resolve({ ok: false, code: 'REMOTE_INSPECTION_INVALID_RESPONSE' }); }
    });
    child.stdin.end(JSON.stringify(request));
  });
}
