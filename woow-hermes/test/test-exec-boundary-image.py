#!/usr/bin/env python3
"""Docker-only synthetic smoke: real boot/s6 and kernel UID, no HA or provider.

Run on the CI runner with the freshly built image reference. Docker output and
container logs are captured, never printed (even on failure). Only fixed checks
are reported. The boot image is unmodified; a separate disposable container
replaces only the final CLI with an environment/UID oracle, not the wrappers,
with-contenv or s6-setuidgid. No host credentials or data are mounted.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid

PYTHON = "/opt/hermes/.venv/bin/python"
TOKENS = ("SUPERVISOR_TOKEN", "HASSIO_TOKEN")
PHASE = 'initial'


def phase(name):
    global PHASE
    PHASE = name
    print('PHASE ' + name, flush=True)


def context_metadata(container):
    code = '''import os,json,pathlib
p=pathlib.Path
out={'path':os.environ.get('PATH','')}
for name in ('s6-setuidgid','with-contenv'):
 f=p('/command')/name
 out[name+'_exists']=f.exists()
 out[name+'_executable']=os.access(f,os.X_OK)
 out[name+'_safe_file']=f.is_file() and (not f.is_symlink() or str(f.resolve()).startswith(('/package/','/run/s6/')))
out['with_contenv_clears_env']=b'emptyenv' in p('/command/with-contenv').read_bytes()
out['pid1_s6']=b's6-svscan' in p('/proc/1/cmdline').read_bytes()
out['tokens_cleaned']=all(not (p('/run/s6/container_environment')/k).exists() for k in ('SUPERVISOR_TOKEN','HASSIO_TOKEN'))
print(json.dumps(out))'''
    value = json.loads(docker('exec', container, PYTHON, '-c', code).stdout)
    keys = {name + '_' + check for name in ('s6-setuidgid', 'with-contenv')
            for check in ('exists', 'executable', 'safe_file')}
    keys.update(('pid1_s6', 'tokens_cleaned', 'with_contenv_clears_env'))
    if set(value) != keys | {'path'} or not isinstance(value['path'], str) or not all(type(value[k]) is bool for k in keys):
        raise ValueError('invalid context metadata')
    print('CONTEXT_CHECKS ' + json.dumps({k:value[k] for k in sorted(keys)}), flush=True)
    return value


def docker(*args, check=True, timeout=90):
    result = subprocess.run(["docker", *args], capture_output=True, timeout=timeout)
    if check and result.returncode:
        print('DOCKER_EXIT ' + str(result.returncode), flush=True)
        raise RuntimeError("docker operation failed (output withheld)")
    return result


def main_context(container):
    # Query only PATH from this same image/container, never the runner's env.
    code = '''import os,json
assert os.access('/command/s6-setuidgid', os.X_OK)
assert os.access('/command/with-contenv', os.X_OK)
print(json.dumps({'path':os.environ['PATH']}))'''
    value = json.loads(docker('exec', container, PYTHON, '-c', code).stdout)
    if set(value) != {'path'} or not isinstance(value['path'], str):
        raise ValueError('invalid image PATH receipt')
    entries = value['path'].split(':')
    if not all(p.startswith('/') for p in entries) or '/opt/hermes/bin' not in entries:
        raise ValueError('unexpected image PATH')
    return '/command:' + value['path']


def exec_cases(path):
    main_env = ['-e', 'PATH=' + path]
    return [
        ([], '/opt/hermes/bin/hermes', '10000', []),
        (['--user', '10000:10000'], '/opt/hermes/bin/hermes', '10000', []),
        (['-e', 'HERMES_DOCKER_EXEC_AS_ROOT=1'], '/opt/hermes/bin/hermes', '0', []),
        (main_env + ['-e', 'HERMES_HOME=/opt/data'], '/opt/hermes/docker/main-wrapper.sh', '10000', ['/boundary-probe']),
        (main_env + ['-e', 'HERMES_HOME='], '/opt/hermes/docker/main-wrapper.sh', '10000', ['/boundary-probe']),
        (main_env + ['--user', '10000:10000', '-e', 'HERMES_HOME=/opt/data'], '/opt/hermes/docker/main-wrapper.sh', '10000', ['/boundary-probe']),
    ]


def seed_environment(path):
    return '''from pathlib import Path as P
p=P('/run/s6/container_environment'); p.mkdir(parents=True, exist_ok=True)
for key in ('SUPERVISOR_TOKEN','HASSIO_TOKEN'): (p/key).write_text('synthetic-rehydrated')
(p/'BOUNDARY_KEEP').write_text('synthetic-preserved')
# Real with-contenv clears inherited variables, including the reentry marker.
# Normal s6 boot supplies this value; the sleep-only fixture must seed it too.
(p/'HERMES_HOME').write_text('/opt/data')
(p/'PATH').write_text(''' + repr(path) + ''')
'''


def main(image):
    names = ["ha-boundary-" + uuid.uuid4().hex for _ in range(2)]
    with tempfile.TemporaryDirectory(prefix="ha-boundary-") as temp:
        root = pathlib.Path(temp)
        root.chmod(0o755)
        # This oracle is the ONLY substituted executable. No real CLI/model runs.
        probe = root / "probe"
        probe.write_text('''#!/opt/hermes/.venv/bin/python
import os, sys
assert os.getuid() == int(sys.argv[1])
assert os.getgid() == int(sys.argv[1])
assert not any(k in os.environ for k in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"))
assert os.environ.get("BOUNDARY_KEEP") == "synthetic-preserved"
assert sys.argv[2:] == ["", "two words", "$(not-a-command)"]
raise SystemExit(42)
''')
        probe.chmod(0o755)
        options = root / "options.json"
        options.write_text(json.dumps({"dashboard_username": "smoke", "env_vars": [],
                                       "public_url": "http://127.0.0.1:9119"}))
        env = [item for key in TOKENS for item in ("-e", key + "=synthetic-ci-only")]
        try:
            # Normal entrypoint, bootstrap, and real long-running s6 services.
            phase('normal-create')
            docker("create", "--name", names[0], "--network", "none", *env,
                   "--mount", f"type=bind,src={options},dst=/data/options.json,readonly",
                   image)
            phase('normal-start')
            docker("start", names[0])
            phase('normal-boot')
            boot_check = pathlib.Path(__file__).with_name('image_boot_probe.py').read_text()
            deadline = time.monotonic() + 240
            while True:
                result = docker("exec", names[0], PYTHON, "-c", boot_check, check=False, timeout=15)
                if result.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    # Our own finite boolean schema, never raw Docker or app output.
                    keys = {"pid1_s6", "tokens_removed_from_envdir", "bootstrap_secret_nonempty",
                            "gateway_json_health", "dashboard_listening", "relay_listening"}
                    keys.update(role + '_' + check for role in ('gateway-default', 'dashboard')
                                for check in ('identity', 'uid10000', 'tokens_absent'))
                    try:
                        checks = json.loads(result.stdout)
                        if set(checks) == keys and all(type(v) is bool for v in checks.values()):
                            print("BOOT_CHECKS " + json.dumps(checks, sort_keys=True))
                    except (ValueError, TypeError):
                        print("BOOT_CHECKS unavailable")
                    raise RuntimeError("normal boot/s6 UID/token check failed (logs withheld)")
                time.sleep(5)
            # Recheck after a stability window, not just one lucky process sample.
            time.sleep(10)
            phase('normal-stability')
            docker("exec", names[0], PYTHON, "-c", boot_check)
            print("PASS normal bootstrap, s6 worker identities, UID10000, token absence, gateway JSON health")

            # Real wrappers and s6 binaries; no external-command doubles.
            phase('fixture-start')
            docker("run", "-d", "--name", names[1], "--network", "none", *env,
                   "-e", "BOUNDARY_KEEP=synthetic-preserved",
                   "--mount", f"type=bind,src={probe},dst=/opt/hermes/.venv/bin/hermes,readonly",
                   "--mount", f"type=bind,src={probe},dst=/boundary-probe,readonly",
                   "--entrypoint", "/bin/sleep", image, "600")
            phase('fixture-context')
            context_metadata(names[1])
            # Verify installed shim is the patched source, not a bypassing link.
            phase('installed-shim')
            docker("exec", names[1], PYTHON, "-c", '''from pathlib import Path as P
assert P('/opt/hermes/bin/hermes').read_bytes() == P('/opt/hermes/docker/hermes-exec-shim.sh').read_bytes()
assert b'unset SUPERVISOR_TOKEN HASSIO_TOKEN' in P('/opt/hermes/bin/hermes').read_bytes()
''')
            phase('main-context')
            path = main_context(names[1])
            phase('seed-envdir')
            docker("exec", names[1], PYTHON, "-c", seed_environment(path))
            cases = exec_cases(path)
            for case, (flags, wrapper, uid, args) in enumerate(cases, 1):
                phase('exec-case-' + str(case))
                result = docker("exec", *flags, names[1], wrapper, *args,
                                uid, "", "two words", "$(not-a-command)", check=False)
                if result.returncode != 42:
                    print("EXEC_CHECK_FAILED case=" + str(case) + " exit=" + str(result.returncode))
                    raise RuntimeError("exec UID/token/argv/exit check failed (output withheld)")
            print("PASS 6 real shim/main/s6 UID cases including root opt-out and with-contenv reentry")
        finally:
            # Named disposable containers only; never prune unrelated resources.
            for name in names:
                docker("rm", "-f", "-v", name, check=False)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise RuntimeError("usage: test-exec-boundary-image.py IMAGE")
        main(sys.argv[1])
    except Exception as error:
        if isinstance(error, subprocess.TimeoutExpired):
            print('CHECK_TIMEOUT phase=' + PHASE, file=sys.stderr)
        print("FAIL exec-boundary image smoke phase=" + PHASE + " (details intentionally withheld)", file=sys.stderr)
        sys.exit(1)
