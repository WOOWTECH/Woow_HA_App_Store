#!/usr/bin/env python3
"""Offline, fail-closed observation gate. NEVER collects or authorizes runtime.

Exit 0: supplied inventory is consistent, NOT runtime acceptance.
Exit 1: blocked observations. Exit 2: invalid JSON/file/usage.
See CANDIDATE-INVENTORY.md for the evidence and authorization boundary.
"""
import argparse
import json
import re
from pathlib import Path

MAX_BYTES = 1024 * 1024
REQUIRED_MODULES = frozenset((
    'apcu', 'bcmath', 'bz2', 'ctype', 'curl', 'dom', 'fileinfo', 'gd', 'gmp',
    'iconv', 'imagick', 'intl', 'mbstring', 'openssl', 'pdo_pgsql', 'pgsql',
    'redis', 'simplexml', 'xml', 'xmlreader', 'xmlwriter', 'zip', 'zlib',
    'zend opcache',
))
SOCKET = '/run/php/php8.4-fpm.sock'
PID_FILE = '/run/php/php8.4-fpm.pid'
PENDING_GATES = [
    'authenticated_runtime_collection', 'signed_build_and_artifact_lock',
    'collation_migration_and_index_rebuild', 'nc33_34_35_and_full_rollback',
    'arm_runtime', 'haos_supervisor', 'production_window_approval',
]


class InvalidObservation(ValueError):
    """A required observation is missing or has the wrong shape."""


def shape(value, fields, path):
    if type(value) is not dict:
        raise InvalidObservation(f'{path}: expected object')
    missing = set(fields) - value.keys()
    if missing:
        raise InvalidObservation(f'{path}: missing {", ".join(sorted(missing))}')
    if value.keys() - set(fields):
        # Do not echo unrecognized user-supplied keys or values into reports.
        raise InvalidObservation(f'{path}: unexpected fields')
    return value


def text(value, path):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise InvalidObservation(f'{path}: expected nonempty bounded string')
    return value


def strings(value, path, lower=False):
    if type(value) is not list or not value:
        raise InvalidObservation(f'{path}: expected nonempty string list')
    values = [text(v, path).lower() if lower else text(v, path) for v in value]
    if len(values) != len(set(values)):
        raise InvalidObservation(f'{path}: duplicate entries')
    return set(values)


def rows(value, path):
    if type(value) is not list or not value:
        raise InvalidObservation(f'{path}: expected nonempty inventory')
    return value


def report(status, errors, kind=None):
    return dict(status=status, errors=errors, evidence_kind=kind,
                runtime_verified=False, haos_verified=False,
                production_authorized=False, pending_gates=list(PENDING_GATES))


def evaluate(bundle):
    errors = []
    kind = None

    def check(condition, path, reason):
        if not condition:
            errors.append(f'{path}: {reason}')

    def exact(value, expected, path):
        check(type(value) is type(expected) and value == expected, path,
              'required observation not satisfied')

    def inventory(value, path):
        shape(value, ('version', 'libc_version', 'icu_version', 'locales',
                      'databases_complete', 'databases'), path)
        check(bool(re.fullmatch(r'16\.\d+(?:\.\d+)?', text(value['version'], path + '.version'))),
              path + '.version', 'PG16 required')
        for key in ('libc_version', 'icu_version'):
            text(value[key], path + '.' + key)
        locales = strings(value['locales'], path + '.locales')
        exact(value['databases_complete'], True, path + '.databases_complete')
        databases = {}
        for index, db in enumerate(rows(value['databases'], path + '.databases')):
            dbpath = f'{path}.databases[{index}]'
            dbrow = locale_row(db, dbpath, database=True)
            check(dbrow['name'] not in databases, dbpath, 'duplicate database')
            exact(db['collations_complete'], True, dbpath + '.collations_complete')
            collations = {}
            for ci, col in enumerate(rows(db['collations'], dbpath + '.collations')):
                colpath = f'{dbpath}.collations[{ci}]'
                colrow = locale_row(col, colpath, parent=dbrow)
                check(colrow['name'] not in collations, colpath, 'duplicate collation')
                collations[colrow['name']] = colrow
            dbrow['collations'] = collations
            databases[dbrow['name']] = dbrow
        return dict(libc_version=value['libc_version'], icu_version=value['icu_version'],
                    locales=sorted(locales), databases=databases)

    def locale_row(value, path, database=False, parent=None):
        fields = ('name', 'provider', 'locale', 'collate', 'ctype',
                  'recorded_version', 'actual_version')
        shape(value, fields + (('collations_complete', 'collations') if database else ()), path)
        result = {key: value[key] for key in fields}
        for key in ('name', 'provider', 'locale', 'collate', 'ctype'):
            text(value[key], path + '.' + key)
        check(value['provider'] in (('c', 'i') if database else ('c', 'i', 'd')),
              path + '.provider', 'unknown locale provider')
        for key in ('recorded_version', 'actual_version'):
            if value[key] is not None:
                text(value[key], path + '.' + key)
        both_null = value['recorded_version'] is None and value['actual_version'] is None
        if value['provider'] == 'd':
            # PG's default collation inherits the database provider/locale.
            # Collector must normalize these three effective locale fields;
            # version safety is checked on the database row, not invented here.
            check(parent is not None and both_null and
                  all(value[key] == parent[key] for key in ('locale', 'collate', 'ctype')),
                  path + '.version', 'invalid inherited database collation')
        elif value['recorded_version'] is None or value['actual_version'] is None:
            c_locales = {'C', 'POSIX', 'C.UTF-8', 'C.utf8'}
            check(value['provider'] == 'c' and both_null and
                  all(value[key] in c_locales for key in ('locale', 'collate', 'ctype')),
                  path + '.version', 'unexplained null collation version')
        check(value['recorded_version'] == value['actual_version'], path + '.version',
              'recorded/actual collation version mismatch; no auto-refresh allowed')
        return result

    try:
        shape(bundle, ('schema_version', 'scope', 'evidence_kind', 'candidate_digest',
                       'source_digest', 'php', 'fpm', 'nginx', 'code', 'postgres'), 'bundle')
        exact(bundle['schema_version'], 1, 'schema_version')
        exact(bundle['scope'], 'isolated-synthetic', 'scope')
        text(bundle['evidence_kind'], 'evidence_kind')
        check(bundle['evidence_kind'] in ('stub', 'collected'), 'evidence_kind',
              'must explicitly distinguish stub from collected input')
        if bundle['evidence_kind'] in ('stub', 'collected'):
            kind = bundle['evidence_kind']
        for key in ('source_digest', 'candidate_digest'):
            check(bool(re.fullmatch(r'sha256:[0-9a-f]{64}', text(bundle[key], key))),
                  key, 'immutable image digest required; not authenticated by this tool')
        php = shape(bundle['php'], ('cli', 'fpm'), 'php')
        for sapi in ('cli', 'fpm'):
            path = 'php.' + sapi
            value = shape(php[sapi], ('version', 'modules', 'ini'), path)
            check(bool(re.fullmatch(r'8\.4\.\d+', text(value['version'], path + '.version'))),
                  path + '.version', 'PHP8.4 required')
            modules = strings(value['modules'], path + '.modules', lower=True)
            check(REQUIRED_MODULES <= modules, path + '.modules', 'required PHP modules missing')
            expected_ini = dict(memory_limit='1024M', upload_max_filesize='16G',
                                post_max_size='16G')
            expected_ini['apc.enable_cli' if sapi == 'cli' else 'opcache.enable'] = '1'
            ini = shape(value['ini'], expected_ini, path + '.ini')
            for key, expected in expected_ini.items():
                exact(ini[key], expected, path + '.ini.' + key)
        check(php['cli']['version'] == php['fpm']['version'], 'php.version',
              'CLI/FPM patch versions differ')
        fpm = shape(bundle['fpm'], ('binary', 'socket', 'socket_is_unix', 'pid_file',
                                   'pid', 'master_pid', 'process_alive', 'config_test_exit'), 'fpm')
        for key, expected in dict(binary='php-fpm8.4', socket=SOCKET,
                                  socket_is_unix=True, pid_file=PID_FILE,
                                  process_alive=True, config_test_exit=0).items():
            exact(fpm[key], expected, 'fpm.' + key)
        for key in ('pid', 'master_pid'):
            check(type(fpm[key]) is int and fpm[key] > 0, 'fpm.' + key, 'positive integer PID required')
        check(fpm['pid'] == fpm['master_pid'], 'fpm.pid', 'PID file and observed master differ')
        nginx = shape(bundle['nginx'], ('config_test_exit', 'process_alive', 'fastcgi_socket'), 'nginx')
        for key, expected in dict(config_test_exit=0, process_alive=True, fastcgi_socket=SOCKET).items():
            exact(nginx[key], expected, 'nginx.' + key)
        code = shape(bundle['code'], ('version', 'version_exit', 'process_alive',
                                     'discovery_http_status', 'discovery_xml_valid',
                                     'websocket_http_status', 'save_roundtrip', 'jail_enabled'), 'code')
        text(code['version'], 'code.version')
        for key, expected in dict(version_exit=0, process_alive=True,
                                  discovery_http_status=200, discovery_xml_valid=True,
                                  websocket_http_status=101, save_roundtrip=True,
                                  jail_enabled=True).items():
            exact(code[key], expected, 'code.' + key)
        pg = shape(bundle['postgres'], ('source', 'candidate'), 'postgres')
        source = inventory(pg['source'], 'postgres.source')
        candidate = inventory(pg['candidate'], 'postgres.candidate')
        for key in source:
            check(source[key] == candidate[key], 'postgres.' + key,
                  'source/candidate drift; reviewed migration/rebuild evidence required')
    except InvalidObservation as exc:
        errors.append(str(exc))
    return report('blocked' if errors else 'inventory_checks_passed', errors, kind)


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate JSON key')
        obj[key] = value
    return obj


def reject_constant(_value):
    raise ValueError('non-finite JSON number')


def finite_float(value):
    number = float(value)
    if number in (float('inf'), float('-inf')):
        raise ValueError('non-finite JSON number')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observations', type=Path, help='explicit offline JSON file; no collection')
    args = parser.parse_args()
    try:
        # Size bounded even if the file grows after opening. No input path is
        # ever interpreted as a command, URL, PGDATA directory or output path.
        if not args.observations.is_file():
            raise ValueError('expected a regular JSON file')
        with args.observations.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('input too large')
        bundle = json.loads(raw, object_pairs_hook=unique_object,
                            parse_constant=reject_constant, parse_float=finite_float)
        result = evaluate(bundle)
    except (OSError, ValueError, RecursionError):
        # Never expose a private path or raw JSON (which could contain secrets).
        print(json.dumps(report('invalid_input', ['Cannot read a bounded, valid JSON observation file.'])))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'inventory_checks_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
