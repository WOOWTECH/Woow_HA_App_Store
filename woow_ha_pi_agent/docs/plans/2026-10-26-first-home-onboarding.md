# HA first-home onboarding implementation plan

**Goal:** A fresh, untouched Pi Web homepage opens its existing unfinished Omnigent setup conversation, including on phones, without taking over another selection or creating a conversation.

**Architecture:** Keep the verified official Pi Web 0.12.0 compiled client/SSR patch and asset-reference checks. Add a client layout effect that reads a minimal same-origin HA bridge projection and navigates once to the saved session. The bridge checks the installed plugin's registered/active lifecycle plus regular same-UID 0600 local state/onboarding files. It never calls runtime status or remote probes for eligibility. Missing cold-boot state can wait but cannot open anything; unreadable/unknown/completed/disabled state stops. No startup worker, credential reuse, provider call, session creation or transcript rewrite is added.

**Tech stack:** Node.js, official compiled Next.js artifact, existing HA bridge/Ingress proxy, Playwright.

## Agreed test boundaries

- Real compiled homepage in fresh desktop/mobile browser contexts behind the repository's Ingress rewrite rules.
- Existing bridge public read interface and HTTP request guards.
- Existing byte/hash/atomicity/idempotence tests for the compiled patch.

## Execution

1. Extend `tests/omnigent-native-browser.mjs` with two SDK-saved fixture conversations (Omnigent and Paseo). Assert zero-click exact Omnigent selection and visible setup instructions, unchanged original transcript bytes and file count, no creation/provider request; run against current patch and retain the failure.
2. Add minimal guarded onboarding projection to `bridge.mjs` and same-origin read-only endpoint to `server.mjs`, first testing disabled/unregistered/completed/missing onboarding exclusions.
3. Add `patches/omnigent-first-home.mjs`, serialize it into the verified client AppShell mount, preserving the existing patch's reverse validation and cache-busted references. Fail closed on explicit URL, saved tab/workspace/terminal selection, storage failure, interaction/draft, malformed or absent session, and failed fetch. Remember a successful automatic navigation per tab and Ingress scope. Use native URL restoration; never create a replacement session or rewrite history.
4. Extend browser regression cases for exclusions, delayed-response input/click races, once/back behavior, and exact Omnigent ID when Paseo exists. Run existing compiled settings/fallback/Ingress/lifecycle checks.
5. Prepare an unmerged HA candidate. Public plugin 0.3.16 tag/release remains on HOLD until Fermat's native/combined adapter follow-up merges. Pin the final official plugin archive only after publication; recheck the next HA version before bumping.

## Official QA after coordinated release

Keep the original offline 0.15.2 host/onboarding untouched until the official Supervisor `backup:true` upgrade. Verify automatic restoration and add-on/VM restart persistence first. Save receipts and check capacity, disconnect only the owned host through the UI, then officially uninstall/reinstall only this task's add-on for fresh zero-click homepage/wizard acceptance. No backup restore, login-flag fabrication or server database removal. Cleanup follows all tests.
