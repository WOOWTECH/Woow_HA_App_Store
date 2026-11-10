Static site navigation and offline search index builder

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator supplies the HTTP runtime and interactive UI.

Input: pages (1-100), each with unique path, title, plain-text body, optional
tags and parent path. Paths are / or slash-separated ASCII letters, digits,
underscores and hyphens, with no trailing slash. Parents need not appear
before children; all references must exist and the hierarchy must be acyclic.
Navigation roots and siblings preserve input order. Physical directory
structure does not implicitly determine parents.

Text uses Unicode NFKC normalization and lowercasing. Tokens are contiguous
Unicode letters/numbers. Title occurrences weigh 3, tags 2, body 1. The
inverted index is sorted by term. A query requires all distinct tokens;
scores sum their weights, with lexical path ordering for ties. Empty queries
return no results. Snippets are the first 160 characters of collapsed body
text. Input is not modified.

Worked example: title Alpha, body "alpha beta beta", tag Guide yields
alpha:4, beta:2, guide:2. Searching "ALPHA beta beta" scores 6.

Limits: title 200, body 20000, path 200, query 200 characters; 20 tags of
64 characters; 500000 combined text characters; 10000 distinct index terms.
No crawling, HTML parsing, stemming, fuzzy search, or filesystem writes.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p45 .; podman run --rm -p 127.0.0.1:8080:8080 p45
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"pages":[{"path":"/notes","title":"Notes","body":"Read notes","tags":["notes"]}],"query":"notes"}
Expected highlights: /notes scores 6 (title 3 + tag 2 + body 1); two indexed terms.
Supported limitation: exact normalized token matching only; no stemming or fuzzy search.
