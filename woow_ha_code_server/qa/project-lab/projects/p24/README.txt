Allowlisted URL Query Workshop

Purpose: Build and parse URLs using only supplied hostnames and query-key
allowlists. No URL is fetched. Run: node test.mjs. API: run(meta.example).

Fields:
- mode: build or parse.
- url: absolute HTTP(S) URL, at most 4096 characters, no credentials, whitespace,
  backslashes or controls. WHATWG URL parsing normalizes scheme/host/path.
- allowedHosts: 1–50 exact lowercase ASCII hostnames (no port, wildcard or IPv6).
  This checks hostname, not port; ports may be present in the URL.
- allowedKeys: up to 50 case-sensitive query keys; names start with a letter and
  contain letters, digits, dot, underscore or dash, at most 64 characters.
- params: required in build mode, forbidden in parse mode. A map of allowed keys
  to string/finite number/boolean, or arrays of up to 20 such values. null or []
  deletes a key. Supplied keys replace all existing values for that key.
All existing keys must pass the allowlist even if params would delete them.

Worked example: build https://example.test/search?lang=en with params
{"q":"a b","tag":["x","y"]}, allowing that host and those keys, produces
https://example.test/search?lang=en&q=a+b&tag=x&tag=y. Build sorts keys stably;
parse preserves the URL query spelling/order. query maps every key to an array,
including singletons and empty values. origin, pathname and raw fragment are
also returned. Repeated values retain order. Malformed percent escapes/UTF-8
and query controls are rejected.

Limits: 1024 characters per value, 200 resulting pairs, 8192 result URL characters.
ASCII/punycode hosts only. Path and fragment are not an allowlist/security policy.
This utility is not a network access control mechanism. No dependencies/network.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p24 .; podman run --rm -p 127.0.0.1:8080:8080 p24
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: parse repeats empty and fragment.
Input: {"mode":"parse","url":"https://example.test/?q=a%2Bb&q=&n=2#section","allowedHosts":["example.test"],"allowedKeys":["q","n"]}
Expected output: {"url":"https://example.test/?q=a%2Bb&q=&n=2#section","origin":"https://example.test","pathname":"/","query":{"q":["a+b",""],"n":["2"]},"fragment":"section"}
Supported limitation: Exact hostname matching only; paths and fragments are not security policies.
