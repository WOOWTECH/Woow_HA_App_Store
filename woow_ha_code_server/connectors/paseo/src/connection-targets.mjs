import path from 'node:path';
import { readRecord } from './onboarding.mjs';
import { RuntimeError } from './state.mjs';

// Verified against WOOWTECH/woowtech-smart 9214c6ea87 brand manifests.
// These are connection profiles, not replacements for the branded push sender.
// Smart deployments previously used 0.10.1, before protected relay security. Keep the
// existing profiles compatible with those clients during managed host upgrades; the
// newer Smart web deployment alone does not update every installed mobile client.
export const CONNECTION_TARGETS = Object.freeze([
  Object.freeze({ id: 'paseo', label: 'Paseo', appUrl: 'https://app.paseo.sh', relayEndpoint: 'relay.paseo.sh:443', openUrl: 'https://app.paseo.sh/', protectedRelay: true }),
  Object.freeze({ id: 'woowtech', label: 'Woowtech Smart', appUrl: 'https://smart.woowtech.io', relayEndpoint: 'relay.woowtech.io:443', openUrl: 'https://smart.woowtech.io/', protectedRelay: false }),
  Object.freeze({ id: 'apporo', label: 'Apporo Smart', appUrl: 'https://smart.apporo.ai', relayEndpoint: 'relay.apporo.ai:443', openUrl: 'https://smart.apporo.ai/', protectedRelay: false }),
]);

export function connectionTarget(id = 'paseo') {
  const target = CONNECTION_TARGETS.find(row => row.id === id);
  if (!target) throw new RuntimeError('INVALID_TARGET');
  return target;
}

export function connectionPreferences(loc) {
  const preferences = readRecord(path.join(loc.stateDir, 'preferences.json'));
  return { ...preferences, name: typeof preferences.name === 'string' ? preferences.name : 'Pi Agent', target: connectionTarget(preferences.target).id,
    // Off unless the user turned it on in Agent Connect settings (Paseo's own default is off too).
    agentCollaboration: preferences.agentCollaboration === true,
    usageLookup: typeof preferences.usageLookup === 'boolean' ? preferences.usageLookup : undefined,
    idleRuntimeCleanup: typeof preferences.idleRuntimeCleanup === 'boolean' ? preferences.idleRuntimeCleanup : undefined };
}

export function targetEnvironment(target) {
  const profile = connectionTarget(target);
  return {
    PI_PASEO_CONNECTION_TARGET: profile.id,
    PASEO_APP_BASE_URL: profile.appUrl,
    PASEO_RELAY_ENABLED: 'true',
    PASEO_RELAY_ENDPOINT: profile.relayEndpoint,
    PASEO_RELAY_PUBLIC_ENDPOINT: profile.relayEndpoint,
    PASEO_RELAY_USE_TLS: 'true',
    PASEO_RELAY_PUBLIC_USE_TLS: 'true',
    PASEO_CORS_ORIGINS: profile.appUrl,
  };
}

export function targetConfiguration(config, target) {
  const profile = connectionTarget(target);
  const origins = config.daemon?.cors?.allowedOrigins || [];
  if (!Array.isArray(origins) || origins.some(origin => typeof origin !== 'string')) throw new RuntimeError('CONFIG_INVALID');
  const managedOrigins = new Set(CONNECTION_TARGETS.map(row => row.appUrl));
  // Pin both policies on every start: the official profile requires protected security,
  // while Smart clients retain compatibility. Switching profiles must replace either value.
  const security = { requireProtectedSecurity: profile.protectedRelay };
  return {
    ...config,
    app: { ...config.app, baseUrl: profile.appUrl },
    daemon: {
      ...config.daemon,
      relay: { ...config.daemon?.relay, enabled: true, endpoint: profile.relayEndpoint, publicEndpoint: profile.relayEndpoint, useTls: true, publicUseTls: true, ...security },
      cors: { ...config.daemon?.cors, allowedOrigins: [...origins.filter(origin => !managedOrigins.has(origin.replace(/\/$/, ''))), profile.appUrl] },
    },
  };
}

export function targetPairUrl(official, target = 'paseo') {
  const profile = connectionTarget(target);
  let url;
  try { url = new URL(official); } catch { throw new RuntimeError('PAIRING_ORIGIN_INVALID'); }
  if (url.origin !== profile.appUrl || url.username || url.password || url.pathname !== '/' || url.search || !/^#offer=[A-Za-z0-9_-]+$/.test(url.hash)) throw new RuntimeError('PAIRING_ORIGIN_INVALID');
  let offer;
  try { offer = JSON.parse(Buffer.from(url.hash.slice(7), 'base64url').toString('utf8')); }
  catch { throw new RuntimeError('PAIRING_OFFER_INVALID'); }
  if (offer?.v !== 2 || typeof offer.serverId !== 'string' || !offer.serverId || typeof offer.daemonPublicKeyB64 !== 'string' || !offer.daemonPublicKeyB64 || offer.relay?.endpoint !== profile.relayEndpoint || offer.relay?.useTls !== true) throw new RuntimeError('PAIRING_TARGET_MISMATCH');
  // An offer pinning a minimum security mode (0.17.4 sends minimumSecurityMode: "protected" while the
  // daemon requires it) cannot be used by an app that predates the field: refuse it, never hand it out.
  if (!profile.protectedRelay && offer.minimumSecurityMode !== undefined) throw new RuntimeError('PAIRING_SECURITY_UNSUPPORTED');
  return `${profile.appUrl}/${url.hash}`;
}
