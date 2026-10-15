"""Ingress-side probe of /mcp-admin/ (test-only). Run inside the Ingress-peer container (172.30.32.2).

usage: python admin_probe.py <addon-host> <action>
  checks        page + bootstrap as admin; fixed backend refused; non-admin / no user refused (JSON lines)
  reveal        print ONLY the current token (for capture into a shell variable; never into a file)
  rotate        print ONLY the new token
  revoke        print the HTTP status
  grant-delete  enable the delete_project write grant; print status
  ungrant       remove all write grants; print status
Env: FAKE_ADMIN_ID, FAKE_USER_ID (two arbitrary Ingress user ids; there is no role lookup to tell them apart).
"""
import json
import os
import sys

import httpx

INGRESS = '/api/hassio_ingress/' + 'TeamHaMcpFakeIngressSession0000000000000000'  # not a secret


def headers(user):
    value = {'X-Ingress-Path': INGRESS}
    if user is not None:
        value['X-Remote-User-Id'] = user
    return value


def main():
    host, action = sys.argv[1], sys.argv[2]
    admin, plain = os.environ['FAKE_ADMIN_ID'], os.environ['FAKE_USER_ID']
    base = 'http://%s:8099/mcp-admin' % host
    with httpx.Client(timeout=15, trust_env=False) as client:
        def bootstrap(user=admin):
            return client.get(base + '/api/bootstrap', headers=headers(user))

        def mutate(name, body=None, method='POST'):
            boot = bootstrap().json()
            extra = {'X-CSRF-Token': boot['csrf']}
            if body is None:
                return client.request(method, base + '/api/' + name, headers={**headers(admin), **extra})
            return client.request(method, base + '/api/' + name, headers={**headers(admin), **extra,
                                  'Content-Type': 'application/json'}, content=json.dumps(body))

        if action == 'checks':
            page = client.get(base + '/', headers=headers(admin))
            print(json.dumps({'case': 'admin page', 'status': page.status_code,
                              'base_injected': INGRESS + '/mcp-admin' in page.text,
                              'csp': page.headers.get('content-security-policy', '')[:60]}))
            boot = bootstrap()
            data = boot.json()
            tools = data.get('tools', {})
            print(json.dumps({'case': 'bootstrap (admin)', 'status': boot.status_code, 'product': data.get('product'),
                              'connection_configured': data.get('connection_configured'),
                              'token_active': data.get('token_active'), 'writes_enabled': data.get('writes_enabled'),
                              'enabled_write_tools': data.get('enabled_write_tools'), 'disabled': data.get('disabled'),
                              'policy_contract': data.get('policy_contract'), 'tool_count': len(tools),
                              'write_tools': sorted(k for k, v in tools.items() if v.get('write')),
                              'health': data.get('health')}, sort_keys=True))
            fixed = mutate('backend', {'connection': {'url': 'http://example.invalid:7456'}}, 'PUT')
            print(json.dumps({'case': 'PUT backend (fixed loopback daemon)', 'status': fixed.status_code}))
            print(json.dumps({'case': 'bootstrap (another HA user; accepted risk: no role lookup)',
                              'status': bootstrap(plain).status_code}))
            print(json.dumps({'case': 'bootstrap (no X-Remote-User-Id)', 'status': bootstrap(None).status_code}))
            nocsrf = client.post(base + '/api/token/reveal', headers=headers(admin))
            print(json.dumps({'case': 'token/reveal without CSRF', 'status': nocsrf.status_code}))
        elif action in ('reveal', 'rotate'):
            r = mutate('token/' + action)
            r.raise_for_status()
            sys.stdout.write(r.json()['token'])
        elif action == 'revoke':
            print(json.dumps({'case': 'token/revoke', 'status': mutate('token/revoke').status_code}))
        elif action == 'grant-delete':
            r = mutate('policy', {'writes_enabled': False, 'disabled': [], 'enabled_write_tools': ['delete_project']}, 'PUT')
            print(json.dumps({'case': 'policy grant delete_project', 'status': r.status_code}))
        elif action == 'ungrant':
            r = mutate('policy', {'writes_enabled': False, 'disabled': [], 'enabled_write_tools': []}, 'PUT')
            print(json.dumps({'case': 'policy remove grants', 'status': r.status_code}))
        else:
            raise SystemExit('unknown action')


if __name__ == '__main__':
    main()
