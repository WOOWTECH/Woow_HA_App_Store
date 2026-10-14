// Regression contract for HAOS running inside a KubeVirt pod network.
//
// HAOS receives a 1450-byte uplink MTU from the cluster overlay, while its
// default hassio Docker bridge is 1500. Apps on that bridge can resolve DNS but
// their HTTPS TLS packets black-hole through the nested NAT path. This add-on
// uses HAOS host networking for the data path, while nginx is deliberately
// bound to the Supervisor-only bridge address so Ingress remains the only
// browser entry point.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const config = readFileSync(join(ROOT, "config.yaml"), "utf8");
const nginx = readFileSync(join(ROOT, "rootfs", "etc", "nginx", "nginx.conf"), "utf8");
const run = readFileSync(join(ROOT, "rootfs", "etc", "s6-overlay", "s6-rc.d", "pi-web", "run"), "utf8");

assert.match(config, /^host_network:\s*true\s*$/m, "the add-on must bypass HAOS's mismatched Docker bridge MTU");
assert.match(nginx, /listen\s+172\.30\.32\.1:30142\s+default_server;/, "nginx must bind only the HA Supervisor bridge gateway");
assert.match(nginx, /^\s*allow\s+172\.30\.32\.2;\s*$/m, "only the HA Supervisor ingress peer may reach nginx");
assert.match(nginx, /^\s*deny\s+all;\s*$/m, "host-network nginx must not expose a LAN listener");
assert.doesNotMatch(nginx, /listen\s+30142\s+default_server;/, "an all-interface nginx listener would bypass HA Ingress authentication");
assert.match(run, /export PI_WEB_HOSTNAME="127\.0\.0\.1"/, "pi-web must remain loopback-only behind nginx");

console.log("HAOS nested-network contract passed: host-network egress with Supervisor-only ingress.");
