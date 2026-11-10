#!/usr/bin/env python3
"""Binary-safe, bounded SSH command transport; no implicit credential lookup.

The EOF check and concurrent stdout/stderr/stdin pump fix the QA harness's
truncated binary output/deadlock behavior. They are not a code-server fix.
"""
import argparse
import hashlib
import json
import math
import shlex
import subprocess
import sys
import time

MAX_INPUT = 128 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024

class TransportError(Exception):
    pass

def ssh_run(client, argv, stdin=None, timeout=60, max_output=MAX_OUTPUT):
    """Drain both streams while sending stdin; no shell interpolation of argv.

Callers must use a remote timeout too: closing SSH alone cannot kill a process.
"""
    if not math.isfinite(timeout) or not 0 < timeout <= 3605:
        raise TransportError("timeout must be between 0 and 3605 seconds")
    if not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
        raise TransportError("argv requires nonempty strings without NUL")
    if not isinstance(max_output, int) or max_output < 1:
        raise TransportError("output limit must be positive")
    data = stdin.encode() if isinstance(stdin, str) else (stdin or b"")
    if len(data) > MAX_INPUT:
        raise TransportError("stdin exceeds input limit")
    channel = client.get_transport().open_session(timeout=15)
    channel.settimeout(min(1, timeout))
    out, err = bytearray(), bytearray()
    deadline = time.monotonic() + timeout
    offset, ended = 0, False
    try:
        channel.exec_command(shlex.join(list(argv)))
        while True:
            if time.monotonic() >= deadline:
                raise TransportError("SSH operation deadline exceeded")
            changed = False
            for ready, receive, destination in ((channel.recv_ready, channel.recv, out),
                                                (channel.recv_stderr_ready, channel.recv_stderr, err)):
                if ready():
                    chunk = receive(65536)
                    if len(destination) + len(chunk) > max_output:
                        raise TransportError("command output limit exceeded")
                    destination.extend(chunk)
                    changed = True
            # Exit status can arrive before the final output packets. An empty
            # buffer is only final once SSH has delivered EOF or closed the channel.
            if ((channel.eof_received or channel.closed) and channel.exit_status_ready()
                    and not channel.recv_ready() and not channel.recv_stderr_ready()):
                if offset != len(data):
                    raise TransportError("remote exited before all stdin was sent")
                return subprocess.CompletedProcess(argv, channel.recv_exit_status(), bytes(out), bytes(err))
            if offset < len(data) and channel.send_ready():
                sent = channel.send(data[offset:offset + 65536])
                if not sent:
                    raise TransportError("remote stdin closed early")
                offset += sent
                changed = True
            if offset == len(data) and not ended:
                channel.shutdown_write()
                ended = True
            if not changed:
                time.sleep(0.01)
    finally:
        channel.close()


def connect(host, user, known_hosts, identity=None, agent=False, port=22):
    """Use only the supplied known-hosts file and explicitly selected auth source."""
    if not host or not user or not known_hosts or bool(identity) == bool(agent):
        raise TransportError('host, user, known-hosts and exactly one of identity/agent are required')
    import paramiko  # Optional; offline tests never import or need Paramiko.
    client = paramiko.SSHClient()
    try:
        client.load_host_keys(known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(hostname=host, port=port, username=user, key_filename=identity,
                       allow_agent=agent, look_for_keys=False, timeout=15,
                       banner_timeout=15, auth_timeout=15)
        return client
    except Exception:
        client.close()
        raise


def run(client, argv, stdin=None, timeout=60, max_output=MAX_OUTPUT):
    if not argv or not 1 <= timeout <= 3600:
        raise TransportError('command and timeout 1..3600 required')
    # A client timeout alone does not terminate remote processes. GNU timeout is
    # an explicit remote prerequisite. Container exec can be part of argv.
    command = ['timeout', '--signal=TERM', '--kill-after=3s', str(timeout)+'s', *argv]
    return ssh_run(client, command, stdin, timeout+5, max_output)


def test_binary_output(client, python='python3'):
    script = ('import sys; n=int(sys.argv[1]); '
              'sys.stdout.buffer.write(bytes(range(256))*(n//256)); sys.stdout.buffer.flush(); '
              'sys.stderr.buffer.write(bytes(reversed(range(256)))*257); sys.stderr.buffer.flush()')
    checks = []
    for size in (2*1024*1024, 4*1024*1024):
        result = run(client, [python, '-B', '-c', script, str(size)], timeout=30)
        streams = {}
        for name, received, expected in (
                ('stdout', result.stdout, bytes(range(256))*(size//256)),
                ('stderr', result.stderr, bytes(reversed(range(256)))*257)):
            streams[name] = {'bytes':len(received), 'sha256':hashlib.sha256(received).hexdigest(),
                             'ok':received == expected}
        checks.append({'exitCode':result.returncode, 'streams':streams,
                       'ok':result.returncode == 0 and all(s['ok'] for s in streams.values())})
    return {'ok':all(c['ok'] for c in checks), 'remoteFilesWritten':0, 'checks':checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--known-hosts', required=True)
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument('--identity', help='explicit private-key file; never copied or printed')
    auth.add_argument('--agent', action='store_true', help='explicitly opt into SSH_AUTH_SOCK')
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('test-output', help='read-only live 2/4 MiB binary output check')
    command = sub.add_parser('exec', help='execute an explicitly supplied remote command')
    command.add_argument('--stdin', action='store_true')
    command.add_argument('--timeout', type=int, default=60)
    command.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('port must be 1..65535')
    client = None
    try:
        client = connect(args.host,args.user,args.known_hosts,args.identity,args.agent,args.port)
        if args.operation == 'test-output':
            report = test_binary_output(client)
            print(json.dumps(report))
            return 0 if report['ok'] else 1
        argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
        data = sys.stdin.buffer.read(MAX_INPUT+1) if args.stdin else None
        result = run(client,argv,data,args.timeout)
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        return result.returncode if 0 <= result.returncode <= 255 else 1
    except Exception as error:
        # Do not serialize authentication exception text, host names or commands.
        print(json.dumps({'ok':False,'errorType':type(error).__name__}),file=sys.stderr)
        return 1
    finally:
        if client is not None: client.close()


if __name__ == '__main__':
    raise SystemExit(main())
