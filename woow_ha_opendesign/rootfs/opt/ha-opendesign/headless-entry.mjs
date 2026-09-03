#!/usr/bin/env node
import { renderSlides } from './headless-renderer.mjs';

const host = '127.0.0.1';
const port = 7456;
let started;
let stopping = false;

async function stop(signal) {
  if (stopping) return;
  stopping = true;
  console.info(`[ha-opendesign] ${signal} received; stopping OpenDesign`);
  try {
    await started?.shutdown?.();
  } catch (error) {
    console.error('[ha-opendesign] shutdown error', error);
  }
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

  process.once('SIGTERM', () => void stop('SIGTERM'));
  process.once('SIGINT', () => void stop('SIGINT'));
  await new Promise((resolve, reject) => {
    started.server.once('close', resolve);
    started.server.once('error', reject);
  });
} catch (error) {
  console.error('[ha-opendesign] failed to start', error);
  process.exitCode = 1;
} finally {
  await stop('exit');
}
