#!/bin/sh
set -eu
cd "$(dirname "$0")"
sha256sum -c checksums.sha256
mkdir -p /opt/opendesign-paseo
tar -xzf package.tgz --strip-components=1 -C /opt/opendesign-paseo
# npm pack intentionally excludes package-lock.json: retain the lock from the
# exact source commit alongside the archive, with its own digest.
cp package-lock.json /opt/opendesign-paseo/package-lock.json
npm ci --omit=dev --ignore-scripts --no-audit --no-fund --prefix /opt/opendesign-paseo
node /opt/opendesign-paseo/scripts/prepare-managed-runtime.mjs /opt/opendesign-paseo/managed-runtime
# The preparer deliberately writes its ready receipt as 0600 and creates the
# release directory as 0700. It runs as root during the image build, while the
# required bridge/runtime child runs as UID 1001. Publish this immutable baked
# runtime read/execute-only to runtime users; no path becomes writable.
chmod -R a+rX,go-w /opt/opendesign-paseo/managed-runtime
# Keep the native launch card aligned with this exact package. Native daemon
# capabilities still come from the pinned core and are verified below.
install -m 0644 /opt/opendesign-paseo/launcher/open-design.json /opt/opendesign-paseo/launcher/SKILL.md /app/plugins/_official/woow/woow-paseo/
node --input-type=module -e '
import {verifyBundledInstallation} from "/opt/opendesign-paseo/host/standalone.mjs";
if(!verifyBundledInstallation("/app/plugins/_official/woow/woow-paseo"))throw Error("Native Paseo core required; obtain reviewed w2.5 digest before building");
'
# Native CAS must be supplied by the core, never a runtime overlay.
test -f /app/apps/daemon/dist/routes/mcp-servers.js
grep -Fq 'registerMcpServerRoutes' /app/apps/daemon/dist/mcp-routes.js
chown -R root:root /opt/opendesign-paseo
chmod -R go-w /opt/opendesign-paseo
