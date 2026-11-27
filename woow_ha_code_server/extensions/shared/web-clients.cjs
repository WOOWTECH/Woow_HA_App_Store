'use strict';

const WEB_CLIENTS = Object.freeze([
  Object.freeze({ id: 'paseo', label: 'Paseo official', url: 'https://app.paseo.sh/', relayEndpoint: 'relay.paseo.sh:443', protectedRelay: true }),
  Object.freeze({ id: 'woowtech', label: 'Woowtech Smart', url: 'https://smart.woowtech.io/', relayEndpoint: 'relay.woowtech.io:443', protectedRelay: false }),
  Object.freeze({ id: 'apporo', label: 'Apporo Smart', url: 'https://smart.apporo.ai/', relayEndpoint: 'relay.apporo.ai:443', protectedRelay: false }),
]);

function cleanWebUrl(value) {
  if (typeof value !== 'string' || value.length > 8192 || /[\x00-\x1f\x7f?#]/.test(value)) return undefined;
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return undefined;
    return url;
  } catch { return undefined; }
}

function webClient(value) {
  const url = cleanWebUrl(value);
  return WEB_CLIENTS.find(client => client.id === value || (url && client.url === url.href));
}

function pairingUrlForWebApp(value, destination) {
  const target = webClient(destination);
  if (!target || typeof value !== 'string' || value.length > 8192 || /[\x00-\x1f\x7f?]/.test(value)) return undefined;
  try {
    const offer = new URL(value);
    if (offer.origin !== new URL(target.url).origin || offer.username || offer.password || offer.pathname !== '/' || offer.search || !/^#offer=[A-Za-z0-9_-]+$/.test(offer.hash)) return undefined;
    const encoded = offer.hash.slice(7);
    const bytes = Buffer.from(encoded, 'base64url');
    if (bytes.toString('base64url') !== encoded) return undefined;
    const authority = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (authority?.v !== 2 || typeof authority.serverId !== 'string' || !authority.serverId || typeof authority.daemonPublicKeyB64 !== 'string' || !authority.daemonPublicKeyB64 || authority.relay?.endpoint !== target.relayEndpoint || authority.relay?.useTls !== true) return undefined;
    if (!target.protectedRelay && authority.minimumSecurityMode !== undefined) return undefined;
    // Never retarget an offer: origin, relay and security belong to one profile.
    return `${target.url}${offer.hash}`;
  } catch { return undefined; }
}

module.exports = { WEB_CLIENTS, cleanWebUrl, webClient, pairingUrlForWebApp };
