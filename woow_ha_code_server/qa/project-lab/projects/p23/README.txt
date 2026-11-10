Synthetic Environment Template Validator

Purpose: Validate synthetic variable strings against a supplied .env-style
schema. This app never reads process.env or any files. Use synthetic data only.
Run: node test.mjs. API: run(meta.example) from ./app.mjs.

Fields: template is a nonempty string up to 30000 characters / 300 lines / 200
variables. values is an object with up to 200 string values, each up to 4096
characters and 100000 combined characters. Names use letters, digits and
underscore, may not start with a digit, and are at most 64 characters.
Assignments are NAME=value; optional export prefixes, blank lines and full-line
comments are supported. Blank defaults (including whitespace-only quoted values)
make a variable required. Other defaults make it optional. Single-quoted defaults
are literal; double-quoted defaults use JSON string escapes. Inline comments
follow a quoted value or begin at # after whitespace in an unquoted value.
Variable expansion and shell evaluation are never performed.

Worked example: template APP_HOST= followed by APP_PORT=8080, with values
{"APP_HOST":"demo.local"}, is valid and resolves APP_PORT to "8080".
missing lists absent required variables; empty lists blank supplied required
variables; unexpected lists undeclared names. Any of those makes valid=false.
resolved contains accepted supplied/default values; unresolved required values
are omitted. Optional defaults may be overridden by an empty supplied string.
Required/missing/empty retain template order; unexpected names are sorted.

Malformed templates, duplicate names, unsafe property names and non-string
values throw useful errors. Limitations: this is a small schema dialect, not a
shell interpreter or complete dotenv implementation. NUL is rejected. No real
credentials should be entered; synthetic resolved values appear in the output.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p23 .; podman run --rm -p 127.0.0.1:8080:8080 p23
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: missing empty and unexpected are distinguished.
Input: {"template":"A=\nB=\nC=fallback","values":{"A":"  ","EXTRA":"demo"}}
Expected output: {"valid":false,"required":["A","B"],"missing":["B"],"empty":["A"],"unexpected":["EXTRA"],"resolved":{"C":"fallback"}}
Supported limitation: Synthetic template dialect only; no variable expansion or shell evaluation.
