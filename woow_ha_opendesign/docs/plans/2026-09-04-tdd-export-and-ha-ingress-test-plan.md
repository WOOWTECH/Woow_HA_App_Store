# TDD export and HA Ingress test plan

**Status:** approved test strategy; implementation has not started  
**Date:** 2026-09-04  
**Primary seams:** export/download behaviour and real authenticated HA Ingress use  
**Release policy:** automated tests gate publication; human HA acceptance is post-release and must complete within 24 hours.

## Decisions confirmed with the product owner

| Decision | Value |
| --- | --- |
| Primary test seams | (3) Export/downloads; (5) real Cloudflare → Home Assistant → sidebar Ingress journey |
| Real-session policy | Post-release, not a publication blocker |
| Test design input | One deterministic, version-controlled minimal fixture |
| Visual checks | Contract checks always; pixel-golden checks nightly and manually dispatched |
| Golden tolerance | Changed pixels ≤0.1% per image and no connected changed region larger than 16×16 px |
| PR blocking budget | 15 minutes wall-clock |
| Human acceptance browsers | Chrome/Chromium desktop only |
| Human-acceptance SLA | Complete within 24 hours of each release |

## Scope and seams

Tests must assert observable behaviour through these public interfaces only. They must not call, stub, or assert private functions in `ha-export-bridge.js`, `headless-renderer.mjs`, or the upstream OpenDesign implementation.

1. **Export HTTP/download seam.** A client submits the documented project export request to the add-on's HTTP API or uses the OpenDesign export UI. The test receives a downloaded file or error response.
2. **HA Ingress browser seam.** A Chromium user opens the authenticated Sidebar route. The browser observes pages, routes, downloads, and network requests after HA's ingress prefix is applied.
3. **Renderer process boundary.** The add-on image runs Chromium to create a file. This is tested through the real exported artefact and the public endpoint, not by asserting renderer call order.

Out of scope for this plan: provider/model generation quality, editable PPTX support (it is intentionally rejected), mobile browsers, Safari/Firefox, and storage of BYOK credentials. Existing security and persistence coverage remains required but is not expanded except where an export test needs it.

## Deterministic export fixture

Add one self-contained fixture, for example `tests/fixtures/export-deck.html`. It must have no network dependency and must use only styles embedded in the document. Its independently specified content is:

- document title: `OpenDesign 匯出驗證 🎨`;
- exactly two `<section class="slide">` elements, each 640×360 CSS pixels;
- slide 1 has an opaque `#165DBA` background and the literal text `第一張 / Slide one`;
- slide 2 has an opaque `#AA3333` background and the literal text `第二張 / Slide two`;
- a fixed slide-number label (`1 / 2`, `2 / 2`), no clock, random value, animation, remote image, web font, or responsive breakpoint.

The fixture is a specification, not an implementation-derived expected value. Expected page count, slide count, text literals, colours, and dimensions are known constants in tests. The fixture must be seeded through the public project-file API in a fresh named Docker volume for each lane; lanes never share `/data`, a container, port, output directory, browser profile, or project identifier.

## Mandatory export contract matrix

Each row is a distinct vertical TDD slice. A single test has one externally visible claim and names that behaviour rather than an internal mechanism.

| Slice | Public action | Independent assertions | Required negative/edge case |
| --- | --- | --- | --- |
| HTML | Export/download fixture as HTML | non-empty download; UTF-8; both literal text strings; two slide sections | malformed/unknown file request returns the documented failure and creates no download |
| ZIP | Export/download fixture as ZIP | `PK` signature; archive opens; expected HTML/asset entries; every archive entry is relative and remains within the archive root | archive contains no `..`, absolute, or symlink escape entry |
| PDF | Export fixture as PDF | `%PDF-` header; parser accepts it; exactly 2 pages; extracted literal text on the expected pages | missing file/export failure returns a non-success result, never a partial PDF |
| PNG | Export full deck as PNG | PNG header/IHDR; width ≥640, height ≥720; representative top/bottom pixels match blue/red within RGB ±3 | invalid image format is rejected before a file is emitted |
| JPEG | Export full deck as JPEG | JPEG SOI/SOF; width ≥640, height ≥720; decoder can load image | invalid image format is rejected before a file is emitted |
| screenshot-PPTX | Export deck as screenshot PPTX | ZIP opens; `[Content_Types].xml`; exactly two `ppt/slides/slide*.xml`; each slide relates to a screenshot image | malformed project returns a documented error and no PPTX |
| editable PPTX | Request editable PPTX | request fails with the stable `Editable PPTX is unsupported` message and no output bytes | the same assertion is retained for both direct HTTP and UI pathways when applicable |

For PDF, use an independent parser such as `pdfinfo` plus a text extractor; do not merely look for a string in raw PDF bytes. For image formats, use a decoder or a deliberately small independent parser, not the renderer's own output metadata. For PPTX, inspect the ZIP with a standard ZIP reader and the Open Packaging Convention entries; do not infer slide count from the implementation response.

## Golden-image policy

Nightly and manually dispatched visual jobs generate PDF page rasters, full-deck PNG/JPEG, and each screenshot image embedded in the PPTX. HTML and ZIP are excluded from pixel comparison because their contract is structural.

The golden environment is one pinned Linux runner/Chromium version, fixed viewport, device scale factor, locale, timezone, colour scheme, font set, and animation-disabled mode. A `golden-manifest.json` records fixture checksum, Chromium version, renderer arguments, image size, baseline SHA-256, and update rationale.

A pixel is changed when alpha differs or any RGB channel differs by more than 3. The result fails when either:

- changed pixels are more than 0.1% of all pixels; or
- an 8-neighbour connected changed region has a bounding box larger than 16×16 pixels.

The job uploads baseline, actual, absolute diff, overlay, mismatch count, connected-component report, and an HTML summary as artifacts. CI never rewrites baselines. Baseline updates require a reviewed PR containing the output artifacts and a human explanation of the intended visual change.

## TDD protocol for every slice

1. Record the public seam, exact behaviour, known-good expected result, and intended test file before code is changed.
2. Add only one test for that behaviour. Run its narrow command and preserve the failing output as the Red evidence in the PR/commit notes. For a defect that already has an implementation, use a minimal failure fixture or a controlled mutation that makes the new assertion fail; do not claim Red based on an imagined failure.
3. Implement only the smallest production change that makes that one test Green. Do not add anticipatory options, abstractions, or unrelated refactors.
4. Run the narrow test again, then its export-format suite, then the complete PR gate. A failure in a later suite returns to a new vertical slice; it is not hidden by broadening a tolerance or retrying blindly.
5. Refactoring is a separate review activity. It may start only after all affected tests are Green and requires another complete gate.

Tests may mock only external boundaries that cannot be made deterministic (wall clock, random source, a deliberately controlled Supervisor-style proxy). They must not mock own modules, Chromium rendering, OpenDesign export endpoints, or download construction. Network-free fixtures are preferred to mocking remote assets.

## Proposed test layout

The existing `tests/container-smoke.sh`, `tests/container-renderer-e2e.mjs`, and `tests/container-ingress-browser-e2e.mjs` already cover important portions of the public seams. Split/add tests by behaviour without deleting their existing coverage:

```text
tests/
  fixtures/export-deck.html                 # deterministic source fixture
  export-http-contract-e2e.mjs              # HTML, ZIP, PDF, PNG, JPEG, PPTX public requests
  export-archive-contract.test.mjs          # archive inspection helpers/contracts
  export-golden-e2e.mjs                     # generate/raster/extract and compare baselines
  container-ingress-browser-e2e.mjs         # retain; make user navigation/download claims explicit
  container-renderer-e2e.mjs                # retain renderer boundary, limits, SSRF, editable rejection
  container-smoke.sh                        # container lifecycle and orchestration only
  golden/
    manifest.json
    pdf/page-1.png
    pdf/page-2.png
    png/full-deck.png
    jpeg/full-deck.png
    pptx/slide-1.png
    pptx/slide-2.png
  HA_RELEASE_ACCEPTANCE.md                  # human runbook and evidence template
scripts/
  run-export-lanes.sh                       # creates isolated containers/volumes and collects results
  compare-golden-images.mjs                 # independent diff/report tool
```

`container-smoke.sh` should seed the fixture through the public API and invoke the separate suites. It should not grow more inline parsing or business assertions. The separate test files preserve useful failure locality and permit targeted Red/Green commands.

## Parallel execution plan

The objective is a 15-minute PR critical path, not maximum unsafe concurrency. Real Chromium renderers are CPU/memory intensive, so browser rendering has a concurrency limit of one on a shared GitHub runner. Independent low-cost work runs concurrently with image construction.

| Lane | Isolation | PR/release | Nightly/manual | Target |
| --- | --- | --- | --- | --- |
| Static validation/security | no container; read-only source | yes | yes | ≤2 min |
| Image build + lifecycle smoke | one amd64 image, dedicated container/volume | yes | yes | ≤10–12 min |
| HTML/ZIP contract | dedicated container/volume after image build | yes | yes | ≤3 min |
| PDF contract | dedicated container/volume; Chromium semaphore 1 | yes | yes | ≤4 min |
| PNG/JPEG contract | dedicated container/volume; Chromium semaphore 1 | yes | yes | ≤4 min |
| screenshot-PPTX/rejection | dedicated container/volume; Chromium semaphore 1 | yes | yes | ≤4 min |
| Ingress browser E2E | dedicated proxy/browser profile; Chromium semaphore 1 | yes | yes | ≤6 min |
| Golden visual diff | isolated pinned runner/image | no | yes | ≤15 min |
| aarch64 build/smoke | QEMU/arm64 runner, independent image | build remains existing policy; full runtime smoke nightly | yes | set by nightly budget |
| Authenticated HA acceptance | real Chrome session | no | after every release | ≤24 h SLA |

On a single runner, build the amd64 test image exactly once, then pass it to the serial Chromium lanes; do not run multiple renderer Chromiums in parallel merely to make the workflow graph look parallel. Static validation and non-rendering contracts can run while Buildx executes. If distinct GitHub jobs are used, they must not exchange an unbounded Docker-image artifact; either use an explicitly measured registry/cache strategy or retain one image-owning test job. The 15-minute cap is verified by workflow timing, not assumed.

Each lane owns only its fixture/test/report files. A single integration owner changes shared scripts, the Dockerfile, workflow YAML, or exporter code after the lane-level Red evidence has been reviewed. This prevents parallel agents from editing the same files or causing false positives through shared container state.

## CI workflow changes

1. Keep `validate` independent and start it immediately.
2. Build the amd64 smoke image once after checkout. Start `validate` in parallel with that build job/step.
3. After the image is ready, run export contract commands with unique names, random ports, fresh named volumes, and a renderer semaphore of one. Collate JUnit/TAP output and all exported files as artifacts on failure.
4. Keep release preflight and both immutable architecture publishes dependent on successful blocking tests.
5. Add a scheduled (`cron`) and `workflow_dispatch` golden workflow. Dispatch inputs: git ref, image tag, and `update_baseline=false`; the update path is a separate review-only maintenance operation, never the default.
6. Add a release workflow step that opens or updates an issue/checklist containing the version, image digest, 24-hour due time, human runbook, and evidence fields. It must not access, request, or log any BYOK key.
7. Keep current non-release architecture builds. Move full aarch64 runtime export smoke to nightly unless measured runtime stays inside the 15-minute critical path; a mere cross-platform image build is not evidence of a functioning renderer.

## Post-release authenticated HA acceptance runbook

The assigned tester completes this within 24 hours of GitHub release publication, using Chrome/Chromium desktop and a real Cloudflare Access + Home Assistant session.

1. Record release tag, add-on version, GHCR image digest, HA version, OS, Chrome/Chromium version, timestamp, and tester identity/role.
2. From the Home Assistant Sidebar, open OpenDesign. Do not navigate directly to the add-on container port or synthesize an ingress token.
3. Hard-refresh. Verify the home page loads. Open Settings and Design systems, verify both visible content and logical URLs, use Back/Forward, then reload a subpage.
4. Restart the add-on and repeat the Sidebar open once.
5. The tester enters their own BYOK key locally. Never copy it into the issue, console, localStorage export, screenshots, HA options, `/data`, or CI.
6. Use a non-sensitive design to perform one real generation and export HTML/ZIP/PDF/PNG/JPEG/screenshot-PPTX. Verify Chrome downloads each requested artifact and local viewers can open them. Request editable PPTX once and verify the expected rejection.
7. Attach only non-sensitive evidence: de-identified screenshots, success/failure table, filenames, SHA-256s, browser/HA/network console errors relevant to the defect, and the exported-format validation results. Do not attach customer content unless separately approved.
8. If acceptance fails, file a bug with the release version and non-sensitive reproduction steps. First add a deterministic failing regression test at the corresponding public seam; then perform the next Red → Green slice. A hotfix release does not waive the acceptance requirement.

## Exit criteria and evidence

A code change is eligible for release only when every blocking command is freshly executed against the candidate commit/image, exits zero, and has artifacts/logs showing the asserted results. The release note links the successful workflow run. The post-release acceptance issue is either completed with evidence within 24 hours or remains explicitly open/escalated; its absence never gets silently treated as success.

Before reporting any slice, CI workflow, or release as complete, run the exact relevant command, inspect the exit status and failure count, and cite that fresh output. Agent reports, previous workflow runs, and a successful build alone are not verification.

## Implementation order

1. Add the fixture and refactor current smoke orchestration without changing export behaviour; prove the initial moved/added tests still catch an intentionally broken fixture assertion.
2. Split HTML/ZIP, PDF, PNG/JPEG, and PPTX/rejection into independent public-contract tests, one Red/Green vertical slice at a time.
3. Make the ingress E2E download assertions explicit and preserve route/proxy transport coverage.
4. Add artifact collection and renderer concurrency control; measure the PR critical path and adjust only by removing duplicated work or moving exhaustive coverage nightly.
5. Add the golden manifest, comparator, baseline-review process, nightly/manual workflow, and artifact report.
6. Add the release acceptance checklist automation and execute the first manual acceptance within 24 hours of the next release.
7. Independently review test seams, Red evidence, tolerance policy, and workflow timing; run the complete candidate gate before merging.
