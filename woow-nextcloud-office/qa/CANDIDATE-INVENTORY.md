# Offline candidate inventory gate (not runtime acceptance)

`candidate_inventory.py` evaluates an explicitly supplied JSON file. It has no
collector, command runner, network client, DB client or remediation path. It
reads only that input and writes a JSON report to stdout. Never give it secrets,
raw config, PGDATA or business data. Collection is a separate, still-unapproved
runtime step; this tool is **not** permission to collect from production.

From the repository root, using the included **synthetic stub**:

```sh
python3 woow-nextcloud-office/qa/candidate_inventory.py \
  woow-nextcloud-office/qa/fixtures/candidate-inventory.stub.json
python3 woow-nextcloud-office/test/test-candidate-inventory.py
```

For strict local binding to raw image-manifest bytes, commits, architecture,
package/archive hashes and provenance receipts, see [ARTIFACT-LOCK.md](ARTIFACT-LOCK.md).
That separate gate composes this evaluator unchanged; it rejects this stub and
never turns input consistency into authenticated build/runtime acceptance.

The fixture's all-`a`/all-`b` image digests are format-only placeholders. They
are not existing or locked images. Its matching source/candidate libc/ICU
inventories are deliberately fabricated for unit tests, **not evidence about
bookworm→trixie**. Never relabel this fixture as collected evidence.

## Exit/report contract

| Exit | Status | Meaning |
| --- | --- | --- |
| 0 | `inventory_checks_passed` | The supplied assertions satisfy this offline gate only. |
| 1 | `blocked` | Missing/unknown fields, wrong types, failed checks or inventory drift. |
| 2 | `invalid_input` | Unreadable, invalid, duplicate-key, non-finite or >1 MiB JSON input. |

Missing CLI arguments exit 2 with argparse usage on stderr. Other outcomes emit
JSON to stdout. Every report sets `runtime_verified`, `haos_verified`, and
`production_authorized` to **false**, even with `evidence_kind=collected`.
The tool does not authenticate a collector, inspect image contents, match a
runtime to its digest, or verify that observations are true/fresh. The two labels
`stub` and `collected` describe what the caller claims, not trust levels.

## Schema v1

The checked-in stub is a complete schema example. All fields are mandatory;
unknown object fields and duplicate inventory names are rejected. Booleans
must be JSON booleans, numbers must be integers where required (not booleans),
strings must be nonblank and at most 256 characters. List ordering is irrelevant
for modules/locales/database/collation inventories. Module names are compared
case-insensitively; duplicate case variants are rejected.

Top-level fields:

- `schema_version`: integer `1`.
- `scope`: exactly `isolated-synthetic` (asserted, not independently verified).
- `evidence_kind`: `stub` or `collected`.
- `source_digest`, `candidate_digest`: `sha256:` + 64 lowercase hex digits;
  format-only checks do not replace immutable artifact lock/build evidence.
- `php`, `fpm`, `nginx`, `code`, `postgres`: objects below.

### PHP, FPM, nginx and CODE

- `php.cli` and `php.fpm`: `version` (`8.4.<patch>`, both identical), `modules`
  (nonempty list) and normalized `ini` (only the four checked settings).
  Both SAPIs require the 24 modules in `REQUIRED_MODULES`, including redis,
  apcu, imagick, intl, pdo_pgsql/pgsql and Zend OPcache. Extra modules are allowed.
- Both ini objects require `memory_limit=1024M`, `upload_max_filesize=16G`,
  `post_max_size=16G` as strings. CLI also requires `apc.enable_cli=1`; FPM
  requires `opcache.enable=1`. A future collector must normalize equivalent
  values deliberately rather than copy a full ini containing secrets.
- `fpm`: `binary=php-fpm8.4`, `socket=/run/php/php8.4-fpm.sock`,
  `socket_is_unix=true`, `pid_file=/run/php/php8.4-fpm.pid`, positive integer
  `pid` and `master_pid` (equal), `process_alive=true`, `config_test_exit=0`.
- `nginx`: `config_test_exit=0`, `process_alive=true`, and `fastcgi_socket`
  equal to the expected FPM socket.
- `code`: nonempty `version`, `version_exit=0`, `process_alive=true`,
  `discovery_http_status=200`, `discovery_xml_valid=true`,
  `websocket_http_status=101`, `save_roundtrip=true`, `jail_enabled=true`.
  These are assertions from future tests, not probes performed by this tool.
  An isolated WOPI edit/save needs genuine persisted-content evidence; a 200
  discovery response alone is insufficient. `--version` alone is not startup.

### PostgreSQL source/candidate inventories

`postgres.source` and `postgres.candidate` each contain:

- `version`: PG `16.<patch>`; patch versions need not be identical.
- `libc_version`, `icu_version`: nonempty strings.
- `locales`: nonempty unique list of installed OS locales.
- `databases_complete=true`, `databases`: nonempty list, unique database names.
  Completeness is asserted; an authenticated collector must eventually prove it.

Each database contains `name`, `provider` (`c` libc / `i` ICU), effective
`locale`, `collate`, `ctype`, `recorded_version`, `actual_version`,
`collations_complete=true`, and a nonempty `collations` list. Use database names
only from synthetic fixtures. Each collation contains the same seven scalar
fields as its database row, with a schema-qualified `name`, but no nested list.
Collation provider `d` (database default) is also allowed.

The collector must inventory all relevant database/column/index collations and
normalize effective locale fields, including values inherited by the default
collation. Version strings must be present and recorded=actual. Null/null
versions are accepted only for:

1. libc `C`, `POSIX`, `C.UTF-8` / `C.utf8` locale fields; or
2. provider `d` collations whose effective locale/collate/ctype match their
   parent database. Their version safety is checked on the database row.

No incomplete/empty inventory or unexplained ICU null version is accepted.
A database inventory's normalized libc/ICU/locales and all database/collation
fields must match the candidate inventory, excluding PG patch version. Missing
or extra databases/collations block the gate too. **Any drift blocks**: even if
someone already refreshed recorded_version to actual_version, source/candidate
comparison still detects it. This is intentionally conservative: normal trixie
libc/ICU changes will block until a separately reviewed migration/index-rebuild
and complete rollback workflow provides a justified disposition. There is no
refresh, reindex, ignore-version or waiver flag.

## Tests and remaining gates

Tests use temporary JSON and synthetic observations, mutate required fields,
check failure paths/CLI exits, and guard the evaluator's dependency boundary.
They do not start PHP/FPM/nginx/CODE/PG or validate runtime access permissions.

Still pending: operator-approved APT environment repair; signed dependency
resolution; immutable base/package/artifact lock and built candidate; authorized
runtime collector and true service tests; source/target collation migration and
index rebuild; synthetic NC33→34→35 and complete rollback; ARM; HAOS/Supervisor;
full MCP acceptance and a separately approved production maintenance window.
