Feature flag deterministic rollout evaluator

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator supplies HTTP entry point and interactive page.

Input: flag {key,enabled?,rolloutPercent?,allow?,deny?,rules?} and
subject {id,attributes?}. enabled defaults true, rolloutPercent defaults 0.
Rollout is 0-100 with at most 2 decimal places. allow/deny each contain
0-1000 unique subject ids. rules contains up to 50 ordered rules
{id,attribute,equals,enabled}, using strict scalar equality. Attributes are
up to 50 scalar fields; strings at most 200 characters. Identifiers are
1-64 ASCII letters, digits, underscores or hyphens. Unknown attributes do
not match rules. Every rule is validated even if the flag is disabled.

Precedence: global disabled, deny, allow, first matching rule, percentage.
Output includes decision, reason, matching rule id or null, and bucket.
To derive bucket, begin h=0 and for each ASCII character in key+":"+id set
h=(31*h+characterCode)%10000. Enable when h < round(rolloutPercent*100).
This gives deterministic membership and monotonic rollout expansion.

Worked example: "a:b" yields 97, 3065, 5113. Rollout 51.13 excludes this
subject; 51.14 includes it. "demo:u1" yields 100,3201,9340,9651,9239,6526,2355 (bucket 2355).

Limitations: simple noncryptographic hashing, with no guarantee of uniform
distribution for structured ids. This is not authorization or randomized
experimentation. No remote flags, persistence, secrets, or network.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p48 .; podman run --rm -p 127.0.0.1:8080:8080 p48
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"flag":{"key":"a","rolloutPercent":100},"subject":{"id":"b"}}
Expected highlights: enabled true, reason rollout, bucket 5113.
Supported limitation: noncryptographic bucketing is not an authorization mechanism.
