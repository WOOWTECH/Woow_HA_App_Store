#!/usr/bin/env node
import {pathToFileURL} from 'node:url';

const adapters = Object.freeze({paseo: './paseo/index.mjs', omnigent: './omnigent/index.mjs'});
const actions = new Set(['status', 'configure', 'start', 'stop', 'restore', 'models', 'verify', 'pair', 'connect', 'disconnect', 'diagnostics', 'chat', 'continue', 'switchModel', 'session', 'archive']);
const failure = (code, message) => ({ok: false, error: {code, message}});

export async function dispatch(request, load = name => import(adapters[name])) {
  if (!request || typeof request !== 'object' || Array.isArray(request)
      || !Object.hasOwn(adapters, request.connector) || !actions.has(request.action)) {
    return failure('INVALID_REQUEST', 'Choose a supported connector and action.');
  }
  if (request.password !== undefined && (typeof request.password !== 'string' || request.password.length > 4096)) {
    return failure('INVALID_REQUEST', 'The login request is invalid.');
  }
  try {
    const adapter = await load(request.connector);
    const result = await adapter.handle(request);
    if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.ok !== 'boolean') {
      return failure('INVALID_RESPONSE', 'The connector returned an invalid response.');
    }
    return result;
  } catch (error) {
    // Neither provider stderr nor arbitrary exception text is safe for the IDE.
    if (error?.code === 'ERR_MODULE_NOT_FOUND' || error?.code === 'MODULE_NOT_FOUND') {
      return failure('RUNTIME_MISSING', 'Install or repair the WOOW connector runtime in this code-server environment.');
    }
    return failure('CONNECTOR_FAILED', 'The connector operation failed. Check its status and retry.');
  }
}

export async function readRequest(input, {maxBytes = 65536, timeoutMs = 15000} = {}) {
  return new Promise((resolve, reject) => {
    const chunks = []; let size = 0;
    const timer = setTimeout(() => done(new Error('Input timeout')), timeoutMs);
    function done(error, value) {
      clearTimeout(timer); input.removeListener('data', data); input.removeListener('end', end); input.removeListener('error', failed);
      if (error) {input.pause(); reject(error);} else resolve(value);
    }
    function failed() {done(new Error('Input failed'));}
    function data(chunk) {
      size += Buffer.byteLength(chunk);
      if (size > maxBytes) return done(new Error('Input too large'));
      chunks.push(Buffer.from(chunk));
    }
    function end() {
      try {done(null, JSON.parse(Buffer.concat(chunks).toString('utf8')));} catch {done(new Error('Invalid JSON'));}
    }
    input.on('data', data); input.once('end', end); input.once('error', failed);
  });
}

export async function main(input = process.stdin, output = process.stdout) {
  let result;
  try {result = await dispatch(await readRequest(input));}
  catch {result = failure('INVALID_REQUEST', 'Send one JSON request of at most 64 KiB on stdin.');}
  output.write(JSON.stringify(result) + '\n');
  return result.ok ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = await main();
