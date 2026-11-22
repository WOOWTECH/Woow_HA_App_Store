"""Verify the final HA runtime using stdlib and exact portable source tests.

Executed only by the reviewed PR workflow inside the loaded final native image.
No SDK/provider imports or code from the installed pycs is executed here.
"""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path
import platform
import re
import stat
import sys
import sysconfig
import tempfile
import types
import unittest


PAYLOAD = Path('/ha-final-verification')
TARGET = Path('/opt/omnigent/venv/lib/python3.12/site-packages/omnigent/native/native_bridge_common.py')
MANIFEST_SHA = '1b5341f48184336fb5697f258340ec541f80abf3440765234a0d2aecc9d766f4'
AFTER_SHA = '68f4c2a3c0a3aa75436a15828e325bd279995435d83931d93b12516cca303962'
EXPECTED_SKIP = 'test_build_patch.SourceScopeTests.test_all_43_captured_sources_unchanged'


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def image_identity(image_id, action_image_id, source_commit):
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', image_id) is not None and
            re.fullmatch(r'[0-9a-f]{40}', source_commit) is not None, 'image_or_source_identity')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', action_image_id) is not None, 'build_action_config_id')
    require(action_image_id == image_id, 'build_action_config_id_mismatch')


def runtime_identity(version, machine, uid, gid, arch):
    require(tuple(version) == (3, 12, 12), 'python_version')
    require(machine == {'amd64': 'x86_64', 'aarch64': 'aarch64'}.get(arch), 'native_architecture')
    require(uid == gid == 1000, 'runtime_uid_gid')


def sandbox_identity(mounts, interfaces, cap_eff, no_new_privs):
    for path, access in [('/', 'ro'), (str(PAYLOAD), 'ro'), ('/tmp', 'rw')]:
        require(path in mounts and access in mounts[path]['options'], 'mount_' + access)
    require(mounts['/tmp']['type'] == 'tmpfs' and
            {'nosuid', 'nodev', 'noexec'} <= set(mounts['/tmp']['options']), 'owned_tmpfs')
    require(set(interfaces) == {'lo'}, 'network_not_none')
    require(int(cap_eff, 16) == 0 and no_new_privs == '1', 'capabilities_or_new_privileges')


def mounts_readback():
    found = {}
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields = left.split()
        found[fields[4]] = {'options': fields[5].split(','), 'type': right.split()[0]}
    return found


def plain_file(path, limit, image=False):
    for parent in path.parents:
        require(stat.S_ISDIR(parent.lstat().st_mode), 'redirected_parent')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit, 'file_type_or_size')
    if image:
        require(stat.S_IMODE(info.st_mode) == 0o644 and info.st_uid == info.st_gid == 0, 'image_file_mode_owner')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require((before.st_dev, before.st_ino) == (info.st_dev, info.st_ino), 'file_changed')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        require(len(raw) == info.st_size and len(raw) <= limit and
                (before.st_mode, before.st_uid, before.st_gid, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_mode, after.st_uid, after.st_gid, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'file_changed')
    finally:
        os.close(fd)
    return raw, {'sha256': sha(raw), 'bytes': len(raw), 'mode': oct(stat.S_IMODE(info.st_mode)),
                 'uid': info.st_uid, 'gid': info.st_gid}


def verify_pyc(blob, source, filename, optimization):
    require(len(blob) > 16 and blob[:4] == importlib.util.MAGIC_NUMBER, 'pyc_magic')
    require(int.from_bytes(blob[4:8], 'little') == 3, 'pyc_checked_hash_flags')
    require(blob[8:16] == importlib.util.source_hash(source), 'pyc_source_hash')
    stream = io.BytesIO(blob[16:])
    code = marshal.load(stream)
    require(stream.read() == b'' and isinstance(code, types.CodeType), 'pyc_marshal_boundary')
    expected = compile(source, filename, 'exec', dont_inherit=True, optimize=optimization)
    require(code == expected, 'pyc_code_differs')
    def filenames(node):
        require(node.co_filename == filename, 'pyc_filename')
        for value in node.co_consts:
            if isinstance(value, types.CodeType):
                filenames(value)
    filenames(code)
    return {'optimization': optimization, 'magic': blob[:4].hex(), 'flags': 3,
            'sourceHash': blob[8:16].hex(), 'marshalMatchesCompiledSource': True}


def installed_readback():
    source, record = plain_file(TARGET, 128 * 1024, image=True)
    require(record['sha256'] == AFTER_SHA, 'installed_source_hash')
    pycs = []
    expected_paths = {Path(importlib.util.cache_from_source(str(TARGET), optimization=o)) for o in ('', 1, 2)}
    require(set(TARGET.parent.joinpath('__pycache__').glob('native_bridge_common.*.pyc')) == expected_paths, 'pyc_set')
    for optimization in (0, 1, 2):
        path = Path(importlib.util.cache_from_source(str(TARGET), optimization='' if optimization == 0 else optimization))
        blob, meta = plain_file(path, 256 * 1024, image=True)
        pycs.append(dict(meta, **verify_pyc(blob, source, str(TARGET), optimization), filename=path.name))
    return {'source': record, 'pycs': pycs}


def portable_payload():
    bundle = PAYLOAD / 'maintenance'
    raw, _ = plain_file(bundle / 'SOURCE-BUNDLE-MANIFEST.json', 32 * 1024)
    require(sha(raw) == MANIFEST_SHA, 'portable_manifest_hash')
    manifest = json.loads(raw)
    expected = set(manifest['files']) | {'SOURCE-BUNDLE-MANIFEST.json'}
    actual = {str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file() or p.is_symlink()}
    require(actual == expected and len(expected) == 18, 'portable_payload_scope')
    for name, item in manifest['files'].items():
        content, _ = plain_file(bundle / name, 128 * 1024)
        require(sha(content) == item['sha256'] and len(content) == item['bytes'], 'portable_payload_hash')
    versions = json.loads(plain_file(PAYLOAD / 'versions.json', 16 * 1024)[0])
    lock = json.loads(plain_file(bundle / 'source-lock.json', 16 * 1024)[0])
    require(versions['omnigent']['version'] == lock['capturedCoreVersion'] == '0.16.0', 'sdk_pin')
    require(not (PAYLOAD / 'actual5164').exists(), 'unexpected_full_capture')
    return bundle


def suite_result(result):
    require(result.testsRun == 57 and result.wasSuccessful(), 'portable_suite_failed_or_incomplete')
    require(len(result.skipped) == 1 and result.skipped[0][0].id() == EXPECTED_SKIP and
            result.skipped[0][1] == 'full 43-source audit is available in review workspace only', 'unexpected_suite_skip')
    return {'run': 57, 'pass': 56, 'fail': len(result.failures), 'errors': len(result.errors),
            'skip': 1, 'skipTest': EXPECTED_SKIP, 'skipReason': result.skipped[0][1]}


def verify(args):
    runtime_identity(sys.version_info[:3], platform.machine(), os.geteuid(), os.getegid(), args.arch)
    require(sys.implementation.name == 'cpython' and sys.prefix == '/opt/omnigent/venv', 'runtime_interpreter')
    require(sysconfig.get_paths()['purelib'] == str(TARGET.parents[2]), 'runtime_purelib')
    mounts = mounts_readback()
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    sandbox_identity(mounts, os.listdir('/sys/class/net'), status['CapEff'].strip(), status['NoNewPrivs'].strip())
    bundle = portable_payload()
    require(importlib.metadata.version('omnigent') == '0.16.0', 'installed_sdk_metadata')
    require(str(importlib.metadata.distribution('omnigent').locate_file('')) == str(TARGET.parents[2]), 'metadata_location')
    before = installed_readback()
    os.environ['PI_NATIVE_MAINTENANCE_TEST_SOURCE'] = str(TARGET)
    sys.dont_write_bytecode = True
    with tempfile.TemporaryDirectory(prefix='ha-final-maintenance-', dir='/tmp') as scratch:
        os.environ['TMPDIR'] = scratch
        tempfile.tempdir = scratch
        suite = unittest.defaultTestLoader.discover(str(bundle / 'tests'), pattern='test_*.py')
        result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
        tests = suite_result(result)
    require(not any(n == 'omnigent' or n.startswith('omnigent.') or n == 'claude_agent_sdk' or
                    n.startswith('claude_agent_sdk.') for n in sys.modules), 'sdk_imported')
    require(installed_readback() == before, 'installed_files_changed_by_tests')
    return {'python': platform.python_version(), 'architecture': platform.machine(), 'uid': os.geteuid(), 'gid': os.getegid(),
            'sdkMetadataVersion': importlib.metadata.version('omnigent'), 'installed': before, 'tests': tests,
            'portablePayloadFiles': 18, 'installedSourceEnvironment': str(TARGET), 'SDKImported': False,
            'sandbox': {p: mounts[p] for p in ['/', '/tmp', str(PAYLOAD)]}, 'networkInterfaces': ['lo'],
            'capabilities': 0, 'noNewPrivileges': True, 'readOnlyRoot': True, 'providerCalls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=['amd64', 'aarch64'], required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--build-action-image-id', default='')
    parser.add_argument('--build-action-digest', default='')
    args = parser.parse_args()
    receipt = {'schema': 'ha-final-image-installed-maintenance/v1', 'success': False,
               'matrixArchitecture': args.arch, 'imageId': args.image_id, 'sourceCommit': args.source_commit,
               'buildActionImageId': args.build_action_image_id, 'buildActionDigest': args.build_action_digest,
               'buildActionImageIdKind': 'config', 'buildActionDigestKind': 'manifest'}
    try:
        image_identity(args.image_id, args.build_action_image_id, args.source_commit)
        receipt.update(verify(args))
        receipt['success'] = True
    except Exception as error:
        receipt['errorType'] = type(error).__name__
        receipt['error'] = str(error)[:500]
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
