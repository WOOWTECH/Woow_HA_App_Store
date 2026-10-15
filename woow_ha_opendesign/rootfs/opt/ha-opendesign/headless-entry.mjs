#!/usr/bin/env node
import { renderSlides } from './headless-renderer.mjs';

const host = '127.0.0.1';
const port = 7456;
let started;
let stopping = false;

// OpenDesign 0.24.1's startServer({ returnServer: true }).shutdown only stops
// daemon runs; it neither closes the HTTP server nor ends background timers, so
// the process must close the server itself and exit explicitly. Otherwise a
// TERM leaves it running until the launcher's KILL deadline.
async function stop(signal) {
  if (stopping) return;
  stopping = true;
  console.info(`[ha-opendesign] ${signal} received; stopping OpenDesign`);
  try {
    await started?.shutdown?.();
  } catch (error) {
    console.error('[ha-opendesign] shutdown error', error);
  }
  const server = started?.server;
  if (server?.listening) {
    await new Promise((resolve) => {
      server.close(() => resolve());
      // SSE and keep-alive connections would otherwise hold close() open.
      server.closeAllConnections?.();
    });
  }
}

function stopAndExit(signal) {
  void stop(signal).finally(() => process.exit(process.exitCode ?? 0));
}

try {
  const { startServer } = await import('/app/apps/daemon/dist/server.js');
  started = await startServer({
    host,
    port,
    returnServer: true,
    desktopSlideRenderer: renderSlides,
    desktopArtifactExporter: null,
  });
  console.info(`[ha-opendesign] OpenDesign ${started.url} with Playwright export renderer`);

  process.once('SIGTERM', () => stopAndExit('SIGTERM'));
  process.once('SIGINT', () => stopAndExit('SIGINT'));
  await new Promise((resolve, reject) => {
    started.server.once('close', resolve);
    started.server.once('error', reject);
  });
  // The server closed without a stop signal: a required process ended.
  if (!stopping) process.exitCode = 1;
} catch (error) {
  console.error('[ha-opendesign] failed to start', error);
  process.exitCode = 1;
} finally {
  if (!stopping) stopAndExit('exit');
}
