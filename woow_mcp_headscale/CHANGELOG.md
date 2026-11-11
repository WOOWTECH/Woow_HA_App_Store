# Headscale Add-on changelog

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
