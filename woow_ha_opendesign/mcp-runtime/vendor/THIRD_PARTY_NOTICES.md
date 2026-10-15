# Third-party notices — scoped inventory, release review pending

This is **not** a repository-wide MIT license, legal clearance, or an assertion
that every image dependency has been audited. No root LICENSE is invented here.
The newly authored boundary/packaging is not a copy of the unimported legacy
shared admin/UI; ambiguities in that unimported code do not relicense or block all
new work. Owner authorization for publication still needs explicit confirmation.

## Included runtime sources

| Distribution scope | Source / version | Applicable notices |
|---|---|---|
| Odoo image | `odoo-mcp==1.1.0`, tuanle96/mcp-odoo | MIT, Copyright 2025 Lê Anh Tuấn; full text `docs/provenance/odoo-LICENSE` |
| Odoo Manage image (0.1.0–0.1.4; archived 2026-10-06, no later image) | `mcp-server-odoo==0.7.1`, ivnvxd/mcp-server-odoo | **MPL-2.0**, full text `docs/provenance/odoo-manage-LICENSE`; see source availability below |
| Hermes vendored runtime | legacy app-only snapshot `614ae663fadd91c76972f60017a76d2627bea87e` | MIT, Copyright 2026 WOOWTECH; `apps/hermes/vendor/LICENSE` |
| OpenDesign vendored runtime | same app-only snapshot; original `WOOWTECH/Woow_opendesign_mcp_server@d6d157ab9542cf18515d7168f5c8082c88b11331` | App MIT text preserved in `apps/opendesign/vendor/LICENSE`; original pinned repository has **no LICENSE/NOTICE/COPYING**. Owner must confirm rights covering the imported file before release. Public availability is not permission. |
| EMQX vendored runtime | `WOOWTECH/Woow_emqx_mcp_server@1be17bad5aef6c7b7519686ccbfe1d80762bc10e` | MIT, Copyright 2026 WOOWTECH; `apps/emqx/vendor/LICENSE` |
| LiteLLM vendored runtime | `WOOWTECH/Woow_litellm_mcp_server@4d4190369216a2d068d1100d53406a67a1d81609` | MIT, Copyright 2026 WOOWTECH; `apps/litellm/vendor/LICENSE` |
| n8n child | npm `n8n-mcp==2.91.0`, czlonkowski/n8n-mcp; `ipaddr.js==1.9.1` | MIT package notices retained by `npm ci`; not the n8n backend's license |
| Nextcloud vendored runtime (from 0.1.7) | `WOOWTECH/Woow_nextcloud_mcp_server@4e09c86f8ee66f147a2d227e7ed1eb9d989394a6` (tag v0.1.5), package `nextcloud_mcp_server` | MIT, Copyright 2026 WOOWTECH; `apps/nextcloud/vendor/LICENSE`. Three files (client.py, server.py, tools.py) carry local add-on changes, each with its reason in `docs/provenance/runtime-sources.json`; they are not upstream behaviour |
| EMQX/LiteLLM/Nextcloud child dependency | FastMCP 3.4.5 and fastmcp-slim extras | **Apache-2.0**, preserve package LICENSE and any shipped NOTICE; not MIT |
| Nextcloud child dependencies beyond the EMQX closure | `defusedxml==0.7.1`, `tzdata==2026.5` (lock `apps/nextcloud/uv.lock`; everything else is the reviewed EMQX lock, same versions) | defusedxml: Python Software Foundation License 2 (shipped LICENSE text; its metadata says only `PSFL`, which is not an SPDX id; owner decision 2026-10-08: version-pinned `known_package_licenses` entry `python:defusedxml:0.7.1` = `PSF-2.0` in `packaging/supply-chain-policy.json`); tzdata: Apache-2.0. Both keep their dist-info license files |

Only the selected app code, its vendored license, core, complete shared UI dist and `apps/runtime` are
copied into each image. Shared provenance/notice documents may describe other
products; that does not mean their code is bundled. Wheel/npm installed metadata
and license files are not stripped. Local source changes, exact hashes, guarded
wheel interfaces and reasons are in `docs/provenance/runtime-sources.json` and
`runtime-patches.json`; the OpenDesign clarification is in
`docs/provenance/opendesign-upstream-chain.md`.

## MPL-2.0 covered source availability (Odoo Manage)

The upstream wheel is not edited on disk. The separate source-guarded launcher
changes transport behavior at runtime; distribute the launcher and shared local
helpers with their modification descriptions too. Do not represent these changes
as upstream behavior or relabel covered files MIT.

The exact locked upstream Source Code Form can currently be obtained at:

<https://files.pythonhosted.org/packages/29/dd/c1b67179fc9531c880dd82c00a46295547380108ae5198d6e07eacde1ba9/mcp_server_odoo-0.7.1.tar.gz>

SHA256: `4d3c2a71db22adb9c7e59fe5696600c4c42e0a3414880c5d00ec345c4963c67b`.
The matching wheel hash is recorded in `apps/odoo-manage/uv.lock`.
Recipients must be informed how to obtain covered Source Code Form under MPL-2.0
(section 3.2), including covered modifications, without restricting those rights.
Before distributing an image, the publisher must verify availability and provide
a durable release-linked source bundle/mirror, retain notices, and document the
exact correspondence to the released digest. This file is **not** evidence that
a source bundle was published, nor an invented blanket offer for all dependencies.
The license release gate remains closed pending that review.

## HA capability approval is not publication/license clearance

Path A is now approved **only for the new n8n pilot** (`homeassistant_api: true`);
the other six remain false. This exposes broad Core administrator authority,
including user management and possible indirect Supervisor/host service effects,
not an enforceable role-only scope or permission to perform unrelated HA changes.
The fixed-endpoint, fresh-query, fail-closed verifier and child-token stripping are
implemented and component-reviewed; UI/guard/provider local integration uses owned fake HA transport only.
**HA NOT TESTED; images not built; tool coverage remains partial (184/65/119).**
This permission decision clears no source/license/secret/image/HA/publication gate.
The verifier adds locked websockets15.0.1 (BSD-3-Clause). Updated dependencies still require
whole-image review; local integration is not redistribution/CVE clearance.

## Self-hosted management UI assets

All store images (`packaging/inputs.json`: seven, Nextcloud first built with 0.1.7) build the package-local UI lock using the existing pinned Node base;
only complete dist/assets/licenses are copied, not fixtures or build dependencies.
Fontsource Poppins5.2.7, Outfit5.2.8, Noto Sans TC5.2.9 retain OFL texts;
Yellowtail5.2.8 retains Apache-2.0; MDI7.4.47 retains its package license.
Exact originals and `packages/mcp-admin-ui/NOTICE.txt` are copied to dist/licenses.
esbuild0.25.12 and Playwright1.61.1 are build/test tooling, not runtime services.
These pins/licenses are inventory, not whole-image or public-release approval.

## Packaging/CI scanner tooling (not shipped in runtime images)

- Gitleaks **8.28.0** — MIT (`gitleaks/gitleaks`).
- Syft **1.20.0** and Grype **0.89.0** — Apache-2.0 (`anchore/syft`, `anchore/grype`).
- Existing hash-pinned PyYAML **6.0.3** is MIT CI/parser tooling.

`packaging/scanner-pins.json` records exact public release archives, official
checksum metadata URLs and verified SHA256 values. Tool binaries are downloaded
only into isolated CI/temp directories, never runtime Docker COPY paths. These
pins do not establish that the tools or their dependencies are vulnerability-free.
The executable whole-image policy and unsigned evidence trust level are described
in `docs/operations/hardening.md`; no signed/SLSA claim or license clearance is made.
Manual source/license/publisher gates remain false. Unknown licenses deliberately
fail the new automated gate rather than inventing a repository-wide license.

## Whole-image obligations still to clear

Python, Node, Debian packages, uv build tooling, MCP SDK, HTTPX, sql.js, bundled
n8n metadata and every transitive dependency retain their own licenses. Base
image digest pinning is integrity evidence, not a CVE/redistribution review.
Produce a per-image dependency/license SBOM and collect required notices/source
obligations before clearance. uv/npm caches, tests, credentials, backups and Git
history are not runtime artifacts. This inventory cannot replace source/history,
image-layer/config and documentation secret review.
