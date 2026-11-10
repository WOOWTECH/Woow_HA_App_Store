Offline RSS 2.0 XML generator

Tests: node test.mjs. API: import {run, meta} from './app.mjs'.
Coordinator provides the standalone server and interactive page.

Input: channel {title,link,description,language?}; items array (0-100).
Each item needs title, absolute HTTP(S) link, publishedAt; guid defaults to
link and description defaults to empty text. Channel language defaults to en.
Times must be real UTC calendar timestamps, exactly YYYY-MM-DDTHH:mm:ssZ.
Titles are limited to 500 characters, links and GUIDs to 2048, descriptions
to 5000. GUIDs must be unique. URL credentials and whitespace are rejected.
Invalid XML characters, including lone surrogates, are rejected.

Output includes XML, itemCount and latestPublishedAt (null for an empty
feed). Articles are sorted newest first, preserving input order for ties.
GUIDs are emitted with isPermaLink=false. Text, including descriptions, is
escaped using XML entities; descriptions are not interpreted as HTML.

Worked example: title "A & B" becomes <title>A &amp; B</title>.
The timestamp 2024-01-01T00:00:00Z becomes
Mon, 01 Jan 2024 00:00:00 GMT. The XML ends with a newline.

Limitations: no fetching, publishing, namespaces, attachments, HTML
sanitization, or date inference. This generates an offline RSS document.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p44 .; podman run --rm -p 127.0.0.1:8080:8080 p44
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Optional maxItems must be an integer 1..100; omit it for no truncation.
All submitted items are validated, sorted newest first (stable input-order ties),
then only the first maxItems are emitted. itemCount and latestPublishedAt describe
emitted items; empty feeds still return 0 and null. No numeric-string coercion.
Example input: {"channel":{"title":"N","link":"https://example.invalid","description":"D"},"items":[{"title":"Old","link":"https://example.invalid/old","publishedAt":"2024-01-01T00:00:00Z"},{"title":"New","link":"https://example.invalid/new","publishedAt":"2024-01-02T00:00:00Z"}],"maxItems":1}
Expected highlights: XML contains only New; itemCount 1, latestPublishedAt 2024-01-02T00:00:00Z.
Supported limitation: maxItems limits output, not validation; input remains capped at 100 items and no feed is fetched or published.
