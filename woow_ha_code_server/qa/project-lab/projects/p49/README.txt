Redaction-safe structured audit report

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator supplies HTTP runtime and interactive page. Use synthetic data.

Input: events (0-200), each with at, actor, action, resource, outcome and
optional details object. at is real UTC YYYY-MM-DDTHH:mm:ssZ. actor is
1-200 characters and is never returned. Actions: create/read/update/delete/
login/deploy. Resources: record/account/service/file/policy. Outcomes:
success/failure/denied. All other top-level event fields are omitted.

Actors receive report-local aliases actor-1, actor-2 in first-seen order.
Every non-null scalar detail value, including numbers and booleans, becomes
[REDACTED]. Null and container shapes remain. A fixed set of generic keys is
preserved: before, after, changes, count, enabled, reason, metadata, field,
email, token, password, secret, authorization, apiKey, value, items, status.
Every other key becomes field_1, field_2, ... within its object, preventing
identifiers embedded in keys from leaking. No user-defined redaction bypass.
Validation messages never embed supplied values.

Output contains totals, actor count, outcome/action counts, redacted-value
count, and sanitized records in input order. Worked example: two events by
operator-a share actor-1. {email:"sample",count:2} becomes
{email:"[REDACTED]",count:"[REDACTED]"} with redactedValues=2.

Bounds: detail depth 8, total detail nodes 20000, 100 entries per container,
128-character keys, 2000-character strings. No network or persistence.
Limitations: deliberately masks all detail scalars; timestamps, enum fields,
structure, counts and within-report actor correlation remain visible. This
is a synthetic reporting prototype, not a production privacy certification.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p49 .; podman run --rm -p 127.0.0.1:8080:8080 p49
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"events":[{"at":"2024-01-01T00:00:00Z","actor":"reviewer","action":"read","resource":"file","outcome":"success","details":{"count":3,"status":null}}]}
Expected highlights: actor-1, count masked, status null, redactedValues 1.
Supported limitation: structural metadata and report-local actor correlation remain visible.
