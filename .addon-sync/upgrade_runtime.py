#!/usr/bin/env python3
"""Upgrade test of one add-on: startup (pipeline #137) and data (#138), category 2 of ADR-0005.

Runs the comparison target's image, then the new image on the same data
directories (/data and one per config.yaml `map` entry, at its `path`:
upgrade_check.mounts), each under a mock Home Assistant Supervisor
(mock_supervisor.py): the hassio bridge network 172.30.32.0/23, the
Supervisor at 172.30.32.2 (also as host `supervisor`), a fake
SUPERVISOR_TOKEN/HASSIO_TOKEN and /data/options.json from config.yaml's
option defaults. Each version must start, judged as upgrade_check.startup_probe
says from the Supervisor's address, and then stay up for stable_seconds; the
add-on's upgrade-check/settings.yaml may override the time limits.

Data directories: <root>/data at /data, or at the `path` of a `data` entry;
each other `map` entry at its `path` or Supervisor's default, from
<root>/<MAP_SOURCES[type] or type> (app_config/addon_config =
all_app_configs/<slug>; legacy names share the new name's directory); entries
Supervisor ignores are listed by upgrade_check.map_warnings().

Data check (#138): the add-on's upgrade-check/ (in the PR) may hold the hooks
`seed` (run once on the comparison target after it started, to write data) and
`verify` (run on the new version after it started, to read that data back).
Both are optional executables (any language with a #! line). They run inside
the mock Supervisor's container (python:3.12-alpine: python3 and busybox sh,
wget, timeout), so they reach the add-on from the Supervisor's address, and
never run docker themselves. Their environment:
  ADDON_URL        the add-on from the Supervisor: its webui's scheme and port,
                   else its ingress port, else http://ADDON_HOST (no path)
  ADDON_HOST       the add-on's address (172.30.33.10)
  ADDON_IMAGE, ADDON_VERSION   the version the hook runs against
  PHASE            old (seed) or new (verify)
  REPORT_DIR       where the hook may write <hook>.json (one directory per phase)
  HOOK_STATE_DIR   kept from seed to verify (ids, keys), never mounted in the add-on
  DATA_DIR_<TYPE>  each data directory as the hook sees it: DATA_DIR_DATA for
                   /data, DATA_DIR_ADDON_CONFIG, DATA_DIR_SHARE... per `map` type
  SUPERVISOR_URL, SUPERVISOR_TOKEN   the mock Supervisor (http://127.0.0.1 in
                   its container, so its request log keeps the add-on's calls only)
A hook passes when it exits 0 within hook_timeout (settings.yaml, default 600 s)
and its report, if any, has no failing check. The time limit covers the whole
docker exec; a hook must not leave background processes running (the mock's
container outlives it until the test ends). A hook that is a symlink out of
upgrade-check/ fails (only that directory is mounted). The report:
  {"checks": [{"name": "...", "result": "pass|fail|skip", "detail": "..."}]}
A failing seed or verify fails the upgrade test. Without verify, data is not
checked and the report says so.

Writes <report-dir>/<name>.json and <name>.md, appends the report to
--summary and exits 1 when the upgrade test fails (::error with the reason),
2 on a usage or tool error. Needs Docker; both images must be local or pullable.

The result (<name>.json; compare reads it): {name, passed, reason, hooks (the
hooks upgrade-check/ has), data_checked (verify ran), phases: [{phase, version,
image, method, started, detail, answer, logs, hooks: [{hook, phase, passed,
exit_code, detail, checks: [{name, result, detail}], output}]}]}. exit_code is
None when the hook timed out or could not be started (a symlink out of upgrade-check/).
"""
from __future__ import annotations
import argparse, json, pathlib, secrets, shutil, subprocess, sys, tempfile, time
import yaml
from upgrade_check import ingress_port, mounts, startup_probe, upgrade_settings, webui_endpoint
from addon_sync import markdown_cell, workflow_command

# The mock Supervisor runs in this image; the fake add-ons of test_upgrade_runtime.py build on it too.
MOCK_IMAGE = 'python:3.12-alpine@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8'
SUBNET, GATEWAY, SUPERVISOR_IP, ADDON_IP = '172.30.32.0/23', '172.30.32.1', '172.30.32.2', '172.30.33.10'
TOOLING = pathlib.Path(__file__).resolve().parent
# How the mock Supervisor runs, and how long open() waits for it to answer (tests slow or break it).
MOCK_COMMAND, MOCK_WAIT = ['python', '-u', '/tooling/mock_supervisor.py', 'serve'], 30
STARTUP_ONLY = 'Startup only: data was not checked (只檢查啟動，沒有檢查資料).'
DATA_CHECKED = 'Data checked: seed wrote data on the comparison target, verify read it back on the new version (已檢查資料).'
DATA_CHECKED_VERIFY_ONLY = 'Data checked by verify on the new version; there is no seed, so no data was written on the comparison target (已檢查資料).'
NOT_CHECKED = 'Data was not checked: the test failed before verify ran (沒有檢查資料).'
PHASE_LABEL = {'old': 'the comparison target', 'new': 'the new version'}
# The data hooks (#138) and the phase each runs in; smoke, in both phases, is category 3.
HOOK_PHASE = {'seed': 'old', 'verify': 'new'}
# Where the mock Supervisor's container sees the add-on's upgrade-check/, the data directories, the hooks' reports and state.
IN_MOCK = {'hooks': '/upgrade-check', 'data': '/upgrade-data', 'reports': '/hook-reports', 'state': '/hook-state'}
CHECK_RESULTS = ('pass', 'fail', 'skip')

def docker(*args, check=True):
    r = subprocess.run(['docker', *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and r.returncode:
        raise RuntimeError(f'docker {args[0]} failed ({r.returncode}): {(r.stderr or r.stdout).strip()[-1000:]}')
    return r.stdout

def default_options(config):
    """What Supervisor writes to /data/options.json for a fresh install: the option defaults (no null ones)."""
    return {k: v for k, v in (config.get('options') or {}).items() if v is not None}

def addon_info(config, options):
    """The mock Supervisor's /addons/self/info for this version."""
    keys = ('name', 'slug', 'version', 'description', 'url', 'arch', 'ingress', 'ingress_port', 'ingress_entry', 'webui', 'watchdog', 'ports')
    info = {k: config[k] for k in keys if k in config}
    # The port the add-on must serve ingress on, as Supervisor reports it: never 0, which it replaces at install.
    if config.get('ingress'):info['ingress_port'] = ingress_port(config)
    return {**info, 'hostname': f'local-{config.get("slug", "addon")}', 'ip_address': ADDON_IP, 'state': 'started', 'boot': 'auto',
        'repository': 'local', 'version_latest': config.get('version'), 'update_available': False, 'options': options,
        'ingress_url': f'/api/hassio_ingress/{secrets.token_hex(8)}/' if config.get('ingress') else None, 'network': config.get('ports')}

def addon_url(config):
    """ADDON_URL of the hooks: the webui's scheme and port, else the ingress port, else the bare address."""
    webui = webui_endpoint(config)
    if webui:return f'{webui[0]}://{ADDON_IP}:{webui[1]}'
    if config.get('ingress'):return f'http://{ADDON_IP}:{ingress_port(config)}'
    return f'http://{ADDON_IP}'

def hook_problem(hooks_dir, hook):
    """Why upgrade-check/<hook> cannot run in the mock Supervisor's container, or '': only upgrade-check/ is mounted
    there, so a symlink that leaves it would point at nothing (a silent exit 127)."""
    path = hooks_dir / hook
    if path.is_symlink() and not path.resolve().is_relative_to(hooks_dir.resolve()):
        return f'upgrade-check/{hook} is a symlink to {path.resolve()}, outside upgrade-check/ (only that directory is mounted where hooks run)'
    return ''

class UpgradeTestEnv:
    """One upgrade test's network, mock Supervisor and data directories, removed by close(). `hooks`: the add-on's
    upgrade-check/ directory, mounted read-only in the mock Supervisor's container (None when it has none)."""
    def __init__(self, work, hooks=None):
        self.work, self.hooks = pathlib.Path(work), hooks
        self.prefix = f'upgrade-test-{secrets.token_hex(4)}'
        self.net, self.supervisor, self.token = self.prefix, f'{self.prefix}-supervisor', secrets.token_hex(24)
        self.state, self.data = self.work / 'supervisor', self.work / 'dirs'
        self.reports, self.hook_state = self.work / 'hook-reports', self.work / 'hook-state'
        for d in (self.state, self.data, self.reports, self.hook_state):d.mkdir(parents=True)
    def open(self):
        docker('network', 'create', '--subnet', SUBNET, '--gateway', GATEWAY, self.net)
        binds = [(TOOLING, '/tooling', True), (self.state, '/state', False), (self.data, IN_MOCK['data'], False),
            (self.reports, IN_MOCK['reports'], False), (self.hook_state, IN_MOCK['state'], False)]
        if self.hooks:binds.append((self.hooks, IN_MOCK['hooks'], True))
        args = []
        for source, target, read_only in binds:
            args += ['--mount', f'type=bind,source={source},target={target}' + (',readonly' if read_only else '')]
        docker('run', '-d', '--name', self.supervisor, '--network', self.net, '--ip', SUPERVISOR_IP, '-e', f'SUPERVISOR_TOKEN={self.token}',
            *args, MOCK_IMAGE, *MOCK_COMMAND)
        # Real Supervisor is up before any add-on starts, and add-ons ask it for their info at once (bashio reads
        # options at boot): return only when the mock answers. Any answer below HTTP 500 will do (401 without the
        # token). Asked from inside the mock (127.0.0.1), so its request log keeps only the add-on's calls.
        deadline = time.monotonic() + MOCK_WAIT
        while not self.probe('http://127.0.0.1/supervisor/ping', 500, timeout=2):
            down = _down(self.supervisor)
            if down or time.monotonic() >= deadline:
                why = f'({down})' if down else f'within {MOCK_WAIT} s'
                raise RuntimeError(f'the mock Supervisor did not answer {why}; its last log lines: {_logs(self.supervisor, 20).strip()[-1000:]}')
            time.sleep(0.5)
    def probe(self, url, below, timeout=5):
        """One check of `url` from the Supervisor's address (mock_supervisor.py probe; `below` None for tcp)."""
        limit = [] if below is None else ['--below', str(below)]
        return subprocess.run(['docker', 'exec', self.supervisor, 'python', '/tooling/mock_supervisor.py', 'probe', '--url', url, *limit,
            '--timeout', str(timeout)], capture_output=True).returncode == 0
    def fetch(self, url):
        """The first 200 characters of what `url` answers from the Supervisor's address ('' when it does not)."""
        code = (f'import urllib.request,ssl;print(urllib.request.urlopen({url!r},timeout=5,context=ssl._create_unverified_context())'
            '.read()[:200].decode(errors="replace"))')
        return docker('exec', self.supervisor, 'python', '-c', code, check=False).strip()
    def start(self, phase, image, config):
        """Start one version on the shared directories; its container name."""
        options = default_options(config)
        (self.state / 'addon.json').write_text(json.dumps(addon_info(config, options)), encoding='utf-8')
        args = []
        for m in mounts(config, self.data.as_posix()):
            pathlib.Path(m['source']).mkdir(parents=True, exist_ok=True)
            args += ['--mount', f'type=bind,source={m["source"]},target={m["target"]}' + (',readonly' if m['read_only'] else '')]
        (self.data / 'data/options.json').write_text(json.dumps(options), encoding='utf-8')
        container = f'{self.prefix}-{phase}'
        # Supervisor adds docker's init unless config.yaml says init: false; no restart policy, so a restart shows as an exit.
        init = [] if config.get('init') is False else ['--init']
        docker('run', '-d', '--name', container, '--network', self.net, '--ip', ADDON_IP, *init,
            '--add-host', f'supervisor:{SUPERVISOR_IP}', '--add-host', f'hassio:{SUPERVISOR_IP}',
            '-e', f'SUPERVISOR_TOKEN={self.token}', '-e', f'HASSIO_TOKEN={self.token}', '-e', 'TZ=UTC', *args, image)
        return container
    def hook_env(self, phase, image, config):
        """The environment of a hook run against this version (the module docstring lists it)."""
        out = {'ADDON_URL': addon_url(config), 'ADDON_HOST': ADDON_IP, 'ADDON_IMAGE': image, 'ADDON_VERSION': str(config.get('version')),
            'PHASE': phase, 'REPORT_DIR': f'{IN_MOCK["reports"]}/{phase}', 'HOOK_STATE_DIR': IN_MOCK['state'],
            'SUPERVISOR_URL': 'http://127.0.0.1', 'SUPERVISOR_TOKEN': self.token}
        for m in mounts(config, IN_MOCK['data']):
            # Named by the type as config.yaml writes it (a renamed type shares its directory with the new name).
            out['DATA_DIR_' + m['type'].upper()] = m['source']
        return out
    def run_hook(self, hook, phase, image, config, timeout):
        """Run upgrade-check/<hook> against the running version: {hook, phase, passed, exit_code, detail, checks, output}."""
        (self.reports / phase).mkdir(exist_ok=True)
        report = self.reports / phase / f'{hook}.json'
        if report.exists():report.unlink()
        unusable = hook_problem(self.hooks, hook)
        if unusable:
            return {'hook': hook, 'phase': phase, 'passed': False, 'exit_code': None, 'detail': f'could not run: {unusable}', 'checks': [], 'output': ''}
        envs = [a for k, v in self.hook_env(phase, image, config).items() for a in ('-e', f'{k}={v}')]
        started = time.monotonic()
        try:
            # busybox timeout ends the hook inside the container; the subprocess timeout only guards a hung docker exec.
            r = subprocess.run(['docker', 'exec', '-w', IN_MOCK['hooks'], *envs, self.supervisor, 'timeout', str(timeout), f'{IN_MOCK["hooks"]}/{hook}'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', timeout=timeout + 60)
            code, output = r.returncode, r.stdout
        except subprocess.TimeoutExpired as e:
            # On POSIX the partial output is bytes even with text=True.
            out = e.stdout or ''
            code, output = None, out.decode('utf-8', 'replace') if isinstance(out, bytes) else out
        elapsed = time.monotonic() - started
        checks, problem = _read_checks(report)
        failing = [c['name'] for c in checks if c['result'] == 'fail']
        if code is None or (code and elapsed >= timeout):detail = f'did not finish within {timeout} s (hook_timeout)'
        elif code == 126:detail = f'could not run (exit 126): is upgrade-check/{hook} executable (git update-index --chmod=+x) with a #! line?'
        elif code == 127:detail = (f'could not run (exit 127): the interpreter on the #! line of upgrade-check/{hook} was not found; hooks run with '
            'python3 and busybox sh only (no bash), and a CRLF line ending breaks the #! line')
        elif code:detail = f'exited with code {code}'
        else:detail = 'exited 0'
        if problem:detail += f'; {problem}'
        elif failing:detail += '; failing checks: ' + ', '.join(failing)
        return {'hook': hook, 'phase': phase, 'passed': code == 0 and not problem and not failing, 'exit_code': code, 'detail': detail,
            'checks': checks, 'output': output[-4000:]}
    def stop(self, container, config):
        docker('stop', '-t', str(config.get('timeout', 10)), container, check=False)
        docker('rm', '-f', container, check=False)
    def close(self):
        docker('rm', '-f', f'{self.prefix}-old', f'{self.prefix}-new', self.supervisor, check=False)
        docker('network', 'rm', self.net, check=False)
        # Containers write as root: remove what they left through a container, then the rest.
        docker('run', '--rm', '--mount', f'type=bind,source={self.work},target=/w', '--entrypoint', 'sh', MOCK_IMAGE, '-c', 'rm -rf /w/* /w/.[!.]*', check=False)

def _read_checks(path):
    """(checks, problem) from a hook's report: [] when it wrote none; problem is why the report cannot be used."""
    if not path.exists():return [], ''
    try:data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:return [], f'its report {path.name} is not JSON: {e}'
    checks = data.get('checks') if isinstance(data, dict) else None
    if not isinstance(checks, list):return [], f'its report {path.name} has no "checks" list'
    out = []
    for c in checks:
        if not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'] or c.get('result') not in CHECK_RESULTS:
            return out, f'its report {path.name} has a check that is not {{"name": "...", "result": "pass|fail|skip"}}: {json.dumps(c)[:200]}'
        if any(o['name'] == c['name'] for o in out):return out, f'its report {path.name} names two checks {c["name"]!r}'
        out.append({'name': c['name'], 'result': c['result'], 'detail': str(c.get('detail', ''))})
    return out, ''

def _logs(container, tail):
    """The container's last `tail` log lines, stdout and stderr."""
    r = subprocess.run(['docker', 'logs', '--tail', str(tail), container], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.stdout + r.stderr

def _state(container):
    """(docker's State of the container, its RestartCount)."""
    state, restarts = docker('inspect', '-f', '{{json .State}} {{.RestartCount}}', container).strip().rsplit(' ', 1)
    return json.loads(state), int(restarts)

def wait_started(env, container, probe):
    """(started, detail, answer): whether the version started as `probe` (upgrade_check.startup_probe) says, why or
    why not, and the start of what its url answered (http only). Started: the probe answers within the time limit
    (none for stays-up), then the container runs stable_seconds without exiting or restarting."""
    url = probe['url'].replace('[HOST]', ADDON_IP)
    if probe['below'] is not None:
        answered = 'with success' if probe['method'] == 'watchdog' else f'below HTTP {probe["below"]}'
    else:answered = 'by accepting a connection'
    started = time.monotonic(); deadline = started + probe['timeout']
    stays = probe['stable_seconds']; answer = ''; prefix = ''
    if probe['method'] != 'stays-up':
        # 1. The probe answers within the time limit (the container must not exit or restart meanwhile).
        while not env.probe(url, probe['below']):
            down = _down(container)
            if down:return False, down, ''
            # startup_probe keeps stable_seconds below the timeout, so only a probe can run out of time.
            if time.monotonic() >= deadline:
                return False, f'the {probe["method"]} {url} did not answer {answered} within {probe["timeout"]} s', ''
            time.sleep(1)
        answer = env.fetch(url) if url.startswith('http') else ''
        prefix = f'the {probe["method"]} {url} answered {answered}, then '
    # 2. The container then runs stable_seconds without exiting or restarting: a version that answers once and
    # dies did not start (owner, 2026-11-03). With no probe, this alone decides.
    since = time.monotonic()
    while time.monotonic() - since < stays:
        down = _down(container)
        if down:return False, f'{prefix}{down} within {stays} s', answer
        time.sleep(1)
    down = _down(container)
    if down:return False, f'{prefix}{down} within {stays} s', answer
    return True, f'{prefix}the container ran {stays} s without exiting or restarting', answer

def _down(container):
    """Why the container is no longer up ('the container exited with code 3' or '... restarted 2 times'), or ''."""
    state, restarts = _state(container)
    if not state.get('Running'):return f'the container exited with code {state.get("ExitCode")}'
    if restarts:return f'the container restarted {restarts} times'
    return ''

def upgrade_test(name, addon_dir, old_image, old_config, new_image, new_config, work):
    """The result described in the module docstring."""
    hooks_dir = pathlib.Path(addon_dir) / 'upgrade-check'
    settings_path = hooks_dir / 'settings.yaml'
    settings = yaml.safe_load(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else None
    limits = upgrade_settings(settings)  # a bad settings.yaml is a tool error before any container starts
    present = [h for h in HOOK_PHASE if (hooks_dir / h).is_file()]
    env = UpgradeTestEnv(work, hooks_dir.resolve() if hooks_dir.is_dir() else None); phases = []
    result = {'name': name, 'passed': False, 'reason': '', 'hooks': present, 'data_checked': False, 'phases': phases}
    try:
        env.open()
        for phase, image, config in (('old', old_image, old_config), ('new', new_image, new_config)):
            probe = startup_probe(config, settings)
            container = env.start(phase, image, config)
            ok, detail, answer = wait_started(env, container, probe)
            entry = {'phase': phase, 'version': str(config.get('version')), 'image': image, 'method': probe['method'], 'started': ok,
                'detail': detail, 'answer': answer, 'logs': '', 'hooks': []}
            phases.append(entry)
            label = f'{PHASE_LABEL[phase]} ({config.get("version")})'
            if not ok:result['reason'] = f'{label} did not start: {detail}'
            for hook in (h for h in present if ok and HOOK_PHASE[h] == phase):
                run = env.run_hook(hook, phase, image, config, limits['hook_timeout'])
                entry['hooks'].append(run)
                if hook == 'verify':result['data_checked'] = True
                if not run['passed'] and not result['reason']:result['reason'] = f'{hook} failed on {label}: {run["detail"]}'
            # After the hooks, so the log shows what the add-on did while they ran.
            entry['logs'] = _logs(container, 60)[-4000:]
            env.stop(container, config)
            if result['reason']:return result
        result['passed'] = True
        return result
    finally:
        env.close()

def report(result):
    """The Markdown report of upgrade_test()'s result: the startup of each version, then every hook's checks."""
    hooks, checked = result.get('hooks', []), result.get('data_checked', False)
    # verify runs only after seed (when there is one) passed, so data_checked with seed means both ran.
    if checked and 'seed' in hooks:data = DATA_CHECKED
    elif checked:data = DATA_CHECKED_VERIFY_ONLY
    elif 'verify' in hooks:data = NOT_CHECKED
    else:data = STARTUP_ONLY
    passed = ('**Passed**: the new version starts on the data of the comparison target' +
        ((', and verify finds the data seed wrote.' if 'seed' in hooks else ', and verify passes on it.') if checked else '.'))
    r = [f'#### Upgrade test: {result["name"]}', '', passed if result['passed'] else f'**Failed**: {markdown_cell(result["reason"])}.', '', data, '',
        '| version | image | judged by | started | detail |', '|---|---|---|---|---|']
    r += [f'| {PHASE_LABEL[p["phase"]]} {markdown_cell(p["version"])} | `{markdown_cell(p["image"])}` | {p["method"]} | {"yes" if p["started"] else "**no**"} | {markdown_cell(p["detail"])} |'
        for p in result['phases']]
    if 'seed' in result.get('hooks', []) and 'verify' not in result.get('hooks', []):
        r += ['', 'upgrade-check/ has seed but no verify: nothing reads the seeded data back.']
    runs = [h for p in result['phases'] for h in p.get('hooks', [])]
    if runs:
        r += ['', '| version | hook | check | result | detail |', '|---|---|---|---|---|']
        for h in runs:
            version = f'{PHASE_LABEL[h["phase"]]} {markdown_cell(next(p["version"] for p in result["phases"] if p["phase"] == h["phase"]))}'
            r.append(f'| {version} | {h["hook"]} | (the hook) | {"pass" if h["passed"] else "**fail**"} | {markdown_cell(h["detail"])} |')
            r += [f'| {version} | {h["hook"]} | {markdown_cell(c["name"])} | {"**fail**" if c["result"] == "fail" else c["result"]} | {markdown_cell(c["detail"])} |'
                for c in h['checks']]
    for p in result['phases']:
        for h in p.get('hooks', []):
            if not h['passed']:
                r += ['', f'<details><summary>Output of {h["hook"]} on {PHASE_LABEL[p["phase"]]}</summary>', '', '```', h['output'].replace('```', "'''"), '```', '', '</details>']
        if not p['started'] or any(not h['passed'] for h in p.get('hooks', [])):
            r += ['', f'<details><summary>Last log lines of {PHASE_LABEL[p["phase"]]}</summary>', '', '```', p['logs'].replace('```', "'''"), '```', '', '</details>']
    return '\n'.join(r) + '\n'

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--name', required=True, help='add-on id in the Store registry')
    p.add_argument('--addon-dir', required=True, help="the add-on's directory in the PR checkout (its upgrade-check/ is read)")
    p.add_argument('--old-image', required=True); p.add_argument('--old-config', required=True, help="the comparison target's config.yaml")
    p.add_argument('--new-image', required=True); p.add_argument('--new-config', required=True, help="the PR's config.yaml")
    p.add_argument('--report-dir', required=True); p.add_argument('--summary', help='Markdown file the report is appended to')
    a = p.parse_args(argv)
    out = pathlib.Path(a.report_dir); out.mkdir(parents=True, exist_ok=True)
    try:
        old, new = (yaml.safe_load(pathlib.Path(f).read_text(encoding='utf-8')) or {} for f in (a.old_config, a.new_config))
        work = tempfile.mkdtemp(prefix='upgrade-test-')
        try:result = upgrade_test(a.name, a.addon_dir, a.old_image, old, a.new_image, new, work)
        finally:shutil.rmtree(work, ignore_errors=True)
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError, yaml.YAMLError) as e:
        # compare reads the result file, so a tool error still leaves one with the reason.
        reason = f'the upgrade test could not run: {e}'
        (out / f'{a.name}.json').write_text(json.dumps({'name': a.name, 'passed': False, 'reason': reason, 'hooks': [], 'data_checked': False,
            'phases': []}, indent=1), encoding='utf-8')
        print(workflow_command('error', 'Upgrade test', f'{a.name}: {reason}')); return 2
    text = report(result)
    (out / f'{a.name}.json').write_text(json.dumps(result, indent=1), encoding='utf-8'); (out / f'{a.name}.md').write_text(text, encoding='utf-8')
    if a.summary:
        with open(a.summary, 'a', encoding='utf-8') as f:f.write(text + '\n')
    # Log lines in the report come from the add-on: GitHub must not read them as workflow commands.
    token = secrets.token_hex(16); print('::stop-commands::' + token); print(text); print('::' + token + '::')
    if not result['passed']:
        print(workflow_command('error', 'Upgrade test', f'{a.name}: {result["reason"]}')); return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
