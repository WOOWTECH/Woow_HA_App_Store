#!/usr/bin/env python3
"""Upgrade test of one add-on: startup (pipeline #137) and data (#138), category 2 of ADR-0005, and the regression
comparison of its smoke checks (#139), category 3.

Runs the comparison target's image, then the new image on the same data
directories (/data and one per config.yaml `map` entry, at its `path`:
upgrade_check.mounts), each under a mock Home Assistant Supervisor
(mock_supervisor.py): the hassio bridge network 172.30.32.0/23, the
Supervisor at 172.30.32.2 (also as host `supervisor`), a fake
SUPERVISOR_TOKEN/HASSIO_TOKEN and /data/options.json (test options, below).
Each version must start, judged as upgrade_check.startup_probe
says from the Supervisor's address, and then stay up for stable_seconds; the
add-on's upgrade-check/settings.yaml may override the time limits.

Data directories: <root>/data at /data, or at the `path` of a `data` entry;
each other `map` entry at its `path` or Supervisor's default, from
<root>/<MAP_SOURCES[type] or type> (app_config/addon_config =
all_app_configs/<slug>; legacy names share the new name's directory); entries
Supervisor ignores are listed by upgrade_check.map_warnings().

Test options (#157): /data/options.json (and the options in the mock's
/addons/self/info) of each version is build_test_options(): its config.yaml option
defaults, with the add-on's upgrade-check/options.yaml (in the PR, the same
file for both versions) laid over them the way Supervisor merges user options
(mappings key by key, any other value replaces the default; only keys the
version's schema has, nested mappings too), and null values left out. Then
every required password option of the schema (`password` or
`password(min,max)`, no `?`; in nested mappings too, creating a required
nested mapping that is missing; not in list items) that is still missing, null
or '' gets a random value of letters and digits, generated once per test and
the same for both versions. When one version requires it, it is written into
every version that keeps the option (its schema has the key, as `password?`
or any other type, or it has no schema), replacing that version's default, as
a real upgrade keeps the user's value. 32 characters, or the nearest length
inside the password length ranges (`?` too) of the versions that receive it
(ranges that do not overlap are a tool error). Hooks
read it from $DATA_DIR_DATA/options.json. Other required options that are
still null or empty are left as they are (null ones are left out of
options.json; Supervisor would refuse to start the add-on then, the test lets
the add-on decide): give them a value in options.yaml.

options.yaml must be a mapping of option: value (an empty file is no options).
Each of these is a tool error before any container starts, naming the key or
the type but never echoing the file: invalid YAML, any other shape, a symlink
out of upgrade-check/, a key (at any depth of a nested mapping schema) that no
version's schema has (Supervisor drops such keys with a warning, so it would
never reach the add-on), and a password option whose value is not a string
(Supervisor's password type takes strings only). Other values are not checked
against the schema.

The result and report never show a password: every generated value and every
password value options.yaml gives (as written and JSON-escaped) is replaced by
MASK in hook output and logs (before they are cut to their last lines),
details, reasons and tool errors; the add-on's name and each version's image
and version are never masked. Password values in config.yaml defaults are
public and not masked. The report names the options.yaml keys and the
generated options, and warns when a repository password is shorter than
WEAK_PASSWORD_LENGTH or appears in the add-on's name, slug, image or version
(it would mask those words in the logs: pick a test-only value).

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

Supervisor fixtures (#142): the add-on's upgrade-check/supervisor/ may hold
answers for Supervisor API paths, one JSON file per path (its `data`):
/services/mqtt -> supervisor/services/mqtt.json (mock_supervisor.py
documents the mapping). A fixture beats the mock's default answer, except that
addons/self/info.json is laid over the info this runtime writes for each
version (its keys only) and /supervisor/ping is never overridden. Paths with
neither answer 404; the report lists them (the UNMOCKED_ROWS most called per
version), and fixtures that cannot be used, per version, with their counts.
Neither fails the test. upgrade-check/supervisor/ must not be, or hold, a
symlink out of upgrade-check/ (only that directory is mounted): that is a tool
error before any container starts.

Writes <report-dir>/<name>.json and <name>.md, appends the report to
--summary and exits 1 when the upgrade test fails (::error with the reason),
2 on a usage or tool error. Needs Docker; both images must be local or pullable.

Regression comparison (#139, category 3): upgrade-check/ may also hold `smoke`,
run the same way on the comparison target (after seed, and only when seed
passed) and on the new version (after verify, and only when category 2 has not
failed by then), so both runs see the data seed wrote. smoke only reads: it
runs between seed and verify on the same data directories, so it must not
change what verify reads back (writes of its own through the add-on's API,
apart from seed's data, are fine). Its environment is the hooks', except that
HOOK_STATE_DIR is its own directory, kept from its run on the comparison
target to its run on the new version and never the one seed hands verify;
its report is $REPORT_DIR/smoke.json. A failing smoke is not itself a failure:
upgrade_check.regression compares the two runs check by check (a check that
passes on the comparison target must pass on the new version; one that does
not pass there is only reported; one only in the new version must pass when
the comparison target's smoke wrote a readable report, whatever its exit code;
without a report, the exit codes), and a regression fails the upgrade comparison. The check name
'(the hook)' is reserved for the hook's own row: a report that uses it cannot
be used. Without smoke, category 3 compares only that both versions start.
The result below also has, since #139: report_error and reported (whether it
wrote its report) in each hook run; smoke in hooks, and a smoke run after the
data hook in phases[].hooks, or smoke_not_run (why) in the new version's
phase when category 2 failed first; regression, upgrade_check.regression() of
the result, {smoke, compared, passed, rows, reason}. passed is false, with
that reason, when category 2 passed but category 3 found a regression.

Time (the runtime job's timeout-minutes): smoke adds at most two hook_timeout
runs per add-on, so with the default limits one add-on whose every wait runs
out takes 2 x (300 + 60) s to start + 4 x 600 s of hooks = 52 minutes. A job
that runs out of time fails compare (the runtime job did not succeed); it
never passes.

The result (<name>.json; compare reads it): {name, passed, reason, hooks (the
hooks upgrade-check/ has), data_checked (verify ran), phases: [{phase, version,
image, method, started, detail, answer, logs, hooks: [{hook, phase, passed,
exit_code, detail, checks: [{name, result, detail}], output}], supervisor:
{unmocked: [{path, count, methods}], broken_fixtures: [same]}}], map_warnings:
{old: [...], new: [...]}, options: {from_repo: [options.yaml keys], generated:
[dotted names of the generated passwords], warnings: [option_warnings()]}}. exit_code is None when the hook timed out or could
not be started (a symlink out of upgrade-check/). supervisor lists the
add-on's own Supervisor calls during that phase (start to stop) that answered
404 (unmocked) or 500 (a fixture that is not valid JSON); calls of the hooks
and of the runtime are not in it. map_warnings are upgrade_check.map_warnings()
of each config.yaml: map entries Supervisor ignores (or why `map` could not be
read). Both are informational.
"""
from __future__ import annotations
import argparse, json, os, pathlib, re, secrets, shutil, string, subprocess, sys, tempfile, time
import yaml
import mock_supervisor
from upgrade_check import HOOK_ROW, STARTS_ROW, ingress_port, map_warnings, mounts, regression, startup_probe, upgrade_settings, webui_endpoint
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
# The data hooks (#138) and the phase each runs in; smoke, in both phases, is category 3 (#139).
HOOK_PHASE = {'seed': 'old', 'verify': 'new'}
# Where the mock Supervisor's container sees the add-on's upgrade-check/, the data directories, the hooks' reports and
# state (seed's for verify; smoke's own, #139).
IN_MOCK = {'hooks': '/upgrade-check', 'data': '/upgrade-data', 'reports': '/hook-reports', 'state': '/hook-state', 'smoke_state': '/smoke-state'}
CHECK_RESULTS = ('pass', 'fail', 'skip')
# How many unmocked paths the report lists per version, the most called first.
UNMOCKED_ROWS = 30

class DockerError(RuntimeError):
    """A docker command that failed: its exit code and output."""
    def __init__(self, message, returncode, output):
        super().__init__(message); self.returncode, self.output = returncode, output

def docker(*args, check=True):
    r = subprocess.run(['docker', *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and r.returncode:
        output = (r.stderr or r.stdout).strip()
        raise DockerError(f'docker {args[0]} failed ({r.returncode}): {output[-1000:]}', r.returncode, output)
    return r.stdout

# #140: what `docker run` says when the image, not the runner, is at fault: it cannot be found or pulled, or the
# container was created but its entrypoint cannot run (docker run exits 126 or 127 then). Anything else (a name or
# address in use, a bind mount, the daemon) is the test's own fault: a tool error, not the add-on's failure.
IMAGE_FAULTS = ('unable to find image', 'pull access denied', 'manifest unknown', 'no matching manifest', 'repository does not exist',
    'failed to resolve reference', 'invalid reference format', 'unable to start container process: exec', 'exec format error',
    'executable file not found')

def image_fault(error):
    """Whether a failed `docker run` (DockerError) is the image's fault: exit 126 or 127 (created, but its entrypoint
    cannot run), or a message in IMAGE_FAULTS."""
    return error.returncode in (126, 127) or any(f in error.output.lower() for f in IMAGE_FAULTS)

# #157: test options. Supervisor's option types (supervisor/apps/options.py RE_SCHEMA_ELEMENT): a password, with an
# optional length range, required unless it ends with '?'.
TEST_OPTIONS = 'options.yaml'
REQUIRED_PASSWORD = re.compile(r'^password(?:\((?P<min>\d+)?,(?P<max>\d+)?\))?$')
# Any password type, optional ('?') or not: its length range also binds a generated value the version receives.
PASSWORD_TYPE = re.compile(r'^password(?:\((?P<min>\d+)?,(?P<max>\d+)?\))?\??$')
PASSWORD_LENGTH, PASSWORD_ALPHABET = 32, string.ascii_letters + string.digits
# A repository password shorter than this gets a warning in the report: masking it would hide ordinary words in the logs.
WEAK_PASSWORD_LENGTH, MASK = 8, '[password]'
# An option whose name looks like this holds a secret, whatever its type (a token in a `str` option): its options.yaml
# string values are masked as passwords are.
SECRET_NAME = re.compile(r'pass|secret|token|api_?key|private_?key|credential', re.IGNORECASE)

def read_test_options(hooks_dir):
    """The add-on's upgrade-check/options.yaml (in the PR), parsed: a mapping of option: value, or None when there is
    none. An empty file is {}. Anything else is a ValueError naming the file and what is wrong with it, never its
    content (it may hold passwords): the test could not run."""
    hooks_dir = pathlib.Path(hooks_dir); path = hooks_dir / TEST_OPTIONS
    if path.is_symlink() and not path.resolve().is_relative_to(hooks_dir.resolve()):
        raise ValueError(f'upgrade-check/{TEST_OPTIONS} is a symlink to {path.resolve()}, outside upgrade-check/')
    if not path.is_file():return None
    try:given = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as e:
        # Not str(e): PyYAML quotes the offending line, which may hold a password.
        mark = getattr(e, 'problem_mark', None)
        where = f' at line {mark.line + 1}, column {mark.column + 1}' if mark else ''
        raise ValueError(f'upgrade-check/{TEST_OPTIONS} is not valid YAML{where}: {getattr(e, "problem", None) or type(e).__name__}') from None
    if given is None:return {}
    if not isinstance(given, dict):
        raise ValueError(f'upgrade-check/{TEST_OPTIONS} must be a mapping of option: value (as in config.yaml options), not a {type(given).__name__}')
    bad = [k for k in given if not isinstance(k, str) or not k]
    if bad:raise ValueError(f'upgrade-check/{TEST_OPTIONS} must be a mapping of option: value; a key is a {type(bad[0]).__name__}, not a name')
    return given

def _schema(config):
    """config.yaml's schema as a mapping, or None when it has none to check against (schema: false or absent)."""
    schema = config.get('schema')
    return schema if isinstance(schema, dict) else None

def _is_password(typ):
    return isinstance(typ, str) and typ.startswith('password')

def check_test_options(given, configs):
    """ValueError when upgrade-check/options.yaml (`given`) sets an option that no version's config.yaml schema lists,
    at any depth of a nested mapping schema: Supervisor drops options that are not in the schema (with a warning,
    apps/options.py), so such a key would never reach the add-on, a mistake the test reports. A version without a
    schema mapping accepts every key, so then no key is unknown. Also a ValueError: a password option (password or
    password?, in any version that has a schema) whose value is not a string or null, as Supervisor's password type
    takes strings only; this is checked even when the other version has no schema."""
    schemas = [_schema(c) for c in configs]
    _check_level(given, [s for s in schemas if s is not None], '', any(s is None for s in schemas))

def _check_level(given, schemas, prefix, any_key):
    """check_test_options() at one level; `any_key`: a version without a schema keeps every key, at every depth."""
    unknown = [] if any_key else [prefix + k for k in given if not any(k in s for s in schemas)]
    if unknown:
        raise ValueError(f'upgrade-check/{TEST_OPTIONS} sets {", ".join(map(repr, unknown))}, which no version\'s config.yaml schema has '
            '(Supervisor drops options that are not in the schema)')
    for k, v in given.items():
        types = [s[k] for s in schemas if k in s]
        if v is not None and any(_is_password(t) for t in types) and not isinstance(v, str):
            raise ValueError(f'upgrade-check/{TEST_OPTIONS}: {prefix + k!r} is a password option, so its value must be a string, not a {type(v).__name__}')
        nested = [t for t in types if isinstance(t, dict)]
        if nested and isinstance(v, dict):_check_level(v, nested, prefix + k + '.', any_key)

def _known(given, schema):
    """`given` without the keys `schema` (a mapping, or None: everything is known) lacks, nested mappings too."""
    if schema is None:return dict(given)
    return {k: _known(v, schema[k]) if isinstance(schema[k], dict) and isinstance(v, dict) else v for k, v in given.items() if k in schema}

def _merge(defaults, given):
    """Supervisor's merge of the defaults with the user's options (apps/app.py _OPTIONS_MERGER): mappings merge key by
    key, any other value replaces the default."""
    out = dict(defaults)
    for k, v in given.items():
        out[k] = _merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out

def _drop_nulls(options):
    """The options without null values (nested mappings too): a null default means "not set"."""
    return {k: _drop_nulls(v) if isinstance(v, dict) else v for k, v in options.items() if v is not None}

def _missing_passwords(options, schema, path=()):
    """[(path, type)] of every required password option of `schema` that is missing or empty (null or '') in
    `options`. Nested mapping schemas are followed, also where the options lack the mapping (Supervisor requires a
    nested mapping: apps/options.py _check_missing_options); list items are not (they have no defaults)."""
    out = []
    for key, typ in schema.items():
        value = options.get(key) if isinstance(options, dict) else None
        if isinstance(typ, dict) and (value is None or isinstance(value, dict)):
            out += _missing_passwords(value or {}, typ, path + (key,))
        elif isinstance(typ, str) and REQUIRED_PASSWORD.match(typ) and value in (None, ''):
            out.append((path + (key,), typ))
    return out

def password_length(name, types):
    """The length of the generated password `name` that every one of `types` (password, password(min,max), either
    with '?', of the versions that receive it) accepts: PASSWORD_LENGTH, moved into the ranges' intersection.
    ValueError when they do not overlap."""
    ranges = [PASSWORD_TYPE.match(t) for t in types]
    low = max([int(m['min']) for m in ranges if m['min']] or [0])
    highs = [int(m['max']) for m in ranges if m['max']]
    high = min(highs) if highs else None
    if high is not None and low > high:
        raise ValueError(f'the password option {name!r} needs a generated value, but its length ranges ({", ".join(types)}) do not overlap: '
            f'give it a value in upgrade-check/{TEST_OPTIONS}')
    return max(low, min(PASSWORD_LENGTH, high) if high is not None else PASSWORD_LENGTH)

def random_password(length):
    """`length` random letters and digits (so it survives shell, JSON and ini files unquoted)."""
    return ''.join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))

def _schema_type(schema, path):
    """(whether Supervisor keeps the option at `path` for a version with `schema`, its type there or None). A version
    without a schema mapping (None) keeps every option; otherwise each key of `path` must be in the schema, and each
    one before the last must be a nested mapping schema."""
    if schema is None:return True, None
    for key in path[:-1]:
        schema = schema.get(key)
        if not isinstance(schema, dict):return False, None
    return (True, schema[path[-1]]) if path[-1] in schema else (False, None)

def build_test_options(configs, given):
    """([/data/options.json of each of `configs`], {dotted name: generated password}) for the upgrade test (#157).
    Each version: its config.yaml option defaults, with upgrade-check/options.yaml (`given`, or None) laid over them
    as Supervisor merges user options (only the keys this version's schema has, nested too, when it has a schema),
    then null values left out. Then every required password option that is still missing or empty in any version's
    schema gets one random value, written into every version that keeps that option (_schema_type(): its schema has
    it, as a password, password? or another type, or it has no schema), replacing that version's own default: a
    real upgrade keeps the user's value, so both versions see the same one. Its length is one that every receiving
    version's password range accepts (password_length()); the nested mappings it sits in are created. Other
    required options that are still null or empty stay as they are (a null one is left out)."""
    built = []
    for config in configs:
        schema = _schema(config)
        built.append((_drop_nulls(_merge(config.get('options') or {}, _known(given or {}, schema))), schema))
    paths = {}
    for options, schema in built:
        for path, _ in (_missing_passwords(options, schema) if schema else []):paths.setdefault('.'.join(path), path)
    generated = {}
    for name, path in paths.items():
        kept = [_schema_type(schema, path) for _, schema in built]
        types = [t for known, t in kept if known and isinstance(t, str) and PASSWORD_TYPE.match(t)]
        generated[name] = random_password(password_length(name, types))
        for (options, _), (known, _) in zip(built, kept):
            if not known:continue
            node = options
            for key in path[:-1]:
                if not isinstance(node.get(key), dict):node[key] = {}
                node = node[key]
            node[path[-1]] = generated[name]
    return [options for options, _ in built], generated

def secret_values(options, schema):
    """The values in `options` that hold a secret, as strings: those of password options (password or password?, by
    `schema`; str() of a value that is not a string) and the string values of options whose name matches SECRET_NAME,
    whatever their type. Nested mappings and lists are followed; with no schema (None) only names count."""
    out = []
    if not isinstance(options, dict):return out
    for key, value in options.items():
        out += _secret_value(key, value, schema.get(key) if isinstance(schema, dict) else None)
    return out

def _secret_value(key, value, typ):
    if isinstance(value, dict):return secret_values(value, typ if isinstance(typ, dict) else None)
    if isinstance(value, list):
        item = typ[0] if isinstance(typ, list) and typ else None
        return [v for each in value for v in _secret_value(key, each, item)]
    if value in (None, ''):return []
    if _is_password(typ):return [value if isinstance(value, str) else str(value)]
    return [value] if isinstance(value, str) and SECRET_NAME.search(key) else []

def repo_passwords(given, configs):
    """The secret values (secret_values()) upgrade-check/options.yaml (`given`) gives, per the schema of any of `configs`."""
    return sorted({v for c in configs for v in secret_values(_known(given or {}, _schema(c)), _schema(c))})

def mask_words(generated, given, configs):
    """What the report must not show, longest first: every generated password and every password options.yaml
    gives (a password option's value, or a string under an option named like a secret: secret_values()), each as
    written and JSON-escaped (as it appears in a JSON log line). Password defaults in config.yaml
    are public and not masked."""
    words = set(generated.values()) | set(repo_passwords(given, configs))
    words |= {json.dumps(w)[1:-1] for w in words}
    return sorted((w for w in words if w), key=len, reverse=True)

def mask(value, words):
    """`value` (a result: nested dicts, lists, strings) with each of `words` replaced by MASK, longest first."""
    if not words:return value
    if isinstance(value, str):
        for w in words:value = value.replace(w, MASK)
        return value
    if isinstance(value, dict):return {k: mask(v, words) for k, v in value.items()}
    if isinstance(value, list):return [mask(v, words) for v in value]
    return value

def mask_result(result, words):
    """The result with `words` masked (mask()), except the add-on's name and each version's image and version."""
    out = mask(result, words)
    if not words:return out
    out['name'] = result['name']
    for masked, original in zip(out.get('phases', []), result.get('phases', [])):
        masked['image'], masked['version'] = original['image'], original['version']
    return out

def option_warnings(given, configs, images):
    """Report warnings about the passwords options.yaml gives: shorter than WEAK_PASSWORD_LENGTH, or found in the
    add-on's name, slug, image or version (masking hides them there in logs and details). Names the option only."""
    out = []
    plain = [str(c.get(k, '')) for c in configs for k in ('name', 'slug', 'version')] + list(images)
    for c in configs:
        schema = _schema(c)
        for key in sorted(_known(given or {}, schema)):
            for v in secret_values({key: (given or {})[key]}, {key: schema[key]} if schema else None):
                if len(v) < WEAK_PASSWORD_LENGTH:warning = f'the password `{key}` is shorter than {WEAK_PASSWORD_LENGTH} characters'
                elif any(v in p for p in plain):warning = f'the password `{key}` appears in the add-on\'s name, slug, image or version'
                else:continue
                warning += '; it is masked wherever it appears, so pick a longer, test-only value'
                if warning not in out:out.append(warning)
    return out
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

def fixtures_problem(hooks_dir):
    """Why upgrade-check/supervisor/ cannot be used in the mock Supervisor's container, or '': only upgrade-check/
    is mounted there, so it, or a file in it, that is a symlink out of upgrade-check/ would point at nothing."""
    root, top = hooks_dir / 'supervisor', hooks_dir.resolve()
    links = [root] if root.is_symlink() else []
    if root.is_dir() and not root.is_symlink():
        links += [pathlib.Path(d, n) for d, dirs, files in os.walk(root) for n in dirs + files if pathlib.Path(d, n).is_symlink()]
    for link in links:
        if not link.resolve().is_relative_to(top):
            rel = link.relative_to(hooks_dir).as_posix()
            return f'upgrade-check/{rel} is a symlink to {link.resolve()}, outside upgrade-check/ (only that directory is mounted for the mock Supervisor)'
    return ''

def _map_warnings(config):
    """upgrade_check.map_warnings(), never raising: a `map` it cannot read is reported as one warning (mounts() fails on it later)."""
    try:return map_warnings(config)
    except (ValueError, TypeError, AttributeError) as e:return [f'map could not be read: {e}']

class UpgradeTestEnv:
    """One upgrade test's network, mock Supervisor and data directories, removed by close(). `hooks`: the add-on's
    upgrade-check/ directory, mounted read-only in the mock Supervisor's container (None when it has none)."""
    def __init__(self, work, hooks=None):
        self.work, self.hooks = pathlib.Path(work), hooks
        # #157: the passwords masked in hook output before it is cut to its last lines (upgrade_test sets them).
        self.words = []
        self.prefix = f'upgrade-test-{secrets.token_hex(4)}'
        self.net, self.supervisor, self.token = self.prefix, f'{self.prefix}-supervisor', secrets.token_hex(24)
        self.state, self.data = self.work / 'supervisor', self.work / 'dirs'
        self.reports, self.hook_state, self.smoke_state = self.work / 'hook-reports', self.work / 'hook-state', self.work / 'smoke-state'
        for d in (self.state, self.data, self.reports, self.hook_state, self.smoke_state):d.mkdir(parents=True)
    def open(self):
        docker('network', 'create', '--subnet', SUBNET, '--gateway', GATEWAY, self.net)
        binds = [(TOOLING, '/tooling', True), (self.state, '/state', False), (self.data, IN_MOCK['data'], False),
            (self.reports, IN_MOCK['reports'], False), (self.hook_state, IN_MOCK['state'], False), (self.smoke_state, IN_MOCK['smoke_state'], False)]
        if self.hooks:binds.append((self.hooks, IN_MOCK['hooks'], True))
        # The repo's Supervisor fixtures (#142) are in the upgrade-check/ mounted above.
        fixtures = ['--fixtures', f'{IN_MOCK["hooks"]}/supervisor'] if self.hooks and (self.hooks / 'supervisor').is_dir() else []
        args = []
        for source, target, read_only in binds:
            args += ['--mount', f'type=bind,source={source},target={target}' + (',readonly' if read_only else '')]
        docker('run', '-d', '--name', self.supervisor, '--network', self.net, '--ip', SUPERVISOR_IP, '-e', f'SUPERVISOR_TOKEN={self.token}',
            *args, MOCK_IMAGE, *MOCK_COMMAND, *fixtures)
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
    def start(self, phase, image, config, options):
        """Start one version on the shared directories with `options` as /data/options.json (build_test_options()); its
        container name."""
        self.log_start = mock_supervisor.log_size(self.state)
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
    def supervisor_calls(self):
        """What the mock could not answer since the last start() (mock_supervisor.summary)."""
        return mock_supervisor.summary(self.state, self.log_start)
    def hook_env(self, phase, image, config, hook='seed'):
        """The environment of `hook` run against this version (the module docstring lists it); smoke has its own HOOK_STATE_DIR."""
        out = {'ADDON_URL': addon_url(config), 'ADDON_HOST': ADDON_IP, 'ADDON_IMAGE': image, 'ADDON_VERSION': str(config.get('version')),
            'PHASE': phase, 'REPORT_DIR': f'{IN_MOCK["reports"]}/{phase}', 'HOOK_STATE_DIR': IN_MOCK['smoke_state' if hook == 'smoke' else 'state'],
            'SUPERVISOR_URL': 'http://127.0.0.1', 'SUPERVISOR_TOKEN': self.token}
        for m in mounts(config, IN_MOCK['data']):
            # Named by the type as config.yaml writes it (a renamed type shares its directory with the new name).
            out['DATA_DIR_' + m['type'].upper()] = m['source']
        return out
    def run_hook(self, hook, phase, image, config, timeout):
        """Run upgrade-check/<hook> against the running version: {hook, phase, passed, exit_code, detail, checks, output,
        report_error, reported}. report_error: why its report cannot be used ('' when it can, or there is none; checks is
        then []); reported: whether it wrote one."""
        (self.reports / phase).mkdir(exist_ok=True)
        report = self.reports / phase / f'{hook}.json'
        if report.exists():report.unlink()
        unusable = hook_problem(self.hooks, hook)
        if unusable:
            return {'hook': hook, 'phase': phase, 'passed': False, 'exit_code': None, 'detail': f'could not run: {unusable}', 'checks': [], 'output': '',
                'report_error': '', 'reported': False}
        envs = [a for k, v in self.hook_env(phase, image, config, hook).items() for a in ('-e', f'{k}={v}')]
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
        checks, problem = _read_checks(report); reported = report.exists()
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
            'checks': checks, 'output': mask(output, self.words)[-4000:], 'report_error': problem,
            'reported': reported}
    def stop(self, container, config):
        docker('stop', '-t', str(config.get('timeout', 10)), container, check=False)
        docker('rm', '-f', container, check=False)
    def close(self):
        docker('rm', '-f', f'{self.prefix}-old', f'{self.prefix}-new', self.supervisor, check=False)
        docker('network', 'rm', self.net, check=False)
        # Containers write as root: remove what they left through a container, then the rest.
        docker('run', '--rm', '--mount', f'type=bind,source={self.work},target=/w', '--entrypoint', 'sh', MOCK_IMAGE, '-c', 'rm -rf /w/* /w/.[!.]*', check=False)

def _read_checks(path):
    """(checks, problem) from a hook's report: [] when it wrote none; problem is why the report cannot be used, and
    then checks is [] too, so no check of an unusable report is compared (#139)."""
    if not path.exists():return [], ''
    try:data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:return [], f'its report {path.name} is not JSON: {e}'
    checks = data.get('checks') if isinstance(data, dict) else None
    if not isinstance(checks, list):return [], f'its report {path.name} has no "checks" list'
    out = []
    for c in checks:
        if not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'] or c.get('result') not in CHECK_RESULTS:
            return [], f'its report {path.name} has a check that is not {{"name": "...", "result": "pass|fail|skip"}}: {json.dumps(c)[:200]}'
        if any(o['name'] == c['name'] for o in out):return [], f'its report {path.name} names two checks {c["name"]!r}'
        if c['name'] == HOOK_ROW:return [], f'its report {path.name} names a check {HOOK_ROW!r}, which is reserved for the hook itself (#139)'
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

# The exceptions main() reports as "the upgrade test could not run" (exit 2); any other one is a bug in this tool.
TOOL_ERRORS = (OSError, ValueError, TypeError, AttributeError, RuntimeError, yaml.YAMLError)

class MaskedError(Exception):
    """A bug's exception (not a TOOL_ERRORS one) whose message held a password: its type name and masked message."""

def upgrade_test(name, addon_dir, old_image, old_config, new_image, new_config, work):
    """The result described in the module docstring."""
    hooks_dir = pathlib.Path(addon_dir) / 'upgrade-check'
    settings_path = hooks_dir / 'settings.yaml'
    settings = yaml.safe_load(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else None
    limits = upgrade_settings(settings)  # a bad settings.yaml is a tool error before any container starts
    present = [h for h in (*HOOK_PHASE, 'smoke') if (hooks_dir / h).is_file()]
    unusable = fixtures_problem(hooks_dir) if hooks_dir.is_dir() else ''
    if unusable:raise ValueError(unusable)  # like a bad settings.yaml: before any container starts
    # #157: the PR's upgrade-check/options.yaml for both versions; a bad one is a tool error before any container starts.
    given = read_test_options(hooks_dir); configs = (old_config, new_config)
    if given:check_test_options(given, configs)
    built, generated = build_test_options(configs, given)
    options, words = dict(zip(('old', 'new'), built)), mask_words(generated, given, configs)
    env = UpgradeTestEnv(work, hooks_dir.resolve() if hooks_dir.is_dir() else None); phases = []; env.words = words
    result = {'name': name, 'passed': False, 'reason': '', 'hooks': present, 'data_checked': False, 'phases': phases,
        'map_warnings': {'old': _map_warnings(old_config), 'new': _map_warnings(new_config)},
        'options': {'from_repo': sorted(given or {}), 'generated': sorted(generated),
            'warnings': option_warnings(given, configs, (old_image, new_image))}}
    try:
        env.open()
        for phase, image, config in (('old', old_image, old_config), ('new', new_image, new_config)):
            probe = startup_probe(config, settings)
            label = f'{PHASE_LABEL[phase]} ({config.get("version")})'
            try:container = env.start(phase, image, config, options[phase])
            except DockerError as e:
                # #140: a version whose image docker cannot run (not found or pulled, entrypoint missing...) did not start;
                # for the comparison target that fails the upgrade comparison with the reason, as an exit does. Any
                # other docker failure is the test's own: a tool error (main(), exit 2).
                if not image_fault(e):raise
                # Created but not started: what it logged, as for a version that exits.
                created = f'{env.prefix}-{phase}'
                logs = mask(_logs(created, 60), words)[-4000:] if docker('ps', '-aq', '--filter', f'name=^{created}$', check=False).strip() else ''
                # It never ran, so it made no Supervisor calls (#142's report section stays empty).
                phases.append({'phase': phase, 'version': str(config.get('version')), 'image': image, 'method': probe['method'], 'started': False,
                    'detail': str(e), 'answer': '', 'logs': logs, 'hooks': [], 'supervisor': {'unmocked': [], 'broken_fixtures': []}})
                result['reason'] = f'{label} did not start: {e}'
                return result
            ok, detail, answer = wait_started(env, container, probe)
            entry = {'phase': phase, 'version': str(config.get('version')), 'image': image, 'method': probe['method'], 'started': ok,
                'detail': detail, 'answer': answer, 'logs': '', 'hooks': []}
            phases.append(entry)
            if not ok:result['reason'] = f'{label} did not start: {detail}'
            # The data hooks of this phase; smoke (in present, not in HOOK_PHASE) runs below.
            for hook in (h for h in present if ok and HOOK_PHASE.get(h) == phase):
                run = env.run_hook(hook, phase, image, config, limits['hook_timeout'])
                entry['hooks'].append(run)
                if hook == 'verify':result['data_checked'] = True
                if not run['passed'] and not result['reason']:result['reason'] = f'{hook} failed on {label}: {run["detail"]}'
            # Category 3 (#139): smoke after the data hook, on the data seed wrote; compared by compare_smoke(), so a
            # failing run sets no reason. Only while category 2 has not failed: on the comparison target a failure ends
            # the test here; on the new version the smoke run is recorded as not run, with category 2's reason.
            if ok and 'smoke' in present and not result['reason']:
                entry['hooks'].append(env.run_hook('smoke', phase, image, config, limits['hook_timeout']))
            elif 'smoke' in present and phase == 'new':entry['smoke_not_run'] = result['reason']
            # After the hooks, so the log shows what the add-on did while they ran.
            entry['logs'] = mask(_logs(container, 60), words)[-4000:]
            env.stop(container, config)
            entry['supervisor'] = env.supervisor_calls()
            if result['reason']:return result
        result['passed'] = True
        return result
    except Exception as e:
        # #157: an error's message must not show a password either. A tool error (main() writes and prints its
        # reason, exit 2) stays one; any other exception is a bug and still crashes with its type and traceback.
        masked = mask(str(e), words)
        if masked == str(e):raise
        if isinstance(e, TOOL_ERRORS):raise RuntimeError(masked) from None
        raise MaskedError(f'{type(e).__name__}: {masked}').with_traceback(e.__traceback__) from None
    finally:
        env.close()
        # #157: the report never shows a password (details, reasons); the returned dict is this one.
        result.update(mask_result(result, words))

def compare_smoke(result):
    """Add category 3 (#139) to upgrade_test()'s result: result['regression'] (upgrade_check.regression), and a
    regression fails a result that passed category 2, with its reason. A result that already failed keeps its reason."""
    result['regression'] = regression(result)
    if result['passed'] and not result['regression']['passed']:
        result['passed'], result['reason'] = False, result['regression']['reason']
    return result

# How the report shows a row's verdict (upgrade_check.regression) and a version's result.
VERDICT_LABEL = {'pass': 'no regression', 'fail': '**regression**', 'not compared': 'not compared: not passing on the comparison target (未比對, report only)'}

def _regression_section(result):
    """Report lines for category 3: each smoke check (or, without smoke, the startup) on both versions."""
    reg = result.get('regression')
    if reg is None:return []
    versions = {p['phase']: markdown_cell(p['version']) for p in result['phases']}
    if not reg.get('compared', True):
        return ['', f'**Regression comparison** (category 3): not compared, smoke did not run on the new version: {markdown_cell(reg["not_run"])}.']
    if not reg['smoke']:
        lead = ('**Regression comparison** (category 3): upgrade-check/ has no smoke, so only startup is compared '
            '(沒有 smoke，只比對能啟動).')
    elif reg['passed']:lead = '**Regression comparison** (category 3): no smoke check that passes on the comparison target fails on the new version.'
    else:lead = f'**Regression comparison** (category 3) **failed**: {markdown_cell(reg["reason"])}.'
    r = ['', lead, '', f'| check | {PHASE_LABEL["old"]} {versions.get("old", "")} | {PHASE_LABEL["new"]} {versions.get("new", "")} | comparison | detail |',
        '|---|---|---|---|---|']
    for row in reg['rows']:
        def cell(side):
            value = row[side]
            if value is None:return 'not run' if row['name'] in (HOOK_ROW, STARTS_ROW) else 'absent'
            return '**fail**' if value == 'fail' else value
        if row['old'] is None and row['verdict'] != 'not compared':
            verdict = 'only in the new version, passes' if row['verdict'] == 'pass' else 'only in the new version: **must pass**'
        else:verdict = VERDICT_LABEL[row['verdict']]
        # The new version's detail, or the comparison target's where the new version has none.
        detail = row['new_detail'] or row['old_detail']
        r.append(f'| {markdown_cell(row["name"])} | {cell("old")} | {cell("new")} | {verdict} | {markdown_cell(detail)} |')
    return r

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
    r += _options_lines(result.get('options') or {})
    if 'seed' in result.get('hooks', []) and 'verify' not in result.get('hooks', []):
        r += ['', 'upgrade-check/ has seed but no verify: nothing reads the seeded data back.']
    r += _regression_section(result)
    # smoke's checks are in the regression table above.
    runs = [h for p in result['phases'] for h in p.get('hooks', []) if h['hook'] != 'smoke']
    if runs:
        r += ['', '| version | hook | check | result | detail |', '|---|---|---|---|---|']
        for h in runs:
            version = f'{PHASE_LABEL[h["phase"]]} {markdown_cell(next(p["version"] for p in result["phases"] if p["phase"] == h["phase"]))}'
            r.append(f'| {version} | {h["hook"]} | (the hook) | {"pass" if h["passed"] else "**fail**"} | {markdown_cell(h["detail"])} |')
            r += [f'| {version} | {h["hook"]} | {markdown_cell(c["name"])} | {"**fail**" if c["result"] == "fail" else c["result"]} | {markdown_cell(c["detail"])} |'
                for c in h['checks']]
    r += _supervisor_sections(result)
    for p in result['phases']:
        for h in p.get('hooks', []):
            if not h['passed']:
                r += ['', f'<details><summary>Output of {h["hook"]} on {PHASE_LABEL[p["phase"]]}</summary>', '', '```', h['output'].replace('```', "'''"), '```', '', '</details>']
        if not p['started'] or any(not h['passed'] for h in p.get('hooks', [])):
            r += ['', f'<details><summary>Last log lines of {PHASE_LABEL[p["phase"]]}</summary>', '', '```', p['logs'].replace('```', "'''"), '```', '', '</details>']
    return '\n'.join(r) + '\n'

def _options_lines(options):
    """Report lines naming the options upgrade-check/options.yaml set and the passwords generated (#157); never values."""
    names = lambda keys: ', '.join(f'`{markdown_cell(k)}`' for k in keys)
    parts = []
    if options.get('from_repo'):parts.append(f'upgrade-check/{TEST_OPTIONS} sets {names(options["from_repo"])}')
    if options.get('generated'):parts.append(f'random passwords for {names(options["generated"])} (the same on both versions)')
    out = ['', f'Test options (測試用的 options): {"; ".join(parts)}.'] if parts else []
    return out + [f'- **Warning**: {markdown_cell(w)}.' for w in options.get('warnings', [])]

def _supervisor_sections(result):
    """Report lines for the unmocked Supervisor calls, broken fixtures and ignored map entries (informational)."""
    r = []
    # Paths come from the add-on: a backquote must not end the code span.
    code = lambda v: markdown_cell(v).replace('`', "'")
    for kind, title, hint in (('unmocked', 'Unmocked Supervisor calls (未模擬的 Supervisor 呼叫)',
            'The mock Supervisor answered these with 404. If the add-on needs one, add its answer as upgrade-check/supervisor/<path>.json '
            '(the `data` of the reply, e.g. supervisor/services/mqtt.json).'),
        ('broken_fixtures', 'Supervisor fixtures that cannot be used',
            'The mock Supervisor answered these with 500: upgrade-check/supervisor/<path>.json is not valid JSON '
            '(or addons/self/info.json is not an object).')):
        rows = []
        for p in result['phases']:
            calls = sorted(p.get('supervisor', {}).get(kind, []), key=lambda c: (-c['count'], c['path']))
            label = f'{PHASE_LABEL[p["phase"]]} {markdown_cell(p["version"])}'
            rows += [f'| {label} | `{code(c["path"])}` | {c["count"]} | {", ".join(c["methods"])} |' for c in calls[:UNMOCKED_ROWS]]
            if len(calls) > UNMOCKED_ROWS:rows.append(f'| {label} | … and {len(calls) - UNMOCKED_ROWS} more paths | | |')
        if rows:r += ['', f'**{title}**: {hint}', '', '| version | path | calls | methods |', '|---|---|---|---|', *rows]
    warnings = result.get('map_warnings') or {}
    old, new = warnings.get('old', []), warnings.get('new', [])
    if old or new:
        r += ['', '**Map entries Supervisor ignores** (config.yaml `map`; these directories are not mounted):', '']
        if old == new:r += [f'- {markdown_cell(w)}' for w in new]
        else:
            r += [f'- {PHASE_LABEL["new"]}: {markdown_cell(w)}' for w in new]
            r += [f'- {PHASE_LABEL["old"]}: {markdown_cell(w)}' for w in old]
    return r

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
        try:result = compare_smoke(upgrade_test(a.name, a.addon_dir, a.old_image, old, a.new_image, new, work))
        finally:shutil.rmtree(work, ignore_errors=True)
    except TOOL_ERRORS as e:
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
