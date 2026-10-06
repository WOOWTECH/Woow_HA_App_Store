"""Live: the Ingress markup family's four readonly/editor screens (#243).

`#243` is the register of Live-tier checks the Ingress markup family left owed.
Four of its five rows have no adapter subcommand, because none of them is the
shape `e2e_menu_action_adapter.py` judges -- "open this screen on both surfaces
and diff the two records". Each is instead *one interaction* whose result is
read in two places: on the screen (did the picture resolve under the prefix and
arrive) and in the database afterwards (is the stored value still
root-relative). The fifth row, #234's, is `e2e_collab_peer_snapshot_live.py`,
whose pure helpers this module reuses rather than copies.

    readonly-plain      #237 check 1. A readonly html field on the plain path
                        (`t-out="state.value"`): the html field's history
                        dialog, which mounts `HtmlViewer` through a `getConfig()`
                        setting neither `hasFullHtml` nor `cssAssetId`, so it is
                        that path by construction. Reads only.
    readonly-iframe     #237 check 2. The same field on the `hasFullHtml` path,
                        inside `sandbox="allow-same-origin allow-popups
                        allow-popups-to-escape-sandbox"`. Needs a full-HTML
                        value, so it seeds a **scratch** task -- never the
                        onboarding to-do, whose stored `src` #235's checks read.
    codeview            #240. A user signature in Preferences with debug mode
                        on: the code view toggled off re-inserts the record's
                        markup, and the save must still store it root-relative.
    media-image-todo    #239 line 1. The media dialog reopened on an existing
                        image in a To-do description. It builds a scratch to-do
                        and its image: #243's pass here came from a hand-made
                        attachment that was cleaned up afterwards, and the
                        onboarding to-do's own picture is a static module asset
                        no dialog can list (#266).
    media-image-website #239 line 2, the more informative one: the same dialog
                        in the website editor, where `data-original-src` arrives
                        prefixed by the *generic HTML location* rather than the
                        shim, which is the branch that `return`s before the
                        first rule. It **builds its own page**, because #243's
                        run found nothing on this host for that branch to
                        execute on and therefore measured nothing (#266).
    media-document-todo #239 line 3 on the **current** editor, where it is
                        unreachable: Replace is namespaced to `image` and a
                        document is an `a.o_image`, so no control reopens the
                        dialog. Kept, because "no control reached it" is the
                        reading, and the premise is measured another way. It
                        builds a scratch to-do and a document so that the
                        unreachability is a reading rather than an absence
                        (#266).
    media-document-mailing
                        #239 line 3 on the **legacy** editor, which does have
                        one. A no-change check: the document tile was never
                        broken, because both operands of its comparison arrive
                        prefixed. Not highlighted here is new information, not
                        a partial fix. It builds its own document, and it
                        measures `#media-replace` as well as the tile, because
                        the toolbar is hidden outright for a media carrying a
                        non-image `data-mimetype` -- which the dialog's own
                        `createElements` always stamps on a document (#266).
                        It builds its **mailing** as well when the database
                        carries no draft or queued one -- `odoo_parity` happens
                        to, and a fresh install does not (#274).
    mailing-readonly    #238 line 3. A *sent* mailing's body: the legacy
                        editor's readonly iframe. Reads only, so it runs first.
    mailing-editable    #238 lines 1 and 2. The mail designer, and the two
                        fields a save writes -- `body_arch` through
                        `getEditingValue`, and `body_html`, which
                        `commitChanges` inlines separately and which is the one
                        that **leaves the installation**. A run that reads back
                        only `body_arch` has measured half the fix. It **builds
                        its own mailing and borrows nothing** unless
                        `--mailing-id` names one (#276): this is the check that
                        *saves*, so a borrowed row kept this run's marker body
                        in both of those fields if the run was killed before the
                        restore or taken without the optional `--cleanup`.

Three judgements are deliberately **not** reimplemented here, because each has
a shape that would make a wrong record look clean:

- **Prefix escape is `adapter.is_prefix_escape`.** The shape a local version
  loses is the doubled prefix: still *under* the prefix, so "did it leave the
  prefix" answers no. `e2e_ingress_hand_checks.py` carries the same note
  because a review caught exactly that there, and every rule in this family
  prefixes a value that may already carry one.
- **A picture's verdict depends on the surface.** Under Ingress a root-relative
  `src` must resolve under the prefix; on the Public origin it must resolve at
  the origin root, and a prefix appearing there at all is a `sub_filter` that
  leaked out of the Ingress asset location (#237 check 3). The surface is a
  parameter, never a constant.
- **An Ingress prefix in a stored value is `e2e_collab_peer_snapshot_live`'s
  shape**, which is derived from the gateway's own `$safe_ingress_path` map and
  pinned against the template. A second regex here would drift away from the
  add-on with nothing noticing. Its `redact` comes with it, so no Supervisor
  token reaches a record even though what every check reads back is *which*
  prefix is in a value.

The pure parts are tested in `test_e2e_ingress_markup_live.py`. **The browser
steps are not**, the way `e2e_collab_peer_snapshot_live.py` says of its own:
they have never been executed against this host. Run the read-only checks first
(`read_only_first`) so a selector that moved costs nothing.

    ~/venvs/woow/bin/python odoo18ce/tests/e2e_ingress_markup_live.py \
      mailing-readonly --env-file /projects/Woow_ha_odoo/.env --db odoo_parity \
      --surface both --out markup.jsonl --run-id WOOW-MARKUP-<UTC timestamp>

Writing: `readonly-iframe` creates one scratch `mail.template` and deletes it on
`--cleanup`; `codeview` writes one **real** `ir.actions.act_window.help` and
hands it back on every path, which is the one thing here that no flag gates
(#297, and it creates nothing for `--cleanup` to own);
`mailing-editable` **creates its own draft mailing** (#276, reclaiming a scratch
one an earlier surface or run left) and writes that mailing's `body_arch` and
`body_html`, deleted under `--cleanup`, and borrows a real campaign only when
`--mailing-id` names one -- in which case both fields are written back instead;
`media-image-website` creates one public image `ir.attachment` and one
`website.page` whose arch carries that attachment's own `image_src` in **both**
`src` and `data-original-src`; `media-document-mailing` creates one public
document `ir.attachment`, writes one mailing's `body_arch`, and **creates that
mailing** when the database has no draft or queued one (#274) -- deleted under
`--cleanup`, as is a scratch mailing an earlier surface or run left behind,
while a mailing it borrowed instead has both fields written back and is never
deleted;
`media-document-todo` and `media-image-todo` each create one public
`ir.attachment` and one scratch `project.task` holding the element that came
from it. **All four media checks build everything they measure** (#266, #274),
because none of them could measure anything on this database otherwise: #243's
run made its image and document fixtures by hand and cleaned them up, and the
only things left on the record are a static module asset and a website logo,
which no dialog lists. `mailing-editable` builds its mailing for the other half
of the same rule (#276): it measures a **save**, so the record it saves over must
not be somebody's campaign. `--cleanup` removes all five. **A borrowed row's own
value is put back whatever the flag says** (#297): the flag deletes what a check
created, and a real record holding this run's marker is nobody's idea of a
fixture left on purpose. A *reclaimed*
mailing's own litter goes with the reclaim instead, whatever the flag says: the
public attachment an earlier run's body links is in no fixture dict the
reclaiming run holds, and the seeding replaces the href that names it, so the
ids are read and unlinked as the row is taken over (#277). Each marker names its
run, so a later reader can tell whose text it is. Every other check reads only. The
boundary is ADR 0012.

**The ambient rows a run leaves are counted by the run** (#256, #264): each
surface counts `website.track` and `website.visitor` over its own session's RPC
after the login and again on the way out, and the delta is appended beside the
records under their own name with `.ambient.json` for its extension
(`markup.jsonl` -> `markup.ambient.json`) -- one line per surface per
invocation, because the records append the same way. Counts only, no URL and no
visitor identity. `media-image-website` is why this driver needs the figure:
it opens the website editor, whose preview iframes load tracked website pages,
so those rows are certainly written -- #243's evidence had to read an absolute
count on the host afterwards and say that no delta could be stated. The
denominator is every document GET the session's browser context made under its
base, which is the only way to count a navigation the editor made for itself.
It is accounting and not a verdict: `diff` never reads it, `read_records`
refuses its schema, and the conservation tally does not move for it.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import e2e_menu_action_adapter as adapter  # noqa: E402
from e2e_collab_peer_snapshot_live import (  # noqa: E402
    INGRESS_PREFIX_SHAPE,
    ingress_prefixes,
    redact,
)
from e2e_menu_action_adapter import parse_env_file  # noqa: E402
from e2e_parity_shared_layers_live import TIMEOUT, Env, IngressSide, PublicSide  # noqa: E402

Surface = adapter.Surface

# Not `odoo-parity-evidence/v1`. That schema is one record per plan item with a
# column for each of the two surfaces, joined and diffed by `diff`. These checks
# are one interaction per record, judged against an expectation that *differs*
# by surface rather than against the other surface, and each carries a stored
# field value the parity schema has nowhere to put. Registered beside
# `woow.peer-snapshot.v1` in the parity plan's section 12; no run here feeds
# `conservation`.
EVIDENCE_SCHEMA = "woow.ingress-markup/v1"

# --- Verdicts -----------------------------------------------------------------

# One picture on one screen.
UNDER_PREFIX = "UNDER-PREFIX"        # Ingress: resolved under the Ingress prefix
AT_ORIGIN_ROOT = "AT-ORIGIN-ROOT"    # Public: resolved at the origin root
NOT_LOADED = "NOT-LOADED"            # resolved where it should, and never arrived
ESCAPED = "ESCAPED"                  # resolved somewhere this surface must not reach
ABSENT = "ABSENT"                    # no picture on the screen at all
# A `data:` or `blob:` source, or one on a third-party origin. The prefix has no
# claim on it, so neither surface's expectation applies -- and saying
# `UNDER-PREFIX` of it would assert something nobody checked. Routine in the mail
# designer and the website preview, which is why it is named rather than folded
# into a pass.
NOT_A_PREFIX_QUESTION = "NOT-A-PREFIX-QUESTION"

PICTURE_VERDICTS = (UNDER_PREFIX, AT_ORIGIN_ROOT, NOT_LOADED, ESCAPED, ABSENT,
                    NOT_A_PREFIX_QUESTION)

# Worst wins. `ABSENT` outranks `ESCAPED` because an escape is a measurement and
# an empty screen is not one: #240's row warns that a full-HTML value renders no
# editor and #237's that the `cssAssetId` branch renders a different target, and
# in both cases the check would otherwise pass while testing nothing.
PICTURE_SEVERITY = {
    UNDER_PREFIX: 0,
    AT_ORIGIN_ROOT: 0,
    NOT_LOADED: 1,
    ESCAPED: 2,
    ABSENT: 3,
    # Ranked, but `screen_verdict` drops it before ranking: it is neither a pass
    # nor a failure, it is a picture that was not this check's subject.
    NOT_A_PREFIX_QUESTION: 0,
}

PASSING = frozenset({UNDER_PREFIX, AT_ORIGIN_ROOT})

# One stored value.
CLEAN = "CLEAN"
PREFIX_STORED = "PREFIX-STORED"

NOT_RUN = "NOT-RUN"

# --- Which *kind* of Stored reading a field carries (#289) --------------------
#
# A different question from what the value says, and the one the record could not
# answer. A **Write-bounding reading** is on a field the check itself wrote, so a
# prefix in it is that check's own save leaking. A **State-bounding reading** is
# on a field it did not, so a prefix is a leak whoever caused it and the check is
# the witness rather than the author (`CONTEXT.md` carries both terms). Five of
# this driver's read-back sites take the second kind -- `readonly-plain`,
# `mailing-readonly` (both its fields), `media-document-mailing`'s `body_html`,
# `readonly-iframe` under `--task-id` and `mailing-editable`'s `body_html` under
# `--mailing-id` -- and all five were reported identically to the first, as a
# `PREFIX-STORED` attributed to the check and surface that merely looked.
#
# **Both kinds are still reported and both still fail the run.** ADR 0014 refuses
# a per-field valve that withholds a verdict, and a per-check "judge but do not
# fail" policy is that same valve one layer out: the finding would still vanish
# from the exit code, the tally and the sweep gate. What the kind changes is the
# *claim* -- a check whose register row says `writes: False` was being printed as
# the author of a write, which on the Public origin is the leaked-`sub_filter`
# finding and a more serious statement than "this row has held a prefix since
# before the run".
#
# **Not composed into the verdict string**, which is where this differs from the
# peer snapshot driver's `classify`. There the kind *is* the verdict:
# `OWN-`/`FOREIGN-`/`UNKNOWN-PREFIX-STORED` are three findings with a severity
# order between them. Here the kind moves no verdict, so folding it into the
# verdict would encode a distinction the verdict does not make -- and would break
# `do_report`'s `stored_verdict == PREFIX_STORED` equality filter besides.
WRITE_BOUNDING = "write-bounding"
STATE_BOUNDING = "state-bounding"
READING_KINDS = (WRITE_BOUNDING, STATE_BOUNDING)

# The names `evidence_record` owns. A flow's own readings are merged flat beside
# them, so a collision would let one quietly replace a verdict with a reading;
# `evidence_record` refuses instead of letting the record lie.
RESERVED_RECORD_KEYS = frozenset({
    "schema", "run_id", "check", "issue", "database", "target", "surface", "screen",
    "expected", "verdict", "stored_verdict", "pictures", "stored", "stored_values",
    "signals", "notes",
})


def is_pass(verdict: str) -> bool:
    return verdict in PASSING


def expected_verdict(surface: Surface) -> str:
    """What a passing picture looks like on `surface`.

    The two surfaces want *different* things of the same root-relative `src`,
    which is why no check here is a two-surface diff: both sides being equal
    would be the failure.
    """
    return UNDER_PREFIX if surface is Surface.HA_INGRESS else AT_ORIGIN_ROOT


def is_prefix_question(url: str, surface: Surface, origin: str) -> bool:
    """Whether the prefix has any claim on `url` at all.

    `adapter.is_prefix_escape` returns `False` both for "this is fine" and for
    "this is none of my business" -- a non-http scheme (`:1160`) and a different
    netloc (`:1164`) -- so on its own it cannot tell a prefixed picture from a
    `data:` URI. The netloc comparison is the adapter's own `_netloc`, not a
    second one written here, so the two functions agree about what same-origin
    means by construction.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https", "ws", "wss"):
        return False
    return adapter._netloc(url) == adapter._netloc(origin)


def picture_verdict(
    surface: Surface, origin: str, prefix: str | None, resolved: str | None, loaded: bool,
) -> str:
    """What one `<img>` says, on this surface.

    `resolved` is the browser's own `element.src` -- the attribute resolved
    against the page's base URL, which is the question, because a root-relative
    attribute is exactly what resolves against the Home Assistant root when
    nothing rewrote it. `loaded` is `complete && naturalWidth > 0`: a rule can
    prefix a URL correctly and still name nothing.
    """
    if not resolved:
        return ABSENT
    if adapter.is_prefix_escape(resolved, surface, origin, prefix):
        return ESCAPED
    if not is_prefix_question(resolved, surface, origin):
        return NOT_A_PREFIX_QUESTION
    if not loaded:
        return NOT_LOADED
    return expected_verdict(surface)


def screen_verdict(verdicts: Sequence[str]) -> str:
    """The worst picture the prefix had a claim on, and `ABSENT` when none.

    Pictures that were never a prefix question are dropped rather than ranked: a
    `data:` URI beside a prefixed one must not outvote it, and a screen whose
    pictures were *all* `data:` URIs measured nothing, which is `ABSENT` for the
    same reason an empty screen is.
    """
    judged = [verdict for verdict in verdicts if verdict != NOT_A_PREFIX_QUESTION]
    if not judged:
        return ABSENT
    return max(judged, key=lambda verdict: PICTURE_SEVERITY[verdict])


def stored_verdict(value: Any) -> tuple[str, int]:
    """Whether a value read back out of the database carries an Ingress prefix.

    An html field with no value comes back `False` from the ORM rather than an
    empty string, so the falsy cases are clean rather than an error.
    """
    if not value:
        return CLEAN, 0
    found = ingress_prefixes(value if isinstance(value, str) else str(value))
    return (PREFIX_STORED, len(found)) if found else (CLEAN, 0)


# --- The register's rows ------------------------------------------------------

CHECKS: dict[str, dict[str, Any]] = {
    "readonly-plain": {
        "issue": 237, "writes": False, "surfaces": ("ingress", "public"),
        "screen": "the html field's history dialog on the To-do form",
        "what": "a readonly html field on the plain path renders its picture through the surface",
    },
    "readonly-iframe": {
        "issue": 237, "writes": True, "surfaces": ("ingress", "public"),
        "screen": "a scratch to-do whose description is a full-HTML value",
        "what": "the same field on the hasFullHtml path, inside the sandboxed iframe",
    },
    "codeview": {
        "issue": 240, "writes": True, "surfaces": ("ingress", "public"),
        "screen": "the user signature in Preferences, with debug mode on",
        "what": "the code view toggled off re-inserts the record's markup under the prefix",
    },
    "media-image-todo": {
        "issue": 239, "writes": True, "surfaces": ("ingress", "public"),
        "screen": "a scratch to-do holding an image, in the current editor",
        "what": "the attachment the image came from is preselected",
    },
    "media-image-website": {
        "issue": 239, "writes": True, "surfaces": ("ingress", "public"),
        "screen": "the website editor's Replace Media dialog on a page this check built",
        "what": "the same, on the path where data-original-src arrives prefixed",
    },
    "media-document-todo": {
        "issue": 239, "writes": True, "surfaces": ("ingress", "public"),
        "screen": "a scratch to-do holding a document link, in the current editor",
        "what": "a no-change check: both operands arrive prefixed, so it was never broken",
    },
    "media-document-mailing": {
        "issue": 239, "writes": True, "surfaces": ("ingress", "public"),
        "screen": "the mail designer's legacy dialog, reopened on a document this check built",
        "what": "the same no-change check, on the one editor that has a control for it",
    },
    "mailing-readonly": {
        "issue": 238, "writes": False, "surfaces": ("ingress", "public"),
        "screen": "a sent mailing's body, the legacy editor's readonly iframe",
        "what": "the readonly iframe renders its pictures under the prefix",
    },
    "mailing-editable": {
        "issue": 238, "writes": True, "surfaces": ("ingress", "public"),
        "screen": "the mail designer, on a draft mailing this check built",
        "what": "the designer loads under the prefix, and stores body_arch AND body_html root-relative",
    },
}


def read_only_first(names: Sequence[str]) -> list[str]:
    """The order a run takes them in: everything that writes nothing, first.

    ADR 0012 allows the writes, and running the cheap read-only checks first
    means a selector that moved is found before anything is stored.
    """
    return sorted(names, key=lambda name: (CHECKS[name]["writes"], name))


# --- The values the run seeds -------------------------------------------------

# `computeContainsComplexHTML()` turns `sandboxedPreview` on for any value whose
# parse yields a non-empty `<head>`, and `displayReadonly` then renders the
# viewer even while the field is editable. There is no view option for it and
# none exists to set, so the value is how the iframe path is reached.
FULL_HTML_VALUE = (
    "<html><head><style>body{margin:0}</style></head>"
    '<body><img src="/project_todo/static/img/todo_access.png"></body></html>'
)

# A *fragment*, deliberately. #240's row: a full-HTML value renders the readonly
# `HtmlViewer` instead of a `Wysiwyg`, so `this.editor` is `undefined` and
# `toggleCodeView` never reaches the assignment the rules patch -- the check
# would pass while testing nothing.
SIGNATURE_VALUE_TEMPLATE = (
    '<p>%s</p><img src="/web/image/res.company/1/logo" alt="logo"/>'
)


def signature_value(run_id: str) -> str:
    """The seeded signature, naming the run that seeded it.

    `docs/agents/live-tier.md` wants every writing step marked with its run id so
    the host stays readable and a later reader can tell whose text is whose. This
    value replaces a real user's signature, so that matters more here than it does
    for a scratch record that can simply be deleted.
    """
    return SIGNATURE_VALUE_TEMPLATE % marker_for(run_id)


# Kept for the Static tier's shape assertions; the run uses `signature_value`.
SIGNATURE_VALUE = SIGNATURE_VALUE_TEMPLATE % "x"

MARKER_PREFIX = "WOOW-MARKUP hand check"


def marker_for(run_id: str) -> str:
    """Text naming the run that typed it, so the host stays readable."""
    return "%s %s" % (MARKER_PREFIX, run_id)


# Every scratch record this driver makes is named with this, run id appended.
# It is a prefix and not just a convention because #274 reads it back: a
# `mailing.mailing` whose subject starts with it is this driver's own litter from
# an earlier surface or run, to be deleted rather than treated as a borrowed
# record and so preserved forever.
SCRATCH_NAME_PREFIX = "WOOW scratch (delete me) "


def scratch_task_name(run_id: str) -> str:
    """The scratch to-do's name: this run's, and disposable.

    #243 is explicit that the iframe check must not use the onboarding to-do,
    because #235's checks read that record's stored `src` and this write would
    be read as their result.
    """
    return SCRATCH_NAME_PREFIX + run_id


# --- #239's two fixtures (#266) -----------------------------------------------
#
# #243's run reached both of the lines below and measured neither, and the
# reason was the same both times: **the host carries nothing either branch can
# execute on.** The website home page's only visible image is
# `/web/image/website/1/logo/My%20Website`, a record-field image whose
# `data-original-src` is `None`, so rule 2's `if (…dataset.originalSrc)` never
# runs. And the only `data-original-src` Odoo ships in stored arch is
# `mass_mailing_themes`' seven themed images -- whose `data-original-id` values
# (435, 436, 437, 347) are ids from the developer's own database, whose paths
# match no `ir.attachment` here, and which reach the designer over
# `render_public_asset`, root-relative. They could never highlight a tile and
# never arrive prefixed, so they are not the screen either.
#
# So these two checks build what they measure. Each fixture is one public
# `ir.attachment` plus one record, both named after the run and both removed by
# `--cleanup`.
#
# A 1x1 PNG, the smallest thing that is still a real `image/png` -- which is
# what the dialog's `['mimetype', 'in', IMAGE_MIMETYPES]` clause asks of it
# (`web_editor/.../image_selector.js:126`).
FIXTURE_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP4z8AAAAMBAQD3A0FDAAAAAElFTkSuQmCC"
)

# The document fixture's bytes. `text/plain` is deliberate: the document
# selector's domain is `['mimetype', 'not in', IMAGE_MIMETYPES]`
# (`document_selector.js:31-45`), so an image would be listed by the other tab.
FIXTURE_DOCUMENT_TEXT = "WOOW document fixture for #239 line 3.\n"

# The alt text is how the website check finds its own image rather than "the
# first visible one" -- which on this host picked the website logo and measured
# nothing (#243).
FIXTURE_IMAGE_ALT = "woow markup fixture"

# The section the fixture page carries, handed to `website.new_page` as
# `sections_arch` so Odoo appends it inside the page's own `#wrap.oe_structure`
# (`website/models/website.py:1162-1167`) and nothing here has to rewrite an
# arch.
#
# **Four `data-*` attributes, and the last one is load-bearing.** A real image
# that has been focused in the website editor's image tools and then saved
# carries all four: `loadImageInfo` sets `originalId`, `originalSrc` and
# `mimetypeBeforeConversion` together from `/web_editor/get_image_info`, and
# `mimetype` if it is not already there (`image_processing.js:528-535`). The
# fixture carries them because of what the *first* line of that function does:
#
#     if ((img.dataset.originalSrc && img.dataset.mimetypeBeforeConversion) || !src) return;
#
# Without `data-mimetype-before-conversion` the function does not early-return,
# and under Ingress it would re-fetch the image info and **overwrite**
# `data-original-src` with the root-relative value the ORM just handed back --
# so the branch would compare two unprefixed values and pass whether or not
# rule 2 shipped. With it, the prefixed attribute the page HTML delivered is
# what the dialog reads, which is the whole measurement.
#
# `%(src)s` is the attachment's own `image_src`, read back from the server
# rather than built here, because it is the comparison's right-hand operand.
WEBSITE_FIXTURE_SECTION = (
    '<section class="s_text_block pt32 pb32" data-snippet="s_text_block" data-name="Text">'
    '<div class="container">'
    "<p>%(marker)s</p>"
    '<p><img class="img img-fluid o_we_custom_image" src="%(src)s" alt="%(alt)s"'
    ' data-original-id="%(id)d" data-original-src="%(src)s" data-mimetype="%(mimetype)s"'
    ' data-mimetype-before-conversion="%(mimetype)s" style="width: 64px;"/></p>'
    "</div></section>"
)

# The anchor exactly as the dialog's own `createElements` writes one:
# `` /web/content/${id}?unique=${checksum}&download=true ``, `title`,
# `data-mimetype` (`web_editor/.../document_selector.js:69-89`), and `o_image`
# added by `media_dialog.js:260`. Writing a different shape would measure a
# document no user has -- and the query string in particular is what rule 3's
# `.replace(/[?].*/, '')` exists for, so a fixture without one leaves half the
# premise unexercised.
DOCUMENT_LINK_TEMPLATE = (
    '<a class="o_image" title="%(name)s" data-mimetype="%(mimetype)s"'
    ' href="/web/content/%(id)d?unique=%(unique)s&amp;download=true"></a>'
)

# The body around whichever element a fixture is built from -- a mailing's
# `body_arch` or a scratch to-do's `description`, and an `<a class="o_image">`
# or an `<img>`. One shape, so the two surfaces and the two element kinds are
# comparable and the marker always sits beside the thing under test.
MEDIA_BODY_TEMPLATE = '<div class="o_layout"><p>%(marker)s</p><p>%(element)s</p></div>'


def document_link_markup(attachment: Mapping[str, Any]) -> str:
    """The fixture anchor for one attachment, in the dialog's own spelling."""
    return DOCUMENT_LINK_TEMPLATE % {
        "name": attachment["name"],
        "mimetype": attachment["mimetype"],
        "id": attachment["id"],
        "unique": attachment["checksum"] or "0",
    }


def mailing_document_body_value(run_id: str, attachment: Mapping[str, Any]) -> str:
    """The seeded mailing body for the document check, naming its run."""
    return MEDIA_BODY_TEMPLATE % {
        "marker": marker_for(run_id),
        "element": document_link_markup(attachment),
    }


def website_fixture_section(run_id: str, attachment: Mapping[str, Any]) -> str:
    """The fixture page's one section, naming its run."""
    return WEBSITE_FIXTURE_SECTION % {
        "marker": marker_for(run_id),
        "alt": FIXTURE_IMAGE_ALT,
        "id": attachment["id"],
        "mimetype": attachment["mimetype"],
        "src": attachment["image_src"],
    }


def fixture_page_name(run_id: str, surface: Surface) -> str:
    """One page per surface, because each surface creates its own over its own RPC.

    `U-D3` names its pages the same way and for the same reason: the two
    surfaces run as separate invocations against one database, so a shared name
    would make the second one reuse the first one's page and measure it twice.
    """
    return "woow-media-fixture-%s-%s" % (run_id.lower(), surface.value.replace("_", "-"))


# --- The record ---------------------------------------------------------------


def evidence_record(
    *,
    check: str,
    issue: int,
    run_id: str,
    database: str | None,
    target: str,
    surface: Surface,
    screen: str,
    pictures: Sequence[Mapping[str, Any]] | None,
    stored: Mapping[str, Any],
    readings: Mapping[str, str] | None = None,
    signals: Mapping[str, int] | None = None,
    extra: Mapping[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """One check on one surface. `pictures` of None means it was never read.

    The verdict is the worse of what the screen showed and what the database
    kept, because #237 check 4 is the half that says the screen passing proves
    nothing about the write: a viewer has no save, so a changed value there
    means the prefix reached one.

    `readings` says which **kind** of Stored reading each field in `stored`
    carries (#289), declared by the flow that took it. It is the flow's to
    declare because the register cannot: `media-document-mailing` is one check
    with one write-bounding field and one state-bounding one, so the row's
    `writes` flag is not the discriminator. A flow is free to *derive* its own
    declaration from a baseline it already holds -- the document-mailing check
    does -- and that stays the flow's business: nothing here knows about
    baselines, which is what keeps the verdict core out of it.
    """
    stored = dict(stored or {})
    readings = dict(readings or {})
    # **No default kind, and no silent one.** Whichever constant a default named
    # would be wrong at some site by construction, and the site it was wrong at
    # is the one nobody looked at. A declaration for a field that is not in
    # `stored` is the other direction of the same mistake -- a renamed field or a
    # typo -- and would read as "declared" while judging nothing. Both raise,
    # where the `RESERVED_RECORD_KEYS` collision raises and for its reason: the
    # record refuses rather than carrying a claim nobody made. Like that guard,
    # this one lands in `run_check`'s outer `except` and costs the surface its
    # record rather than stopping the run, so the guard that actually keeps the
    # six sites honest is the Static-tier test that pins every one of them.
    undeclared = sorted(set(stored) - set(readings))
    if undeclared:
        raise ValueError("a Stored reading must say which kind it is (#289); no "
                         "reading declared for: %s" % ", ".join(undeclared))
    orphaned = sorted(set(readings) - set(stored))
    if orphaned:
        raise ValueError("a reading was declared for a field this check did not "
                         "read back: %s" % ", ".join(orphaned))
    unknown = sorted({kind for kind in readings.values() if kind not in READING_KINDS})
    if unknown:
        raise ValueError("a Stored reading is %s; not: %s" % (
            " or ".join(READING_KINDS), ", ".join(map(str, unknown))))
    # **A check the register declares non-writing cannot host a write-bounding
    # reading.** That pairing is exactly the false claim #289 is about, and here
    # it would be made by the flow itself rather than inferred by a reader.
    # `readonly-plain` and `mailing-readonly` are the two rows it pins; a check
    # this module does not carry a row for is left alone, since the tests build
    # records for names the register has never heard of.
    if CHECKS.get(check, {}).get("writes", True) is False:
        claimed = sorted(field for field, kind in readings.items()
                         if kind == WRITE_BOUNDING)
        if claimed:
            raise ValueError("%s is registered as writing nothing, so it cannot have "
                             "written: %s" % (check, ", ".join(claimed)))

    stored_results = {}
    worst_stored = CLEAN
    for field, value in stored.items():
        verdict, count = stored_verdict(value)
        stored_results[field] = {"verdict": verdict, "prefixes": count,
                                 "reading": readings[field]}
        if verdict == PREFIX_STORED:
            worst_stored = PREFIX_STORED

    if worst_stored == PREFIX_STORED:
        # Before the `pictures is None` branch, deliberately. A prefix that
        # reached a write is the worst thing this run can find, and a check whose
        # screen could not be read still read the database -- reporting that as
        # `NOT-RUN` would drop it out of the tally entirely, since `summarise`
        # skips `NOT-RUN` and the check was seen so it is not in `not_run` either.
        verdict = PREFIX_STORED
    elif pictures is None:
        verdict = NOT_RUN
    else:
        verdict = screen_verdict([picture["verdict"] for picture in pictures])

    record: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "run_id": run_id,
        "check": check,
        "issue": issue,
        "database": database,
        "target": target,
        "surface": surface.value,
        "screen": screen,
        "expected": expected_verdict(surface),
        "verdict": verdict,
        "stored_verdict": worst_stored if stored_results else NOT_RUN,
        "pictures": list(pictures) if pictures is not None else None,
        "stored": stored_results,
        # The values themselves, so a reader can see *what* was stored without
        # seeing a token. This is the one place a Supervisor secret could reach
        # the evidence, and the redaction is where it does not.
        "stored_values": redact(dict(stored), {}),
        "signals": dict(signals or {}),
        "notes": notes,
    }
    if extra:
        collisions = sorted(set(extra) & RESERVED_RECORD_KEYS)
        if collisions:
            raise ValueError("a check's extra readings may not use the record's own "
                             "names: %s" % ", ".join(collisions))
        record.update(redact(dict(extra), {}))
    return record


def summarise(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What `report` prints: the tally, the failures, and what never ran.

    **The last record for a check and surface is its verdict.** A run keeps every
    attempt -- a past reading is what it recorded -- and this run retried five of
    the eight checks after finding a fixture or a selector wrong. Tallying every
    attempt would report a fixed check as a failure for ever.
    """
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        latest[(record["check"], record["surface"])] = record
    passed = failed = 0
    failures: list[str] = []
    seen: set[str] = set()
    for record in latest.values():
        seen.add(record["check"])
        verdict = record["verdict"]
        if verdict == NOT_RUN:
            continue
        if is_pass(verdict):
            passed += 1
        else:
            failed += 1
            failures.append("%s/%s: %s" % (record["check"], record["surface"], verdict))
    return {
        "passed": passed,
        "failed": failed,
        "failures": sorted(failures),
        "not_run": sorted(set(CHECKS) - seen),
        # How many readings were taken to get there, so a retried run is legible
        # as retried rather than looking like a clean first pass.
        "attempts": len(records),
    }


# --- Selectors ----------------------------------------------------------------
#
# Every selector this driver uses, in one block, read from the pinned package
# (`ODOO_DEB_VERSION` in `odoo18ce/Dockerfile`) rather than guessed. A selector
# that moved is the most likely reason a first run fails, and `ABSENT` is the
# verdict that says so rather than passing quietly.

HTML_FIELD = ".o_field_html"
EDITABLE = HTML_FIELD + " .odoo-editor-editable"
READONLY_CONTENT = ".o_readonly"
VIEWER_IFRAME = HTML_FIELD + " iframe"
SAVE_BUTTON = ".o_form_button_save"
DISCARD_BUTTON = ".o_form_button_cancel"
UNSAVED = ".o_form_status_indicator_buttons:not(.invisible)"
# The discard's own two bounds. No `set_default_timeout` is applied anywhere in
# this driver -- `TIMEOUT` is only ever passed explicitly -- so a wait with no
# `timeout=` takes Playwright's 30 s default, and `do_codeview`'s interrupt path
# spends them between the operator's Ctrl+C and the only restore a real
# `ir.actions.act_window.help` is going to get (#280).
#
# They are two numbers because they wait for different things, and the second one
# waits for far more than the first. The click needs nothing but an actionable
# button, which was matched `visible=true` in the same breath. The indicator
# clearing afterwards does **not** wait on a reload -- `_discard`
# (`web/static/src/model/relational_model/record.js:565`) is purely local, it
# resets `_changes` from the save point and re-renders, with no RPC at all. What
# it waits on is the line above it: `discard()` (`:183`) does
# `await this.model._askChanges()` first, which raises `NEED_LOCAL_CHANGES`, and
# the html field answers that by pushing `commitChanges()` into the promise list
# (`html_editor/static/src/fields/html_field.js:78`). On the mail designer that
# is `MassMailingHtmlField.commitChanges`, which runs `cleanForSave`, clones the
# editable into an `srcdoc` iframe, **awaits that iframe's `load`** ("Wait for
# the css and images to be loaded"), runs `toInline` over it and writes the
# result back into the record
# (`mass_mailing/static/src/js/mass_mailing_html_field.js:147-186`). So a discard
# on the designer pays the whole inlining pipeline before the indicator can
# clear -- the same pipeline the save path budgets `side.settle(6000)` for, and
# `extra["save_incomplete"]` exists because that is sometimes still not enough.
# A 5 s bound here therefore recorded `discarded: false` -- "the form was left
# dirty" -- for a discard that did come off, which is the misreading this issue
# exists to remove, arriving from the other side (#288). Hence 15 s: comfortably
# past the measured pipeline and still half of Playwright's default.
#
# **These two bounds are now the whole of what the seam spends** (#288). They
# were not: the window also held an unbounded-in-practice resolve -- `side.root`
# re-entering `_find_frame(wait_s=60)` whenever the Ingress frame reported
# detached, which is the interrupt scenario itself -- and a `side.settle(2000)`
# after the confirmation, worth about 10 s on every successful discard because
# `Side.settle` runs an 8 s `networkidle` that Odoo's open bus makes time out
# before it sleeps. The resolve is now `side.root_now`, which hands back the held
# frame and never enters that search, and the settle is gone: nothing any caller
# does after this seam touches a page or a frame. So these two are now the only
# waits the seam asks for: `<= 2 s` + `<= 15 s`, and about **nothing** when the
# discard comes off at once. Not a bound on the seam in every case, and this
# comment will not imply one again: the two `count()` calls take no `timeout=`
# because `count()` does not wait for anything, but they do need the renderer to
# answer, so on one of the conditions this function reports `false` for -- "a page
# that stopped responding" -- nothing here is bounded. Nothing bounded it before
# either; what the bounds cover is every case where the page still answers.
DISCARD_TIMEOUT = 2_000
DISCARD_CLEAN_TIMEOUT = 15_000
DIALOG = ".o_dialog .modal-content"
PICTURES = "img"


def read_pictures(root, selector: str, side) -> list[dict[str, Any]]:
    """Every `<img>` under `selector`, and what each one says on this surface.

    Three readings per picture, and all three are needed: the attribute is what
    the rewrite produced, the resolved URL is what the browser made of it
    against the page's base (which is the whole question -- a root-relative
    attribute is exactly what resolves against the Home Assistant root when
    nothing rewrote it), and `loaded` is whether the byte arrived.
    """
    images = root.locator(selector)
    try:
        attributes = images.evaluate_all("els => els.map(e => e.getAttribute('src'))")
        resolved = images.evaluate_all("els => els.map(e => e.src)")
        loaded = images.evaluate_all("els => els.map(e => e.complete && e.naturalWidth > 0)")
    except Exception as error:  # noqa: BLE001 -- a frame that navigated away
        return [{"unreadable": type(error).__name__, "verdict": ABSENT}]
    pictures = []
    for index, source in enumerate(resolved):
        pictures.append({
            "attribute": side.env.mask(attributes[index] if index < len(attributes) else None),
            "resolved": side.env.mask(source),
            "loaded": bool(loaded[index]) if index < len(loaded) else False,
            "verdict": picture_verdict(
                side.surface, side.env.ha if side.surface is Surface.HA_INGRESS else side.env.public,
                side.env.prefix if side.surface is Surface.HA_INGRESS else None,
                source, bool(loaded[index]) if index < len(loaded) else False,
            ),
        })
    return pictures


def _discard_unsaved_form(side, extra) -> None:
    """Leave the form clean, so no `beforeunload` save follows a check out.

    An Odoo form persists a dirty editor on `beforeunload` **and** on an ungated
    `visibilitychange`, without the record itself being dirty at all (#263 is the
    same mechanism on the To-do form), and `run_check` closes the session *after*
    the handler has returned -- outside every reading the check took. Clicking
    inside an editable is enough to leave the form dirty, so for a check that
    drives a record it did not create this is the difference between a write it
    measured and one nobody could have.

    Reported in `extra["discarded"]` rather than silently, because "the form was
    dirty on the way out" is a reading about the screen. Three readings, not two
    (#280): no key at all for a page with nothing to discard, `true` for a
    discard that came off, and `false` once `UNSAVED` has matched and the form
    did not come clean -- a modal over the button, a page that stopped
    responding, no visible discard button to click, an indicator that never
    cleared. Without that third reading a failed discard is indistinguishable
    from an already-clean form, while the step after it still stamps
    `body_restored` / `help_restored` over a write this run's own `beforeunload`
    can put straight back. `discard_quietly` in
    `e2e_collab_peer_snapshot_live` reports the same pair for the same reason.
    """
    try:
        # `side.root_now` and not `side.root`, resolved once and held rather than
        # reached for at each of the three steps below. Both halves of that are
        # about the same minute: `root` is a property, and on `IngressSide` it
        # re-enters `_find_frame(wait_s=60)` whenever the held Ingress frame
        # reports detached, so each read of it is a chance to spend 60 s inside a
        # seam the interrupt path runs *ahead of* its only restore (#288).
        # `root_now` hands back the frame the side is already holding and never
        # enters that search; on the Public side it is `root` itself.
        #
        # It is also the reading, three times over. `IngressSide` caches the
        # frame and re-resolves only when it is detached, so re-reads returned
        # the same object in every case but one -- a panel that re-mounted its
        # Ingress iframe. There a re-read resolves to the *replacement* frame,
        # whose freshly loaded document has no `UNSAVED` match, so waiting for it
        # to go hidden returns at once and records `true` while the dirty form
        # sits in the frame that just went -- and that detach is exactly when
        # `beforeunload` fires. The same door is open at the *entry* read, where
        # a zero `count()` on a replacement frame reads as "nothing to discard"
        # and adds no key at all. Holding one `root_now` shuts both: a detached
        # frame raises here and adds no key (nothing was attempted, nothing is
        # known) or raises below and leaves the reading `false`. Nothing after
        # this wants the incidental re-resolve either: `Side.rpc` posts through
        # the request context, not a frame, so the restore does not need one.
        root = side.root_now
        if not root.locator(UNSAVED).count():
            return
    except Exception:  # noqa: BLE001 -- a frame that cannot be read is no reading
        return
    # `UNSAVED` matched, so from here on the form is known to be dirty and the
    # only reading that may say otherwise is a discard that actually came off.
    extra["discarded"] = False
    try:
        # `>> visible=true` rather than `.first`, this repository's idiom for this
        # same button (`e2e_collab_peer_snapshot_live.discard_form`): `.first`
        # takes the first DOM match whatever its state, so one hidden earlier
        # button -- a dialog's, a sub-form's -- would spend the bound on an
        # element that can never be clicked and never reach the real one.
        discard = root.locator(DISCARD_BUTTON + " >> visible=true").first
        if not discard.count():
            return
        discard.click(timeout=DISCARD_TIMEOUT)
        # `true` has to mean the form came clean, not that the click did not
        # raise. The indicator carries `invisible` again once the record is clean,
        # so `UNSAVED` stops matching and a locator with no element counts as
        # hidden -- `discard_form` reads the outcome the same way. Without this
        # wait a discard that did not take (a dialog raised over it, an invalid
        # record the form refuses to leave) reads as `true` while `run_check`'s
        # `side.close()` still has a dirty form to save.
        root.locator(UNSAVED).first.wait_for(
            state="hidden", timeout=DISCARD_CLEAN_TIMEOUT)
    except Exception:  # noqa: BLE001 -- the reading stays `false`
        return
    # The indicator went hidden, so the form came clean -- and that is the whole
    # of what this key reports, so it is written where nothing can fail after it.
    #
    # There used to be a `side.settle(2000)` here, for the step *after* this one:
    # the restore's RPC, "which wants the page quiet". It does not. Every step
    # any caller takes after this seam -- `read_field`/`write_field`,
    # `_restore_borrowed_mailing_body`, `_remove_mailing_fixture`, and the
    # document check's record read-back -- goes through `Side.rpc`, which posts
    # through the browser context's request API and touches neither a page nor a
    # frame. So the quiet page that sleep bought had no beneficiary, while its
    # cost was real and in the worst place: `Side.settle` runs an 8 s
    # `networkidle` that Odoo's open bus makes time out and *then* sleeps, about
    # 10 s on every successful discard, all of it between an operator's Ctrl+C
    # and the only restore that record is going to get (#288).
    #
    # Nor did the sleep protect the restore from a page-initiated save, which is
    # worth being exact about because it is this seam's whole subject. There are
    # two, and the confirmation above covers one of them: `Record.discard` awaits
    # `_askChanges`, which resolves `this.mutex.getUnlockedDef()` as well as the
    # field commits (`relational_model.js:209-213`), so anything that went
    # through `model.mutex` has landed before the indicator can clear -- and
    # `beforeVisibilityChange`, the ungated `visibilitychange` save of #263, is
    # `root.save()` (`form_controller.js:483-496`), which does
    # (`record.js:226-229`). The one that is not is `urgentSave`: it calls
    # `_save` **outside** the mutex (`record.js:267-272`), so
    # `getUnlockedDef()` returns straight past it. But it is wired to
    # `beforeunload` only (`form_controller.js:507`), and the form view sets
    # `useSendBeaconToSaveUrgently: true` (`:383`), so that save leaves over
    # `navigator.sendBeacon` and is **fire-and-forget** (`record.js:1014-1033`):
    # no wait on this side bounds it, and a 10 s sleep only made losing the race
    # less likely, never impossible. That window is `run_check`'s own
    # `side.close()`, which is what the discard itself exists to make empty.
    extra["discarded"] = True


def wait_for_editable(side, selector: str = EDITABLE) -> bool:
    """Wait for the html field's editable to mount before reading it.

    `wait_webclient()` returns when the action manager has rendered, which is
    before the editor has mounted and filled the field. Without this wait a
    reading taken straight afterwards found no `<img>` on a record that stores
    one -- a race reported as "the description holds no image", which is the
    same sentence a genuinely empty record produces. `open_todo` in
    `e2e_collab_peer_snapshot_live` waits the same way.
    """
    try:
        side.root.locator(selector).first.wait_for(timeout=TIMEOUT)
        return True
    except Exception:  # noqa: BLE001 -- a form that genuinely has no editable
        return False


def viewer_frame(side):
    """The readonly viewer's iframe content, or None when it rendered no iframe.

    `HtmlViewer` picks its path at `get showIframe()` (`hasFullHtml ||
    cssAssetId`), so the absence of an iframe here is a reading: it means the
    value did not take the path the check is about.
    """
    handles = side.root.locator(VIEWER_IFRAME).element_handles()
    for handle in handles:
        frame = handle.content_frame()
        if frame is not None:
            return frame
    return None


def open_one(env: Env, browser, surface: Surface, *, viewport=(1920, 1080)):
    """One surface, started. `PublicSide` does not need the Ingress prefix.

    `open_sides` starts Ingress first because the prefix it learns is what the
    `Masker` redacts with. A public-only run has none to redact, and
    `is_prefix_escape` on the Public surface asks only whether the literal
    `/api/hassio_ingress/` appears -- it needs no token to answer.
    """
    side = (IngressSide if surface is Surface.HA_INGRESS else PublicSide)(env, browser, viewport=viewport)
    side.start()
    return side


# --- The database, over the session's own RPC ---------------------------------
#
# Read back through the *same* session that took the interaction, so the value
# judged is the one that session's save produced. `#256` settled that a reading
# a run needs about its own effect is the session's own RPC and not an `ssh`
# into the host.


def read_field(side, model: str, record_id: int, field: str) -> Any:
    [record] = side.rpc(model, "read", [[record_id], [field]])
    return record.get(field)


def write_field(side, model: str, record_id: int, field: str, value: Any) -> None:
    side.rpc(model, "write", [[record_id], {field: value}])


def seed_scratch_task(side, run_id: str) -> int:
    """A to-do of this run's own, holding the full-HTML value.

    A to-do is a `project.task` with no project (`e2e_collab_peer_snapshot_live`
    finds one the same way). It is a **new** record rather than the onboarding
    to-do on purpose: #235's checks read that record's stored `src`, and this
    write would be read as their result.
    """
    return side.rpc("project.task", "create", [{
        "name": scratch_task_name(run_id),
        "description": FULL_HTML_VALUE,
        "project_id": False,
    }])


def seed_scratch_template(side, run_id: str) -> int:
    """A scratch `mail.template` holding the full-HTML value.

    `body_html` is `sanitize_tags=False`, so unlike `project.task.description` it
    keeps the `<head>` that `computeContainsComplexHTML()` needs. `model_id` is
    required, so it is pointed at `res.partner`.
    """
    model_ids = side.rpc("ir.model", "search", [[["model", "=", "res.partner"]]], {"limit": 1})
    return side.rpc("mail.template", "create", [{
        "name": scratch_task_name(run_id),
        "model_id": model_ids[0],
        "subject": marker_for(run_id),
        "body_html": FULL_HTML_VALUE,
    }])


def delete_scratch_task(side, task_id: int) -> None:
    side.rpc("project.task", "unlink", [[task_id]])


def create_fixture_attachment(side, run_id: str, *, document: bool) -> dict[str, Any]:
    """A public `ir.attachment` the media dialog is certain to list, and list first.

    Two properties make it a usable fixture, and both are read off the selector
    rather than hoped for:

    - **`public=True` puts it in the grid whatever record the dialog was opened
      from.** The domain is
      `['|', ('public','=',True), '&', ('res_model','=',resModel), ('res_id','=',resId)]`
      (`web_editor/.../file_selector.js:242-250`). #243's run had to scope its
      attachment to the record precisely because it did not set this, and the
      website editor's dialog -- opened from an `ir.ui.view`, not from the
      record -- would not have listed a record-scoped one at all.
    - **`order: 'id desc'` with a limit of 30** (`:264-279`) means the newest
      attachment is the **first** tile. So the check never searches for it, and
      `fetchAttachments`'s first page is certain to hold it -- which matters
      because the preselection runs inside that first page's loop and a tile on
      page two would never be compared.

    `image_src` and `checksum` are read back rather than built here. `image_src`
    is the comparison's right-hand operand (`html_editor/models/ir_attachment.py:37-62`),
    and a value this driver computed itself would be a second authority that
    could drift from the server's.
    """
    kind = "document" if document else "image"
    name = "woow-%s-fixture-%s.%s" % (kind, run_id.lower(), "txt" if document else "png")
    payload = (
        base64.b64encode(FIXTURE_DOCUMENT_TEXT.encode("utf-8")).decode("ascii")
        if document
        else FIXTURE_PNG_BASE64
    )
    attachment_id = side.rpc("ir.attachment", "create", [{
        "name": name,
        "datas": payload,
        "mimetype": "text/plain" if document else "image/png",
        "public": True,
    }])
    [record] = side.rpc("ir.attachment", "read",
                        [[attachment_id], ["image_src", "checksum", "mimetype"]])
    return {
        "id": attachment_id,
        "name": name,
        "mimetype": record.get("mimetype"),
        "checksum": record.get("checksum") or None,
        "image_src": record.get("image_src") or None,
    }


def seed_media_task(side, run_id: str, *, document: bool) -> dict[str, Any]:
    """A scratch to-do holding one media element, and the attachment it came from.

    `element_survived` is read back rather than assumed, because
    `project.task.description` is `sanitize_tags=True` and this driver has
    already been caught once by that field: #237's check 2 seeded a full-HTML
    value into it and got back the bare `<img>`. Both fixtures' attributes are
    in the sanitizer's whitelist (`data-mimetype` among them), so they are
    expected to survive -- but "expected to" is what the read-back replaces.

    **The image fixture carries no `data-original-src`, deliberately.** That
    attribute's branch `return`s before the `src` comparison, so an image
    carrying one would measure rule 2 on a screen whose point is rule 1 -- and
    rule 2 has a screen of its own (`media-image-website`), which is the only
    one on which the attribute arrives prefixed at all.
    """
    attachment = create_fixture_attachment(side, run_id, document=document)
    # Everything after the `create` is inside the guard, because a seeder that
    # raises half-way has already made a row: `run_check` discards a handler's
    # return value on a raise, so the leftover would be on the host with
    # nothing in the evidence naming it.
    try:
        if document:
            element = document_link_markup(attachment)
            wanted = "/web/content/%d" % attachment["id"]
        else:
            if not attachment["image_src"]:
                raise RuntimeError("the fixture attachment has no image_src, so there is "
                                   "no right-hand operand to compare against")
            element = '<img src="%s" alt="%s">' % (attachment["image_src"], FIXTURE_IMAGE_ALT)
            wanted = attachment["image_src"]
        description = MEDIA_BODY_TEMPLATE % {
            "marker": marker_for(run_id),
            "element": element,
        }
        task_id = side.rpc("project.task", "create", [{
            "name": scratch_task_name(run_id),
            "description": description,
            "project_id": False,
        }])
    except BaseException:
        _remove_fixture_attachment(side, attachment)
        raise
    try:
        stored = str(read_field(side, "project.task", task_id, "description") or "")
    except BaseException:
        remove_media_task(side, {"task_id": task_id, "attachment": attachment})
        raise
    return {
        "task_id": task_id,
        "attachment": attachment,
        "element_survived": wanted in stored,
    }


def remove_media_task(side, created: Mapping[str, Any]) -> dict[str, bool]:
    """Delete the scratch to-do and its attachment, and say what went."""
    removed: dict[str, bool] = {}
    try:
        delete_scratch_task(side, created["task_id"])
        removed["task"] = True
    except Exception:  # noqa: BLE001
        removed["task"] = False
    removed.update(_remove_fixture_attachment(side, created["attachment"]))
    return removed


def seed_website_fixture_page(side, run_id: str) -> dict[str, Any]:
    """One attachment and one website page whose stored arch carries it.

    `website.new_page`'s `sections_arch` is the supported way in: Odoo parses
    the template's arch, appends each section inside `#wrap`, and writes the
    result back (`website/models/website.py:1151-1180`). Doing it that way
    means this driver never hand-edits an `ir.ui.view`, and the page it gets is
    the one the *New page* flow produces.
    """
    attachment = create_fixture_attachment(side, run_id, document=False)
    # As in `seed_media_task`: every step after the first `create` is guarded,
    # because each of them can raise with a row already made. The guard removes
    # what exists at that point -- the attachment alone, or the page and its
    # view beside it.
    fixture: dict[str, Any] = {"attachment": attachment}
    try:
        if not attachment["image_src"]:
            raise RuntimeError("the fixture attachment has no image_src, so there is "
                               "no right-hand operand to compare against")
        created = side.rpc("website", "new_page", [], {
            "name": fixture_page_name(run_id, side.surface),
            "add_menu": False,
            "sections_arch": website_fixture_section(run_id, attachment),
        })
        fixture.update({key: created.get(key) for key in ("url", "view_id", "page_id")})
        if not fixture.get("url"):
            raise RuntimeError("website.new_page returned no url, so the editor has "
                               "no page to open")
    except BaseException:
        remove_website_fixture_page(side, fixture)
        raise
    return fixture


def remove_website_fixture_page(side, fixture: Mapping[str, Any]) -> dict[str, bool]:
    """Remove the page, its view and the attachment, and say what went.

    Each unlink is guarded separately and the outcome recorded, because
    `website.page.unlink` may already have taken the view with it -- in which
    case unlinking the view afterwards raises on a record that is correctly
    gone. A silent `except` here would read as "removed" for a fixture still on
    the host.
    """
    removed: dict[str, bool] = {}
    for key, model, label in (
        ("page_id", "website.page", "page"),
        ("view_id", "ir.ui.view", "view"),
    ):
        record_id = fixture.get(key)
        if not record_id:
            continue
        try:
            side.rpc(model, "unlink", [[record_id]])
            removed[label] = True
        except Exception:  # noqa: BLE001 -- already gone with its page
            removed[label] = False
    attachment = (fixture.get("attachment") or {}).get("id")
    if attachment:
        try:
            side.rpc("ir.attachment", "unlink", [[attachment]])
            removed["attachment"] = True
        except Exception:  # noqa: BLE001
            removed["attachment"] = False
    return removed


def pick_help_action(side) -> int:
    """An `ir.actions.act_window` whose `help` this check may borrow.

    Chosen by lowest id for repeatability, and its prior value is restored. The
    field is #158's, and the view that renders it sets `codeview`.
    """
    ids = side.rpc("ir.actions.act_window", "search", [[]], {"limit": 1, "order": "id asc"})
    if not ids:
        raise RuntimeError("no ir.actions.act_window on this database")
    return ids[0]


def current_user_id(side) -> int:
    """The logged-in user, found by the login the run signed in with."""
    ids = side.rpc("res.users", "search", [[["login", "=", side.env.login]]], {"limit": 1})
    if not ids:
        raise RuntimeError("no res.users row for the configured login")
    return ids[0]


def sent_mailing_id(side) -> int | None:
    """A mailing whose body renders through the legacy editor's readonly iframe.

    The body field is `readonly="state in ('sending','done')"`, so the readonly
    path needs a mailing in one of those states. None of them is created here --
    sending a mailing is outside what a parity run may do -- so a host with no
    sent mailing records this check as unreachable rather than sending one.
    """
    ids = side.rpc("mailing.mailing", "search",
                   [[["state", "in", ["sending", "done"]]]], {"limit": 1})
    return ids[0] if ids else None


# The two states in which the mail designer's body field is editable; its
# `readonly` is `state in ('sending','done')`. One constant, because #274 makes
# this driver *create* such a row and a seed that drifted away from the lookup's
# own predicate would hand the check a readonly designer.
EDITABLE_MAILING_STATES = ("draft", "in_queue")


def editable_mailing_id(side) -> int | None:
    ids = side.rpc("mailing.mailing", "search",
                   [[["state", "in", list(EDITABLE_MAILING_STATES)]]], {"limit": 1})
    return ids[0] if ids else None


# --- The mailing fixture both mailing checks need (#274, #276) ----------------
#
# Two checks in this module drive a `mailing.mailing`, and both used to rest on
# a record the database happened to carry. #274 moved `media-document-mailing`
# off that; #276 moved `mailing-editable`, which is the one that **saves**. The
# seam is shared and the *policy* is not: `fixture_mailing`'s `borrow` is where
# each check says whether a real draft on the database is something it may
# write to.


# The scratch mailing's sender, used only where the ORM's own precompute cannot
# reach a value (see `create_fixture_mailing`). `.invalid` is reserved by
# RFC 2606 and so is certainly unroutable, which matters not at all for a draft
# that is deleted without being sent -- but a required field needs *something*,
# and an address that could reach somebody is not it.
SCRATCH_MAILING_EMAIL_FROM = "woow-scratch@woow.invalid"


def create_fixture_mailing(side, run_id: str) -> dict[str, Any]:
    """A draft mailing of this run's own, for a database that carries none.

    **`subject` is the only field whose value this invents.** `mailing_model_id`
    is required with a default of `mass_mailing.model_mailing_list` -- the very
    record #271's hand seeding searched for -- so it is passed when that search
    finds it, so the create does not rest on a module data ref resolving, and
    omitted when it does not, so the field's own default still gets its turn.
    `state`, `schedule_type` and `mailing_type` have plain defaults.

    **`email_from` is the one required field whose precompute can come back
    empty**, and a required stored field is `NOT NULL` in Postgres
    (`fields.apply_required`), so that would be an `IntegrityError` rather than
    an odd record. With no `mail_server_id` the compute resolves to
    `create_uid.email_formatted or env.user.email_formatted`
    (`mailing.py:260-275`), and `email_formatted` is **False** for a user whose
    partner has no email -- which is exactly the fresh or catch-up database this
    seed exists for. The compute is left to do its job wherever it can: the
    fallback is passed only when the value it would reach is empty.

    **The state is read back rather than assumed**, the way `seed_media_task`
    reads its description back. The body field is
    `readonly="state in ('sending','done')"`, so a row outside
    `EDITABLE_MAILING_STATES` would give this check a readonly designer and read
    exactly like a fixture that did not survive its field. The row is removed
    when that happens: `run_check` discards a handler's return value on a raise,
    so a leftover would be on the host with nothing in the evidence naming it.
    """
    values: dict[str, Any] = {"subject": scratch_task_name(run_id)}
    model_ids = side.rpc("ir.model", "search",
                         [[["model", "=", "mailing.list"]]], {"limit": 1})
    if model_ids:
        values["mailing_model_id"] = model_ids[0]
    [user] = side.rpc("res.users", "read",
                      [[current_user_id(side)], ["email_formatted"]])
    if not user.get("email_formatted"):
        values["email_from"] = SCRATCH_MAILING_EMAIL_FROM
    mailing_id = side.rpc("mailing.mailing", "create", [values])
    try:
        [record] = side.rpc("mailing.mailing", "read",
                            [[mailing_id], ["state", "subject"]])
        if record.get("state") not in EDITABLE_MAILING_STATES:
            raise RuntimeError(
                "the scratch mailing came back in state %r, which the mail designer "
                "renders readonly; this check needs one of %s" % (
                    record.get("state"), ", ".join(EDITABLE_MAILING_STATES)))
    except BaseException:
        _remove_fixture_mailing(side, mailing_id)
        raise
    return {"id": mailing_id, "subject": record.get("subject"),
            "state": record.get("state")}


def scratch_mailing_id(side) -> int | None:
    """This driver's own scratch mailing, if an earlier run left one behind.

    The search a check that borrows **nothing** makes (#276). `editable_mailing_id`
    would hand it somebody's campaign; the only row such a check may reuse is one
    **this driver** wrote -- either mailing check's, since both name their scratch
    rows the same way -- and `--cleanup` is optional, so there usually is one.

    `=like` and not `like`: the prefix is anchored at the start, so a real campaign
    whose subject merely *mentions* the words is not a match -- the same test
    `reclaimable_scratch_mailing` then repeats on the value itself. The state bound
    is `editable_mailing_id`'s own, because a reclaimed row the designer renders
    readonly reads exactly like a fixture that did not survive its field.
    """
    ids = side.rpc("mailing.mailing", "search",
                   [[["subject", "=like", SCRATCH_NAME_PREFIX + "%"],
                     ["state", "in", list(EDITABLE_MAILING_STATES)]]], {"limit": 1})
    return ids[0] if ids else None


def reclaimable_scratch_mailing(side, mailing_id: int) -> dict[str, Any] | None:
    """This driver's own scratch mailing, or `None` for somebody's real one.

    The subject is the whole test, and it is sound because **this driver** is the
    only thing in the repository that ever creates a `mailing.mailing`: a subject
    starting with `SCRATCH_NAME_PREFIX` was written by an earlier surface or an
    earlier run of one of its two mailing checks -- either of them, since #276,
    which is why the sentence is about the driver and not about one check. Such a
    row is deleted rather than preserved; see `fixture_mailing` for why reading it
    as borrowed is worse than it sounds.

    A reclaim reaches the public `ir.attachment` that row's body links as well
    as the row: it is in no fixture dict this run holds, so if the reclaim did
    not remove it nothing ever would (#277). **`body_arch` is read here, in the
    same call as the test**, because this is the last moment it says anything:
    the seeder's own body write replaces the href, and the delete takes the row.
    See `reclaimed_attachment_ids`, which is the only reader of the value, and
    `extra["fixture"]` for what reaches the evidence -- the body itself does not,
    for `redact`'s reason.
    """
    [record] = side.rpc("mailing.mailing", "read",
                        [[mailing_id], ["subject", "state", "body_arch"]])
    if not (record.get("subject") or "").startswith(SCRATCH_NAME_PREFIX):
        return None
    return {"id": mailing_id, "subject": record.get("subject"),
            "state": record.get("state"), "body_arch": record.get("body_arch")}


def fixture_mailing(side, run_id: str, mailing_id, *, borrow: bool) -> dict[str, Any]:
    """Which mailing a check drives, and what that makes `--cleanup` answerable for.

    Four ways to one, and `borrow` decides whether the third is open:

    - **`--mailing-id` named one** (`given`): reuse it, do not look, do not
      create, do not delete -- and do not second-guess its state, because the
      operator chose the row.
    - **this driver's own scratch row is on the database** (`reclaimed`): named
      with `SCRATCH_NAME_PREFIX` by an earlier surface or an earlier run that ran
      without `--cleanup`. It is **reclaimed** and not borrowed, because reading
      it as borrowed would restore *this run's own* fixture body while recording
      `body_restored: true` -- evidence saying a real campaign was put back when
      nothing was -- and would make the row permanent, since every later run
      would read it the same way and no `--cleanup` would ever delete it.
    - **a real draft or queued mailing is on the database** (`found`): borrowed,
      and only by a check that asks to. Its body is written back and the row is
      never deleted, because #266's lesson is that a check which deletes what it
      did not create is how the next run ends up with nothing to measure.
    - **nothing is** (`created`): build one (#274) and delete it under
      `--cleanup`.

    **`borrow` is the whole difference between this module's two mailing checks,
    and it is not a style choice.** `media-document-mailing` never saves -- it
    *discards* the form and reads the record back to prove it -- so the only
    write a borrowed row takes is a `body_arch` the same run writes back.
    `mailing-editable` types in the designer and **clicks save**, because #238's
    subject *is* the save seam, and it therefore stores this run's marker body in
    both `body_arch` and `body_html` -- the field that leaves the installation
    with the mail. A run killed between the save and the restore would leave a
    real campaign holding it, and until #297 a run merely taken without the
    optional `--cleanup` did too. So that check passes `borrow=False` and loses
    nothing by it: the designer,
    `getEditingValue` and `commitChanges` do not care which record they are on
    (#276).
    """
    if mailing_id is not None:
        return {"mailing_id": mailing_id, "scratch": None, "source": "given"}
    found = editable_mailing_id(side) if borrow else scratch_mailing_id(side)
    if found is not None:
        scratch = reclaimable_scratch_mailing(side, found)
        if scratch is not None:
            return {"mailing_id": found, "scratch": scratch, "source": "reclaimed"}
        if borrow:
            return {"mailing_id": found, "scratch": None, "source": "found"}
        # A row the scratch search matched whose subject did not survive the
        # read back: somebody renamed it between the two calls, or the LIKE
        # pattern read differently from `startswith`. Build one rather than
        # write to a record no test now says is this driver's.
    scratch = create_fixture_mailing(side, run_id)
    return {"mailing_id": scratch["id"], "scratch": scratch, "source": "created"}


def _restore_mailing_body(side, mailing_id: int, before: Mapping[str, Any]) -> None:
    side.rpc("mailing.mailing", "write", [[mailing_id], {
        "body_arch": before.get("body_arch") or False,
        "body_html": before.get("body_html") or False,
    }])


def _remove_fixture_attachment(side, attachment: Mapping[str, Any]) -> dict[str, bool]:
    try:
        side.rpc("ir.attachment", "unlink", [[attachment["id"]]])
        return {"attachment": True}
    except Exception:  # noqa: BLE001
        return {"attachment": False}


# The attachment hrefs a fixture body carries, which is the only handle a
# reclaim has on the rows an earlier run's body links (#277). Deliberately not
# anchored at the start: that litter was left by a check which *saves*, and
# #238's whole subject is that a save may store the href prefixed --
# `/<token>/web/content/77` names attachment 77 as surely as `/web/content/77`.
FIXTURE_ATTACHMENT_HREF = re.compile(r"/web/content/(\d+)")


def reclaimed_attachment_ids(fixture: Mapping[str, Any]) -> list[int]:
    """The attachments a reclaimed scratch mailing's body links, and no others (#277).

    Until this, `--cleanup` removed `fixture["attachment"]` -- the attachment
    *this* run created -- and the scratch mailing, whoever made it. So a run
    taken without `--cleanup` left a mailing whose `body_arch` links a public
    `ir.attachment`, the next run reclaimed and deleted that mailing, and the
    attachment survived in no fixture dict any run holds: a fixture attachment is
    only ever reachable through the `fixture` block of the run that made it.

    **The bound is `scratch_mailing`'s own `body_arch`, and it is what makes
    reading ids out of markup sound.** That key is set only by
    `reclaimable_scratch_mailing`, so the body read here is a row whose subject
    carried `SCRATCH_NAME_PREFIX` -- this driver's own fixture body, whose
    attachment ids are this driver's. A row this run **created** comes from
    `create_fixture_mailing`, which returns no body, and a row this run
    **borrowed** -- `found`, or named by `--mailing-id` -- has no
    `scratch_mailing` dict at all: neither can reach this list, which is what
    keeps a real campaign's attachments out of it.
    """
    body = str((fixture.get("scratch_mailing") or {}).get("body_arch") or "")
    return sorted({int(found) for found in FIXTURE_ATTACHMENT_HREF.findall(body)})


def reclaim_stranded_attachments(side, fixture: Mapping[str, Any], extra) -> None:
    """Delete the litter a reclaimed body links, at the moment the reclaim strands it.

    **Not under `--cleanup`, and the asymmetry with the rest of the fixture is
    the point.** `--cleanup` answers "leave the host as this run found it", and
    for a row this run made that is the whole question. These attachments are an
    *earlier* run's, already abandoned, and the seeding destroys the only handle
    on them whatever the flag says: the body write below replaces the href, and
    the row itself goes at the next `--cleanup` run, which by then reads a body
    naming nothing. So a run without the flag would strand them exactly as
    before this fix. This is the first step inside the seeder's guard for the
    same reason -- everything after it can fail, and the compensation deletes the
    reclaimed row.

    Both the ids and the outcome are recorded, in the `extra["fixture"]` block a
    later reader consults to know what this run is answerable for. A removal that
    failed must say so for `_remove_mailing_fixture`'s reason: a silent `except`
    reads as "removed" for a public attachment still on the host.
    """
    stranded = reclaimed_attachment_ids(fixture)
    if not stranded:
        return
    extra["fixture"]["reclaimed_attachment_ids"] = stranded
    extra["fixture"]["reclaimed_attachments_removed"] = (
        _remove_reclaimed_attachments(side, stranded)["reclaimed_attachments"])


def _remove_reclaimed_attachments(side, ids: Sequence[int]) -> dict[str, bool]:
    """Unlink the rows a reclaimed body links, through a search that proves they exist.

    `unlink` on an id that is already gone is a `MissingError`, and that case is
    reachable rather than theoretical: this module unlinks a fixture attachment
    before its mailing and reports the two separately, so a run whose mailing
    unlink failed left exactly this -- a body naming an attachment that no longer
    exists. Letting that fail the reclaim would keep live litter alive over
    litter that is already gone.
    """
    try:
        live = side.rpc("ir.attachment", "search", [[["id", "in", list(ids)]]])
        if live:
            side.rpc("ir.attachment", "unlink", [live])
        return {"reclaimed_attachments": True}
    except Exception:  # noqa: BLE001
        return {"reclaimed_attachments": False}


def _remove_fixture_mailing(side, mailing_id: int) -> bool:
    try:
        side.rpc("mailing.mailing", "unlink", [[mailing_id]])
        return True
    except Exception:  # noqa: BLE001
        return False


def _restore_borrowed_mailing_body(side, fixture: Mapping[str, Any], extra) -> None:
    """Write a borrowed mailing's body back, and never a scratch one's.

    This is the distinction #274 turns on. A row this run **made** -- or
    reclaimed from an earlier run of the same check, which is the same thing for
    this purpose -- is deleted, so writing its old value back first would put
    `body_restored: true` in a record where nothing was borrowed, and that field
    is the only reading saying a real campaign's body was put back. A row this
    run **borrowed** must be restored and must not be deleted. `before` is empty
    until it has been read, which is the one case where there is nothing to put
    back at all.

    **Every exit calls this, and none of them gates it on `--cleanup`** (#297).
    That gate used to sit on the two success paths, so a run taken without the
    flag handed back nothing -- and the gate was never needed to keep this
    function off a row the run owns, because the first line is that test.
    """
    if fixture.get("scratch_mailing") is not None or not fixture.get("before"):
        return
    try:
        _restore_mailing_body(side, fixture["mailing_id"], fixture["before"])
        extra["body_restored"] = True
    except Exception:  # noqa: BLE001 -- the session itself may be gone
        extra["body_restored"] = False


def _remove_mailing_fixture(side, fixture: Mapping[str, Any]) -> dict[str, bool]:
    """Remove what this run owns: the attachment, and the mailing if it owns one.

    Each removal is reported rather than swallowed, for
    `remove_website_fixture_page`'s reason -- a silent `except` reads as
    "removed" for a fixture still on the host. A borrowed mailing gets no key at
    all, because "could not be removed" and "was never mine to remove" are
    different readings and a reader checking the host needs to tell them apart.

    The litter a *reclaimed* row's body links is not here but in
    `reclaim_stranded_attachments` (#277), which runs whether or not this does:
    the seeding strands those rows under either flag.
    """
    removed: dict[str, bool] = {}
    attachment = fixture.get("attachment")
    if attachment:
        removed.update(_remove_fixture_attachment(side, attachment))
    scratch = fixture.get("scratch_mailing")
    if scratch:
        removed["mailing"] = _remove_fixture_mailing(side, scratch["id"])
    return removed


def _abandon_mailing_fixture(side, fixture: Mapping[str, Any], extra,
                             check: str) -> None:
    """Undo a seed that raised, and name on the console what it could not undo.

    Every mailing seeder's `except BaseException`, because `run_check` discards a
    handler's return value when it raises: a step failing in a seeder would
    otherwise leave a public `ir.attachment` -- and a `mailing.mailing` beside
    it -- on the host with nothing in the evidence naming them. The restore is in
    that path too, because the body write is the seeder's last step and a
    borrowed row must not keep this run's body just because the step after it
    failed.

    A compensation that *itself* fails has nowhere in the record to say so --
    `extra`, and with it `fixture_removed`, never reaches the evidence from
    here -- so it says it on stderr. Leaving it unsaid is the very thing
    `_remove_mailing_fixture` reports outcomes to avoid.
    """
    _restore_borrowed_mailing_body(side, fixture, extra)
    removed = _remove_mailing_fixture(side, fixture)
    # The reclaim (#277) ran before anything in the seeder could fail, so its
    # outcome is not in `removed` -- and a failure there is the same kind of news:
    # a public attachment still on the host that no later run can name.
    reclaimed = (extra.get("fixture") or {}).get("reclaimed_attachments_removed")
    if reclaimed is False or not all(removed.values()):
        said: dict[str, Any] = {
            "attachment_id": (fixture.get("attachment") or {}).get("id"),
            "mailing_id": (fixture.get("scratch_mailing") or {}).get("id"),
            "removed": removed,
        }
        stranded = reclaimed_attachment_ids(fixture)
        if stranded:
            said["reclaimed_attachment_ids"] = stranded
            said["reclaimed_attachments_removed"] = reclaimed
        print("%s left a fixture behind: %s" % (
            check, json.dumps(said, sort_keys=True)), file=sys.stderr)


def onboarding_todo_id(side) -> int | None:
    ids = side.rpc("project.task", "search", [[["project_id", "=", False]]], {"limit": 1})
    return ids[0] if ids else None


def session_database(side) -> str | None:
    """The database this session ended up on, read rather than assumed."""
    try:
        return side.root.evaluate("() => (odoo.info && odoo.info.db) || null")
    except Exception:  # noqa: BLE001 -- no web client on the current page
        return None


# --- Running one check on one surface -----------------------------------------


SURFACES = {"ingress": Surface.HA_INGRESS, "public": Surface.PUBLIC}


def handler_for(check: str):
    """The `do_` function for a check name, by the one naming rule.

    `test_every_check_the_parser_takes_has_a_branch_and_a_row` holds the parser,
    this lookup and `CHECKS` together, so a check cannot be added to the
    register without a branch to run it.
    """
    return globals()["do_" + check.replace("-", "_")]


def run_check(
    check: str,
    surfaces: Sequence[str],
    *,
    db: str,
    out_path: str,
    run_id: str,
    task_id: int | None = None,
    mailing_id: int | None = None,
    cleanup: bool = False,
    headed: bool = False,
) -> int:
    from playwright.sync_api import sync_playwright

    row = CHECKS[check]
    handler = handler_for(check)
    records: list[dict[str, Any]] = []
    # Which surfaces have a record on disk, so the surface-failure fallback below
    # cannot write a second, contradicting line for one of them.
    kept: set[str] = set()
    # An ambient figure that could not be written, held until every surface has
    # run. `ambient_accounting` raises when the figure is a passing run's only
    # failure (#256), and raising it where it arrives would cost the *other*
    # surface its measurement -- a run of `--surface both` would open the public
    # origin never, record nothing for it, and exit by traceback.
    unaccounted: list[Exception] = []

    def keep(record: dict[str, Any], side=None) -> None:
        """Append one record to `--out` the moment it exists.

        Buffering them to the end loses the evidence for writes already made when
        a *later* surface fails -- and this driver writes. `Env.mask` runs over the
        finished record rather than only over the picture URLs: `redact` removes
        the Supervisor token and nothing else, while the values read back here are
        production field values that carry absolute base URLs and `access_token`
        path tokens (`mailing.mailing.body_html` especially).
        """
        masked = side.env.mask(record) if side is not None else record
        with open(out_path, "a", encoding="utf-8") as out:
            out.write(json.dumps(masked, ensure_ascii=False, sort_keys=True) + "\n")
        # After the write, both of them: `kept` is read as "this surface's record
        # is on disk" and `records` as "this is what the run recorded", and a line
        # the file never got is neither.
        records.append(masked)
        kept.add(masked["surface"])
        print("%s/%s %s  (expected %s)" % (
            masked["check"], masked["surface"], masked["verdict"], masked["expected"]))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        try:
            for name in surfaces:
                surface = SURFACES[name]
                env = Env(db)
                side = None
                try:
                    side = open_one(env, browser, surface)
                    # This surface's ambient-row figure, counted by the run itself
                    # (#256, #264) and appended beside the records as
                    # `markup.ambient.json`. The window opens here, after the
                    # login, because the counts go over this session's own RPC --
                    # and it is per surface for the same reason the records are:
                    # each surface has its own session, and a delta over a
                    # database-wide count cannot be split between two of them
                    # afterwards. `media-image-website` is why this driver needs
                    # the figure at all: it opens the website editor, whose
                    # preview iframes load tracked pages.
                    with adapter.ambient_accounting(
                        adapter.SessionAmbientDriver(side, mask=env.mask),
                        adapter.RunInfo(run_id=run_id, target=env.target,
                                        database=session_database(side) or db),
                        surface, out_path, command=check, append=True,
                        navigation_basis=adapter.AMBIENT_BASIS_DOCUMENTS,
                    ):
                        outcome: dict[str, Any] = {
                            "screen": row["screen"], "pictures": None, "stored": {},
                            # Beside `stored` and empty for the same reason: a
                            # handler that threw before its read-back declared
                            # nothing, and an empty `stored` needs no declaration
                            # (#289).
                            "readings": {}, "notes": "",
                        }
                        mark = side.recorder.mark() if side.recorder else None
                        try:
                            outcome.update(handler(
                                side, run_id, task_id=task_id, mailing_id=mailing_id,
                                cleanup=cleanup,
                            ) or {})
                        except Exception as error:  # noqa: BLE001 -- a step that could not run
                            # A step that threw is `NOT-RUN` with its reason, never a
                            # pass and never a silent gap: `pictures` stays None.
                            outcome["notes"] = "%s: %s" % (
                                type(error).__name__, adapter.sanitize_diagnostic(str(error)))
                        signals = side.recorder.since(mark) if (side.recorder and mark) else {}
                        record = evidence_record(
                            check=check, issue=row["issue"], run_id=run_id,
                            database=session_database(side) or db,
                            target=env.target, surface=surface,
                            screen=outcome.get("screen") or row["screen"],
                            pictures=outcome.get("pictures"),
                            stored=outcome.get("stored") or {},
                            readings=outcome.get("readings") or {},
                            signals=signals,
                            extra=outcome.get("extra"),
                            notes=outcome.get("notes", ""),
                        )
                        keep(record, side)
                except Exception as error:  # noqa: BLE001 -- the surface itself failed
                    # `open_one`, `side.close()` and `evidence_record`'s own
                    # collision guard all sit outside the handler's `try`. Letting
                    # one escape would have abandoned the whole run with `--out`
                    # never opened, leaving a host this driver had already written
                    # to with no evidence line accounting for it.
                    if surface.value in kept:
                        # This surface's record is on disk, so the failure is in
                        # something after it -- the ambient accounting, which
                        # raises when it is a passing run's only failure (#256). A
                        # second line for the same surface would be read as this
                        # surface's verdict by `summarise`, which takes the last,
                        # so the figure's failure is held and raised after the
                        # loop instead.
                        unaccounted.append(error)
                        continue
                    keep({
                        "schema": EVIDENCE_SCHEMA, "run_id": run_id, "check": check,
                        "issue": row["issue"], "database": db, "target": os.environ.get(
                            "PARITY_TARGET", "local"),
                        "surface": surface.value, "screen": row["screen"],
                        "expected": expected_verdict(surface), "verdict": NOT_RUN,
                        "stored_verdict": NOT_RUN, "pictures": None, "stored": {},
                        "stored_values": {}, "signals": {},
                        "notes": "the surface could not be driven: %s: %s" % (
                            type(error).__name__, adapter.sanitize_diagnostic(str(error))),
                    })
                finally:
                    if side is not None:
                        try:
                            side.close()
                        except Exception:  # noqa: BLE001 -- a context already gone
                            pass
        finally:
            browser.close()

    if unaccounted:
        # Every surface has run and every record it took is on disk; what is left
        # is a figure that could not be written, and #256 exists so that is not
        # swallowed. The first one is raised and the rest are named, because an
        # operator needs the reason and not a count of reasons.
        for later in unaccounted[1:]:
            print("a further ambient figure could not be written: %s"
                  % adapter.sanitize_diagnostic(str(later)), file=sys.stderr)
        raise unaccounted[0]
    if not records:
        print("no record was written: nothing ran")
        return 1
    return 0 if all(is_pass(record["verdict"]) for record in records) else 1


def do_report(records_path: str) -> int:
    with open(records_path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    summary = summarise(records)
    print("%d passed, %d failed (from %d recorded attempt(s); the last record for a "
          "check and surface is its verdict)" % (
              summary["passed"], summary["failed"], summary["attempts"]))
    for failure in summary["failures"]:
        print("  FAIL " + failure)
    if summary["not_run"]:
        print("  not run: " + ", ".join(summary["not_run"]))
    # The register's own escalation hooks, applied to what was read rather than
    # left for a reader to apply. #239 cannot escalate -- nothing it measures is
    # stored -- and #237 check 4 is the one that can, on any check at all.
    stored = [record for record in records if record.get("stored_verdict") == PREFIX_STORED]
    # Every attempt is checked for a stored prefix, not just the last: a prefix
    # that reached a write happened even if a later attempt was clean.
    print("stored_prefix_found=%s" % ("yes" if stored else "no"))
    for record in stored:
        # **Name the kind beside the field** (#289), and name only the fields that
        # carry the prefix. "PREFIX STORED by readonly-plain/public in
        # project.task.description" read as an accusation against a check the
        # register declares non-writing; the kind is what makes the same line a
        # witness statement. Listing a `CLEAN` field here alongside them was the
        # smaller half of the same problem -- it put a field in the sentence that
        # was never part of the claim. A record written before #289 has no kind to
        # print, which is said rather than guessed at: every record in this repo's
        # three evidence files is `CLEAN`, so none of them reaches this line, but
        # the subcommand still reads any JSONL it is handed.
        fields = record.get("stored") or {}
        named = ", ".join(
            "%s (%s)" % (field, entry.get("reading") or "kind not recorded")
            for field, entry in sorted(fields.items())
            if (entry or {}).get("verdict") == PREFIX_STORED)
        print("  PREFIX STORED by %s/%s in %s" % (
            record["check"], record["surface"], named))
    return 1 if (summary["failed"] or stored) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in read_only_first(list(CHECKS)):
        sub = commands.add_parser(name, help=CHECKS[name]["what"])
        sub.add_argument("--env-file", help="read unset credentials from this NAME=value file")
        sub.add_argument("--db", required=True, help="the database the surfaces must serve")
        sub.add_argument("--out", required=True, help="JSONL evidence file; appended to")
        sub.add_argument("--run-id", required=True, help="the marker the records are named with")
        sub.add_argument("--surface", default="both", choices=["ingress", "public", "both"])
        sub.add_argument("--task-id", type=int, help="reuse a to-do instead of finding or creating one")
        sub.add_argument("--mailing-id", type=int,
                         help="reuse a mailing instead of finding or creating one")
        sub.add_argument("--cleanup", action="store_true",
                         help="delete what this check created before it returns")
        sub.add_argument("--headed", action="store_true")
    report = commands.add_parser("report", help="tally one or more runs' records")
    report.add_argument("records")
    args = parser.parse_args(argv)

    if args.command == "report":
        return do_report(args.records)
    if getattr(args, "env_file", None):
        with open(args.env_file, encoding="utf-8") as handle:
            parse_env_file(handle, os.environ)
    surfaces = ["ingress", "public"] if args.surface == "both" else [args.surface]
    surfaces = [name for name in surfaces if name in CHECKS[args.command]["surfaces"]]
    if not surfaces:
        # Otherwise the loop never runs, `all(...)` over an empty list is True and
        # a run that measured nothing exits 0 -- the one outcome this whole verdict
        # scheme exists to refuse.
        parser.error("%s does not run on surface %r; it runs on %s" % (
            args.command, args.surface, ", ".join(CHECKS[args.command]["surfaces"])))
    return run_check(
        args.command, surfaces, db=args.db, out_path=args.out, run_id=args.run_id,
        task_id=args.task_id, mailing_id=args.mailing_id, cleanup=args.cleanup, headed=args.headed,
    )



# --- #237: the readonly html field --------------------------------------------


def do_readonly_iframe(side, run_id: str, *, task_id=None, cleanup=False, **_) -> dict[str, Any]:
    """#237 check 2: the `hasFullHtml` path, inside the sandboxed iframe.

    There is no view option for this path and none exists to set.
    `computeContainsComplexHTML()` turns `sandboxedPreview` on for any value
    whose parse yields a non-empty `<head>`, and `displayReadonly` then renders
    the viewer even while the field is editable -- so the *value* is how the path
    is reached, which is why this check seeds one.

    **Not on `project.task.description`, which is the field #237's row names.**
    That field is `sanitize_tags=True`, so the ORM strips `<html>`, `<head>` and
    `<style>` on write: a full-HTML value seeded there comes back as the bare
    `<img>`, `computeContainsComplexHTML()` never sees a `<head>`, and the field
    renders the plain path -- which is check 1's screen, measured twice. Measured
    on this host: the seeded value read back as
    `<img src="/project_todo/static/img/todo_access.png">` and
    `rendered_iframe` was false on both surfaces.

    `mail.template.body_html` is `sanitize_tags=False`, so it keeps a full-HTML
    value, and it renders through `html_mail` -- a subclass of the same
    `HtmlField`. It is the field #240's row warns is "the value most likely to be
    full HTML" for exactly this reason. A scratch template is created and deleted
    rather than an existing one edited.

    Check 4 rides along: the field is read back afterwards, and a viewer has no
    save, so a value that changed means the prefix reached a write and the "no
    `OUT` half" decision is wrong.
    """
    created = None
    if task_id is None:
        task_id = created = seed_scratch_template(side, run_id)
    side.goto("/odoo/mail.template/%d" % task_id)
    side.wait_webclient()
    side.close_chat_windows()
    side.settle(2000)

    frame = viewer_frame(side)
    extra: dict[str, Any] = {
        "record_id": task_id,  # a mail.template id on this check, not a task
        "created_template": created,
        # The viewer is only on the iframe path when it rendered an iframe. Its
        # absence is a reading, not a retry: it says the value did not take the
        # path this check is about.
        "rendered_iframe": frame is not None,
    }
    if frame is None:
        pictures = None
        notes = ("the html field rendered no iframe, so the value did not take the "
                 "hasFullHtml path; nothing about #237 check 2 was measured")
    else:
        handle = side.root.locator(VIEWER_IFRAME).first
        # `t-att-sandbox` evaluates to this exact string on the `hasFullHtml`
        # branch and to `false` on the `cssAssetId`-only one, so the attribute
        # also says which branch rendered.
        extra["sandbox"] = handle.get_attribute("sandbox")
        pictures = read_pictures(frame, PICTURES, side)
        notes = ""

    stored = {"mail.template.body_html": read_field(side, "mail.template", task_id, "body_html")}
    # **The flag decides the kind** (#289). By default this check creates the
    # template and seeds the full-HTML value, so the field it reads back is one it
    # wrote and a prefix in it is this check's own: write-bounding. Under
    # `--task-id` it seeds nothing -- `created` is the only thing that says so --
    # and reads back a template the operator named, whose `body_html` may have
    # held a prefix since long before this run. Same reading, same field, and the
    # record has to say which, because `writes: True` on the register row is true
    # of the check and not of this field on this invocation.
    readings = {"mail.template.body_html":
                WRITE_BOUNDING if created is not None else STATE_BOUNDING}
    if cleanup and created is not None:
        side.rpc("mail.template", "unlink", [[created]])
        extra["deleted_template"] = created
    return {"screen": "/odoo/mail.template/%d" % task_id, "pictures": pictures,
            "stored": stored, "readings": readings, "extra": extra, "notes": notes}


# --- #238: the legacy web_editor ----------------------------------------------


# The mailing body is `body_arch` on the form; Odoo renders a field wrapper
# carrying the field's name, which is how this driver reaches a widget it has no
# class name for.
MAILING_BODY = '.o_field_widget[name="body_arch"]'


def do_mailing_readonly(side, run_id: str, *, mailing_id=None, **_) -> dict[str, Any]:
    """#238 line 3: a *sent* mailing's body, the legacy readonly iframe.

    Rules 3, 4 and 5 are `_setupReadonlyIframe`'s three branches. The body field
    is `readonly="state in ('sending','done')"`, so this needs a mailing in one
    of those states -- and this run does not create one, because sending a
    mailing is outside what a parity run may do. No save, nothing stored, which
    is why it goes first.
    """
    if mailing_id is None:
        mailing_id = sent_mailing_id(side)
    if mailing_id is None:
        return {"pictures": None, "notes":
                "no mailing.mailing in state sending or done on this database, and this "
                "run does not send one: #238's readonly iframe is unreachable here"}
    side.goto("/odoo/mailing.mailing/%d" % mailing_id)
    side.wait_webclient()
    side.close_chat_windows()
    side.settle(2000)

    extra: dict[str, Any] = {"mailing_id": mailing_id}
    handles = side.root.locator(MAILING_BODY + " iframe").element_handles()
    frame = next((handle.content_frame() for handle in handles if handle.content_frame()), None)
    extra["rendered_iframe"] = frame is not None
    if frame is None:
        return {"screen": "/odoo/mailing.mailing/%d" % mailing_id, "pictures": None, "extra": extra,
                "notes": "the mailing body rendered no iframe; the readonly path was not reached"}
    pictures = read_pictures(frame, PICTURES, side)
    # Read only: the two fields are recorded so the evidence says what the body
    # held, not because this check could have changed them.
    stored = {
        "mailing.mailing.body_arch": read_field(side, "mailing.mailing", mailing_id, "body_arch"),
        "mailing.mailing.body_html": read_field(side, "mailing.mailing", mailing_id, "body_html"),
    }
    # Which is `STATE_BOUNDING`, and now the record says so rather than the
    # comment above saying it to a reader (#289). This check has no save at all --
    # the body is `readonly` in the two states it needs -- so a prefix in either
    # field is a leak whoever caused it, with this check as the witness. The
    # register's `writes: False` makes the other declaration unavailable here:
    # `evidence_record` refuses a write-bounding reading from a row that writes
    # nothing.
    readings = {field: STATE_BOUNDING for field in stored}
    return {"screen": "/odoo/mailing.mailing/%d" % mailing_id, "pictures": pictures,
            "stored": stored, "readings": readings, "extra": extra}


# --- #240: the code view round trip -------------------------------------------

# `base.action_res_users_my` is `target="new"`, so Preferences is a dialog over
# whatever is on screen (`base/views/res_users_views.xml:506-512`), and its
# footer carries its own save -- `.o_form_button_save` is not on it.
# **Not the user signature, which is the screen #240's row names.** Measured on
# this host: that field renders through `o_field_html_mail` -- the `html_mail`
# subclass -- and its editor comes up **empty**, showing the `o-we-hint`
# placeholder, even with a fragment value present in the record. With an empty
# editable there is no text to select, so the floating toolbar is never raised and
# the `codeview` group never renders. #240's row picked the signature *because*
# `html_mail` was the thing to avoid (a mail body is the value most likely to be
# full HTML); on this build the signature is served by that widget anyway.
#
# `ir.actions.act_window.help` is the other `codeview` view
# (`base/views/ir_actions_views.xml:230`, #158's field). It is a plain `html`
# field on the current editor, `sanitize_tags=True` so it keeps a fragment and
# cannot become a sandboxed preview, and there are 707 records to pick from.
HELP_FIELD = '.o_field_html[name="help"]'
HELP_EDITABLE = HELP_FIELD + " .odoo-editor-editable"
SIGNATURE_FIELD = '.o_field_html[name="signature"]'
SIGNATURE_EDITABLE = SIGNATURE_FIELD + " .odoo-editor-editable"

# Turning the code view **on** for a fragment value is a toolbar item, not the
# button beside the field: `html_field.xml:26` renders `#codeview-btn-group` only
# when `state.showCodeView` is already true or the value is a sandboxed preview,
# and `html_field.js:292-310` registers the toggle as a toolbar command with
# `icon: "fa-code"` whose button carries `name="codeview"`
# (`main/toolbar/toolbar.xml`). So: select text to raise the floating toolbar,
# click it to go on, and click the field's own button to come back off.
CODEVIEW_TOOLBAR_BUTTON = '.o-we-toolbar button[name="codeview"]'
CODEVIEW_OFF_BUTTON = "#codeview-btn-group .o_codeview_btn"
CODEVIEW_TEXTAREA = "textarea.o_codeview"


def _restore_borrowed_help(side, uid: int, before, extra) -> None:
    """Hand the borrowed `ir.actions.act_window.help` back, on every path (#297).

    `_restore_borrowed_mailing_body`'s shape, for its reason, with the reading it
    gives: `help_restored` is `true` when the write took, `false` when it did not,
    and **absent** when the handler never got as far as seeding -- the three
    readings a reader of the record checks the host against.

    **Not under `--cleanup`, and that is the whole of this ticket.** The flag
    deletes what a check *created*; `pick_help_action` creates nothing, it takes
    the lowest-id `ir.actions.act_window` and seeds a record that belongs to the
    installation. Leaving a scratch row named after the run is a legible choice,
    and #183's and #265's evidence make it deliberately; leaving a real action
    holding this run's marker is not one, and the only sign of it in the evidence
    was the *absence* of a key. #282's run paid for that: its first invocation
    was taken without the flag, and action 1 ("Load demo data") kept the marker
    until a hand-written `odoo shell` repair put it back
    (`docs/testing/evidence/2026-10-04-issue-282/`).

    The write cannot fail the whole check either. A measurement that succeeded
    and a restore that did not are two readings, so this one is reported and not
    raised -- raising it would send the success path into the handler's
    `except Exception` and turn a measured record into `NOT-RUN`.
    """
    try:
        write_field(side, "ir.actions.act_window", uid, "help", before or False)
        extra["help_restored"] = True
    except Exception:  # noqa: BLE001 -- the session itself may be gone
        extra["help_restored"] = False


def do_codeview(side, run_id: str, **_) -> dict[str, Any]:
    """#240: the code view toggled off re-inserts the record's markup.

    The screen is the user signature in **Preferences** with debug mode on, and
    the field is a *fragment* on purpose: `computeContainsComplexHTML()` turns
    `sandboxedPreview` on for a value whose parse yields a non-empty `<head>`,
    the field then renders the readonly `HtmlViewer` instead of a `Wysiwyg`, and
    `this.editor` is `undefined` -- so `toggleCodeView` never reaches the
    assignment at `html_field.js:236` that the rules patch. A full-HTML value
    here would pass while testing nothing.

    Two halves, both recorded: the picture loads under the prefix after the
    toggle, and `res.users.signature` is still root-relative after the save.

    **`--cleanup` has nothing to do here, and the signature says so by not
    taking it** (#297). This is the one check in the register that creates no
    record at all: it borrows a real `ir.actions.act_window.help`, and
    `_restore_borrowed_help` hands that back on all three paths. `run_check`
    passes the flag to every handler, so `**_` absorbs it -- a thread-through
    that reached nothing would read as a restore somebody forgot to gate.
    """
    uid = pick_help_action(side)
    before = read_field(side, "ir.actions.act_window", uid, "help")
    extra: dict[str, Any] = {"action_id": uid, "help_before": redact(before or "", {})}
    # Seeded over RPC rather than typed, so the value under test is exactly the
    # one the Static tier measured and the check does not also depend on the
    # code view's own typing working.
    write_field(side, "ir.actions.act_window", uid, "help", signature_value(run_id))
    try:
        return _codeview_after_seeding(side, run_id, uid, before, extra)
    except Exception as error:
        # The partial readings are the whole value of a failed attempt -- was debug
        # on, did the toolbar appear, was there a selection -- and `run_check`
        # discards a handler's return value when it raises. So discard, restore,
        # then return them as a NOT-RUN outcome rather than re-raising and
        # losing them -- the discard for the same reason as on the success path,
        # and more pressingly here, since a step that failed is likelier to have
        # left the editor dirty.
        _discard_unsaved_form(side, extra)
        _restore_borrowed_help(side, uid, before, extra)
        return {"screen": "/odoo/ir.actions.act_window/%d (help, debug)" % uid, "pictures": None,
                "stored": {}, "extra": extra,
                "notes": "%s: %s" % (type(error).__name__,
                                     adapter.sanitize_diagnostic(str(error))[:300])}
    except BaseException:
        # The interrupt path: Ctrl+C, a kill, a timeout that raises outside
        # `Exception`. A real action's `help` was replaced by this check before any
        # browser step, so it is put back here too and the interrupt then continues.
        # The outer guard is the discard's: a second Ctrl+C inside it raises
        # through, which is the window #288 measured, and the restore is the one
        # step after it that a `KeyboardInterrupt` has nowhere else to come from.
        try:
            _discard_unsaved_form(side, extra)
            _restore_borrowed_help(side, uid, before, extra)
        except Exception:  # noqa: BLE001 -- the session itself may be gone
            pass
        raise


def _codeview_after_seeding(side, run_id, uid, before, extra) -> dict[str, Any]:
    """The browser half of `do_codeview`, split out so the seed has a restore."""
    # Debug mode first: `codeview` is `Boolean(odoo.debug && options.codeview)`
    # (`html_field.js:375`), so without it the toolbar item is never registered
    # and there is nothing to toggle.
    side.goto("/odoo?debug=1")
    side.wait_webclient()
    extra["debug"] = side.root.evaluate("() => (window.odoo && odoo.debug) || ''")
    # `?debug=1` goes on **this** navigation, not only on the `/odoo` one before
    # it. Measured on this host: after `/odoo?debug=1` the next page reported
    # `odoo.debug === ""`, so the flag did not survive the navigation, the
    # `codeview` command was never registered (`html_field.js:375` needs
    # `odoo.debug && options.codeview`), and the floating toolbar came up with
    # seven groups and no code view -- which reads exactly like a missing button.
    side.goto("/odoo/ir.actions.act_window/%d?debug=1" % uid)
    side.wait_webclient()
    side.settle(1500)

    editable = side.root.locator(HELP_EDITABLE).first
    editable.wait_for(timeout=TIMEOUT)
    # The toolbar is a selection toolbar; it is not in the DOM until there is one.
    editable.click()
    # A *text* selection, made with the keyboard. A programmatic `Range` fires
    # `selectionchange`, but the floating toolbar is raised from the editor's own
    # pointer and key handling, so a JS-only selection left it absent for the full
    # 60 s wait. `Home` then `Shift+End` selects the first line's text and nothing
    # else -- deliberately not the whole editable, because the toolbar hides a
    # group whose `namespace` does not match the selection's
    # (`toolbar_plugin.js:393`) and the `codeview` group declares none, so an
    # image in the selection would put it in the `image` namespace and hide the
    # one button this check needs.
    # A **triple-click on the paragraph**, which is the real pointer sequence a
    # user makes to select a line. `editable.click()` followed by `Home` /
    # `Shift+End` left the selection collapsed (`{collapsed: true, text: ""}`
    # measured on this host), so the toolbar was never raised and the wait below
    # timed out with nothing to show for it.
    paragraph = side.root.locator(HELP_EDITABLE + " p").first
    extra["paragraph_count"] = paragraph.count()
    extra["editable_visible"] = editable.is_visible()
    extra["dom"] = side.root.evaluate(
        """(sel) => {
            const wrappers = [...document.querySelectorAll(".o_field_html")].map(
                e => (e.getAttribute("name") || "?") + ":" + e.className.slice(0, 50));
            const ed = document.querySelector(sel);
            return {
                html_fields: wrappers,
                editable_html: ed ? ed.innerHTML.slice(0, 180) : null,
                editable_class: ed ? ed.className.slice(0, 80) : null,
                iframes_in_field: document.querySelectorAll(
                    '.o_field_html[name="help"] iframe').length,
            };
        }""", HELP_EDITABLE)
    target = paragraph if paragraph.count() else editable
    target.click(click_count=3)
    # Measured immediately: a settle first let whatever stole focus collapse the
    # selection before it was read, which made the reading say "no selection"
    # when the question was "did the click land".
    extra["after_click"] = side.root.evaluate(
        """() => {
            const s = window.getSelection();
            const a = document.activeElement;
            return {
                collapsed: s.isCollapsed,
                text: (s.toString() || "").slice(0, 40),
                active: a ? (a.tagName + "." + (a.className || "").slice(0, 60)) : null,
                toolbars: document.querySelectorAll(".o-we-toolbar").length,
                codeview_buttons: document.querySelectorAll(
                    '.o-we-toolbar button[name="codeview"]').length,
                any_codeview: document.querySelectorAll(
                    '[name="codeview"], .o_codeview_btn, #codeview-btn-group').length,
                // `odoo.debug` **on this page**. It was read once on the
                // `?debug=1` navigation, but the form is a separate document and
                // `var odoo = {debug: ...}` is baked in at render time, so the
                // question is whether the session carried it here.
                debug_here: (window.odoo && odoo.debug) || "",
                toolbar_buttons: [...document.querySelectorAll(".o-we-toolbar button")]
                    .map(b => b.getAttribute("name") || b.title || "?").slice(0, 30),
                toolbar_groups: [...document.querySelectorAll(".o-we-toolbar .btn-group")]
                    .map(g => g.getAttribute("name") || "?").slice(0, 20),
            };
        }""")
    side.page.wait_for_timeout(1500)
    extra["selection"] = side.root.evaluate(
        "() => { const s = window.getSelection();"
        " return {collapsed: s.isCollapsed, text: (s.toString() || '').slice(0, 40)}; }")
    extra["toolbar_present"] = side.root.locator(".o-we-toolbar").count() > 0
    extra["codeview_button"] = side.root.locator(CODEVIEW_TOOLBAR_BUTTON).count()
    toolbar = side.root.locator(CODEVIEW_TOOLBAR_BUTTON).first
    toolbar.wait_for(timeout=TIMEOUT)
    toolbar.click()
    # The textarea is deliberately not rewritten: it shows the record's own
    # bytes, which is why #240's own prerequisite note says typing a picture
    # there is the easy way to get one in.
    side.root.locator(CODEVIEW_TEXTAREA).first.wait_for(timeout=TIMEOUT)
    extra["code_view_shown"] = True
    extra["code_view_bytes"] = redact(
        side.root.locator(CODEVIEW_TEXTAREA).first.input_value(), {})

    off = side.root.locator(CODEVIEW_OFF_BUTTON).first
    off.wait_for(timeout=TIMEOUT)
    off.click()
    side.settle(1500)
    # This is the reading #240 is about: the markup `toggleCodeView` just
    # re-inserted at `html_field.js:236`, rendered.
    pictures = read_pictures(side.root, HELP_EDITABLE + " img", side)

    save = side.root.locator(SAVE_BUTTON).first
    save.wait_for(timeout=TIMEOUT)
    save.click()
    side.settle(4000)
    extra["unsaved_after_save"] = side.root.locator(UNSAVED).count() > 0
    after = read_field(side, "ir.actions.act_window", uid, "help")
    stored = {"ir.actions.act_window.help": after}
    # Write-bounding, and the simple case of #289: this check seeded the field
    # over RPC before any browser step and has just saved it through the editor,
    # so what it reads back is its own save and a prefix in it is this save's
    # leaking. There is no flag that turns this one -- `pick_help_action` chooses
    # the record and seeds it either way.
    readings = {"ir.actions.act_window.help": WRITE_BOUNDING}

    # Read first, then leave the form clean, and only then restore (#276). This
    # check replaced a **real** `ir.actions.act_window.help`, and `run_check`
    # closes the session after the handler returns: a `beforeunload` save on a
    # form still showing unsaved changes -- which `unsaved_after_save` just
    # recorded and nothing acted on -- would put this run's marked help text
    # back on that action permanently, with `help_restored: true` in the
    # evidence saying otherwise.
    #
    # The restore itself is unconditional, like both recovery paths above and
    # unlike `--cleanup`'s own job: `_restore_borrowed_help` carries why (#297).
    _discard_unsaved_form(side, extra)
    _restore_borrowed_help(side, uid, before, extra)
    return {"screen": "/odoo/ir.actions.act_window/%d (help, debug)" % uid, "pictures": pictures,
            "stored": stored, "readings": readings, "extra": extra}


# --- #237: the plain path, through the history dialog --------------------------

# **The register names "the To-do form" and that form does not have this item.**
# `ProjectTaskFormController` is the only controller that adds it
# (`project_task_form_controller.js:28-38`), and `project_todo`'s own
# `TodoFormController.actionMenuItems` *whitelists* its cog items -- archive,
# unarchive, duplicate, delete and "Convert to Task"
# (`project_todo/static/src/views/todo_form/todo_form_controller.js:20-33`) -- so
# Version History is filtered out there. The screen is therefore the **project
# task** form: `/odoo/project.task/<id>` resolves to `project.view_task_form2`,
# which carries `js_class="project_task_form"` (`project_task_views.xml:322`).
# A to-do is still a `project.task`, so the same record opens on it.
#
# The opener is a *static action menu item* -- the cog,
# `description: _t("Version History")`, icon `fa-history`.
# The cog is `web.ActionMenus`' Actions dropdown (`action_menus.xml:23-28`,
# `data-hotkey="u"`), and its items are `DropdownItem`s classed `o_menu_item`.
COG_BUTTON = '.o_cp_action_menus button[data-hotkey="u"]'
COG_ITEM = ".o_menu_item"
VERSION_HISTORY_LABEL = "Version History"

# `html_editor.HistoryDialog` (`history_dialog.xml`). Its `getConfig()` sets
# neither `hasFullHtml` nor `cssAssetId`, so the `HtmlViewer` it mounts is on the
# plain `t-out="state.value"` path *by construction* -- which is why this is the
# screen for #237 check 1 rather than a field that happens to be readonly.
HISTORY_DIALOG = ".html-history-dialog"
HISTORY_CONTENT = HISTORY_DIALOG + " .history-container"
HISTORY_NO_CONTENT = "No history"
HISTORY_REVISIONS = HISTORY_DIALOG + " .revision-list a"
# Never "Restore history": that writes. The run closes the dialog.
HISTORY_DISCARD = ".o_dialog footer button.btn-secondary"


def do_readonly_plain(side, run_id: str, *, task_id=None, **_) -> dict[str, Any]:
    """#237 check 1: a readonly html field on the plain path.

    `openHistoryDialog` refuses to open when the record has no
    `html_field_history_metadata.description` -- it posts a notification and
    returns -- so this needs a to-do with one past revision. #235's check 2
    created one when it saved the onboarding to-do under Ingress. A host without
    one records this as unreachable rather than saving the record to make one,
    because that is #210's screen and #235's check.

    Reads only: the dialog is closed with Discard, never Restore history.
    """
    if task_id is None:
        task_id = onboarding_todo_id(side)
    if task_id is None:
        return {"pictures": None, "notes": "no to-do (project.task with no project) on this database"}
    # Read the controller's own precondition before driving anything. It refuses
    # on a falsy `html_field_history_metadata.description`, and the field is
    # `None` until the versioned field has been written at least once
    # (`html_field_history_mixin.py:29-41`), so this says *why* in advance rather
    # than leaving a notification to be inferred from an absent dialog.
    metadata = read_field(side, "project.task", task_id, "html_field_history_metadata")
    extra: dict[str, Any] = {
        "task_id": task_id,
        "has_description_history": bool((metadata or {}).get("description")
                                        if isinstance(metadata, Mapping) else metadata),
        "form": "project.view_task_form2 (js_class project_task_form)",
    }
    if not extra["has_description_history"]:
        return {"screen": "/odoo/project.task/%d" % task_id, "pictures": None, "extra": extra,
                "notes": "html_field_history_metadata has no 'description' entry, so "
                         "openHistoryDialog refuses: this record's description has never been "
                         "written and the plain path is unreachable on it. Saving it to make a "
                         "revision is #210's screen and #235's check, not this one."}
    side.goto("/odoo/project.task/%d" % task_id)
    side.wait_webclient()
    side.close_chat_windows()
    side.settle(1500)

    side.root.locator(COG_BUTTON).first.click()
    side.settle(600)
    item = side.root.locator(COG_ITEM).filter(has_text=VERSION_HISTORY_LABEL).first
    if not item.count():
        return {"screen": "/odoo/project.task/%d" % task_id, "pictures": None, "extra": extra,
                "notes": "the cog has no %r item on this form" % VERSION_HISTORY_LABEL}
    item.click()
    side.settle(2500)

    dialog = side.root.locator(HISTORY_DIALOG).first
    if not dialog.count():
        # The controller's own refusal path: a notification instead of a dialog.
        return {"screen": "/odoo/project.task/%d" % task_id, "pictures": None, "extra": extra,
                "notes": "the history dialog did not open: the to-do has no past revision of "
                         "its description, so the plain path is unreachable on this record"}
    body = dialog.inner_text()
    extra["revisions"] = side.root.locator(HISTORY_REVISIONS).count()
    if HISTORY_NO_CONTENT in body and not extra["revisions"]:
        pictures, notes = None, "the history dialog opened with no revisions"
    else:
        # `.o_readonly` is the plain path's own div; scoping to it rather than to
        # the dialog keeps the revision list's own markup out of the reading.
        pictures = read_pictures(side.root, HISTORY_CONTENT + " " + READONLY_CONTENT + " img", side)
        notes = ""
    discard = side.root.locator(HISTORY_DISCARD).first
    if discard.count():
        discard.click()
        side.settle(800)
    stored = {"project.task.description": read_field(side, "project.task", task_id, "description")}
    # State-bounding (#289), and this check is the clearest case of it: it
    # *requires* `has_description_history` -- it refuses a record whose
    # description has never been written -- and then reads that description back.
    # Any prefix in it predates the run, and the docstring above already points at
    # whose write it would be. The register's `writes: False` makes the other
    # declaration unavailable here.
    readings = {"project.task.description": STATE_BOUNDING}
    return {"screen": "/odoo/project.task/%d (Version History)" % task_id, "pictures": pictures,
            "stored": stored, "readings": readings, "extra": extra, "notes": notes}


# --- #239: the media dialog's preselection -------------------------------------

# Both editors' dialogs, current and legacy, use the same content class and the
# same tile markers -- `html_editor/.../media_dialog.js:48` and
# `web_editor/.../media_dialog.js:50` both set `o_select_media_dialog`, and both
# `image_selector.xml` and `document_selector.xml` put `o_we_attachment_selected`
# on `.o_existing_attachment_cell` when the tile is the selected one. That class
# **is** #239: the preselection the three rules restored.
MEDIA_DIALOG = ".o_select_media_dialog"
MEDIA_TILE = MEDIA_DIALOG + " .o_existing_attachment_cell"
MEDIA_TILE_SELECTED = MEDIA_TILE + ".o_we_attachment_selected"
MEDIA_DISCARD = ".o_dialog footer button.btn-secondary"

# Reopening the dialog on an existing image. Two editors, two controls:
# `html_editor`'s is a toolbar item in the `image` namespace
# (`media_plugin.js:44-56`, `text: "Replace"`, so `name="replace_image"`), and the
# legacy editor's is the Replace button of its own toolbar
# (`web_editor/static/src/xml/editor.xml:278`).
REPLACE_CURRENT = '.o-we-toolbar button[name="replace_image"]'
REPLACE_LEGACY = "#media-replace"

# The **website editor**'s Replace is neither of those: it is a snippet option,
# `web_editor/views/snippets.xml:415-419`
# (`<div data-js="ReplaceMedia" ...><we-button data-replace-media="true">Replace`),
# and the `snippet-option-<data-js>` class is how the panel names it
# (`snippets.editor.js:3279-3283`). `#media-replace` is the legacy *toolbar*'s
# button and is kept only as a fallback.
REPLACE_WEBSITE = '.snippet-option-ReplaceMedia we-button[data-replace-media="true"]'

# A document in either editor carries `o_image`
# (`document_selector.js:10`, `mediaSpecificClasses`).
DOCUMENT_LINK = "a.o_image"


def media_dialog_reading(side, *, tab: str | None = None) -> dict[str, Any]:
    """What the open media dialog says about preselection.

    `tiles_selected` is the whole of #239: a tile carrying
    `o_we_attachment_selected` is the attachment the element came from, matched
    by a comparison whose two operands the three rules put on the same footing.
    """
    dialog = side.root.locator(MEDIA_DIALOG).first
    dialog.wait_for(timeout=TIMEOUT)
    if tab:
        candidate = side.root.locator(MEDIA_DIALOG + " .nav-link").filter(has_text=tab).first
        if candidate.count():
            candidate.click()
            side.settle(1500)
    # The tiles arrive from `fetchAttachments`, which is a round trip. Reading
    # straight after the dialog appears gave `tiles: 0` on one surface and
    # `tiles: 3` on the other for the same record -- a load race recorded as a
    # difference between the surfaces. Wait for the first tile, then settle.
    try:
        side.root.locator(MEDIA_TILE).first.wait_for(timeout=15000)
    except Exception:  # noqa: BLE001 -- a dialog that genuinely lists none
        pass
    side.settle(1500)
    tiles = side.root.locator(MEDIA_TILE)
    reading = {
        "tiles": tiles.count(),
        "tiles_selected": side.root.locator(MEDIA_TILE_SELECTED).count(),
        "tab": tab or "Images",
    }
    # What the dialog actually offered. Without this, "preselected none" cannot
    # be told apart from "the element never came from any attachment it listed",
    # and those two readings mean opposite things for #239.
    try:
        reading["tile_sources"] = [side.env.mask(source) for source in tiles.evaluate_all(
            """els => els.slice(0, 8).map(e => {
                const img = e.querySelector("img");
                return (img && (img.getAttribute("src") || img.src)) || e.textContent.trim().slice(0, 60);
            })""")]
    except Exception as error:  # noqa: BLE001
        reading["tile_sources"] = ["unreadable: " + type(error).__name__]
    reading.update(rewrite_reached_the_browser(side))
    return reading


# `@html_editor/main/media/media_dialog/image_selector` is where #239's rules 1
# and 2 live. Asking the page whether the served method carries the helper is the
# re-derivation the Issue's "Watch for" section demands when a check fails: it
# separates "the pattern did not match the deployed bytes" from "the rule ran and
# the comparison still disagreed", which are opposite findings.
#
# **Both dialogs are read, because the two media checks open different ones**
# (#266). The backend forms open `html_editor`'s; the mail designer and the
# website editor's snippet options open the legacy `web_editor` one, and rule 2
# is the single pattern the two spell identically -- so the legacy reading is
# the one that says the rule reached the dialog `media-image-website` actually
# drove. The current editor's keys keep their #243 names so the two runs stay
# comparable, and the legacy ones are added beside them.
_RULE_PROBE = """() => {
    const out = {markup_out_global: typeof window.__WOOW_INGRESS_MARKUP_OUT__};
    const read = (path, prefix) => {
        try {
            const mod = odoo.loader.modules.get(path);
            const source = mod.ImageSelector.prototype.isInitialMedia.toString();
            out[prefix + "rule_in_served_method"] =
                source.includes("__WOOW_INGRESS_MARKUP_OUT__");
            out[prefix + "served_method_length"] = source.length;
            out[prefix + "dataset_branch_in_served_method"] =
                source.includes("dataset.originalSrc");
        } catch (error) {
            out[prefix + "probe_error"] = String(error).slice(0, 120);
        }
    };
    read("@html_editor/main/media/media_dialog/image_selector", "");
    read("@web_editor/components/media_dialog/image_selector", "legacy_");
    return out;
}"""


# Rule 3's argument is that **both** operands of the document comparison arrive
# prefixed: the element's `href` by the Runtime shim, and the literal
# `` `/web/content/${attachment.id}` `` by one of the generic literal rules the
# asset location has shipped since #166, because it begins `` `/web/ ``. No `OUT`
# was shipped for that read and a Static-tier test refuses one. Since no control
# reopens the dialog on a document in the current editor, reading the served
# method is how the premise is measured on the host instead.
#
# **Which dialog is a parameter** (#266). Odoo ships this comparison twice, once
# per dialog, and the Static tier records both as measured-and-left-alone. The
# current editor has no control that reaches it; the legacy one does, so the
# legacy reading sits beside the tile that check actually read and the current
# one stands in where no tile could be read at all.
#
# **`attachmentsDomain` is read too, and it is not about #239.** The same
# selector's domain excludes generated asset bundles with
# `!['url', '=like', '/web/assets/%']` -- and that literal is in the same bundle
# as the comparison, so whatever prefixes `` `/web/content/ `` reaches it as
# well. A prefixed exclusion matches no stored `url`, which would make the
# Documents tab list every asset bundle under Ingress and none on the Public
# origin. #266's run saw exactly that difference in `tiles` and this reading is
# how the cause is measured rather than inferred.
# A raw string: every `\/` below is a JavaScript regex escape and must reach the
# page as it is written, not as Python's reading of it.
_DOCUMENT_OPERAND_PROBE = r"""(spec) => {
    const out = {dialog: spec.dialog};
    try {
        const mod = odoo.loader.modules.get(spec.module);
        const source = mod.DocumentSelector.prototype.fetchAttachments.toString();
        const prefixed = (path) => new RegExp(spec.prefix_shape + path);
        out.served_literal_prefixed = prefixed("/web/content/").test(source);
        out.served_has_web_content_literal = source.includes("/web/content/");
        out.served_method_length = source.length;
        out.served_strips_query = source.includes("replace(/[?].*/");
        const described = Object.getOwnPropertyDescriptor(
            mod.DocumentSelector.prototype, "attachmentsDomain");
        const domain = described && described.get ? described.get.toString() : "";
        out.served_domain_length = domain.length;
        out.served_domain_has_web_assets_literal = domain.includes("/web/assets/");
        out.served_domain_asset_exclusion_prefixed = prefixed("/web/assets/").test(domain);
    } catch (error) { out.probe_error = String(error).slice(0, 140); }
    return out;
}"""

CURRENT_DOCUMENT_SELECTOR = "@html_editor/main/media/media_dialog/document_selector"
LEGACY_DOCUMENT_SELECTOR = "@web_editor/components/media_dialog/document_selector"


def document_operand_reading(side, *, module: str = CURRENT_DOCUMENT_SELECTOR,
                             dialog: str = "current") -> dict[str, Any]:
    """Both served reads, with the prefix shape handed in rather than written twice.

    The shape is `INGRESS_PREFIX_SHAPE`, the gateway's own, derived from the
    `$safe_ingress_path` map and pinned against the template by
    `test_e2e_collab_peer_snapshot.py`. The probe used to spell it out in
    JavaScript, once per read -- two copies that could drift from the add-on
    with nothing noticing, which is the third of the three judgements this
    module's docstring refuses to reimplement. It is a `str` here only because
    JavaScript needs one; the authority is still the one `re.Pattern`.
    """
    try:
        return side.root.evaluate(_DOCUMENT_OPERAND_PROBE, {
            "module": module,
            "dialog": dialog,
            "prefix_shape": INGRESS_PREFIX_SHAPE.pattern,
        })
    except Exception as error:  # noqa: BLE001
        return {"dialog": dialog, "probe_error": type(error).__name__}


def rewrite_reached_the_browser(side) -> dict[str, Any]:
    try:
        return side.root.evaluate(_RULE_PROBE)
    except Exception as error:  # noqa: BLE001
        return {"probe_error": type(error).__name__}


def close_media_dialog(side) -> None:
    discard = side.root.locator(MEDIA_DISCARD).first
    if discard.count():
        discard.click()
        side.settle(800)


def _media_verdict(reading: Mapping[str, Any], side) -> tuple[list[dict[str, Any]], str]:
    """#239 is display state, so its pass is the tile and not a picture.

    The record still carries a picture list, because the evidence table is one
    shape for the whole run: a preselected tile is reported as the surface's own
    expected verdict, and no tile is `ABSENT` -- nothing was measured about the
    attachment the element came from.
    """
    if reading["tiles_selected"]:
        return [{"tile": "selected", "verdict": expected_verdict(side.surface)}], ""
    if not reading["tiles"]:
        return [], "the dialog listed no attachment tiles at all, so the preselection was not measured"
    # Listed tiles and none selected is **not** an escape. `isInitialMedia` only
    # ever matches an attachment the dialog actually listed, so a non-match can
    # equally mean the element never came from one -- a static module asset, a
    # record-field image like a website logo. Measured on this host: the
    # onboarding to-do's picture is `/project_todo/static/img/todo_access.png`,
    # which is no attachment at all, and the website home page's is
    # `/web/image/website/1/logo/...`, a field image; both preselected none on
    # **both** surfaces. So this is `ABSENT` -- nothing about the rules was
    # measured -- and a real regression looks different: the same element
    # selected on the Public origin and not under Ingress. That comparison is
    # between two records and belongs to the evidence, not to one verdict.
    return [{"tile": "none selected", "verdict": ABSENT}], (
        "the dialog listed %d tile(s) and preselected none; on this surface that is only a "
        "finding if the other surface preselected one for the same element" % reading["tiles"])


# --- The two to-do media checks' shared seam (#266) ---------------------------
#
# Both create a scratch `project.task` and a public `ir.attachment` *before*
# their first navigation, and `run_check` discards a handler's return value when
# it raises -- so a step that failed between the seed and the verdict would leave
# both on the host with nothing in the evidence naming them. These three
# functions are the seam that cannot happen through: one place that seeds, one
# that every exit goes through, and one for the paths where returning a record
# is no longer possible.


def _seed_media_todo(side, run_id: str, task_id, *,
                     document: bool) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Seed the fixture unless `--task-id` named a record, and start the `extra`."""
    created: dict[str, Any] | None = None
    if task_id is None:
        created = seed_media_task(side, run_id, document=document)
        task_id = created["task_id"]
    extra: dict[str, Any] = {"task_id": task_id}
    if created is not None:
        fixture = {
            "attachment_id": created["attachment"]["id"],
            "attachment_name": created["attachment"]["name"],
            "task_id": created["task_id"],
            "element_survived": created["element_survived"],
        }
        if document:
            fixture["href"] = "/web/content/%d" % created["attachment"]["id"]
        else:
            fixture["image_src"] = created["attachment"]["image_src"]
        extra["fixture"] = fixture
    return created, extra


def _leave_media_todo(side, created, extra, screen, *, cleanup, pictures,
                      notes) -> dict[str, Any]:
    """Every exit from either to-do media check, so none of them leaks a fixture."""
    if cleanup and created is not None:
        extra["fixture_removed"] = remove_media_task(side, created)
    return {"screen": screen, "pictures": pictures, "stored": {}, "extra": extra,
            "notes": notes}


def _remove_media_todo_quietly(side, created, *, cleanup) -> None:
    """The `BaseException` path: there is no record to put the outcome in."""
    if cleanup and created is not None:
        try:
            remove_media_task(side, created)
        except Exception:  # noqa: BLE001 -- the session itself may be gone
            pass


def do_media_image_todo(side, run_id: str, *, task_id=None, cleanup=False,
                        **_) -> dict[str, Any]:
    """#239 line 1: the dialog reopened on an image in a To-do description.

    Nothing is stored either way -- this is the row that cannot escalate in
    severity from what the host shows -- so the dialog is discarded and the form
    is never saved.

    **It builds a scratch to-do and its image** (#266). #243's run got its pass
    here from an attachment scoped to the onboarding to-do by hand, and cleaned
    it up: the next run found the onboarding to-do's own picture, which is
    `/project_todo/static/img/todo_access.png` -- a static module asset with no
    `ir.attachment` behind it -- and so preselected none on both surfaces, which
    is `ABSENT` and measures nothing. The fixture is what makes the pass
    repeatable rather than a property of one afternoon's host state. A scratch
    record and never the onboarding one, for #243's reason: #235's checks read
    that record's stored `src`.
    """
    created, extra = _seed_media_todo(side, run_id, task_id, document=False)
    task_id = extra["task_id"]
    screen = "/odoo/project.task/%d" % task_id
    try:
        return _media_image_todo_after_seeding(
            side, task_id, created, extra, screen, cleanup=cleanup)
    except Exception as error:
        return _leave_media_todo(side, created, extra, screen, cleanup=cleanup, pictures=None,
                                 notes="%s: %s" % (type(error).__name__,
                                                   adapter.sanitize_diagnostic(str(error))[:300]))
    except BaseException:
        _remove_media_todo_quietly(side, created, cleanup=cleanup)
        raise


def _media_image_todo_after_seeding(side, task_id, created, extra, screen,
                                    *, cleanup=False) -> dict[str, Any]:
    """The browser half of `do_media_image_todo`."""
    side.goto(screen)
    side.wait_webclient()
    side.close_chat_windows()
    extra["editable"] = wait_for_editable(side)
    side.settle(2000)

    # The fixture's own image, by its `alt`, so that another image on the record
    # cannot stand in for it; with no fixture (`--task-id`) any image will do.
    selector = EDITABLE + (
        ' img[alt="%s"]' % FIXTURE_IMAGE_ALT if created is not None else " img")
    image = side.root.locator(selector).first
    if not image.count():
        return _leave_media_todo(side, created, extra, screen, cleanup=cleanup, pictures=None,
                                 notes="the description holds no image (%s); read "
                                       "`element_survived` before suspecting the screen, "
                                       "because the field is sanitize_tags=True" % selector)
    # The element the dialog is asked about, recorded first: #239's comparison is
    # between this `src` and the attachment's `image_src`, and rule 2's branch is
    # about `data-original-src` on the same element.
    extra["element"] = {
        "src": side.env.mask(image.get_attribute("src")),
        "data_original_src": side.env.mask(image.get_attribute("data-original-src")),
    }
    image.click()
    side.settle(1000)
    replace = side.root.locator(REPLACE_CURRENT).first
    if not replace.count():
        return _leave_media_todo(side, created, extra, screen, cleanup=cleanup, pictures=None,
                                 notes="the image toolbar showed no Replace item")
    replace.click()
    reading = media_dialog_reading(side)
    extra["dialog"] = reading
    pictures, notes = _media_verdict(reading, side)
    close_media_dialog(side)
    return _leave_media_todo(side, created, extra, screen + " (media dialog, image)",
                             cleanup=cleanup, pictures=pictures, notes=notes)


def do_media_document_todo(side, run_id: str, *, task_id=None, cleanup=False,
                           **_) -> dict[str, Any]:
    """#239 line 3 on the current editor, where there is no control for it.

    This one was never broken: its comparison's left operand is
    `` `/web/content/${attachment.id}` ``, one of the generic literal rules the
    asset location has shipped since #166, so it arrives prefixed and is compared
    against a prefixed `href`. No `OUT` was shipped for it and a Static-tier test
    refuses one. So a tile **not** highlighted here is new information -- it says
    the `` `/web/ `` coupling does not hold on the host -- and is reported
    against #239 rather than recorded as a partial fix.

    **It builds its own scratch to-do and its own document** (#266). #243's run
    reached this row from a document link and an attachment made by hand, and
    cleaned both up afterwards -- so the finding it recorded, that no control in
    the current editor reopens the dialog on a document, was not repeatable: the
    next run found no `a.o_image` on the record at all and could only say so.
    The fixture makes the *unreachability* a reading rather than an absence. The
    record is a **scratch** to-do and never the onboarding one, for #243's
    reason: #235's checks read that record's stored `src`, and a write here
    would be read as their result.
    """
    created, extra = _seed_media_todo(side, run_id, task_id, document=True)
    task_id = extra["task_id"]
    screen = "/odoo/project.task/%d" % task_id
    try:
        return _media_document_todo_after_seeding(
            side, task_id, created, extra, screen, cleanup=cleanup)
    except Exception as error:
        return _leave_media_todo(side, created, extra, screen, cleanup=cleanup, pictures=None,
                                 notes="%s: %s" % (type(error).__name__,
                                                   adapter.sanitize_diagnostic(str(error))[:300]))
    except BaseException:
        _remove_media_todo_quietly(side, created, cleanup=cleanup)
        raise


def _media_document_todo_after_seeding(side, task_id, created, extra, screen,
                                       *, cleanup=False) -> dict[str, Any]:
    """The browser half of `do_media_document_todo`."""
    side.goto(screen)
    side.wait_webclient()
    side.close_chat_windows()
    extra["editable"] = wait_for_editable(side)
    side.settle(2000)

    document = side.root.locator(EDITABLE + " " + DOCUMENT_LINK).first
    if not document.count():
        return _leave_media_todo(side, created, extra, screen, cleanup=cleanup, pictures=None,
                                 notes="the description holds no document link (a.o_image): "
                                       "`project.task.description` is sanitize_tags=True, so "
                                       "read `element_survived` before suspecting the screen")
    # `data_original_src` is recorded on every media check, including the two
    # document ones where it is structurally absent (#266): an `<a>` has no
    # `src` for the image tools to have optimised, so `None` here is the
    # reading, and a record that simply omitted the key could not be told apart
    # from one taken before the key existed.
    extra["element"] = {
        "href": side.env.mask(document.get_attribute("href")),
        "data_original_src": side.env.mask(document.get_attribute("data-original-src")),
        "data_mimetype": document.get_attribute("data-mimetype"),
    }
    extra["operand"] = document_operand_reading(side)
    # Deliberately **not** a click. A document is an `<a href>`, and clicking one
    # inside the editable navigates or starts a download -- which detaches the
    # element, so the next step times out "waiting for locator" and the check
    # records a timeout rather than a reading. Selecting the node is what raises
    # the toolbar anyway, and it leaves the page where it was.
    side.root.evaluate(
        """(selector) => {
            const anchor = document.querySelector(selector);
            const range = document.createRange();
            range.selectNode(anchor);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        }""",
        EDITABLE + " " + DOCUMENT_LINK,
    )
    side.settle(1200)
    # The current editor's Replace is in the toolbar's `image` **namespace**
    # (`media_plugin.js:50`, `namespace: "image"`), and a document is an
    # `<a class="o_image">` rather than an `<img>` -- so selecting one does not
    # raise that group. Try it anyway, then fall back to a double-click, and
    # record which control opened the dialog so the evidence says how it was
    # reached rather than implying the toolbar did it.
    replace = side.root.locator(REPLACE_CURRENT).first
    if replace.count():
        extra["replace_control"] = REPLACE_CURRENT
        replace.click()
    else:
        # `force` because a document box can be laid out with zero size until the
        # editor's own stylesheet sizes it, and Playwright then refuses the click
        # as not actionable -- which is a fixture property, not a finding.
        extra["replace_control"] = "dblclick"
        document.dblclick(force=True)
    side.settle(1500)
    if not side.root.locator(MEDIA_DIALOG).count():
        return _leave_media_todo(
            side, created, extra, screen, cleanup=cleanup, pictures=None,
            notes="no control reopened the media dialog on the document link: the current "
                  "editor's Replace item is namespaced to `image` and a document is an "
                  "a.o_image, and its own file plugin suppresses the toolbar inside a "
                  "file box, so this row is unreachable here by construction. The tile "
                  "is read by `media-document-mailing`, on the legacy dialog")
    reading = media_dialog_reading(side, tab="Documents")
    extra["dialog"] = reading
    pictures, notes = _media_verdict(reading, side)
    close_media_dialog(side)
    return _leave_media_todo(side, created, extra, screen + " (media dialog, document)",
                             cleanup=cleanup, pictures=pictures, notes=notes)


def do_media_image_website(side, run_id: str, *, cleanup=False, **_) -> dict[str, Any]:
    """#239 line 2, the more informative image check: the website editor.

    Rule 2's prefix only appears on this path. `data-original-src` is not
    prefixed by the shim -- `IN`'s attribute test is an exact name, so
    `data-original-src` is not a `data-src`, and the `setAttribute` wrapper's
    list is four names. What prefixes it is the generic HTML location's rule,
    written for `src="/` and matched as a plain substring, so it claims the tail
    of the longer attribute name. Markup delivered as an **HTML response**
    therefore carries a prefixed `data-original-src` while the same attribute on
    a field value, which arrives over `call_kw` with its quotes escaped, does
    not. That branch `return`s before rule 1, so rule 1 alone would not have
    reached it. This dialog is also the legacy `web_editor` one.

    **It builds its own page, and that is the whole of #266 for this line.**
    #243's run drove this screen and measured nothing: the home page's only
    visible image is the website logo, a record-field image whose
    `data-original-src` is `None`, so the branch never executed and both
    surfaces preselected none -- which is "nothing measured", not a pass and not
    a gap. There is no shipped website page on this host carrying the attribute
    (`mass_mailing_themes` is the only module that ships it in stored arch at
    all, and not in a website page), so the fixture is the measurement.

    Nothing is saved: the editor is discarded, and `--cleanup` removes the page,
    its view and the attachment.
    """
    fixture = seed_website_fixture_page(side, run_id)
    extra: dict[str, Any] = {"fixture": {
        "attachment_id": fixture["attachment"]["id"],
        "attachment_name": fixture["attachment"]["name"],
        "image_src": fixture["attachment"]["image_src"],
        "page_id": fixture.get("page_id"),
        "view_id": fixture.get("view_id"),
        "url": fixture.get("url"),
    }}
    try:
        return _website_after_seeding(side, fixture, extra, cleanup=cleanup)
    except Exception as error:
        # Same shape as `do_mailing_editable`: a handler that raises has its
        # return value discarded by `run_check`, and the readings taken before
        # the failure are the whole value of a failed attempt. It leaves through
        # the same door as every other exit, so a failed attempt does not leave
        # a page behind for the next one to find and measure instead of its own.
        return _leave_website_media(
            side, fixture, extra,
            "/odoo/action-website.website_preview (Edit, Replace media)",
            cleanup=cleanup, pictures=None,
            notes="%s: %s" % (type(error).__name__,
                              adapter.sanitize_diagnostic(str(error))[:300]))
    except BaseException:
        if cleanup:
            try:
                remove_website_fixture_page(side, fixture)
            except Exception:  # noqa: BLE001 -- the session itself may be gone
                pass
        raise


def _website_after_seeding(side, fixture, extra, *, cleanup=False) -> dict[str, Any]:
    """The browser half of `do_media_image_website`, split out for the same reason."""
    screen = "/odoo/action-website.website_preview (Edit, Replace media, %s)" % fixture["url"]
    # `path` and `enable_editor` are the website preview action's own parameters,
    # read off `context.params` (`website_preview.js:118`, `:136`) -- they are
    # what the module's own Edit links carry, so this is the user's route to the
    # editor on a named page rather than a hand-built one.
    side.goto("/odoo/action-website.website_preview?path=%s&enable_editor=1"
              % quote(fixture["url"], safe=""))
    side.wait_webclient()
    root = side.root
    try:
        root.locator(".o-snippets-menu, #oe_snippets, .o_we_website_top_actions").first.wait_for(
            timeout=TIMEOUT)
    except Exception:  # noqa: BLE001 -- `enable_editor` did not take; use the control
        control = root.locator(
            ".o_edit_website_container button, .o_edit_website_container a").first
        if not control.count():
            return _leave_website_media(
                side, fixture, extra, screen, cleanup=cleanup, pictures=None,
                notes="the editor did not open on the fixture page and no Edit control "
                      "was present")
        control.click()
        root.locator(".o-snippets-menu, #oe_snippets, .o_we_website_top_actions").first.wait_for(
            timeout=TIMEOUT)
    side.settle(2500)
    extra["editor"] = "open"

    # The page is an iframe inside the editor; the editor holds two preview
    # frames, the page and the hidden fallback it navigates through, and which
    # is first in the DOM is not a contract
    # (`e2e_ingress_hand_checks.preview_frames` carries the same note). #243
    # picked "the first visible image" and got the website logo, which is why
    # this looks for the fixture's own `alt` instead: the element under test is
    # named, so a frame holding some *other* image can no longer stand in for it.
    frames = [handle.content_frame()
              for handle in root.locator(".o_website_preview iframe").element_handles()]
    image = None
    for candidate in frames:
        if candidate is None:
            continue
        option = candidate.locator('img[alt="%s"]' % FIXTURE_IMAGE_ALT).first
        try:
            if option.count() and option.is_visible():
                image = option
                break
        except Exception:  # noqa: BLE001 -- a frame that navigated away
            continue
    if image is None:
        return _leave_website_media(
            side, fixture, extra, screen, cleanup=cleanup, pictures=None,
            notes="no preview frame held the fixture image (img[alt=%r]); the page was "
                  "created but the editor did not render it" % FIXTURE_IMAGE_ALT)
    try:
        image.scroll_into_view_if_needed(timeout=15000)
    except Exception:  # noqa: BLE001 -- already in view
        pass
    extra["element"] = {
        "src": side.env.mask(image.get_attribute("src")),
        "data_original_src": side.env.mask(image.get_attribute("data-original-src")),
        "data_mimetype_before_conversion": image.get_attribute(
            "data-mimetype-before-conversion"),
    }
    image.click()
    side.settle(2000)
    # Read the attribute **again**, after the click and before the dialog. Two
    # things in the image tools run in that window and either would turn rule
    # 2's branch into rule 1's with nothing in the record to say so:
    # `_initializeImage` loads `data-original-src` and **deletes** the whole
    # `data-original-*` group when that load is rejected
    # (`snippets.options.js:7679-7686`), and `loadImageInfo` overwrites the
    # attribute from `/web_editor/get_image_info` unless
    # `data-mimetype-before-conversion` is already present
    # (`image_processing.js:490-496`). The fixture carries that attribute so the
    # second does not happen; this reading is how that is known rather than
    # assumed.
    extra["element_after_select"] = {
        "src": side.env.mask(image.get_attribute("src")),
        "data_original_src": side.env.mask(image.get_attribute("data-original-src")),
    }
    replace = root.locator(REPLACE_WEBSITE).first
    if replace.count():
        extra["replace_control"] = REPLACE_WEBSITE
    else:
        replace = root.locator(REPLACE_LEGACY).first
        extra["replace_control"] = REPLACE_LEGACY
    if not replace.count():
        return _leave_website_media(
            side, fixture, extra, screen, cleanup=cleanup, pictures=None,
            notes="neither the ReplaceMedia snippet option nor #media-replace was present "
                  "for the selected image")
    replace.click()
    reading = media_dialog_reading(side)
    extra["dialog"] = reading
    pictures, notes = _media_verdict(reading, side)
    close_media_dialog(side)
    return _leave_website_media(side, fixture, extra, screen, cleanup=cleanup,
                                pictures=pictures, notes=notes)


def _leave_website_media(side, fixture, extra, screen, *, cleanup, pictures,
                         notes) -> dict[str, Any]:
    """Every exit from `media-image-website`: discard the editor, then clean up.

    Same reason as `_leave_media_todo`. This check creates an `ir.attachment`,
    a `website.page` and an `ir.ui.view` before its first navigation, and three
    of its four exits are give-up paths -- so the discard and the removal belong
    in one place rather than repeated at each of them.
    """
    _discard_website_editor(side)
    if cleanup:
        extra["fixture_removed"] = remove_website_fixture_page(side, fixture)
    return {"screen": screen, "pictures": pictures, "stored": {}, "extra": extra,
            "notes": notes}


def _discard_website_editor(side) -> None:
    """Leave the editor without saving, the way `U-D2` does."""
    try:
        side.root.locator(
            "button[data-action='cancel'], .o_we_website_top_actions button"
        ).filter(has_text=re.compile("Discard")).first.click()
        side.settle(1000)
        dialog = side.root.locator(".o_dialog footer button.btn-primary")
        if dialog.count():
            dialog.first.click()
            side.settle(800)
    except Exception:  # noqa: BLE001 -- nothing to discard
        pass


# --- #238: the mail designer, and the two fields a save writes -----------------

# The designer's own iframe, read from `mass_mailing_html_field.js`: its
# `contentDocument` holds `#iframe_target` (:224) and the editable `.note-editable`
# (:176), and the theme chooser is `.o_mail_theme_selector_new` (:259) whose theme
# links carry the theme name as their element id (`xml/mass_mailing.xml:25-27`).
# Editing is blocked until a theme is picked, and `basic` is the plain one
# (:455, :729).
MAILING_IFRAME = MAILING_BODY + " iframe"
MAILING_EDITABLE = ".note-editable"
MAILING_THEME_SELECTOR = ".o_mail_theme_selector_new"
MAILING_THEME_BASIC = "a#basic, #basic"

# A root-relative picture, so there is something for the rules to get wrong.
MAILING_BODY_TEMPLATE = (
    '<div class="o_layout"><p>%s</p>'
    '<img src="/web/image/res.company/1/logo" alt="logo"></div>'
)


def mailing_body_value(run_id: str) -> str:
    """The seeded mailing body, naming the run that seeded it."""
    return MAILING_BODY_TEMPLATE % marker_for(run_id)


MAILING_BODY_VALUE = MAILING_BODY_TEMPLATE % "WOOW parity"


def body_html_marked(run_id: str, read: Mapping[str, Any]) -> bool:
    """Is this run's typed marker in the `body_html` of a `read` of the mailing?

    The field can come back `False` rather than a string on either side of the
    save: `create_fixture_mailing` leaves it unset, the seed clears it on a row
    this check owns (#286), and a save that never inlined leaves it that way.
    """
    return marker_for(run_id) in (read.get("body_html") or "")


def body_html_inlined(run_id: str, before: Mapping[str, Any],
                      after: Mapping[str, Any]) -> bool:
    """Did **this** save's `commitChanges` build `body_html` (rule 8)?

    The marker is the discriminator because of which *field* the seed writes: it
    writes `body_arch` -- where the marker also sits, `mailing_body_value` puts it
    there -- and leaves `body_html` empty, so rule 8 is the only thing in this
    check that can carry the marker across.

    "Present after the save" is not that reading though, and #279 is where the
    difference shows: `--run-id` is one value for the whole invocation and
    `--surface both` drives the check on both surfaces against one database, so
    without `--cleanup` the second surface's `scratch_mailing_id` reclaims the
    first surface's scratch row -- by design, the subject is this run's. Its
    `body_html` already holds `marker_for(run_id)` from the first save, so a
    second save that stored only `body_arch` would read as inlined.

    So the marker has to be **newly** present: in `after` and not in the value
    the field held when the browser half began. `body_html_baseline` is that
    value and it is already in hand, so this costs no further read, and the
    reading closes a re-run of the *same* surface under one run id as well, which
    a surface-specific marker would not.

    **On a row this check owns the seed clears the field** (#286), so both
    readings are available there: `false` is a save that never inlined, `true` is
    this save's own doing. The clear is gated on the fixture carrying a scratch
    row -- the seeder is where that gate's argument is -- so on the one row it is
    withheld on, the one `--mailing-id` named, a marker already in the field
    leaves this `false` whichever way the save went. That is the direction to fail
    in for a reading whose whole job is to refuse a false pass --
    `stored_verdict(False)` is `CLEAN`, so "inlined" is the claim that needs the
    evidence -- and `body_html_marker_before` beside it says which of the two
    `false`s it is. A positive reading on that row wants a run id of its own.
    """
    return body_html_marked(run_id, after) and not body_html_marked(run_id, before)


def body_html_baseline(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    """The reading `body_html_inlined` measures a save's own output against (#286).

    `fixture["seeded"]` on a row this check owns -- what the seed left the field
    as, which is empty -- and the pre-run read on the one row it does not, where
    the clear is withheld and #279's reading stands exactly as it was: a marker
    already in the campaign `--mailing-id` named is no evidence that *this* save
    inlined it. `fixture["before"]` is empty until it has been read, which is how
    the give-up paths leave it and why neither key is assumed present.
    """
    return fixture.get("seeded") or fixture.get("before") or {}


def mailing_body_html_reading(fixture: Mapping[str, Any]) -> str:
    """Which kind of Stored reading `mailing-editable`'s `body_html` carries (#289).

    The same gate `body_html_baseline` turns on, and for the same reason. On a row
    this check owns the seed cleared the field (#286), so what the save leaves in
    it is this save's own output and a prefix there is this save's
    `commitChanges` leaking: **write-bounding**, which is what the check means
    that reading to be. On the one row the clear is withheld on -- the campaign
    `--mailing-id` named -- the field still holds whatever that campaign held, so
    a save that never inlined leaves a value this check did not write:
    **state-bounding**. #286 fixed four of the five sites' worth of this at the
    write and could not fix this one, because an ungated clear would blank a real
    campaign's body.
    """
    return WRITE_BOUNDING if fixture.get("seeded") else STATE_BOUNDING


def document_mailing_body_html_reading(fixture: Mapping[str, Any],
                                       after: Mapping[str, Any]) -> str:
    """Which kind `media-document-mailing`'s `body_html` carries (#289). Derived.

    This is the site where a flat declaration would throw the reading away. The
    check never writes this field -- it discards the form on purpose and the
    read-back exists to prove the discard worked -- so on a borrowed draft the
    value is the campaign's own: state-bounding. But if the discard did *not*
    hold, the save that got through is exactly what inlines `body_html`
    (`commitChanges`, #238 rule 8), and a prefix in what it wrote is then this
    check's own leak: write-bounding, and the discard failing is this check's
    subject rather than the row's history.

    Which of the two happened is not declarable in advance, and it is not
    guessable from the value either -- the campaign's own body may have held a
    prefix for months. It is **the change** that separates them, and the baseline
    is already in hand: `fixture["before"]` is read before the seed and is the
    restore source besides, so deriving this costs no further read. ADR 0014's
    attribution option is what allows a derivation at all; a suppression would
    have had to pick one of the two answers and be wrong half the time.

    A fixture that never reached its `before` read has no baseline -- the give-up
    paths leave it that way -- and that is state-bounding rather than unknown: a
    handler that got no further than its seed never navigated, so no save of its
    could have reached the field.
    """
    before = fixture.get("before") or {}
    if "body_html" not in before:
        return STATE_BOUNDING
    return (WRITE_BOUNDING if after.get("body_html") != before.get("body_html")
            else STATE_BOUNDING)


def do_mailing_editable(side, run_id: str, *, mailing_id=None, cleanup=False, **_) -> dict[str, Any]:
    """#238 lines 1 and 2: the designer loads, and the save stores **two** fields.

    `body_arch` goes through `getEditingValue` (rule 7). `body_html` does not:
    `commitChanges` builds it separately by cloning the editable into a `srcdoc`
    iframe and running `toInline` over it (rule 8), and it is the field that
    **leaves the installation** with the mail. A run that reads back only
    `body_arch` has measured half the fix.

    If the designer renders blank under Ingress, the first place to look is *not*
    these rules: the editor iframe is built with `document.write`, so no Runtime
    shim runs inside it, and its `<script src>` tags come from the generic HTML
    location's `"src": "/` rewrite of `/web/bundle` JSON.

    **It builds its own mailing, and it borrows nothing** (#276). Until #276 this
    check only *looked up* a `draft` or `in_queue` mailing, so it recorded
    `NOT-RUN` on a database that carries none -- a fresh install, a catch-up
    database, the local add-on's own -- which is exactly what happened to
    `media-document-mailing` on #271's run before #274. The other half is worse
    here than it was there: this check **saves**, so a run stored its marker body
    in both fields of a mailing somebody else made, and `--cleanup` -- which
    writes them back -- is optional. Nothing is lost by building the row: the
    save seam is the same on a scratch mailing as on a real one, because the
    designer, `getEditingValue` and `commitChanges` do not care which record they
    are on. `--mailing-id` is the one way to point it at a real campaign, and the
    restore stays in the check for it.
    """
    fixture = seed_editable_mailing_fixture(side, run_id, mailing_id)
    extra = fixture["extra"]
    screen = "/odoo/mailing.mailing/%d (mail designer)" % fixture["mailing_id"]
    try:
        return _mailing_after_seeding(side, fixture, run_id, cleanup=cleanup)
    except Exception as error:
        # Discard first, then restore, then return the partial readings rather
        # than re-raising: a handler that raises has its return value discarded
        # by `run_check`, and the readings are the whole value of a failed
        # attempt. The discard is not optional on this path and this is where it
        # matters most: the typing is already done when a step fails, so the form
        # is dirty, and `run_check` closes the session *after* this return --
        # a `beforeunload` save there would write this run's body back over the
        # restore made two lines below and the record would still say
        # `body_restored: true`.
        _discard_unsaved_form(side, extra)
        _restore_borrowed_mailing_body(side, fixture, extra)
        if cleanup:
            extra["fixture_removed"] = _remove_mailing_fixture(side, fixture)
        return {"screen": screen, "pictures": None, "stored": {}, "extra": extra,
                "notes": "%s: %s" % (type(error).__name__,
                                     adapter.sanitize_diagnostic(str(error))[:300])}
    except BaseException:
        # Same reason as `do_codeview`: this replaced a mailing's body, every
        # step after it can raise, and `run_check` discards the outcome on a
        # raise. The removal is unconditional here and not under `--cleanup`,
        # as in `do_media_document_mailing`: an interrupted run is nobody's to
        # come back and tidy.
        try:
            _discard_unsaved_form(side, extra)
            _restore_borrowed_mailing_body(side, fixture, extra)
            _remove_mailing_fixture(side, fixture)
        except Exception:  # noqa: BLE001 -- the session itself may be gone
            pass
        raise


def seed_editable_mailing_fixture(side, run_id: str, mailing_id) -> dict[str, Any]:
    """The mailing `mailing-editable` drives, and this run's marker body in it.

    `fixture_mailing` with `borrow=False`, which is the decision #276 owns: a
    real draft on the database is left alone and this check builds its own row
    beside it, because this is the mailing check that saves. Everything else is
    `seed_document_mailing_fixture`'s shape without the attachment -- the same
    guard, for the same reason: `run_check` discards a handler's return value
    when it raises, so a failure between the `create` and the body write would
    leave a `mailing.mailing` on the host with nothing in the evidence naming it.

    **The screen is the same whichever way the mailing arrived.** The designer's
    theme chooser -- the one thing that could stand between a brand-new mailing
    and the editable -- is appended only when
    `value === "" || value === blankEditable`
    (`mass_mailing_html_field.js:520-534`), and the value it reads is the
    `body_arch` written here: a non-empty `.o_layout` div in every case. The
    chooser is still handled in the browser half, for a seed that did not take.
    """
    chosen = fixture_mailing(side, run_id, mailing_id, borrow=False)
    mailing_id, scratch = chosen["mailing_id"], chosen["scratch"]
    extra: dict[str, Any] = {"mailing_id": mailing_id,
                             "mailing_source": chosen["source"], "fixture": {}}
    fixture: dict[str, Any] = {"mailing_id": mailing_id, "scratch_mailing": scratch,
                               "attachment": None, "before": {}, "extra": extra}
    try:
        if scratch is not None:
            # What this run will remove, for a later reader who has to find it.
            # `mailing_reclaimed` separates the row this run made from the one an
            # earlier run left, since only the first is news.
            extra["fixture"] = {
                "mailing_id": scratch["id"],
                "mailing_subject": scratch["subject"],
                "mailing_state": scratch["state"],
                "mailing_reclaimed": chosen["source"] == "reclaimed",
            }
            # #277, and first because every step below it can fail while the
            # compensation deletes the row these ids live in.
            reclaim_stranded_attachments(side, fixture, extra)
        before = side.rpc("mailing.mailing", "read",
                          [[mailing_id], ["body_arch", "body_html"]])[0]
        fixture["before"] = before
        extra["body_arch_before"] = redact(before.get("body_arch") or "", {})
        # Whether the marker was on the row **before this run touched it**,
        # recorded where it is read: without it a record showing this run's marker
        # in the stored `body_html` beside `body_html_inlined: false` cannot be
        # explained from itself (#279). Whether the marker was in it, and not the
        # value -- the reading is that one bit, and the field's own value is what
        # `stored` carries. It is read before the seed write, which since #286
        # clears that field on a row this check owns.
        extra["body_html_marker_before"] = body_html_marked(run_id, before)
        # Seeded over RPC so the value under test is exactly the measured one, and
        # so the check does not also depend on the designer's own typing working.
        #
        # **`body_html` is cleared in the same write, on a row this check owns**
        # (#286). That field's Stored reading is meant to be write-bounding -- a
        # prefix in it is *this* save's `commitChanges` leaking -- and on a
        # reclaimed row it was not: the value read back after a save that stored
        # only `body_arch` was the earlier surface's inlined body, and
        # `stored_verdict` judges every field it is handed, so the record
        # attributed to one surface a prefix the other surface's save wrote.
        # Suppressing that judgement is refused by ADR 0014; the correction is
        # here, at the write, so what comes back is this save's output and
        # nothing else.
        #
        # **The gate is `_restore_borrowed_mailing_body`'s own guard inverted**,
        # and that is what makes the clear safe: the two are exact inverses, so it
        # can never blank a value the restore would have put back. `created` is a
        # no-op, since the field is already `False`; `reclaimed` is the case this
        # fixes, this driver's own litter; `given` is the row the operator named,
        # whose inlined body an ungated clear would blank with the restore running
        # under `--cleanup` only; and `found` is unreachable, because this check
        # passes `borrow=False`. One write carrying both fields, the shape
        # `_restore_mailing_body` already uses on this model.
        seed: dict[str, Any] = {"body_arch": mailing_body_value(run_id)}
        if scratch is not None:
            seed["body_html"] = False
        side.rpc("mailing.mailing", "write", [[mailing_id], seed])
        if "body_html" in seed:
            # What the seed left the field as, which is the value
            # `body_html_inlined` compares the save against -- recorded once the
            # write has taken, and *beside* `fixture["before"]` rather than over
            # it: that reading is the restore source and the evidence of the row's
            # pre-run state, and the same fixture shape is shared with the
            # document-mailing seeder.
            fixture["seeded"] = {"body_html": seed["body_html"]}
    except BaseException:
        _abandon_mailing_fixture(side, fixture, extra, "mailing-editable")
        raise
    return fixture


def _mailing_after_seeding(side, fixture, run_id, *, cleanup=False) -> dict[str, Any]:
    """The browser half of `do_mailing_editable`, split out for the same reason."""
    mailing_id = fixture["mailing_id"]
    extra = fixture["extra"]
    screen = "/odoo/mailing.mailing/%d (mail designer)" % mailing_id
    side.goto("/odoo/mailing.mailing/%d" % mailing_id)
    side.wait_webclient()
    side.close_chat_windows()
    side.settle(3000)

    handles = side.root.locator(MAILING_IFRAME).element_handles()
    frame = next((handle.content_frame() for handle in handles if handle.content_frame()), None)
    extra["rendered_iframe"] = frame is not None
    if frame is None:
        return _mailing_editable_leaving(side, fixture, extra, screen, cleanup=cleanup,
                                         pictures=None, stored={}, readings={},
                                         notes=(
            "the mail designer rendered no iframe; look at the generic HTML location's "
            "\"src\": \"/ rewrite of /web/bundle JSON before these rules"))
    if frame.locator(MAILING_THEME_SELECTOR).count():
        basic = frame.locator(MAILING_THEME_BASIC).first
        if basic.count():
            basic.click()
            side.settle(3000)
            extra["theme"] = "basic"
    editable = frame.locator(MAILING_EDITABLE).first
    if not editable.count():
        return _mailing_editable_leaving(side, fixture, extra, screen, cleanup=cleanup,
                                         pictures=None, stored={}, readings={},
                                         notes=(
            "the designer's iframe held no %s editable" % MAILING_EDITABLE))
    pictures = read_pictures(frame, MAILING_EDITABLE + " img", side)

    # Type into the designer so the form is **dirty**. The body was seeded over
    # RPC, so the form loads clean and the save button, while present in the DOM,
    # stays hidden behind `o_form_status_indicator_buttons.invisible` -- clicking
    # it then times out as not actionable. Typing is also what #238's row asks
    # for: the two rules are the save seam, and a save of an unchanged record
    # writes nothing for them to act on.
    try:
        editable.click()
        side.page.keyboard.press("Control+End")
        side.page.keyboard.type(" " + marker_for(run_id))
        side.settle(1500)
        extra["typed"] = True
    except Exception as error:  # noqa: BLE001
        extra["typed"] = False
        extra["typing_error"] = type(error).__name__

    save = side.root.locator(SAVE_BUTTON).first
    extra["save_visible"] = save.is_visible() if save.count() else False
    if not extra["save_visible"]:
        # Without the save, #238's whole subject is untouched: `getEditingValue`
        # (rule 7) never runs and `commitChanges` never inlines `body_html` (rule
        # 8). And `body_arch` read back would be the value *this run* seeded over
        # RPC -- root-relative, so `CLEAN` -- which with the pictures already
        # read would score a pass for a check that exercised neither rule. The
        # form is loaded clean precisely because the seed was an RPC write, so this
        # path is likely rather than hypothetical.
        extra["saved"] = False
        return _mailing_editable_leaving(side, fixture, extra, screen, cleanup=cleanup,
                                         pictures=None, stored={}, readings={},
                                         notes=(
            "%s never became visible, so nothing was saved: the two rules this "
            "check is about are the save seam, and a read-back of the RPC-seeded "
            "body_arch would have scored a pass without exercising either"
            % SAVE_BUTTON))
    save.click()
    side.settle(6000)
    extra["saved"] = True
    extra["unsaved_after_save"] = side.root.locator(UNSAVED).count() > 0
    if extra["unsaved_after_save"]:
        extra["save_incomplete"] = True
    after = side.rpc("mailing.mailing", "read", [[mailing_id], ["body_arch", "body_html"]])[0]
    stored = {
        "mailing.mailing.body_arch": after.get("body_arch"),
        "mailing.mailing.body_html": after.get("body_html"),
    }
    # `body_arch` is write-bounding at every branch -- this check seeded it and
    # has just saved it through `getEditingValue`, so a prefix in it is this
    # save's. `body_html` is the one the gate decides (#289).
    readings = {
        "mailing.mailing.body_arch": WRITE_BOUNDING,
        "mailing.mailing.body_html": mailing_body_html_reading(fixture),
    }
    # **Did rule 8 run at all?** Building the row (#276) makes `False` the
    # baseline for `body_html`, and `stored_verdict(False)` is `CLEAN` -- so a
    # save that stored `body_arch` and never inlined `body_html` would score a
    # pass for the one field this check exists to measure, the field that leaves
    # the installation with the mail. The marker the designer typed is what
    # separates "inlined, and root-relative" from "never inlined", and it has to
    # be *newly* there: on a reclaimed row the marker was already in `body_html`
    # (#279), so the reading is against what the field held when this half began
    # -- `body_html_baseline`, which the seed's clear (#286) makes empty on a row
    # this check owns and which is the pre-run read on the one row it does not.
    # Recorded rather than judged, for the reason `_media_verdict` is: a verdict
    # here would make this check's `PARITY` depend on a mechanism that is not its
    # subject.
    extra["body_html_inlined"] = body_html_inlined(run_id, body_html_baseline(fixture), after)
    return _mailing_editable_leaving(side, fixture, extra, screen, cleanup=cleanup,
                                     pictures=pictures, stored=stored,
                                     readings=readings, notes="")


def _mailing_editable_leaving(side, fixture, extra, screen, *, cleanup, pictures,
                              stored, readings, notes) -> dict[str, Any]:
    """Leave the designer: restore what was borrowed, remove what was made.

    Every exit from the check comes through here, so a run that gave up early
    still undoes its seed. That is the trap and not tidiness: the body is written
    over RPC **before** the first navigation, three of the four exits above are
    give-up paths, and the restore used to sit only on the path that had saved --
    so a `--cleanup` run that gave up at the iframe left this run's marker body
    in a borrowed `body_arch`.

    `stored` arrives as a parameter rather than being read here -- and `readings`
    with it, because the two travel together: `evidence_record` pairs them by
    field and refuses a value with no kind declared (#289) -- which is the one
    way this differs from `_document_mailing_leaving`. #238's two rules **are**
    the save seam, and on a path where nothing was saved the read-back would
    return the RPC-seeded `body_arch` -- root-relative by construction, so
    `CLEAN` -- and score a pass for a check that exercised neither rule. Only the
    path that saved has a reading to pass.

    **The restore is not under `--cleanup` and the removal is** (#297). The two
    answer different questions, and this check is where the difference costs the
    most: the only row it can borrow is the one `--mailing-id` named, that row is
    a real campaign in `draft` or `in_queue` -- a row that can still be *sent* --
    and this is the check that clicks save, so without the restore it keeps this
    run's marker in `body_arch` **and** in the inlined `body_html` that leaves
    the installation with the mail. Naming a row licenses using it, not keeping
    it altered. `_restore_borrowed_mailing_body` is a no-op on a scratch or
    reclaimed row, so calling it on every path cannot restore what this run owns.
    """
    _discard_unsaved_form(side, extra)
    _restore_borrowed_mailing_body(side, fixture, extra)
    if cleanup:
        extra["fixture_removed"] = _remove_mailing_fixture(side, fixture)
    return {"screen": screen, "pictures": pictures, "stored": stored,
            "readings": readings, "extra": extra, "notes": notes}


# --- #239 line 3 on the legacy editor (#266) ----------------------------------


def do_media_document_mailing(side, run_id: str, *, mailing_id=None, cleanup=False,
                              **_) -> dict[str, Any]:
    """#239 line 3, on the one editor that has a control for it.

    `media-document-todo` records the current editor as unreachable, and it is
    right: Replace is namespaced to `image`, a document is an `a.o_image`, and
    `html_editor` does not even produce one any more -- its document selector
    renders a `span.o_file_box` whose whole subtree suppresses the toolbar. The
    **legacy** dialog is the other half of the sentence, and it is the one the
    mail designer opens.

    **The control is there, and the fixture decides whether it is usable.**
    `#media-replace` is un-hidden for anything matching
    `img, .fa, .o_image, .media_iframe_video` -- `.o_image` included, and it is
    the one case the snippets sidebar does not steal the button from, because
    that only happens for an `img`. But twelve lines further on the same
    function hides the whole toolbar for a media whose `data-mimetype` is not an
    image, and the dialog's own `createElements` always stamps `data-mimetype`
    on a document. So on a faithful fixture -- which is what this check builds,
    the anchor spelled exactly as the dialog writes one -- the toolbar is hidden
    and `#media-replace` is **not** the way in. A double-click is: it is bound
    on the same selector, it has no mimetype guard, and it calls
    `openMediaDialog` with the anchor. Both are tried and which one worked is
    recorded, because "the control that was looked for" is half of what #266
    asks of this line.

    **It is still a no-change check.** Both operands of the comparison arrive
    prefixed -- the element's `href` by the Runtime shim's `setAttribute`
    wrapper and by `IN`, and the literal `` `/web/content/${attachment.id}` ``
    by one of the generic literal rules the asset location has shipped since
    #166, because it begins `` `/web/ ``. No `OUT` was shipped for it and a
    Static-tier test refuses one. So a tile **not** highlighted here is new
    information, and is reported against #239 rather than recorded as a partial
    fix.

    **Nothing is meant to be saved, and three different things carry that
    rather than the sentence.** Clicking inside the designer's editable can
    leave the form dirty, and an Odoo form persists a dirty editor on
    `beforeunload` and on `visibilitychange` without the record being dirty at
    all (#263 is the same mechanism on the To-do form). So: the form is
    **discarded** whenever it shows unsaved changes, which is what stops the
    save; `body_arch` and `body_html` are **read back** into `stored`, where
    `stored_verdict` judges them, so a prefixed `href` that reached the record
    *during* the check fails it; and because this read-back happens before
    `run_check` closes the session, a save that a `beforeunload` on that close
    would make is outside it and is covered by the host reading the evidence
    takes afterwards. Saying which of the three answers which window is the
    point -- a read-back alone would not have covered the close.

    **It builds its mailing too, and the two outcomes are not the same** (#274).
    This was the one member of the family that still *looked up* a record it
    needed -- `odoo_parity` happens to carry a draft mailing, so every recorded
    run found one, and the gap appeared the moment the check was pointed
    anywhere else: #271's run, on a `catchup164b` where `mass_mailing` had been
    installed minutes earlier, got `NOT-RUN` and had to seed a mailing by hand
    over `odoo shell`. A mailing this check **made** is named after the run,
    recorded in `extra["fixture"]` beside the attachment, and **deleted** under
    `--cleanup`; a mailing it **borrowed** has both fields written back and is
    never deleted, because #266's lesson is that a check which deletes what it
    did not create is how the next run ends up with nothing to measure.
    `--mailing-id` keeps its meaning: reuse this one, do not create, do not
    delete. A scratch mailing an earlier surface or run left behind is
    **reclaimed** rather than borrowed, so it does not become permanent litter
    no `--cleanup` can reach.

    `--cleanup` removes what this run made and restores what it borrowed.
    """
    fixture = seed_document_mailing_fixture(side, run_id, mailing_id)
    extra = fixture["extra"]
    screen = "/odoo/mailing.mailing/%d (mail designer, document)" % fixture["mailing_id"]
    try:
        return _document_mailing_after_seeding(side, fixture, extra, cleanup=cleanup)
    except Exception as error:
        # The discard belongs on this path for the reason the docstring gives
        # above: the element has been clicked by the time most steps can fail,
        # and `run_check` closes the session after this return. Only the exits
        # through `_document_mailing_leaving` used to have it.
        _discard_unsaved_form(side, extra)
        _restore_borrowed_mailing_body(side, fixture, extra)
        if cleanup:
            extra["fixture_removed"] = _remove_mailing_fixture(side, fixture)
        return {"screen": screen, "pictures": None, "stored": {}, "extra": extra,
                "notes": "%s: %s" % (type(error).__name__,
                                     adapter.sanitize_diagnostic(str(error))[:300])}
    except BaseException:
        try:
            _discard_unsaved_form(side, extra)
            _restore_borrowed_mailing_body(side, fixture, extra)
            _remove_mailing_fixture(side, fixture)
        except Exception:  # noqa: BLE001 -- the session itself may be gone
            pass
        raise


def seed_document_mailing_fixture(side, run_id: str, mailing_id) -> dict[str, Any]:
    """The whole fixture for `media-document-mailing`, and where it came from.

    The mailing comes from `fixture_mailing`, which holds the four ways to one
    and what each makes `--cleanup` answerable for. This check passes
    `borrow=True`: it never saves -- it discards the form and reads the record
    back to prove it -- so the only write a borrowed row takes is a `body_arch`
    this same run writes back, and borrowing is what keeps the check measuring
    the screen an operator's own mailing renders. `mailing-editable` answers the
    same question the other way, and `fixture_mailing` says why (#276).

    Everything after the first `create` is guarded, as in `seed_media_task` and
    `seed_website_fixture_page`: `run_check` discards a handler's return value
    when it raises, so a step failing in here would otherwise leave a public
    `ir.attachment` -- and now a mailing beside it -- on the host with nothing in
    the evidence naming them. The restore is in that path too, because the body
    write is the last step and a borrowed row must not keep this run's body just
    because the step after it failed.

    **The screen is the same whichever way the mailing arrived**, which is what
    makes a created one measurable rather than merely present. The designer's
    theme chooser -- the one thing that could have stood between a brand-new
    mailing and the editable -- is appended only when
    `value === "" || value === blankEditable`
    (`mass_mailing_html_field.js:520-534`), and the value it reads is the
    `body_arch` this seeder has already written: an `.o_layout` div in all three
    cases. The chooser is still handled in the browser half, for a seed that did
    not take.
    """
    chosen = fixture_mailing(side, run_id, mailing_id, borrow=True)
    mailing_id, scratch, source = (chosen["mailing_id"], chosen["scratch"],
                                   chosen["source"])
    extra: dict[str, Any] = {"mailing_id": mailing_id, "mailing_source": source,
                             "fixture": {}}
    fixture: dict[str, Any] = {"mailing_id": mailing_id, "scratch_mailing": scratch,
                               "attachment": None, "before": {}, "extra": extra}
    try:
        if scratch is not None:
            # Beside the attachment below, because the two are the same kind of
            # thing now: rows this run will remove, which a later reader may have
            # to find. `mailing_reclaimed` separates the row this run made from
            # the one an earlier run left, since only the first is news.
            extra["fixture"].update({
                "mailing_id": scratch["id"],
                "mailing_subject": scratch["subject"],
                "mailing_state": scratch["state"],
                "mailing_reclaimed": source == "reclaimed",
            })
            # #277, and ahead of the attachment this run builds: every step
            # below can fail, and the compensation that follows deletes the
            # reclaimed row whose body these ids are read from.
            reclaim_stranded_attachments(side, fixture, extra)
        attachment = create_fixture_attachment(side, run_id, document=True)
        fixture["attachment"] = attachment
        extra["fixture"].update({
            "attachment_id": attachment["id"],
            "attachment_name": attachment["name"],
            "href": "/web/content/%d" % attachment["id"],
        })
        before = side.rpc("mailing.mailing", "read",
                          [[mailing_id], ["body_arch", "body_html"]])[0]
        fixture["before"] = before
        extra["body_arch_before"] = redact(before.get("body_arch") or "", {})
        # Seeded over RPC for `do_mailing_editable`'s reason: the value under test
        # is then exactly the measured one, and the check does not also depend on
        # the designer's own insertion working.
        write_field(side, "mailing.mailing", mailing_id, "body_arch",
                    mailing_document_body_value(run_id, attachment))
    except BaseException:
        _abandon_mailing_fixture(side, fixture, extra, "media-document-mailing")
        raise
    return fixture


def _document_mailing_after_seeding(side, fixture, extra,
                                    *, cleanup=False) -> dict[str, Any]:
    """The browser half of `do_media_document_mailing`."""
    mailing_id = fixture["mailing_id"]
    screen = "/odoo/mailing.mailing/%d (mail designer, document)" % mailing_id
    side.goto("/odoo/mailing.mailing/%d" % mailing_id)
    side.wait_webclient()
    side.close_chat_windows()
    side.settle(3000)

    handles = side.root.locator(MAILING_IFRAME).element_handles()
    frame = next((handle.content_frame() for handle in handles if handle.content_frame()), None)
    extra["rendered_iframe"] = frame is not None
    if frame is None:
        return _document_mailing_leaving(side, fixture, extra, screen,
                                         cleanup=cleanup, pictures=None, notes=(
            "the mail designer rendered no iframe; look at the generic HTML location's "
            "\"src\": \"/ rewrite of /web/bundle JSON before this check's own subject"))
    # The theme chooser only appears on an empty body, and the body was seeded.
    # Kept because a mailing whose seed did not take would otherwise block on a
    # chooser nothing clicks.
    if frame.locator(MAILING_THEME_SELECTOR).count():
        basic = frame.locator(MAILING_THEME_BASIC).first
        if basic.count():
            basic.click()
            side.settle(3000)
            extra["theme"] = "basic"

    document = frame.locator(MAILING_EDITABLE + " " + DOCUMENT_LINK).first
    if not document.count():
        return _document_mailing_leaving(side, fixture, extra, screen,
                                         cleanup=cleanup, pictures=None, notes=(
            "the designer's editable held no %s; the seeded body_arch did not survive the "
            "field" % DOCUMENT_LINK))
    extra["element"] = {
        "href": side.env.mask(document.get_attribute("href")),
        "data_original_src": side.env.mask(document.get_attribute("data-original-src")),
        "data_mimetype": document.get_attribute("data-mimetype"),
    }
    extra["operand"] = document_operand_reading(
        side, module=LEGACY_DOCUMENT_SELECTOR, dialog="legacy")

    # One click first: it is what sets `lastMediaClicked` and so what decides
    # whether `#media-replace` is usable at all. `force` because a document box
    # can be laid out with zero size until the editor's own stylesheet sizes it,
    # and Playwright then refuses the click as not actionable -- a fixture
    # property, not a finding.
    document.click(force=True)
    side.settle(1500)
    # The legacy toolbar is rendered outside the designer's iframe on some
    # screens and inside it on others, so look in both and say where it was.
    replace = None
    for where, root in (("page", side.root), ("iframe", frame)):
        candidate = root.locator(REPLACE_LEGACY).first
        if candidate.count():
            extra["replace_control_found_in"] = where
            replace = candidate
            break
    extra["replace_control_present"] = replace is not None
    visible = False
    if replace is not None:
        try:
            visible = replace.is_visible()
        except Exception:  # noqa: BLE001 -- detached between count and read
            visible = False
    extra["replace_control_visible"] = visible
    if visible:
        extra["replace_control"] = REPLACE_LEGACY
        replace.click()
    else:
        # `wysiwyg.js` hides the whole toolbar for a media carrying a non-image
        # `data-mimetype`, which every dialog-inserted document has. The
        # double-click binding on the same selector has no such guard.
        extra["replace_control"] = "dblclick"
        document.dblclick(force=True)
    side.settle(2000)
    if not side.root.locator(MEDIA_DIALOG).count():
        return _document_mailing_leaving(side, fixture, extra, screen,
                                         cleanup=cleanup, pictures=None, notes=(
            "neither %s (present: %s, visible: %s) nor a double-click reopened the legacy "
            "media dialog on the document link" % (REPLACE_LEGACY,
                                                   extra["replace_control_present"], visible)))
    reading = media_dialog_reading(side, tab="Documents")
    extra["dialog"] = reading
    pictures, notes = _media_verdict(reading, side)
    close_media_dialog(side)
    return _document_mailing_leaving(side, fixture, extra, screen,
                                     cleanup=cleanup, pictures=pictures, notes=notes)


def _document_mailing_leaving(side, fixture, extra, screen,
                              *, cleanup, pictures, notes) -> dict[str, Any]:
    """Leave the designer, read the two fields back, and restore.

    Every exit from the check comes through here, so a run that gave up early
    still discards, still reads the record back and still cleans up. A read-back
    that *failed* leaves both `stored` and its declarations empty together, which
    is the only shape `evidence_record` accepts: a field with no kind raises, and
    a kind with no field raises too (#289). The
    read-back is in `stored` on purpose: the only way a prefix could reach the
    database from this check is the dirty-form save, and `stored_verdict` is
    what names it. It bounds the check and not the session -- a save made by a
    `beforeunload` on `run_check`'s own `side.close()` falls after this reading,
    and the evidence's host check is what covers that window.

    **And it takes no `settle` of its own** (#288, which took the seam's out). The
    read-back is an RPC through the request context, so it does not want a quiet
    page for its own sake; what it could want is time for a page-initiated save to
    land before it reads. It does not need to buy that either. When `discarded` is
    `true` the discard's confirmation has waited out `_askChanges`, which resolves
    the model's mutex as well as the field commits, so every save that goes
    through that mutex -- `root.save()`, which is what the ungated
    `visibilitychange` of #263 calls -- had landed before the indicator cleared.
    The one that does not is `urgentSave`, and no sleep bounds that one either: it
    leaves over `navigator.sendBeacon`, fire-and-forget, in the `beforeunload` this
    seam exists to find nothing to save. When `discarded` is `false` or absent the
    form was left dirty and no sleep makes this reading sound -- which is exactly
    what that reading is for, and why the paragraph above bounds the check rather
    than the session.
    """
    _discard_unsaved_form(side, extra)
    stored: dict[str, Any] = {}
    readings: dict[str, str] = {}
    try:
        after = side.rpc("mailing.mailing", "read",
                         [[fixture["mailing_id"]], ["body_arch", "body_html"]])[0]
        stored = {
            "mailing.mailing.body_arch": after.get("body_arch"),
            "mailing.mailing.body_html": after.get("body_html"),
        }
        # One check, one field of each kind -- which is why the declaration is
        # per field and not the register's `writes` row (#289). `body_arch` is
        # this check's own seed, root-relative by construction, so a prefix in it
        # is the dirty-form save's. `body_html` this check never writes, and
        # whether the value in it is nonetheless this check's doing is derived
        # from the pre-run baseline rather than declared.
        readings = {
            "mailing.mailing.body_arch": WRITE_BOUNDING,
            "mailing.mailing.body_html": document_mailing_body_html_reading(fixture, after),
        }
    except Exception as error:  # noqa: BLE001
        extra["read_back_error"] = type(error).__name__
    # Restore on every path, remove only under `--cleanup` (#297). This check
    # borrows on two of its four branches -- `found` takes a real draft whenever
    # the database has one, which is every run on `odoo_parity` -- and its own
    # seed replaces that campaign's `body_arch` before the first navigation. The
    # flag answers "delete what this run made"; it was never an answer to "whose
    # body is in that row now". The call is a no-op on a scratch or reclaimed
    # row, so this cannot restore what the run owns.
    _restore_borrowed_mailing_body(side, fixture, extra)
    if cleanup:
        extra["fixture_removed"] = _remove_mailing_fixture(side, fixture)
    return {"screen": screen, "pictures": pictures, "stored": stored,
            "readings": readings, "extra": extra, "notes": notes}


if __name__ == "__main__":
    raise SystemExit(main())
