Semver Compatibility Comparator

Purpose: Compare strict semantic versions and check a deliberately bounded range
language. Run: node test.mjs. API: run(meta.example) from ./app.mjs.

Fields: current and candidate are strict major.minor.patch versions (up to 128
characters), optionally followed by -prerelease and +build identifiers. Numeric
core/prerelease identifiers reject leading zeroes. Core arithmetic uses BigInt.
range is optional; absent produces range=null and satisfiesRange=null.
Supported selectors: exact or =, >, >=, <, <=, ^ and ~, each immediately followed
by a full version. Whitespace joins comparisons with AND; || joins alternatives.
At most eight alternatives, eight selectors each, and 1024 range characters.
Prereleases match only alternatives explicitly mentioning a prerelease with the
same major/minor/patch core. Build metadata never changes version precedence.

Worked example: current=1.4.0, candidate=1.5.2, range=^1.4.0 returns newer,
change=minor, satisfiesRange=true. ^0.2.3 excludes 0.3.0; ^0.0.3 excludes 0.0.4.
~1.2.3 allows patches below 1.3.0. comparison is candidate relative to current;
change identifies the first differing core component, or prerelease, or none.

Limitations: no wildcards, partial versions, v-prefixes, hyphen ranges or package
registry access. A matching range is declared version compatibility, not evidence
of runtime/API compatibility. Unknown input fields are rejected.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p22 .; podman run --rm -p 127.0.0.1:8080:8080 p22
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: zero-major caret excludes next minor.
Input: {"current":"0.2.3","candidate":"0.3.0","range":"^0.2.3"}
Expected output: {"current":"0.2.3","candidate":"0.3.0","comparison":"newer","change":"minor","range":"^0.2.3","satisfiesRange":false}
Supported limitation: No wildcards or partial versions; version ranges do not prove API compatibility.
