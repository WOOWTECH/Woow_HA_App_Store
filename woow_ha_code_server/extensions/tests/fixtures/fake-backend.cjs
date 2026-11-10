#!/usr/bin/env node
'use strict';
// Local protocol fixture only. It never contacts a provider or persists input.
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  const request = JSON.parse(input);
  if (process.argv.length !== 2 || request.fields) process.exit(2);
  if (request.action === 'connect' && request.password !== 'fixture-password') process.exit(3);
  const response = { ok: true, phase: 'fixture-online', host: { name: '測試工作機' }, engines: [{ id: 'pi', installed: true, authenticated: false }], verification: null };
  process.stdout.write(JSON.stringify(response) + '\n');
});
