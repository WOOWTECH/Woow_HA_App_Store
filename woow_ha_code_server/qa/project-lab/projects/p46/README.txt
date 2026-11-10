Backup manifest integrity verifier from supplied hashes

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator provides standalone HTTP runtime and the interactive page.

Input: expected and actual arrays, each 0-1000 entries {path,size,sha256}.
Paths are unique case-sensitive relative ASCII paths, up to 240 characters,
using letters, digits, dots, underscores, hyphens and slash separators.
Absolute paths, empty segments, backslashes and . or .. segments are rejected.
size is an integer byte count 0-1e12. sha256 is exactly 64 hexadecimal digits;
digest comparison is case insensitive. allowExtra defaults to false.

Output includes a sorted union of file paths, each classified as matched,
missing, changed or extra. Changed files list size and/or sha256 issues.
Summary counts describe the comparison. valid requires no missing/changed
files and no extras unless allowExtra is true.

Worked example: the supplied size 3 and SHA-256
ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
match the same metadata for notes.txt. Changing only its size produces
status changed with issues ["size"] even if the supplied hashes match.

Limitations: compares supplied metadata only; never reads files, computes
file hashes, restores backups, or proves that supplied hashes are truthful.
No network or filesystem side effects. Synthetic manifest prototype.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p46 .; podman run --rm -p 127.0.0.1:8080:8080 p46
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"expected":[{"path":"empty.txt","size":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}],"actual":[]}
Expected highlights: valid false, missing 1, empty.txt status missing.
Supported limitation: supplied hashes are compared, not recomputed from files.
