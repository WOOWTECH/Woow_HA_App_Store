Webhook payload validation and routing preview

Run tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator supplies the HTTP entry point and interactive page.

Input: event with id/type (1-128 characters) and payload object; schema with
properties mapping top-level keys to string, number, integer, boolean, array,
object, or null; optional required list; allowUnknown boolean (default false).
routes is an array of up to 50 named routes, each with eventType or wildcard *.
Each route has up to 20 AND conditions: field, op, value. Operators: strict
eq/neq, exists (boolean), gt/gte/lt/lte (number), prefix (string). Missing
fields fail every predicate except exists:false. Numeric strings are not
coerced. Optional properties are validated when present. All routes are
validated even when their event type does not match.

Worked example: an order.created payload {amount:120,region:"TW"} matches
both amount>=100 and region=="TW" routes in meta.example. Every matching
route is returned in declared order. No match returns disposition unmatched.

Limits: 65536 serialized input characters, 100 schema fields. No recursive
schema validation, signatures, HTTP delivery, deduplication, or persistence.
No actual webhook request is sent. Use synthetic payloads only.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p42 .; podman run --rm -p 127.0.0.1:8080:8080 p42
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"event":{"id":"review-1","type":"note","payload":{"ready":true}},"schema":{"properties":{"ready":"boolean"},"required":["ready"]},"routes":[{"name":"ready","eventType":"note","conditions":[{"field":"ready","op":"eq","value":true}]}]}
Expected highlights: disposition routed and matchedRoutes ["ready"].
Supported limitation: top-level schema validation only; no webhook delivery.
