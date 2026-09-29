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

Captured 2026-09-28 the same way, for the Ingress prefix rewrite of issue #170:

| File | Bundle | What it holds |
|---|---|---|
| `website_editor_snippet_thumbnail.js` | `web_editor.assets_wysiwyg` | `registerTemplate("web_editor.SnippetsMenu", ...)`, the Blocks panel's OWL template, which draws each tile with `t-attf-style="background-image: url({{snippet.thumbnailSrc}});"` |

Odoo 18 appends its OWL templates to the bundle unminified, after the
JavaScript, as `registerTemplate(<name>, <source path>, <template>)` with the
last two arguments written as template literals — so a template is served
through the same Ingress asset location as the code, and an exact-expression
rewrite can reach it. The excerpt is that whole call, because the test parses
its third argument as XML to prove the rewritten attribute is still
well-formed.

`url({{snippet.thumbnailSrc}})` was measured on 2026-09-28 across every bundle
the control group serves on that route. Only `web_editor.assets_wysiwyg` — the
bundle the website editor loads lazily — carries it, once. `web.assets_backend`,
`web.assets_web`, `web.assets_web_print`, `web.assets_frontend`,
`web.assets_frontend_lazy`, `web.assets_frontend_minimal`,
`web.assets_backend_lazy`, `web.report_assets_common`, `website.assets_wysiwyg`,
`website.assets_editor`, `web_editor.assets_media_dialog`,
`mass_mailing.assets_wysiwyg` and `im_livechat.assets_embed_external` carry it
zero times. `website.SnippetsMenu` (in `website.assets_wysiwyg`) does not repeat
the tile: it is a `t-inherit` patch over this template, so it takes the rewritten
attribute with it.

Captured 2026-09-28 the same way, for the `location` writes of issue #174:

| File | Bundle | What it holds |
|---|---|---|
| `action_menu_url_item.js` | `web.assets_web` | `ActionMenus.onItemSelected`, which runs `browser.location=item.url` for a cog-menu item that carries a `url` and no `action` — the invoice **Download > PDF** item |
| `act_url_self_target.js` | `web.assets_web` | `_executeActURLAction`, whose `target==="self"` branch runs `browser.location.assign(url)` |
| `home_client_action.js` | `web.assets_web` | the `home` client action, which builds `"/"+location.search` and runs the identical `browser.location.assign(url)` |

Measured on 2026-09-28 across every bundle the control group serves on that
route. `browser.location=item.url` occurs once and `browser.location.assign(url)`
twice — the `self` branch and the `home` action — in `web.assets_web`,
`web.assets_backend` and `web.assets_web_print`, and zero times in
`web.assets_frontend`, `web.assets_frontend_lazy`, `web.assets_frontend_minimal`,
`web.assets_backend_lazy`, `web.report_assets_common`, `web_editor.assets_wysiwyg`,
`website.assets_wysiwyg`, `website.assets_editor` and
`im_livechat.assets_embed_external`. The three excerpts above are byte-identical
in all three bundles that carry them, so one is captured from `web.assets_web`
and stands for the others.

Two other `location` writes share the neighbourhood and are deliberately left
alone: `browser.location.assign(_url.href)` and `browser.location.assign(href)`
(the router's `redirect()`, whose callers pass literals the shipped prefix rules
already cover) and `window.location.assign(response.url)` (session expiry, an
absolute URL). Neither matches either pattern.

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
