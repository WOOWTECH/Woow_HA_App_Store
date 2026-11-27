'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { WEB_CLIENTS, pairingUrlForWebApp } = require('../shared/web-clients.cjs');

test('each target accepts only its canonical V2 offer and retains all private bytes', () => {
  for(const app of WEB_CLIENTS) {
    const authority={v:2,serverId:'fixture-private',daemonPublicKeyB64:'fixture-public-key',relay:{endpoint:app.relayEndpoint,useTls:true}};
    const url=`${app.url}#offer=${Buffer.from(JSON.stringify(authority)).toString('base64url')}`;
    assert.equal(pairingUrlForWebApp(url,app.id),url);assert.equal(pairingUrlForWebApp(url,app.url),url);
    for(const other of WEB_CLIENTS.filter(x=>x.id!==app.id))assert.equal(pairingUrlForWebApp(url,other.id),undefined);
    for(const change of [{v:1},{serverId:''},{daemonPublicKeyB64:''},{relay:{endpoint:'relay.evil.example:443',useTls:true}},{relay:{endpoint:app.relayEndpoint,useTls:false}},...(!app.protectedRelay?[{minimumSecurityMode:'protected'}]:[])]) {
      const modified=`${app.url}#offer=${Buffer.from(JSON.stringify({...authority,...change})).toString('base64url')}`;
      assert.equal(pairingUrlForWebApp(modified,app.id),undefined);
    }
  }
});
test('pairing rejects malformed authority and unknown producer or redirect routes', () => {
  for(const value of ['https://evil.example/#fixture','https://app.paseo.sh.evil.example/#fixture','http://app.paseo.sh/#fixture','https://user:password@app.paseo.sh/#fixture','https://app.paseo.sh/redirect#fixture','https://app.paseo.sh/','https://app.paseo.sh/#fixture\n','javascript:alert(1)',undefined]) {
    assert.equal(pairingUrlForWebApp(value,'https://smart.woowtech.io/'),undefined);
  }
  for(const target of ['https://user:password@smart.apporo.ai/','https://smart.apporo.ai/?','https://smart.apporo.ai/#','https://smart.apporo.ai/?token=private','https://smart.apporo.ai/#private','https://smart.apporo.ai/\n','javascript:alert(1)','']) {
    assert.equal(pairingUrlForWebApp('https://app.paseo.sh/#fixture',target),undefined);
  }
});
