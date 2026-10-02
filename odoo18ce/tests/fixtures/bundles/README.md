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

Captured 2026-09-30 the same way, for the HTML editor's content round trip of
issue #210:

| File | Bundle | What it holds |
|---|---|---|
| `html_editor_attach_content.js` | `web.assets_backend` | `Editor.attachTo`, whose `editable.innerHTML=fixInvalidHTML(this.config.content)` is where an html field's stored value becomes DOM |
| `collaboration_reset_from_server.js` | `web.assets_backend` | `resetFromServerAndResyncWithPeers`, the collaboration plugin's stale-document reset, which assigns the ORM value straight to `editable.innerHTML` — the second render site, and one a `'collaborative': true` field reaches |
| `html_field_update_value.js` | `web.assets_backend` | `HtmlField.updateValue`, the one place the field writes the record — every save path reaches it, and `lastValue` is computed from the same argument |
| `html_field_commit_changes.js` | `web.assets_backend` | `HtmlField._commitChanges`, whose `comparisonValue` is read off the clone and compared with `lastValue` on the urgent path |
| `image_processing_relative_src.js` | `web.assets_backend` | `loadImageInfo`'s preamble, which turns an `<img>`'s `src` into the `relativeSrc` it sends to `/html_editor/get_image_info` |

Measured on 2026-09-30 across every bundle the control group serves on that
route. Each row is the `sub_filter` source as the template ships it, byte for
byte — a shortened stand-in would be a count of a different pattern:

| Pattern | Bundles that carry it, once each | Bundles that carry it zero times |
|---|---|---|
| `editable.innerHTML=fixInvalidHTML(this.config.content)` | `web.assets_backend`, `web.assets_web`, `web.assets_web_print` | the twelve others below |
| `if(content){this.editable.innerHTML=content;}` | the same three | the twelve others below |
| `async updateValue(value,{changeId}={changeId:this.lastChangeId}){this.lastValue=normalizeHTML(value,this.clearElementToCompare.bind(this));` | the same three | the twelve others below |
| `const comparisonValue=el.innerHTML;` | the same three | the twelve others below |
| `const relativeSrc=srcUrl.pathname;` | the same three, plus `web.assets_frontend`, `web.assets_frontend_lazy` and `web_editor.assets_wysiwyg` | the nine others |

The twelve others are `web.assets_frontend`, `web.assets_frontend_lazy`,
`web.assets_frontend_minimal`, `web.assets_backend_lazy`,
`web.report_assets_common`, `web_editor.assets_wysiwyg`,
`web_editor.assets_media_dialog`, `website.assets_wysiwyg`,
`website.assets_editor`, `mass_mailing.assets_wysiwyg`,
`im_livechat.assets_embed_external` and `html_builder.assets`. So the first
four rewrites reach the backend web client and no frontend or website-editor
bundle.

The fifth row, `const relativeSrc=srcUrl.pathname;`, reaches more, and that is
wanted: `loadImageInfo` exists twice in Odoo 18, once in `html_editor`
(`docHref.startsWith("about:")`, calling `/html_editor/get_image_info`) and
once in the legacy `web_editor` (`docHref==="about:srcdoc"`, calling
`/web_editor/get_image_info`). The pattern is the one line they share, both
routes are the same controller method, and
both need the same root-relative path — so one rule covers the backend and the
frontend editor alike. Only the `html_editor` variant is captured here, since
it is the one the To-do form loads; `test_the_fixtures_are_verbatim_regions`
pins the excerpt's ends so a drift in either shows up.

The first four excerpts are byte-identical in the three bundles that carry
them, so each is captured from `web.assets_backend` and stands for the others.
Each is a whole method or a self-contained preamble, because the test executes
it: `attachTo` and `resetFromServerAndResyncWithPeers` against an editable that
reports what the browser would fetch, `updateValue` against a record stand-in
that reports what would be stored, `_commitChanges` on its urgent path to count
the writes, and the preamble against a fake `<img>`.

Captured 2026-09-28 the same way, for the `/@` links of issue #211, and
re-derived on 2026-09-30 from the pinned `.deb` (`ODOO_DEB_VERSION`
18.0.20260930) through Odoo's own serve path -- `transpile_javascript()` then
`rjsmin.jsmin()` -- which reproduces both excerpts byte for byte, so the
capture is current for the Odoo this image pins:

| File | Bundle | What it holds |
|---|---|---|
| `website_frontend_to_backend_edit.js` | `web.assets_frontend_minimal` | `redirect.js`'s whole `DOMContentLoaded` listener, which builds the "Edit this content" button's `href` and the two `window.location.replace` addresses beside it |
| `website_link_popover_preview.js` | `website.assets_wysiwyg` | `LinkPopoverWidget._onPreviewLinkClick`, the website editor's "open this link in the backend" handler |

Measured 2026-09-30 across the fourteen bundles the control group serves on
that route:

| Pattern | Bundles that carry it, once each | Bundles that carry it zero times |
|---|---|---|
| ``currentUrl.pathname=`/@`` | `web.assets_frontend_minimal`, `web.assets_frontend`, `website.assets_wysiwyg` | the eleven others below |
| `!currentUrl.pathname.startsWith('/@/')` | `website.assets_wysiwyg` | the eleven others, plus `web.assets_frontend_minimal` and `web.assets_frontend` |

The eleven others are `web.assets_backend`, `web.assets_backend_lazy`,
`web.assets_frontend_lazy`, `web.assets_web`, `web.assets_web_print`,
`web.report_assets_common`, `web_editor.assets_wysiwyg`,
`web_editor.assets_media_dialog`, `website.assets_editor`,
`mass_mailing.assets_wysiwyg` and `im_livechat.assets_embed_external`.
`web.assets_frontend` carries the builder because
`web.assets_frontend_minimal` is part of it; `web.assets_frontend_lazy`
removes `redirect.js` again and so carries neither pattern. The two excerpts
are byte-identical wherever they occur, so each is captured from one bundle
and stands for the others -- which is what lets a single `sub_filter_once off`
rule serve all three sites.

Two other `/@` occurrences in those bundles are **not** link builders and no
rule touches them: `web.assets_backend`, `web.assets_web` and
`web.assets_web_print` carry `_isTopWindowURL`'s `pathname.startsWith('/@/')`,
a classifier for the website editor's iframe rather than a URL being built,
and several bundles carry an `@mediapipe` CDN path. Odoo's two server-side
`f'/@{action["url"]}'` builders (`website_sale`'s invoice and sale-order
actions) produce a canonical `/@/...` that reaches `browser.location.assign`
and is prefixed once by the issue #174 rule above.

The first excerpt is the whole listener and the second the whole method,
because the tests execute them: the listener against a document whose
`.o_frontend_to_backend_edit_btn` is an anchor with a real `href` accessor --
so the Runtime shim's own wrapper decides the address -- and the method
against a link popover driven with one target.

Derived 2026-10-01 from the pinned `.deb` (`ODOO_DEB_VERSION`
18.0.20260930) through Odoo's own serve path, for the readonly html field of
issue #237:

| File | Bundle | What it holds |
|---|---|---|
| `html_viewer_iframe_content.js` | `web.assets_backend` | `HtmlViewer.updateIframeContent`, the whole method — the render site of the `hasFullHtml`/`cssAssetId` path, which picks `documentElement` or `#iframe_target` and then assigns the value to `innerHTML` |
| `html_viewer_readonly_template.js` | `web.assets_backend` | the whole `registerTemplate("html_editor.HtmlViewer", …)` call the xml bundle appends — the render site of the plain path, `t-out="state.value"` on the `o_readonly` div |

| Pattern | Bundles that carry it, once each | Bundles that carry it zero times |
|---|---|---|
| `iframeTarget.innerHTML=content;` | `web.assets_backend`, `web.assets_web`, `web.assets_web_print`, `project.webclient` | the twelve others of #210's table |
| `<div t-ref="readonlyContent" class="o_readonly" t-out="state.value"/>` | the same four | the same twelve |

Both live in `html_editor/static/src/fields/html_viewer.{js,xml}`, and
`html_editor/static/src/**/*` is named by exactly two manifests:
`html_editor`'s own, in `web.assets_backend` (so `web.assets_web` and
`web.assets_web_print` carry it by inclusion), and `project`'s, in
`project.webclient` — the bundle `project_sharing_project_task_templates.xml`
calls for the project-sharing client, where a shared user's task description
is readonly. That fourth bundle is wanted: it is the same escape on a portal
screen. The twelve others #210's table lists carry neither pattern, because
neither file is a member of any of them.

**How each was counted.** Both patterns were counted in the served bytes of
every `*/static/src/**/*.{js,xml}` file in the pinned package, reproducing
`addons/base/models/assetsbundle.py`: for JavaScript,
`rjsmin(transpile_javascript(url, source))`; for a template, lxml's
`XMLAsset._fetch_content` unwrap followed by `generate_xml_bundle`'s
`etree.tostring` inside `registerTemplate(name, path, template)`. A template
is therefore served **unminified**, through the same Ingress asset location as
the code, and reachable by an exact-expression rewrite — the same property the
snippet-thumbnail rule of #170 uses.

Both counts are one per bundle, and the anchors are longer than they look for
measured reasons. `t-out="state.value"` alone occurs **twice** in
`web.assets_backend`: the viewer's div and `web.MonetaryField`'s ghost value
(`web/static/src/views/fields/monetary/monetary_field.xml`), so the rule
carries the whole `<div>`. The attributes in it are single-spaced and the tag
ends `"/>` although the source file has two spaces and a space before the
slash: `etree.tostring` normalises both, which is why the pattern has to come
from the serve path and not from the file. `iframeTarget.innerHTML` alone
occurs three more times, all in the legacy `web_editor`'s html field
(`iframeTarget.innerHTML!==this.props.record.data[this.props.name]`, the
assignment beside it, and `iframeTarget.innerHTML=value;`) — none of them is
`=content;`, and that editor is ADR 0004's own open item.

Derived 2026-10-01 from the pinned `.deb` (`ODOO_DEB_VERSION` 18.0.20260930)
through Odoo's own serve path, for the **legacy** `web_editor` editor of issue
#238 — the one ADR 0004's postscript said "carries none of these expressions",
which is literally true: #210's and #237's eight patterns are all in
`html_editor`, and this editor's own load and save sites are different
expressions.

| File | Bundle | What it holds |
|---|---|---|
| `legacy_wysiwyg_start_edition.js` | `web_editor.backend_assets_wysiwyg` | `Wysiwyg.startEdition`'s preamble, whose `this.$editable.html(options.value)` is the editable's first load |
| `legacy_editor_reset_content.js` | `web_editor.backend_assets_wysiwyg` | `OdooEditor.resetContent`, the whole method — the load every *later* render goes through: a record switch, a discard, the collaboration stale-document reset, a mail theme switch, and the code view on its way back off |
| `legacy_readonly_iframe.js` | `web.assets_backend` | the legacy field's `_setupReadonlyIframe`, the whole method — which reaches markup three times, once per branch |
| `legacy_html_field_template.js` | `web.assets_backend` | the whole `registerTemplate("web_editor.HtmlField", …)` call the xml bundle appends — the plain readonly path, `t-out="markupValue"` on the `o_readonly` div |
| `legacy_html_field_editing_value.js` | `web.assets_backend` | `HtmlField.getEditingValue` and the `updateValue` beside it that writes what it returns |
| `legacy_html_field_code_view.js` | `web.assets_backend` | `HtmlField.toggleCodeView`, the whole method — two `record.update` calls that do not go through `getEditingValue` |
| `mass_mailing_inline_field.js` | `web.assets_backend` | the tail of `MassMailingHtmlField.commitChanges`, which reads the inlined clone out of a `srcdoc` iframe and stores it as `body_html` |
| `legacy_editor_bundle_membership.json` | — | the manifest asset entries of `web_editor.wysiwyg_iframe_editor_assets`, `web_editor.backend_assets_wysiwyg` and `web_editor.assets_wysiwyg`, plus every bundle they include, so a test can resolve bundle membership with no package present |

Measured 2026-10-01 across the eighteen bundles the control group serves on that
route. Each row is the `sub_filter` source as the template ships it, byte for
byte, and each occurs **once** in the whole package — in exactly one file:

| Pattern | Bundles that carry it, once each |
|---|---|
| `editable.html(options.value);` | `web_editor.assets_wysiwyg`, `web_editor.backend_assets_wysiwyg` |
| `this.editable.innerHTML=value;` | the same two |
| `iframeTarget.innerHTML=this.props.record.data[this.props.name];` | `web.assets_backend`, `web.assets_web`, `web.assets_web_print` |
| `iframeTarget.innerHTML=value;` | the same three |
| `cwindow.document.documentElement.innerHTML=value;` | the same three |
| `<div t-ref="readonlyElement" class="o_readonly" t-out="markupValue"/>` | the same three |
| `getEditingValue(){const codeViewEl=this._getCodeViewEl();if(codeViewEl){return codeViewEl.value;}else{if(this.wysiwyg){return this.wysiwyg.getValue();}else{return null;}}}` | the same three |
| `const inlineHtml=editableClone.innerHTML;` | the same three |
| `this.wysiwyg.odooEditor.toolbarHide();const value=this.wysiwyg.getValue();` | the same three |
| `codeview.val();this.props.record.update({[this.props.name]:value});` | the same three |

The eighteen are the sixteen of #237's table plus the two this family added:
`web.assets_backend`, `web.assets_backend_lazy`, `web.assets_web`,
`web.assets_web_print`, `web.assets_frontend`, `web.assets_frontend_lazy`,
`web.assets_frontend_minimal`, `web.report_assets_common`,
`web_editor.assets_wysiwyg`, **`web_editor.backend_assets_wysiwyg`**,
**`web_editor.wysiwyg_iframe_editor_assets`**, `web_editor.assets_media_dialog`,
`website.assets_wysiwyg`, `website.assets_editor`,
`mass_mailing.assets_wysiwyg`, `im_livechat.assets_embed_external`,
`html_builder.assets` and `project.webclient`. Every bundle not named in a row
above carries that row's pattern **zero** times.

Two of those memberships are the point rather than bookkeeping:

- **`web_editor.backend_assets_wysiwyg`** is where the first two patterns arrive
  in the backend. The legacy field does not ship the editor in
  `web.assets_backend`; `_lazyloadWysiwyg` fetches that bundle with
  `loadBundle`, which builds a `<script src>` the Runtime shim prefixes, so the
  request goes through the Ingress asset location and gets the rewritten bytes.
  `web_editor.assets_wysiwyg` is the frontend twin and carries the same two.
- **`web_editor.wysiwyg_iframe_editor_assets`** carries **none** of the ten, and
  that is the answer to #238's question about the mail designer's nested
  iframes. It is the one membership claim here that is **executed** and not only
  recorded: `legacy_editor_bundle_membership.json` holds the manifest asset
  entries of that bundle, of the two that do carry the editor, and of every
  bundle those include -- closed, so membership resolves with no package present
  -- and `test_ingress_legacy_html_editor.py` resolves `wysiwyg.js` and
  `OdooEditor.js` against it both ways. An Odoo bump that moved either file into
  that bundle would put a rewritten expression in a realm where no shim ran, with
  every other test still green, which is why this one does not live in prose. That bundle is the one `_loadIframe` injects into the editor's own
  iframe — a document built with `document.write`, which never was an HTTP
  response and in which no Runtime shim ran. It holds neither
  `web_editor/static/src/js/wysiwyg/wysiwyg.js` nor
  `…/odoo-editor/src/OdooEditor.js`, so no rewritten expression runs in that
  realm. Every one of the ten runs in the page's realm, where the globals are.
  (The inner `srcdoc` iframe of `commitChanges` is only *read* from, by the
  parent's own code.)

**How each was counted.** Reproducing `addons/base/models/assetsbundle.py` over
every `*/static/src/**/*.{js,xml}` file in the pinned package: for JavaScript,
`rjsmin(transpile_javascript(url, source))`; for a template, `XMLAsset._fetch_content`'s
unwrap followed by `generate_xml_bundle`'s `etree.tostring` inside
`registerTemplate(name, path, template)`. Bundle membership comes from
`ast.literal_eval` on each addon's `__manifest__.py`, walking `d["assets"]` with
`**/` matching zero or more directories and honouring `remove` and `replace`.
The same derivation reproduces #237's two fixtures byte for byte, which is how
it was checked before any count here was trusted.

**Two patterns begin mid-identifier, and that is deliberate.** nginx reads `$`
in a parameter as the start of a variable and there is no escape for it, so
`this.$editable.html(options.value);` and `$codeview.val();…` cannot be matched
whole — an unknown variable is a config nginx refuses to load. Each pattern
starts *after* the `$` and leaves `this.$` / `$` outside the match, which is the
same move the `${`-crossing rules make elsewhere in the template.
`test_ingress_legacy_html_editor.py` asserts each is really the tail of the full
expression, because a suffix could otherwise be matching something else.

`getEditingValue`'s whole body is the anchor rather than a line inside it,
because the strip has to be the *last* thing that happens to the value before
`updateValue` compares it with the record's: strip at the `record.update`
instead and the comparison is prefixed-against-unprefixed, so every commit looks
dirty and writes the field. The seven JavaScript excerpts are whole methods or
self-contained regions because the tests execute them.

Derived 2026-10-01 from the pinned `.deb` (`ODOO_DEB_VERSION` 18.0.20260930)
through Odoo's own serve path, for the media dialog's preselection comparisons
of issue #239 -- the two ADR 0004's postscript named as "the mirror problem:
two comparisons that expect an *unprefixed* URL and are handed a prefixed one".
Four excerpts, because each comparison exists in **both** media dialogs Odoo 18
ships: `html_editor`'s, which a backend form opens, and the legacy
`web_editor`'s, which `wysiwyg.js` and the website editor's snippet options
open (`website/static/src/snippets/s_image/options.js` and seven more: nine
files outside its own directory and outside `static/tests/` import
`@web_editor/components/media_dialog/media_dialog`). The two files are the same
code with different quote characters.

| File | Bundle | What it holds |
|---|---|---|
| `media_dialog_image_preselect.js` | `web.assets_backend` | `ImageSelector.isInitialMedia` **and** the `fetchAttachments` that calls it -- the loop that highlights a tile -- out of `html_editor`'s dialog |
| `legacy_media_dialog_image_preselect.js` | `web.assets_backend` | the same two methods out of the legacy `web_editor` dialog |
| `media_dialog_document_preselect.js` | `web.assets_backend` | `DocumentSelector.fetchAttachments`, whose comparison is the whole method, out of `html_editor`'s dialog |
| `legacy_media_dialog_document_preselect.js` | `web.assets_backend` | the same method out of the legacy `web_editor` dialog |

Each excerpt is both methods (or the whole method) because the test executes
them: it drives `fetchAttachments` over a two-attachment list and a media
element, and reads back which attachment the dialog selected -- the question the
issue asks, rather than a narrower one about an expression.

Measured 2026-10-01 across the nineteen bundles the control group serves on that
route: #238's eighteen plus `html_editor.assets_media_dialog`, which this family
added because it is the bundle `html_editor`'s manifest `('include', ...)`s into
both `web.assets_backend` and `web.assets_frontend`. Four of the five patterns
occur **once** in the whole package, in exactly one file; the first occurs once
in each of the two dialogs, because it is the one line the two spell the same
way -- so one rule serves both, and `sub_filter_once off` is what lets it match
twice in a bundle that carries both:

| Pattern | Rewritten | Bundles that carry it, once each |
|---|---|---|
| `if(this.props.media.dataset.originalSrc){return this.props.media.dataset.originalSrc===attachment.image_src;}` | yes | the five below **twice each** -- it is byte-identical in both dialogs -- plus `html_editor.assets_media_dialog`, `web_editor.assets_media_dialog` and `project.webclient` once each |
| `return this.props.media.getAttribute("src")===attachment.image_src;` | yes | `web.assets_backend`, `web.assets_web`, `web.assets_web_print`, `web.assets_frontend`, `web.assets_frontend_lazy`, `html_editor.assets_media_dialog`, `project.webclient` |
| `return this.props.media.getAttribute('src')===attachment.image_src;` | yes | the first five of those, plus `web_editor.assets_media_dialog` |
| `===this.props.media.getAttribute("href").replace(/[?].*/,"")` | **no** | the same seven as the second row |
| `===this.props.media.getAttribute('href').replace(/[?].*/,'')` | **no** | the same six as the third row |

Every bundle not named in a row carries that row's pattern **zero** times:
`web.assets_backend_lazy`, `web.assets_frontend_minimal`,
`web.report_assets_common`, `web_editor.assets_wysiwyg`,
`web_editor.backend_assets_wysiwyg`, `web_editor.wysiwyg_iframe_editor_assets`,
`website.assets_wysiwyg`, `website.assets_editor`, `mass_mailing.assets_wysiwyg`,
`im_livechat.assets_embed_external` and `html_builder.assets`. The two media
dialog bundles are each other's complement rather than a pair: neither dialog's
files are in the other's bundle, and `project.webclient` carries only
`html_editor`'s, which is the project-sharing client again.

**Two of the five patterns are measured and deliberately not rewritten, and
which two is this capture's finding.** The three comparisons of
`ImageSelector.isInitialMedia` and `DocumentSelector.fetchAttachments` do not
all have the same direction, and each one's direction had to be measured on
both operands before any rule was written.

- The **document comparison** was already correct under Ingress, and the strip
  the issue asked for would have **broken** it. Its left operand is the template
  literal `` `/web/content/${attachment.id}` ``, which begins `` `/web/ `` -- one
  of the generic literal rules the Ingress asset location has shipped since
  #166. So that operand arrives at the browser already prefixed and the
  comparison is prefixed-against-prefixed. The two image excerpts, by contrast,
  come back from that location changed only by this family's own three rules,
  because `attachment.image_src` is an ORM value and the element's reads are DOM
  reads, so no generic rule can reach either operand.
  `test_a_real_nginx_agrees_about_what_each_excerpt_becomes` is that
  measurement, executed: it serves all four excerpts through a real nginx
  carrying this location's own literal rule set and requires the answer to equal
  what the tests' own `str.replace` produced, byte for byte.
  `test_ingress_media_dialog_preselect.py` also refuses a `sub_filter` that
  names the `href` read at all, so the rule the issue asked for cannot arrive
  later from a reader following ADR 0004's old open list.
- The **dataset branch** is rewritten, and the reason is **not** the shim.
  `data-original-src` is not a `data-src`: the markup helper's attribute test is
  an exact name and the `setAttribute` wrapper's list is
  `href`/`src`/`action`/`xlink:href`, so a value the shim handled keeps that
  attribute root-relative, and `loadImageInfo` assigns the server's own
  `image_src` into it. What prefixes it is the **generic HTML location**, whose
  rule is written for `src="/` and, `sub_filter` being a plain substring search,
  matches inside the longer attribute name `data-original-src="/...` -- no
  neighbouring rule claims that position first, and `data-src="/` claims only
  its own. Odoo ships that attribute inside stored arch (every themed image in
  `mass_mailing_themes/views/mass_mailing_themes_templates.xml` carries one), so
  markup delivered as an HTML response reaches the browser with a prefixed
  `data-original-src` while the same attribute on a field value is
  root-relative. The branch `return`s *before* the `src` one, so the `src` rules
  alone would not have reached the website editor's dialog.
  `test_a_real_nginx_shows_what_prefixes_data_original_src` serves a page-HTML
  sample through that location's rules and is where this paragraph is executed.

**How each was counted.** Reproducing `addons/base/models/assetsbundle.py` over
every `*/static/src/**/*.js` file in the pinned package --
`rjsmin(transpile_javascript(url, source))` -- with bundle membership from
`ast.literal_eval` on each addon's `__manifest__.py`, walking `d["assets"]` with
`**/` matching zero or more directories and honouring `remove`, `replace` and
`('include', ...)`. The same derivation reproduces #237's and #238's fixtures
byte for byte, which is how it was checked before any count here was trusted.

**A newline inside a method is why `isInitialMedia` is three patterns and not
one.** `rjsmin` keeps the line break Odoo's source has before the second
`return`, so the method as served spans two lines; an nginx `sub_filter`
parameter that carried that newline would be a two-line directive, which the
tests that read this template line by line do not expect. Each pattern is
therefore one served line: the first branch (one pattern, both dialogs) and the
second (one per quote style).

Derived 2026-10-01 from the pinned `.deb` (`ODOO_DEB_VERSION` 18.0.20260930)
through Odoo's own serve path, for the code view round trip of issue #240 — the
last item on ADR 0004's open list, and the sixth markup insertion of
`html_editor`'s own html field:

| File | Bundle | What it holds |
|---|---|---|
| `html_field_toggle_code_view.js` | `web.assets_backend` | `HtmlField.toggleCodeView`, the whole method — which re-inserts the record's value into the editable when the code view goes back off |
| `html_field_value_getter.js` | `web.assets_backend` | `HtmlField`'s `get value()`, the whole getter — captured because it is what decides which helper the rewrite calls: it returns `markup(newVal)` whenever the record's value is a `Markup`, and #210's `IN` returns a non-string as it came |

| Pattern | Bundles that carry it, once each | Bundles that carry it zero times |
|---|---|---|
| `this.editor.editable.innerHTML=this.value;` | `web.assets_backend`, `web.assets_web`, `web.assets_web_print`, `project.webclient` | the fifteen others of #239's table, listed below |

Those fifteen, so the claim is a list and not a count: `web.assets_frontend`,
`web.assets_frontend_lazy`, `web.assets_frontend_minimal`,
`web.assets_backend_lazy`, `web.report_assets_common`,
`web_editor.assets_wysiwyg`, `web_editor.backend_assets_wysiwyg`,
`web_editor.wysiwyg_iframe_editor_assets`, `web_editor.assets_media_dialog`,
`html_editor.assets_media_dialog`, `website.assets_wysiwyg`,
`website.assets_editor`, `mass_mailing.assets_wysiwyg`,
`im_livechat.assets_embed_external` and `html_builder.assets`. The four that do
are the same four as #237's two patterns and for the same reason: both files are
`html_editor/static/src/fields/*`, which exactly two manifests name —
`html_editor`'s own, in `web.assets_backend` (so `web.assets_web` and
`web.assets_web_print` carry it by inclusion), and `project`'s, in
`project.webclient`, the project-sharing client. The media-dialog bundles do
*not* carry it, which is the difference from #239: `html_editor`'s manifest
includes only its media dialog into the frontend.

**The getter is a fixture rather than a stub because the issue's own claim
depends on it.** The whole question at this site is whether the value is a
string or an OWL `Markup`: on a string the plain `IN` works and on a `Markup`
it is a silent no-op, which is the trap #237 found and this rule inherits. So
`test_ingress_code_view_toggle.py` splices Odoo's own getter into the class it
drives and runs the toggle through it, and a separate test drives the rule
written with `IN` instead and shows the picture still fetched from the Home
Assistant root.

**How each was counted.** The same derivation as #239's: reproducing
`addons/base/models/assetsbundle.py` over every `*/static/src/**/*.js` file in
the pinned package — `rjsmin(transpile_javascript(url, source))` — with bundle
membership from `ast.literal_eval` on each addon's `__manifest__.py`, walking
`d["assets"]` with `**/` matching zero or more directories, honouring `remove`,
`replace` and `('include', ...)`, and skipping a file the bundle already holds
the way `AssetPaths.append` does. Checked by reproducing #237's and #239's
counts, which it does row for row.

**A newline inside the getter, and why the pattern is still one line.** `rjsmin`
keeps the line break Odoo's source has before the getter's second `return`, so
`html_field_value_getter.js` is two served lines. The rewritten expression is on
neither of them — `toggleCodeView` is one line as served — so no `sub_filter`
parameter here would have to carry a newline. The test pins both line counts, so
a re-capture that changed either says so.

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
