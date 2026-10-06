#!/usr/bin/env python3
"""Read-only PUBLIC artifact consistency gate; never authenticates/builds/collects.

Exit 0 = offline_lock_consistent, 1 = blocked, 2 = argparse usage error.
See ARTIFACT-LOCK.md. Paths and caller-supplied content are not echoed on errors.
"""
import sys

# Keep the CLI read-only even when the caller did not set Python's -B flag.
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re
import stat

import candidate_inventory as inventory

MAX_JSON_BYTES = 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ARTIFACTS = 256
CHUNK_BYTES = 64 * 1024
ARCHITECTURES = {'amd64', 'arm64', 'armhf'}
PENDING_GATES = [
    'signed_dependency_resolution_and_build', 'authenticated_runtime_collection',
    'collation_migration_and_index_rebuild', 'nc33_34_35_and_full_rollback',
    'arm_runtime', 'haos_supervisor', 'full_mcp_acceptance',
    'production_window_approval',
]


class Blocked(ValueError):
    """Only constant/safe diagnostic messages may cross the report boundary."""


def require(condition, reason):
    if not condition:
        raise Blocked(reason)


def shape(value, fields):
    require(type(value) is dict and set(value) == set(fields), 'Missing or unexpected schema fields.')


def label(value):
    require(type(value) is str and 0 < len(value) <= 128 and
            bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+:~-]*', value)), 'Invalid label.')
    require(not set(re.split(r'[._+:~-]+', value.lower())) & {
        'stub', 'fixture', 'synthetic', 'placeholder', 'unresolved', 'unknown',
        'pending', 'todo', 'tbd', 'changeme', 'latest', 'rolling',
    }, 'Placeholder or unresolved label.')
    return value


def digest(value, length=64):
    require(type(value) is str and bool(re.fullmatch('[0-9a-f]{%d}' % length, value)),
            'Invalid immutable hash or commit.')
    require(not any(value == (value[:n] * ((length + n - 1) // n))[:length]
                    for n in range(1, 17)), 'Placeholder hash or commit.')
    return value


def image_digest(value):
    require(type(value) is str and value.startswith('sha256:'), 'Invalid image digest.')
    digest(value[7:])


def unique_list(value):
    require(type(value) is list and 0 < len(value) <= MAX_ARTIFACTS, 'Invalid input list.')
    for item in value:
        label(item)
    require(len(set(value)) == len(value), 'Duplicate input references.')
    return value


def parse(raw):
    require(len(raw) <= MAX_JSON_BYTES, 'JSON size limit exceeded.')
    try:
        return json.loads(raw, object_pairs_hook=inventory.unique_object,
                          parse_constant=inventory.reject_constant, parse_float=inventory.finite_float)
    except (ValueError, RecursionError):
        raise Blocked('Invalid, duplicate-key, non-finite or too-deep JSON.') from None


def components(path, absolute=False):
    require(type(path) is str and 0 < len(path) <= 4096 and '\\' not in path and
            not any(ord(c) < 32 or ord(c) == 127 for c in path), 'Invalid public path.')
    require(path.startswith('/') == absolute, 'Expected an explicit public root or relative input path.')
    parts = path.split('/')[1:] if absolute else path.split('/')
    require(bool(parts) and len(parts) <= 64 and all(
        p and not p.startswith('.') and p.lower() not in {'gnupg', 'pgdata'} for p in parts),
        'Hidden, private, traversal or empty path components are forbidden.')
    if absolute:
        require(parts[0] not in {'dev', 'proc', 'sys', 'etc', 'root'}, 'Sensitive root is forbidden.')
    return parts


class PublicFiles:
    """Descriptor-relative reads; never resolve/follow symlinks or scan a tree.

    Caller must supply a curated PUBLIC root. Reject hardlinks too: an otherwise
    innocent filename must not alias sensitive bytes outside that root.
    """
    def __init__(self, root):
        parts = components(root, absolute=True)
        self.fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.total = 0
        try:
            for part in parts:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                os.close(self.fd)
                self.fd = child
        except BaseException:
            self.close()
            raise

    def close(self):
        os.close(self.fd)

    def read(self, path, expected_size=None, keep=False):
        parts = components(path)
        directory = os.dup(self.fd)
        fd = None
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            # NONBLOCK prevents opening a supplied FIFO from hanging before fstat.
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                    'Input must be a single-link regular file, without symlinks.')
            limit = MAX_JSON_BYTES if keep else MAX_FILE_BYTES
            require(0 < before.st_size <= limit, 'File size limit exceeded or empty input.')
            require(expected_size is None or before.st_size == expected_size, 'Declared file size mismatch.')
            require(self.total + before.st_size + 1 <= MAX_TOTAL_BYTES, 'Total read limit exceeded.')
            hasher, blocks, size = hashlib.sha256(), [], 0
            # Read at most the observed size, then one byte to detect growth.
            while size < before.st_size:
                block = os.read(fd, min(CHUNK_BYTES, before.st_size - size))
                require(bool(block), 'Input changed while reading.')
                size += len(block)
                self.total += len(block)
                hasher.update(block)
                if keep:
                    blocks.append(block)
            require(not os.read(fd, 1), 'Input grew while reading.')
            after = os.fstat(fd)
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                    'Input changed while reading.')
            return hasher.hexdigest(), b''.join(blocks)
        finally:
            if fd is not None:
                os.close(fd)
            os.close(directory)


def report(errors, count=0, total=0):
    return dict(status='blocked' if errors else 'offline_lock_consistent', errors=errors,
                artifact_count=count, bytes_read=total,
                signed_source_verified=False, image_build_verified=False,
                provenance_authenticated=False, runtime_verified=False,
                haos_verified=False, production_authorized=False,
                pending_gates=list(PENDING_GATES))


def verify(public_root, manifest_path):
    """Only reads explicitly declared files under public_root; never writes.

    `verified` in a receipt is an unauthenticated caller claim, not our verdict.
    """
    files = None
    try:
        files = PublicFiles(public_root)
        _, raw = files.read(manifest_path, keep=True)
        doc = parse(raw)
        shape(doc, ('schema_version', 'scope', 'evidence_kind', 'architecture',
                    'observation', 'images', 'artifacts'))
        require(type(doc['schema_version']) is int and doc['schema_version'] == 1, 'Unsupported schema version.')
        require(doc['scope'] == 'isolated-synthetic' and doc['evidence_kind'] == 'collected',
                'Only isolated collected declarations are eligible; stubs remain blocked.')
        require(type(doc['architecture']) is str and doc['architecture'] in ARCHITECTURES, 'Unsupported architecture.')
        shape(doc['images'], ('source', 'candidate'))
        require(type(doc['artifacts']) is list and 0 < len(doc['artifacts']) <= MAX_ARTIFACTS,
                'Invalid artifact count.')
        artifacts, paths = {}, {manifest_path}
        for row in doc['artifacts']:
            require(type(row) is dict and type(row.get('kind')) is str, 'Invalid artifact record.')
            kind = row['kind']
            require(kind in {'package', 'archive', 'image-manifest', 'provenance', 'observation'}, 'Unknown artifact kind.')
            shape(row, ('id', 'kind', 'path', 'sha256', 'size_bytes') +
                  (('name', 'version', 'architecture') if kind in {'package', 'archive'} else ()))
            aid = label(row['id'])
            require(aid not in artifacts, 'Duplicate artifact ID.')
            components(row['path'])
            require(row['path'] not in paths, 'Duplicate artifact path or self-reference.')
            paths.add(row['path'])
            digest(row['sha256'])
            require(type(row['size_bytes']) is int and 0 < row['size_bytes'] <= MAX_FILE_BYTES, 'Invalid declared size.')
            if kind in {'package', 'archive'}:
                label(row['name'])
                label(row['version'])
                require(any(c.isdigit() for c in row['version']), 'Unresolved package/archive version.')
                require(type(row['architecture']) is str and row['architecture'] in
                        {doc['architecture'], 'all'}, 'Package/archive architecture mismatch.')
            artifacts[aid] = row
        used = set()

        def reference(aid, kinds):
            label(aid)
            require(aid in artifacts and artifacts[aid]['kind'] in kinds, 'Missing or wrong-kind artifact reference.')
            used.add(aid)
            return artifacts[aid]

        observation = reference(doc['observation'], {'observation'})
        for side in ('source', 'candidate'):
            image = doc['images'][side]
            shape(image, ('digest', 'source_commit', 'architecture', 'manifest', 'inputs', 'receipt'))
            image_digest(image['digest'])
            digest(image['source_commit'], 40)
            require(image['architecture'] == doc['architecture'], 'Source/candidate architecture mismatch.')
            manifest = reference(image['manifest'], {'image-manifest'})
            require(image['digest'] == 'sha256:' + manifest['sha256'], 'Image digest/manifest mismatch.')
            for aid in unique_list(image['inputs']):
                reference(aid, {'package', 'archive'})
            reference(image['receipt'], {'provenance'})
        require(used == set(artifacts), 'Unreferenced artifacts are forbidden.')
        require(files.total + sum(row['size_bytes'] + 1 for row in artifacts.values()) <= MAX_TOTAL_BYTES,
                'Total read limit exceeded.')
        documents = {}
        for aid, row in artifacts.items():
            keep = row['kind'] in {'observation', 'image-manifest', 'provenance'}
            actual, raw = files.read(row['path'], expected_size=row['size_bytes'], keep=keep)
            require(actual == row['sha256'], 'Artifact SHA256 mismatch.')
            if keep:
                documents[aid] = parse(raw)
        bundle = documents[observation['id']]
        require(type(bundle) is dict and bundle.get('evidence_kind') == 'collected',
                'Observation stub or unresolved evidence is forbidden.')
        require(inventory.evaluate(bundle)['status'] == 'inventory_checks_passed',
                'Observation inventory gate blocked.')
        for side, image in doc['images'].items():
            require(bundle[side + '_digest'] == image['digest'], 'Observation/image digest mismatch.')
            manifest = documents[image['manifest']]
            # Envelope check only, not a recursive OCI graph/content verification.
            require(type(manifest) is dict and type(manifest.get('schemaVersion')) is int and
                    manifest['schemaVersion'] == 2 and manifest.get('mediaType') in
                    ('application/vnd.oci.image.manifest.v1+json',
                     'application/vnd.docker.distribution.manifest.v2+json') and
                    type(manifest.get('config')) is dict and type(manifest.get('layers')) is list,
                    'Expected raw image-manifest JSON bytes, not an archive or image index.')
            receipt = documents[image['receipt']]
            shape(receipt, ('schema_version', 'verification_status', 'image_digest', 'source_commit',
                            'architecture', 'observation_sha256', 'inputs'))
            require(type(receipt['schema_version']) is int and receipt['schema_version'] == 1 and
                    receipt['verification_status'] == 'verified', 'Unresolved provenance assertion.')
            require(receipt['image_digest'] == image['digest'] and
                    receipt['source_commit'] == image['source_commit'] and
                    receipt['architecture'] == image['architecture'] and
                    receipt['observation_sha256'] == observation['sha256'], 'Provenance binding mismatch.')
            require(type(receipt['inputs']) is list and 0 < len(receipt['inputs']) <= MAX_ARTIFACTS,
                    'Invalid provenance inputs.')
            inputs = {}
            for item in receipt['inputs']:
                shape(item, ('id', 'sha256'))
                aid = label(item['id'])
                require(aid not in inputs, 'Duplicate provenance input.')
                inputs[aid] = digest(item['sha256'])
            require(inputs == {aid: artifacts[aid]['sha256'] for aid in image['inputs']},
                    'Provenance input hash binding mismatch.')
        return report([], len(artifacts), files.total)
    except Blocked as exc:
        return report([str(exc)], total=files.total if files else 0)
    except (OSError, ValueError, RecursionError):
        return report(['Cannot read bounded regular PUBLIC inputs.'], total=files.total if files else 0)
    finally:
        if files is not None:
            files.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-root', required=True, help='explicit absolute curated PUBLIC directory')
    parser.add_argument('--manifest', required=True, help='relative manifest path within PUBLIC root')
    args = parser.parse_args()
    result = verify(args.public_root, args.manifest)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'offline_lock_consistent' else 1


if __name__ == '__main__':
    raise SystemExit(main())
