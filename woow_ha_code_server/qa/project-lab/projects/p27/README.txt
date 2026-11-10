Release Note Grouper

Purpose: Turn supplied synthetic commit messages into grouped release notes and
an intent-based release-increment suggestion. Run: node test.mjs. API: run(meta.example).

Fields: version is a release label up to 64 letters/digits/dots/dashes/underscores,
starting with a letter/digit. commits contains 1–500 {id,message} objects. IDs
are unique, up to 40 letters/digits/dashes, starting with a letter/digit. Messages
are nonblank, up to 4000 characters each / 100000 combined. Unknown keys reject.
Conventional subjects use type(scope)!: description, with optional scope and !.
A ! or a nonempty BREAKING CHANGE:/BREAKING-CHANGE: line marks a breaking change.

Worked example: feat(ui): Add tabs and fix: Correct count group into Features and
Fixes; suggestedBump is minor. refactor(api): Remove legacy with a BREAKING CHANGE:
footer groups into Breaking changes and suggests major. Nonconventional subjects
are preserved under Other. Entries within a group retain their supplied order.
Groups appear in order: Breaking changes, Features, Fixes, Performance,
Documentation, Maintenance, Other. Empty groups are omitted. Maintenance covers
chore/test/build/ci/refactor/style/revert. Features/fixes counts include breaking
entries; each entry appears in exactly one group.

Output includes counts, structured groups, and escaped Markdown. Bump priority:
major for breaking, minor for feat, patch for fix/perf, otherwise none.
Limitations: no Git access, deduplication by content, issue lookup, or API analysis.
Commit declarations determine suggestions; version is a label, not an inferred
next version. Bodies are used only to recognize breaking-change declarations.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p27 .; podman run --rm -p 127.0.0.1:8080:8080 p27
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: breaking footer promotes maintenance.
Input: {"version":"2.0.0","commits":[{"id":"c3","message":"refactor(api): Remove legacy\n\nBREAKING CHANGE: old endpoint removed"}]}
Expected output: {"version":"2.0.0","suggestedBump":"major","counts":{"total":1,"breaking":1,"features":0,"fixes":0},"groups":[{"category":"Breaking changes","entries":[{"id":"c3","scope":"api","description":"Remove legacy"}]}],"markdown":"# Release 2.0.0\n\n## Breaking changes\n\n- **api:** Remove legacy (c3)\n"}
Supported limitation: Commit declarations determine the bump; no API analysis or Git access.
