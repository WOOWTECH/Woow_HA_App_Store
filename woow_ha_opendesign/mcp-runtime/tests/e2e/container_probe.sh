#!/bin/sh
# In-container isolation / resource probe of the built-in MCP server (test-only; run as root via docker exec).
# Prints facts only: process owners and memory, whether Supervisor credentials are in each process environment
# (a count, never the value), listening ports, file modes, and what UID 1001 / ha-ingress can and cannot open.
set -u
py=/opt/woow/.venv/bin/python
run=/run/ha-opendesign-mcp

od=$(pgrep -f '^/usr/local/bin/node /opt/ha-opendesign/headless-entry.mjs' | head -1)
ngx=$(pgrep -f 'nginx: master' | head -1)
tty=$(pgrep -f '/usr/bin/ttyd' | head -1)
mgmt=$(pgrep -f 'ha_opendesign_mcp/management.py' | head -1)
child=$(pgrep -f 'ha_opendesign_mcp/child.py' | head -1)

echo '== processes (uid, VmRSS kB, Pss kB, SUPERVISOR_TOKEN entries in environ)'
# /proc/<pid>/environ and smaps_rollup need ptrace-read access: read them as the process's own uid (this exec has
# no CAP_SYS_PTRACE). The MCP management process is not dumpable (vendored guard), so even its own uid cannot.
for entry in "opendesign-daemon:$od" "nginx-master:$ngx" "ttyd:$tty" "mcp-management:$mgmt" "mcp-child:$child"; do
  name=${entry%%:*}
  pid=${entry#*:}
  if [ -z "$pid" ]; then echo "$name MISSING"; continue; fi
  uid=$(awk '/^Uid:/{print $2}' /proc/$pid/status)
  rss=$(awk '/^VmRSS:/{print $2}' /proc/$pid/status)
  pss=$(su-exec "$uid" awk '/^Pss:/{print $2}' /proc/$pid/smaps_rollup 2>/dev/null || true)
  env=$(su-exec "$uid" cat /proc/$pid/environ 2>/dev/null | tr '\0' '\n')
  if [ -n "$env" ]; then sup=$(printf '%s\n' "$env" | grep -c '^SUPERVISOR_TOKEN=' || true); else sup='unreadable(not dumpable)'; fi
  echo "$name pid=$pid uid=$uid rss_kb=$rss pss_kb=${pss:-n/a} supervisor_token_env=$sup"
done
for pid in $(pgrep -f 'nginx: worker'); do
  uid=$(awk '/^Uid:/{print $2}' /proc/$pid/status)
  echo "nginx-worker pid=$pid uid=$uid supervisor_token_env=$(su-exec "$uid" cat /proc/$pid/environ | tr '\0' '\n' | grep -c '^SUPERVISOR_TOKEN=' || true)"
done
total_rss=0
for pid in $(pgrep -u 10001); do
  total_rss=$((total_rss + $(awk '/^VmRSS:/{print $2}' /proc/$pid/status)))
done
echo "uid10001_total rss_kb=$total_rss processes=$(pgrep -u 10001 | wc -l)"
echo "container memory (cgroup): $(cat /sys/fs/cgroup/memory.current 2>/dev/null) bytes"

echo '== listening TCP sockets'
netstat -ltn 2>/dev/null | awk 'NR>2{print $4}' | sort

echo '== modes'
stat -c '%a %U:%G %n' /data/mcp /data/mcp/state.json "$run" "$run/admin.sock" "$run/child" "$run/child/child.sock" 2>&1

echo '== as open-design (UID 1001: OpenDesign, agents, ttyd shell)'
su-exec open-design:open-design cat /data/mcp/state.json >/dev/null 2>&1 && echo 'read state.json: ALLOWED (FAIL)' || echo 'read state.json: denied'
su-exec open-design:open-design ls "$run" >/dev/null 2>&1 && echo 'list socket dir: ALLOWED (FAIL)' || echo 'list socket dir: denied'
su-exec open-design:open-design "$py" -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])' "$run/admin.sock" 2>/dev/null && echo 'connect admin.sock: ALLOWED (FAIL)' || echo 'connect admin.sock: denied'
su-exec open-design:open-design cat "/proc/$mgmt/environ" >/dev/null 2>&1 && echo 'read MCP environ: ALLOWED (FAIL)' || echo 'read MCP environ: denied'
su-exec open-design:open-design "$py" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 3000)); print("bind 127.0.0.1:3000: free for OpenDesign agents")'

echo '== as ha-ingress (nginx)'
su-exec ha-ingress:ha-ingress "$py" -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); print("connect admin.sock: allowed")' "$run/admin.sock" 2>/dev/null || echo 'connect admin.sock: denied (FAIL)'
su-exec ha-ingress:ha-ingress "$py" -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])' "$run/child/child.sock" 2>/dev/null && echo 'connect child.sock: ALLOWED (FAIL)' || echo 'connect child.sock: denied'

echo '== child (vendored OpenDesign MCP server) tools over child.sock, as uid mcp'
su-exec mcp:mcp "$py" - "$run/child/child.sock" <<'PY'
import json, sys, httpx
client = httpx.Client(transport=httpx.HTTPTransport(uds=sys.argv[1]), timeout=10)
url = 'http://127.0.0.1:3000/mcp'
h = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
def parse(r):
    for ev in r.text.split('\n\n'):
        d = '\n'.join(l[5:].lstrip() for l in ev.splitlines() if l.startswith('data:'))
        if d.strip():
            return json.loads(d)
    return r.json()
r = client.post(url, headers=h, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'probe', 'version': '0'}}})
h['mcp-session-id'] = r.headers['mcp-session-id']
h['mcp-protocol-version'] = parse(r)['result']['protocolVersion']
client.post(url, headers=h, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
tools = parse(client.post(url, headers=h, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}))['result']['tools']
print(json.dumps({'child_tools_count': len(tools), 'names': sorted(t['name'] for t in tools)}))
client.delete(url, headers=h)
PY
