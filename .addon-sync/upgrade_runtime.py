#!/usr/bin/env python3
"""Upgrade test of one add-on, startup only (pipeline #137, category 2 of ADR-0005).

Runs the comparison target's image, then the new image on the same data
directories (/data and one per config.yaml `map` entry, at its `path`:
upgrade_check.mounts), each under a mock Home Assistant Supervisor
(mock_supervisor.py): the hassio bridge network 172.30.32.0/23, the
Supervisor at 172.30.32.2 (also as host `supervisor`), a fake
SUPERVISOR_TOKEN/HASSIO_TOKEN and /data/options.json from config.yaml's
option defaults. Each version must start, judged as upgrade_check.startup_probe
says from the Supervisor's address; the add-on's upgrade-check/settings.yaml
may override the time limits.

Writes <report-dir>/<name>.json and <name>.md, appends the report to
--summary and exits 1 when the upgrade test fails (::error with the reason),
2 on a usage or tool error. Data is not checked yet: the report says so.
Needs Docker; both images must be local or pullable.
"""
from __future__ import annotations
import argparse, json, pathlib, secrets, shutil, subprocess, sys, tempfile, time
import yaml
from upgrade_check import mounts, startup_probe
from addon_sync import markdown_cell, workflow_command

# The mock Supervisor runs in this image; the fake add-ons of test_upgrade_runtime.py build on it too.
MOCK_IMAGE = 'python:3.12-alpine@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8'
SUBNET, GATEWAY, SUPERVISOR_IP, ADDON_IP = '172.30.32.0/23', '172.30.32.1', '172.30.32.2', '172.30.33.10'
TOOLING = pathlib.Path(__file__).resolve().parent
STARTUP_ONLY = 'Startup only: data was not checked (只檢查啟動，沒有檢查資料).'
# Below this HTTP status a probe counts as an answer: the watchdog needs success, ingress and webui any answer short of a server error.
BELOW = {'watchdog': 300, 'ingress': 500, 'webui': 500}
SIDE = {'old': 'the comparison target', 'new': 'the new version'}

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
    return {**info, 'hostname': f'local-{config.get("slug", "addon")}', 'ip_address': ADDON_IP, 'state': 'started', 'boot': 'auto',
        'repository': 'local', 'version_latest': config.get('version'), 'update_available': False, 'options': options,
        'ingress_url': f'/api/hassio_ingress/{secrets.token_hex(8)}/' if config.get('ingress') else None, 'network': config.get('ports')}

class Run:
    """One upgrade test: its network, mock Supervisor and data directories, removed by close()."""
    def __init__(self, name, work):
        self.name, self.work = name, pathlib.Path(work)
        self.prefix = f'upgrade-test-{secrets.token_hex(4)}'
        self.net, self.supervisor, self.token = self.prefix, f'{self.prefix}-supervisor', secrets.token_hex(24)
        self.state, self.data = self.work / 'supervisor', self.work / 'dirs'
        self.state.mkdir(parents=True); self.data.mkdir()
    def open(self):
        docker('network', 'create', '--subnet', SUBNET, '--gateway', GATEWAY, self.net)
        docker('run', '-d', '--name', self.supervisor, '--network', self.net, '--ip', SUPERVISOR_IP, '-e', f'SUPERVISOR_TOKEN={self.token}',
            '--mount', f'type=bind,source={TOOLING},target=/tooling,readonly', '--mount', f'type=bind,source={self.state},target=/state',
            MOCK_IMAGE, 'python', '-u', '/tooling/mock_supervisor.py', 'serve')
    def probe(self, url, below):
        """One check of `url` from the Supervisor's address (mock_supervisor.py probe)."""
        return subprocess.run(['docker', 'exec', self.supervisor, 'python', '/tooling/mock_supervisor.py', 'probe', '--url', url, '--below', str(below)],
            capture_output=True).returncode == 0
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
    def stop(self, container, config):
        docker('stop', '-t', str(config.get('timeout', 10)), container, check=False)
        docker('rm', '-f', container, check=False)
    def close(self):
        docker('rm', '-f', f'{self.prefix}-old', f'{self.prefix}-new', self.supervisor, check=False)
        docker('network', 'rm', self.net, check=False)
        # Containers write as root: remove what they left through a container, then the rest.
        docker('run', '--rm', '--mount', f'type=bind,source={self.work},target=/w', '--entrypoint', 'sh', MOCK_IMAGE, '-c', 'rm -rf /w/* /w/.[!.]*', check=False)

def _state(container):
    """(docker's State of the container, its RestartCount)."""
    state, restarts = docker('inspect', '-f', '{{json .State}} {{.RestartCount}}', container).strip().rsplit(' ', 1)
    return json.loads(state), int(restarts)

def wait_started(run, container, probe):
    """(started, detail): whether the version started as `probe` says, and why not."""
    url = probe['url'].replace('[HOST]', ADDON_IP)
    started = time.monotonic(); deadline = started + probe['timeout']
    while True:
        state, restarts = _state(container)
        if not state.get('Running'):
            return False, f'the container exited with code {state.get("ExitCode")}'
        if restarts:
            return False, f'the container restarted {restarts} times'
        if probe['method'] == 'stays-up':
            if time.monotonic() - started >= probe['stable_seconds']:
                return True, f'the container ran {probe["stable_seconds"]} s without exiting or restarting'
        elif run.probe(url, BELOW[probe['method']]):
            what = 'with success' if probe['method'] == 'watchdog' else 'below HTTP 500'
            return True, f'the {probe["method"]} {url} answered {what}'
        if time.monotonic() >= deadline:
            what = 'with success' if probe['method'] == 'watchdog' else ''
            return False, f'the {probe["method"]} {url} did not answer{" " + what if what else ""} within {probe["timeout"]} s'
        time.sleep(1)

def upgrade_test(name, addon_dir, old_image, old_config, new_image, new_config, work):
    """{'name', 'passed', 'reason', 'phases': [{phase, version, image, method, started, detail, answer, logs}]}."""
    settings_path = pathlib.Path(addon_dir) / 'upgrade-check/settings.yaml'
    settings = yaml.safe_load(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else None
    run = Run(name, work); phases = []; result = {'name': name, 'passed': False, 'reason': '', 'phases': phases}
    try:
        run.open()
        for phase, image, config in (('old', old_image, old_config), ('new', new_image, new_config)):
            probe = startup_probe(config, settings)
            container = run.start(phase, image, config)
            ok, detail = wait_started(run, container, probe)
            answer = ''
            if ok and probe['method'] != 'stays-up':
                url = probe['url'].replace('[HOST]', ADDON_IP)
                answer = docker('exec', run.supervisor, 'python', '-c', f'import urllib.request,ssl;print(urllib.request.urlopen({url!r},timeout=5,'
                    'context=ssl._create_unverified_context()).read()[:200].decode(errors="replace"))', check=False).strip() if url.startswith('http') else ''
            logs = subprocess.run(['docker', 'logs', '--tail', '60', container], capture_output=True, text=True, encoding='utf-8', errors='replace')
            phases.append({'phase': phase, 'version': str(config.get('version')), 'image': image, 'method': probe['method'], 'started': ok,
                'detail': detail, 'answer': answer, 'logs': (logs.stdout + logs.stderr)[-4000:]})
            run.stop(container, config)
            if not ok:
                result['reason'] = f'{SIDE[phase]} ({config.get("version")}) did not start: {detail}'
                return result
        result['passed'] = True
        return result
    finally:
        run.close()

def report(result):
    """The Markdown report of upgrade_test()'s result."""
    r = [f'#### Upgrade test: {result["name"]}', '', ('**Passed**: the new version starts on the data of the comparison target.' if result['passed']
        else f'**Failed**: {markdown_cell(result["reason"])}.'), '', STARTUP_ONLY, '', '| version | image | judged by | started | detail |', '|---|---|---|---|---|']
    r += [f'| {SIDE[p["phase"]]} {markdown_cell(p["version"])} | `{markdown_cell(p["image"])}` | {p["method"]} | {"yes" if p["started"] else "**no**"} | {markdown_cell(p["detail"])} |'
        for p in result['phases']]
    for p in result['phases']:
        if not p['started']:
            r += ['', f'<details><summary>Last log lines of {SIDE[p["phase"]]}</summary>', '', '```', p['logs'].replace('```', "'''"), '```', '', '</details>']
    return '\n'.join(r) + '\n'

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--name', required=True, help='add-on id in the Store registry')
    p.add_argument('--addon-dir', required=True, help="the add-on's directory in the PR checkout (its upgrade-check/ is read)")
    p.add_argument('--old-image', required=True); p.add_argument('--old-config', required=True, help="the comparison target's config.yaml")
    p.add_argument('--new-image', required=True); p.add_argument('--new-config', required=True, help="the PR's config.yaml")
    p.add_argument('--report-dir', required=True); p.add_argument('--summary', help='Markdown file the report is appended to')
    a = p.parse_args(argv)
    try:
        old, new = (yaml.safe_load(pathlib.Path(f).read_text(encoding='utf-8')) or {} for f in (a.old_config, a.new_config))
        work = tempfile.mkdtemp(prefix='upgrade-test-')
        try:result = upgrade_test(a.name, a.addon_dir, a.old_image, old, a.new_image, new, work)
        finally:shutil.rmtree(work, ignore_errors=True)
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as e:
        # compare reads the result file, so a tool error still leaves one with the reason.
        reason = f'the upgrade test could not run: {e}'
        out = pathlib.Path(a.report_dir); out.mkdir(parents=True, exist_ok=True)
        (out / f'{a.name}.json').write_text(json.dumps({'name': a.name, 'passed': False, 'reason': reason, 'phases': []}, indent=1), encoding='utf-8')
        print(workflow_command('error', 'Upgrade test', f'{a.name}: {reason}')); return 2
    out = pathlib.Path(a.report_dir); out.mkdir(parents=True, exist_ok=True)
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
