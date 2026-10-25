"""Offline migration planning. Never invoked by ProductStore startup.

Both policies are explicit. The runtime review defaults its selection to all_on
but requires administrator confirmation before applying a legacy migration.
Reports and recovery records contain policy only. A returned state is
private operational data and must not be logged or used as a rollback backup.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import ConfigError, State, Store, strict_json
from .legacy_catalog import LEGACY_TOOLS
from .products import PRODUCTS, ProductState, TOOLS, fresh_write_grants, write_grants
from .surface import full_tools, names

POLICIES = ('preserve', 'all_on')
POLICY_FIELDS = ('writes_enabled', 'disabled', 'enabled_write_tools', 'denied_operations')
MAX_BYTES = 65536


class MigrationError(ValueError):
    """Fixed public error; never expose validation input or credentials."""


@dataclass(frozen=True)
class MigrationPlan:
    state: ProductState = field(repr=False)
    report: dict
    recovery: dict | None


class _RecoveryPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    writes_enabled: bool
    disabled: list[str]
    enabled_write_tools: list[str]
    denied_operations: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator('denied_operations')
    @classmethod
    def valid_denies(cls, value):
        return ProductState.operation_denies(value)

    @field_validator('disabled')
    @classmethod
    def valid_disabled(cls, value):
        return State.names(value)


def _tools(product):
    return full_tools(product) if product == 'n8n' else TOOLS[product]


def _policy(state):
    return {key: deepcopy(getattr(state, key)) for key in POLICY_FIELDS}


def _legacy_grants(product):
    return {grant for name, tool in LEGACY_TOOLS[product].items()
            for grant in ([name] if tool['write'] else []) +
            [f'{name}:{op}' for op in tool['write_operations']]}


def _validate(value, product):
    """Validate the original policy before replacing any field or version."""
    try:
        if product not in (*PRODUCTS, 'n8n') or not isinstance(value, dict):
            raise ValueError
        version = value.get('schema_version')
        if type(version) is not int or version not in (1, 2, 3, 4):
            raise ValueError
        value = deepcopy(value)
        if version == 1:
            if product != 'n8n' or set(value) != set(State.model_fields):
                raise ValueError
            value = {**State.model_validate(value).model_dump(), 'product': product, 'connection': None}
        else:
            expected = set(ProductState.model_fields) - {'mcp_access_token', 'denied_operations'}
            if version == 2:
                expected -= {'enabled_write_tools'}
            if (set(value) - {'mcp_access_token', 'denied_operations'} != expected
                    or value.get('product') != product):
                raise ValueError
        if version < 3:
            value['enabled_write_tools'] = []
        value.setdefault('mcp_access_token', None)
        value.setdefault('denied_operations', {})
        value['schema_version'] = 4
        state = ProductState.model_validate(value)
        if version < 4 and set(state.enabled_write_tools) - _legacy_grants(product):
            raise ValueError
        return version, state
    except (ValueError, TypeError, RecursionError):
        raise MigrationError('invalid, incompatible or wrong-product migration source') from None


def _effective(state, *, legacy):
    grants = set(state.enabled_write_tools)
    if legacy and state.writes_enabled:
        grants.update(name for name, tool in LEGACY_TOOLS[state.product].items() if tool['legacy_write'])
    return {g for g in grants if g.split(':', 1)[0] not in state.disabled
            and (':' not in g or g.split(':', 1)[1] not in state.denied_operations.get(g.split(':', 1)[0], ()))}


def _preserve(state):
    tools = _tools(state.product)
    old = LEGACY_TOOLS[state.product]
    # Keep the conservative batch2 migration boundary: expanded argument validation
    # also needs review before the tool is enabled, even with operation denies.
    expanded_reads = {name for name, tool in tools.items() if name in old
                      and set(tool.read_operations) - set(old[name]['read_operations'])}
    # The full child validates a broader argument surface than the old bounded
    # models (e.g. Odoo model allowlists). Grant names alone cannot preserve
    # that boundary. Hold these tools disabled until the owner reviews them.
    argument_review = {name for name, tool in tools.items() if name in old and tool.child_schema}
    disabled = sorted(set(state.disabled) | (set(tools) - set(old)) | expanded_reads | argument_review)
    grants = set(state.enabled_write_tools)
    if state.writes_enabled:
        grants.update(name for name, tool in old.items() if tool['legacy_write'])
    return ProductState.model_validate({**state.model_dump(), 'disabled': disabled,
                                        'enabled_write_tools': sorted(grants)})


def _catalog_digest(product):
    current = {name: {'write': t.write, 'legacy_write': t.legacy_write,
                      'read_operations': t.read_operations, 'write_operations': t.write_operations}
               for name, t in _tools(product).items()}
    raw = json.dumps([LEGACY_TOOLS[product], current], sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def source_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def plan_migration(value, product, *, policy):
    """Pure explicit-choice plan. Schema 4 policy/identity/backend are unchanged.

    Comparisons use the final 0.1.x catalog, not an inferred installation date.
    Argument constraints formerly enforced by bounded models are not restored.
    """
    if policy not in POLICIES:
        raise MigrationError('choose preserve or all_on explicitly')
    version, before = _validate(value, product)
    tools = _tools(product)
    old = LEGACY_TOOLS[product]
    after = before
    recovery = None
    if version < 4:
        preserved = _preserve(before)
        after = preserved
        if policy == 'all_on' and product != 'odoo-manage':
            after = ProductState.model_validate({**before.model_dump(), 'writes_enabled': True,
                                                 'disabled': [], 'denied_operations': {}, 'enabled_write_tools': fresh_write_grants(product)})
        recovery = {'format': 1, 'product': product, 'source_schema': version,
                    'catalog_sha256': _catalog_digest(product), 'policy': _policy(preserved)}
    before_grants, after_grants = _effective(before, legacy=version < 4), _effective(after, legacy=False)
    groups = names(product)
    classified = {name for group in groups.values() for name in group}
    # Retired Manage uses its bounded catalog, not surface.py's broader inventory.
    if product == 'odoo-manage':
        classified = set(old)
    report = {
        'product': product, 'source_schema': version, 'target_schema': 4, 'policy': policy,
        'source_sha256': source_digest(value),
        'changed': before.model_dump() != after.model_dump() or version < 4,
        'source_catalog': 'final-0.1.x-bounded' if version < 4 else 'current-schema-4',
        'before': _policy(before), 'after': _policy(after),
        'disabled_added': sorted(set(after.disabled) - set(before.disabled)),
        'disabled_removed': sorted(set(before.disabled) - set(after.disabled)),
        'write_grants_added': sorted(set(after.enabled_write_tools) - set(before.enabled_write_tools)),
        'write_grants_removed': sorted(set(before.enabled_write_tools) - set(after.enabled_write_tools)),
        'effective_writes_added': sorted(after_grants - before_grants),
        'effective_writes_removed': sorted(before_grants - after_grants),
        'new_tools': sorted(set(tools) - set(old)) if version < 4 else [],
        'new_write_operations': sorted({g for n, t in tools.items() for g in t.grants(n)} - _legacy_grants(product))
                                if version < 4 else [],
        'unclassified_tools': sorted(set(tools) - classified),
        'unverified_tools': sorted(set(groups['unverified']) & set(tools)),
        'expanded_read_tools': sorted(n for n, t in tools.items() if n in old
                                     and set(t.read_operations) - set(old[n]['read_operations'])) if version < 4 else [],
        'argument_review_tools': sorted(n for n, t in tools.items() if n in old and t.child_schema) if version < 4 else [],
    }
    return MigrationPlan(after, report, recovery)


def plan_restore(value, product, recovery):
    """Restrictive policy recovery into CURRENT schema 4; never restore identity.

    Newer disabled tools and revoked grants stay revoked. This is neither a
    binary downgrade nor a full-state backup restore.
    """
    version, current = _validate(value, product)
    if version != 4:
        raise MigrationError('recovery requires current schema 4 state')
    try:
        if (not isinstance(recovery, dict) or set(recovery) !=
                {'format', 'product', 'source_schema', 'catalog_sha256', 'policy'}
                or type(recovery['format']) is not int or recovery['format'] != 1
                or type(recovery['source_schema']) is not int or recovery['source_schema'] not in (1, 2, 3)
                or recovery['product'] != product or (recovery['source_schema'] == 1 and product != 'n8n')
                or recovery['catalog_sha256'] != _catalog_digest(product)
                or not isinstance(recovery['policy'], dict)
                or set(recovery['policy']) not in (set(POLICY_FIELDS), set(POLICY_FIELDS) - {'denied_operations'})):
            raise ValueError
        baseline = _RecoveryPolicy.model_validate(recovery['policy'])
        if (len(set(baseline.enabled_write_tools)) != len(baseline.enabled_write_tools)
                or set(baseline.enabled_write_tools) - write_grants(product)):
            raise ValueError
        restored = ProductState.model_validate({
            **current.model_dump(),
            'disabled': sorted(set(current.disabled) | set(baseline.disabled)),
            'enabled_write_tools': sorted(set(current.enabled_write_tools) & set(baseline.enabled_write_tools)),
            'writes_enabled': current.writes_enabled and baseline.writes_enabled,
            'denied_operations': {name: sorted(set(current.denied_operations.get(name, ()))
                                                | set(baseline.denied_operations.get(name, ())))
                                  for name in current.denied_operations.keys() | baseline.denied_operations.keys()},
        })
    except (ValueError, TypeError, RecursionError):
        raise MigrationError('invalid or incompatible policy recovery record') from None
    return MigrationPlan(restored, {'product': product, 'source_schema': 4, 'target_schema': 4,
                                    'source_sha256': source_digest(value),
                                    'policy': 'recovery', 'before': _policy(current), 'after': _policy(restored),
                                    'changed': current.model_dump() != restored.model_dump()}, None)


def read_document(path):
    """Read without Store construction, chmod, migration, links or unbounded IO."""
    try:
        path = Path(os.path.abspath(path))
        if any(p.is_symlink() for p in (*path.parents, path)):
            raise ValueError
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                raise ValueError
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError
        return strict_json(raw)
    except (OSError, ValueError, RecursionError):
        raise MigrationError('migration document unavailable or invalid') from None


def save_recovery(path, plan):
    """Create one secret-free 0600 record in an existing owner-only directory.

    Never overwrite a record. Interrupted writes cannot authorize recovery:
    readers reject incomplete JSON. The caller must stop if durability fails.
    """
    if plan.recovery is None:
        raise MigrationError('no legacy policy recovery record for this plan')
    # Revalidate the public mutable record before persisting any caller data.
    plan_restore(plan.state.model_dump(), plan.state.product, plan.recovery)
    data = json.dumps(plan.recovery, sort_keys=True, indent=2).encode() + b'\n'
    if len(data) > MAX_BYTES:
        raise MigrationError('policy recovery record too large')
    directory_fd = None
    try:
        path = Path(os.path.abspath(path))
        if any(p.is_symlink() for p in (*path.parents, path)):
            raise ValueError
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory_fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory_fd)
    except (OSError, ValueError):
        raise MigrationError('policy recovery record not durably saved; source unchanged') from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


@contextmanager
def _existing_writer(directory):
    """Use the runtime's lock and atomic writer without starting its migration."""
    writer = object.__new__(Store)
    writer.directory = Path(os.path.abspath(directory))
    writer.path = writer.directory / 'state.json'
    writer._lock_fd = None
    writer._poisoned = False
    try:
        if any(p.is_symlink() for p in (*writer.directory.parents, writer.directory)):
            raise ValueError
        info = writer.directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError
        # Never bootstrap an empty directory or replace the existing lock inode.
        writer._lock_fd = os.open(writer.directory / '.writer.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(writer._lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError
        fcntl.flock(writer._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError):
        writer.close()
        raise MigrationError('existing state unavailable or writer active; stop runtime before applying') from None
    try:
        yield writer
    finally:
        writer.close()


def apply_migration(directory, product, *, policy, expected_sha256):
    """Explicit offline apply; recoverable policy saved before atomic replacement.

    The caller must supply the digest from its reviewed dry run. A changed state
    or existing recovery record is refused, never overwritten.
    """
    with _existing_writer(directory) as writer:
        return apply_migration_locked(writer, product, policy=policy, expected_sha256=expected_sha256)


def apply_migration_locked(writer, product, *, policy, expected_sha256):
    """Apply under the existing writer's lock, shared by CLI and startup review."""
    if writer._lock_fd is None or writer._poisoned:
        raise MigrationError('migration writer unavailable')
    value = read_document(writer.path)
    plan = plan_migration(value, product, policy=policy)
    if plan.report['source_sha256'] != expected_sha256:
        raise MigrationError('state changed since preview; run preview again')
    if plan.recovery is not None:
        save_recovery(writer.directory / 'migration-policy-recovery.json', plan)
        try:
            writer._write(plan.state)
        except ConfigError:
            raise MigrationError('durable migration write failed; recovery record retained; inspect state') from None
    return plan.report


def apply_restore(directory, product, recovery_path, *, expected_sha256):
    """Apply only the restrictive policy plan; current credentials stay current."""
    with _existing_writer(directory) as writer:
        plan = plan_restore(read_document(writer.path), product, read_document(recovery_path))
        if plan.report['source_sha256'] != expected_sha256:
            raise MigrationError('state changed since preview; run preview again')
        if plan.report['changed']:
            try:
                writer._write(plan.state)
            except ConfigError:
                raise MigrationError('durable recovery write failed; inspect current state') from None
        return plan.report


def main(argv=None):
    """CLI also available inside product images: python -m mcp_admin_core.migration."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Existing data directory containing state.json')
    parser.add_argument('--product', required=True, choices=(*PRODUCTS, 'n8n'))
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--policy', choices=POLICIES, help='Explicit migration choice (no default)')
    choice.add_argument('--restore-policy', type=Path, help='Restrictive recovery record, never a full state backup')
    parser.add_argument('--apply', action='store_true', help='Write offline under the existing runtime lock')
    parser.add_argument('--expected-sha256', help='Required with --apply: source_sha256 from reviewed dry run')
    parser.add_argument('--save-recovery', type=Path, help='Dry run only: save policy in an existing protected directory')
    args = parser.parse_args(argv)
    if args.apply and (not args.expected_sha256 or args.save_recovery):
        parser.error('--apply requires --expected-sha256 and cannot use --save-recovery')
    if not args.apply and args.expected_sha256:
        parser.error('--expected-sha256 is only used with --apply')
    if args.restore_policy and args.save_recovery:
        parser.error('--save-recovery requires --policy')
    try:
        if args.apply:
            if args.restore_policy:
                report = apply_restore(args.directory, args.product, args.restore_policy,
                                       expected_sha256=args.expected_sha256)
            else:
                report = apply_migration(args.directory, args.product, policy=args.policy,
                                         expected_sha256=args.expected_sha256)
        else:
            source = read_document(args.directory / 'state.json')
            plan = (plan_restore(source, args.product, read_document(args.restore_policy)) if args.restore_policy else
                    plan_migration(source, args.product, policy=args.policy))
            if args.save_recovery:
                save_recovery(args.save_recovery, plan)
            report = plan.report
    except MigrationError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps({'dry_run': not args.apply, **report}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
