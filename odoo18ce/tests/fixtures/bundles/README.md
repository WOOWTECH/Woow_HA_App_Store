# Asset bundle fixtures

Excerpts taken verbatim from the JavaScript bundles the control group serves
(ADR 0003), with the parity plan's 25 applications installed. They exist for
the exact-expression Literal rewrites of ADR 0006: an unmatched `sub_filter`
is a silent no-op — nginx does not complain, no test turns red, the page
renders and only the link is wrong — so a rule may never be written from a
guess about what the bundle says.

Captured 2026-09-22 from Odoo 18.0, through the control group's Public origin:

| File | Bundle | What it holds |
|---|---|---|
| `discuss_invitation_link.js` | `web.assets_backend` | `Thread.invitationLink`, the Discuss channel invitation link |
| `website_page_url_field.js` | `web.assets_backend` | `PageUrlField.setup`, the base shown before a website page's path |
| `website_share_snippet.js` | `web.assets_frontend` | `ShareWidget._onShareLinkClick`, the share snippet's outbound URL |

The same expressions appear unchanged in `web.assets_web`,
`web.assets_web_print`, `web.assets_frontend_lazy` and
`im_livechat.assets_embed_external`; each bundle carries exactly one
occurrence, and no in-Ingress address shares any of the three patterns.

## Re-capturing

The bundles are public, so no login is needed; the asset route redirects a
stale version to the current one:

    curl -sL --compressed -o web.assets_backend.min.js \
      "$ODOO_BASE_URL/web/assets/1/any/web.assets_backend.min.js"

Then cut the region between the anchors the tests assert on
(`tests/test_ingress_browser_built_links.py`) and replace the file here. If an
Odoo upgrade moves one of the expressions, the fixture no longer contains the
`sub_filter` pattern and the test says so — but note the direction of that
guard: it protects the rules in this repository against a **fixture** that has
been re-captured, not against a live bundle that drifted while the fixture sat
still. Re-capture on every Odoo point release.
