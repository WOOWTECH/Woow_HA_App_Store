Path Ignore Rule Explorer

Purpose: Explain ordered ignore rules against a supplied list of relative file
paths. Never traverses or reads the filesystem. Run: node test.mjs. API: run(meta.example).

Fields: paths (up to 200 unique strings) and patterns (up to 100 strings). Each
path/pattern is at most 256 characters. Paths use POSIX / separators; absolute
paths, backslashes, drive/colon notation, controls, empty segments, . and .. reject.
Patterns: * matches zero or more characters within a segment; ? matches one UTF-16
code unit; ** must occupy an entire segment and matches zero or more segments.
Slashless patterns match a basename at any depth. A leading / anchors to the root;
patterns containing / are root-relative. A trailing / means directory descendants
only; supplied paths denote files, so cache/ never excludes a file named cache.
A leading ! re-includes matches; the last matching rule always wins, including
re-inclusion of files below ignored directories. Blank and # comment rules skip.
Dotfiles match normally. Braces, character classes, escaping and embedded ** reject.

Worked example: paths ["src/app.js","build/app.js","build/keep.txt","docs/debug.log"]
and patterns ["build/","*.log","!build/keep.txt"] exclude build/app.js and
docs/debug.log; build/keep.txt is included by the final rule. Each result names
the last matchedPattern and original 1-based matchedRule, or null if unmatched.

Limits: combined estimated matching work may not exceed ten million units.
Dynamic programming bounds wildcard matching. This is a documented small glob
dialect, not a complete Git-ignore implementation; no parent-directory pruning,
symlink awareness, filesystem resolution, normalization or platform-specific paths.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p28 .; podman run --rm -p 127.0.0.1:8080:8080 p28
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: anchored and globstar patterns.
Input: {"paths":["root.log","sub/root.log","src/a.js","src/deep/b.js"],"patterns":["/root.log","src/**/?.js"]}
Expected output: {"results":[{"path":"root.log","ignored":true,"matchedPattern":"/root.log","matchedRule":1},{"path":"sub/root.log","ignored":false,"matchedPattern":null,"matchedRule":null},{"path":"src/a.js","ignored":true,"matchedPattern":"src/**/?.js","matchedRule":2},{"path":"src/deep/b.js","ignored":true,"matchedPattern":"src/**/?.js","matchedRule":2}],"ignored":["root.log","src/a.js","src/deep/b.js"],"included":["sub/root.log"]}
Supported limitation: Small glob dialect only; no filesystem resolution or symlink awareness.
