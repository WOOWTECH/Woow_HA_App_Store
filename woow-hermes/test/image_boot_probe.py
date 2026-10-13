"""Finite, secret-free evidence from real s6 worker PIDs, not CMD heartbeats."""
import json
import os
from pathlib import Path
import socket
import subprocess
import urllib.request


def secret_nonempty(path):
    return path.is_file() and path.stat().st_size > 0


def service_pid(role):
    result = subprocess.run(['/command/s6-svstat', '-p', '/run/service/' + role],
                            capture_output=True, text=True)
    return int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else 0


def environment_checks(path):
    # Same UID reads its worker environment; no SYS_PTRACE or secret output.
    code = """import pathlib,sys,json
items=pathlib.Path(sys.argv[1]).read_bytes().split(bytes([0]))
print(json.dumps({'tokens_absent':not any(x.startswith((b'SUPERVISOR_TOKEN=',b'HASSIO_TOKEN=')) for x in items),
'supervised_child':b'HERMES_S6_SUPERVISED_CHILD=1' in items}))"""
    result = subprocess.run(['/command/s6-setuidgid', 'hermes', '/opt/hermes/.venv/bin/python',
                             '-c', code, str(path)], capture_output=True)
    if result.returncode:
        return {'tokens_absent': False, 'supervised_child': False}
    return json.loads(result.stdout)


def worker_checks(role, pid, main_pid, proc=Path('/proc'), env_reader=environment_checks):
    out = {'identity': False, 'uid10000': False, 'tokens_absent': False}
    if pid <= 0 or pid == main_pid:
        return out
    try:
        root = proc / str(pid)
        args = [x.decode() for x in (root / 'cmdline').read_bytes().split(bytes([0])) if x]
        status = dict(line.split(':', 1) for line in (root / 'status').read_text().splitlines() if ':' in line)
        parent_args = [x.decode() for x in (proc / status['PPid'].strip() / 'cmdline').read_bytes().split(bytes([0])) if x]
        supervised = bool(parent_args) and Path(parent_args[0]).name == 's6-supervise' and parent_args[-1].rstrip('/').split('/')[-1] == role
        cli = next((i for i, arg in enumerate(args) if Path(arg).name == 'hermes'), -1)
        expected = ['gateway', 'run', '--replace'] if role == 'gateway-default' else ['dashboard']
        identity = cli >= 0 and args[cli + 1:cli + 1 + len(expected)] == expected
        env = env_reader(root / 'environ')
        out['identity'] = supervised and identity and (role != 'gateway-default' or env['supervised_child'])
        out['uid10000'] = status['Uid'].split() == ['10000'] * 4
        out['tokens_absent'] = env['tokens_absent'] is True
    except (OSError, KeyError, ValueError):
        pass
    return out


def gateway_health():
    # Pinned runtime gateway/platforms/api_server.py:2217,3162: GET /health,
    # unauthenticated JSON {status: ok, platform: hermes-agent, version: ...}.
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8642/health', timeout=2) as response:
            body = response.read(4097)
            return (response.status == 200 and response.headers.get_content_type() == 'application/json'
                    and len(body) <= 4096 and valid_health(json.loads(body)))
    except (OSError, ValueError):
        return False


def valid_health(value):
    return isinstance(value, dict) and value.get('status') == 'ok' and value.get('platform') == 'hermes-agent'


def collect():
    checks = {'pid1_s6': b's6-svscan' in Path('/proc/1/cmdline').read_bytes(),
              'tokens_removed_from_envdir': all(not (Path('/run/s6/container_environment') / k).exists() for k in ('SUPERVISOR_TOKEN', 'HASSIO_TOKEN')),
              'bootstrap_secret_nonempty': secret_nonempty(Path('/data/secrets/api_server_key')),
              'gateway_json_health': gateway_health()}
    main_pid = service_pid('main-hermes')
    for role in ('gateway-default', 'dashboard'):
        checks.update({role + '_' + k: v for k, v in worker_checks(role, service_pid(role), main_pid).items()})
    for port, role in ((9119, 'dashboard'), (9121, 'relay')):
        checks[role + '_listening'] = False
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                checks[role + '_listening'] = True
        except OSError:
            pass
    return checks


if __name__ == '__main__':
    checks = collect()
    print(json.dumps(checks))
    raise SystemExit(0 if all(checks.values()) else 1)
