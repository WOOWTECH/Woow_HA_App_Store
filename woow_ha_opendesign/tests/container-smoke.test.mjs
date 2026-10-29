import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const smoke = await readFile(new URL('./container-smoke.sh', import.meta.url), 'utf8');

test('browser smoke runs beside the container playwright-core dependency', () => {
  const browserSmokePath = '/opt/ha-opendesign/container-ingress-browser-e2e.mjs';
  assert.ok(
    smoke.includes(`docker cp tests/container-ingress-browser-e2e.mjs "$container:${browserSmokePath}"`),
    'browser smoke must be copied beneath the runtime package root for ESM dependency resolution',
  );
  assert.ok(
    smoke.includes(`docker exec "$container" node ${browserSmokePath}`),
    'browser smoke must run from the path beneath the runtime package root',
  );
  assert.ok(
    !smoke.includes('node /tmp/container-ingress-browser-e2e.mjs'),
    'running the browser smoke from /tmp cannot resolve the runtime playwright-core dependency',
  );
});

test('the checks that other containers and the container itself are refused cannot be dropped silently', () => {
  // The CHANGELOG and DOCS describe this coverage; deleting the network emulation or a probe must fail validation, not just weaken the smoke.
  for (const needle of [
    'docker network create --subnet 172.30.32.0/23 --gateway 172.30.32.2 "$net"',
    '--network "$net" --ip "$addon_ip"',
    '--network "$net" --ip "$sibling_ip"',
    'addon_ip=172.30.33.10',
    'sibling_ip=172.30.33.20',
    'acl_routes=(/mcp-admin/ /api/paseo-bridge /paseo/setup /paseo/setup/ /paseo/assets/setup.js)',
    'for route in / /console/ /api/health /api/integrations/omnigent/status /ha-ingress.js /ha-export-bridge.js \\\n  /api/projects/smoke/export/pdf "${acl_routes[@]}"; do',
    '  probe sibling "$route"\n',
    '  probe sibling "$route" "${ingress_headers[@]}"',
    '  probe host "$route" "${ingress_headers[@]}"',
    '  probe loopback "$route" "${ingress_headers[@]}"',
    'sibling_redirect /console /console/',
    'sibling_redirect /terminal /console/',
    'sibling_redirect /terminal/ /console/',
    'sibling_redirect /mcp-admin /mcp-admin/',
    'sibling_redirect /_woow/support https://aiot.woowtech.io/woow',
    "expect_nginx_refusal 'a sibling container on the hassio network' \"$route\"",
    "expect_nginx_refusal 'a sibling container sending Ingress-shaped headers' \"$route\"",
    "expect_nginx_refusal 'a process inside the add-on container' \"$route\"",
    'nginx refused the emulated Supervisor Ingress gateway',
  ]) {
    assert.ok(smoke.includes(needle), `container-smoke.sh lost: ${needle}`);
  }
  // A refusal only counts when it is nginx's own page: the application answers 403 by itself for some of these routes.
  assert.ok(smoke.includes(`nginx_page='<center>nginx</center>'`), 'the refusal check must recognise nginx\'s own error page');
});
