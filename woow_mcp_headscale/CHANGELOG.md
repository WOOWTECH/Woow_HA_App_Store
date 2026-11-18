# Headscale Add-on changelog

## 0.4.19 — maintenance release (image published and verified)

- Main reason for this release: the admin panel accepts Home Assistant Core 2026.11.2 (PR #120). The administrator check of 0.4.18 accepts Core only up to 2026.11.1, so on Core 2026.11.2 it refuses every admin panel request (the panel says the Core version has not been reviewed, and the add-on log gets one line); MCP endpoints do not use this check and are not affected. In 2026.11.2 the 25 Core contract and adjacent files are byte-identical to 2026.11.1, and Supervisor 2026.11.0 ships the reviewed WebSocket proxy unchanged. Later patches (such as 2026.11.3) and pre-releases stay refused until reviewed.
- Log redaction now applies the PaaS server's rules first and then the add-on's own (PR #98). In the add-on log, credential values in URL query strings show as `***`, and a record whose format string does not match its arguments shows `[redacted: invalid log message]`. In the log and in child output on the diagnostics page, a line whose URL encoding cannot be judged, or where the combined rules would show a part the old rules hid, is replaced as a whole with `[redacted: ambiguous URL encoding]`, and strings over 128 KiB are cut short. Child output also masks `key=` values, so ordinary text such as `cache key: x` is masked too, and a child line whose masking fails shows `line withheld (redaction failed)`. The `[REDACTED]` and `/private_[REDACTED]` forms are unchanged.
- The MCP child on the container's loopback port 3000 now serves only the gateway's own child bearer (PR #94): a direct request inside the container without exactly one `Authorization: Bearer <child token>` header gets HTTP 401 with no body, and the child refuses to start without a valid child token. Requests through port 8081 and the admin panel are unchanged.
- Restore detection (groundwork for multiple profiles; PR #97): after Home Assistant restores this add-on's backup, the first start leaves an empty, owner-only marker file `.restore-detected` in `/data/mcp`, and the restore repair log line counts it (`re-owned N restored entries`). A later version reads and removes it; until then it stays, also in later backups. If the marker cannot be saved, that start logs one line with the reason (an errno name such as `ENOSPC`, or `name in use`); with multi-profile data on disk (none today) the start is refused and retried at the next start. Starts without a restore are unchanged.
- If the MCP child answers `initialize` with an error that contains this add-on's own credentials (the MCP token, the child token, a backend secret or its Basic form), those parts now reach the client as `[REDACTED]`, as every other text the gateway passes on from the child or the backend already did (PR #103). The status code, the other headers and the rest of the text are unchanged (only `Content-Length` follows the new length); an error without credentials is returned exactly as before.
- Gateway request limits aligned with the PaaS server (PR #105): a request body over 64 KiB is read under a byte budget derived at startup from the container's memory limit, or from MemAvailable less 256 MiB when there is none (at least 16 MiB, at most 64 MiB for the add-on's profile). What counts is the larger of the body as received and as forwarded to the add-on's MCP server, which escapes non-ASCII text, so Chinese text counts about twice its size and emoji about three times (with the smallest 16 MiB share, a 6 MiB body of emoji is refused); a Content-Length sent together with Transfer-Encoding is ignored and the bytes that arrive are counted. A large body the budget cannot hold is answered with JSON-RPC error -32003 and `Retry-After: 5` (HTTP 200 under its id when its head or tail shows it, else 503) instead of being processed, and one that sends nothing for 30 seconds is dropped with HTTP 408 (`-32003`, `Connection: close`); the 60-second whole-read limit and its 408 are unchanged. A body that declares more than 16 MiB gets the same HTTP 413 as before, now before any of it is read. A JSON body nested deeper than 64 levels or with more than 200,000 elements is refused before it is parsed (HTTP 200 with `-32602` under its id when its head or tail shows it, else 413); so is a body that is not UTF-8 (UTF-16 and UTF-32 bodies were processed before; invalid UTF-8, and malformed JSON with that much structure, got HTTP 400 before). Requests within these limits are answered exactly as before; each kind of refusal writes one warning a minute.
- Fixed: stopping the add-on could wait for Home Assistant's 30 s stop timeout in rare cases (PR #106).
- dnspython in the MCP child's environment goes from 2.9.0 to 2.9.2 (GHSA-vvf4-9x63-8xvv, CVE-2026-128089, High): 2.9.0's zone-file parser sizes a WKS record's bitmap from an unchecked service number, so crafted zone text can exhaust memory or CPU. Here dnspython is only email-validator's dependency and no zone file is parsed; the update clears the release scanner's block on this fixable High vulnerability. The 0.4.18 image carries 2.9.0.
- This image also carries the groundwork for multiple profiles per add-on (PRs #91, #93, #95, #99, #101–#104, #107, #110, #111 and #114). It stays switched off for this add-on: requests, responses, the admin panel and the files in `/data/mcp` are unchanged apart from the changes listed above.
- Image published and verified on 2026-11-18: `ghcr.io/woowtech/amd64-mcp-headscale:0.4.19` (manifest `sha256:a05e1a35fe3a048590b34fb542a38bd9a2fa2883d5151bd5732903d7c44baed9`), the exact image the GitHub-hosted release route tested (PR #121). HAOS acceptance, the Stable Release and Store distribution remain separate gates.

## 0.4.18 — reviewed output schemas

- Publish the reviewed object output schema for each of the 11 Headscale MCP tools so clients can consume the same metadata declared by the pinned child.
- Preserve all 29 native API operations, input schemas, permissions and backend behavior from 0.4.17.
- Fail closed by omitting output metadata if a future child schema or reviewed source binding drifts.

## 0.4.17 — DNS address fallback release candidate

- Try each validated Headscale DNS address within the bounded connection deadline, so a failed first address does not hide a reachable later one.
- Include the 0.4.16 secret URL Origin restriction in the first candidate built after the DNS fix. Version 0.4.16 is a Stable Release in the Store; its immutable image predates the DNS fix.
- Publish only after exact-image supply-chain gates, Stable Release checks, Store sync and QA Supervisor acceptance.

## 0.4.16 — publish secret URL browser Origin policy

- Publish the Headscale-only Origin restriction after re-building from the fully reviewed source and runtime ledger.
- Preserve native clients without Origin and allow only `https://claude.ai` for the secret URL browser connector.

## 0.4.15 — unreleased image candidate (superseded)

- Accept the existing Claude.ai connector origin and requests without an Origin header on Headscale's secret URL; reject any other or duplicate Origin with HTTP 403 after validating the URL token.
- Leave the Bearer MCP endpoint and all other add-on products' secret URL rules unchanged.
- This candidate image was pushed and scanned but never promoted to Stable Release, Store, or production; the embedded runtime ledger predates its final reviewed correction.

## 0.4.14 — HA Core 2026.11 compatibility candidate

- Review 25 Home Assistant Core contract/adjacent files for 2026.11.0 and 2026.11.1, plus Supervisor 2026.10.5 WebSocket proxy. Add only these two exact Core releases to the admin verifier; later patches and prereleases remain denied.
- Give Headscale its own release version in the shared package, build and registry gates. Other add-ons keep their published 0.4.13 images and version reports.
- Store and HAOS 2026.11.1 acceptance require a new scanned image and Stable Release; this source change alone is not a published 0.4.14 image.

## 0.4.13 — first stable release

- Add a Headscale MCP Add-on with a Home Assistant administrator panel on Ingress 8099, optional bearer-protected MCP on 8081, and a private child on loopback 3000.
- Use the existing 0.4.13 shared management and image base contracts. Headscale has its own slug, image name and Release tag; the seven existing Add-ons keep their 0.4.13 versions and published tags.
- The public amd64 image passed exact-image supply-chain gates and isolated HAOS 2026.10.4 acceptance; Stable Release and Store synchronization followed. It predates Core 2026.11 review, so its management GUI refuses Core 2026.11.x.
