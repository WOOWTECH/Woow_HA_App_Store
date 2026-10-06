# Changelog

## 0.4.11 — 2026-10-06

Only #271 changes the image: the gateway no longer prefixes the media dialog's
document domain, so the dialog stops listing generated asset bundles as
documents. Everything else below is parity drivers, Static-tier tests,
evidence and ADR text, none of it in the add-on's runtime -- hence the ~0.1 MiB
download (#303).

### Added
- The Ingress markup family's owed Live-tier checks are run on Release 0.4.10
  (#243), and four of the five rows have a driver they did not have:
  `odoo18ce/tests/e2e_ingress_markup_live.py`, eight checks, each judged against
  an expectation that **differs** by surface -- under Ingress a root-relative
  `src` must resolve under the prefix, on the Public origin at the origin root,
  and the two sides being *equal* is the failure, which is why none of these is
  the adapter's two-surface diff. Its records are the parity plan's fourth
  evidence schema, `woow.ingress-markup/v1`, and like the other two additions it
  does not feed `conservation`. Escape judgement is `adapter.is_prefix_escape`
  and the stored-prefix shape and its redaction come from
  `e2e_collab_peer_snapshot_live`, so neither is reimplemented here.
- Results: #237's four checks `PARITY` on both surfaces, with the iframe path's
  `sandbox` attribute confirming which branch rendered; #238's three lines
  `PARITY`, including the half that matters -- `mailing.mailing.body_html`, the
  inlined field that leaves the installation, read back root-relative after a
  real save from the designer; #240's two halves `PARITY`; #239's image line
  `PARITY`; #234 `CLEAN` on both pairs with `escalate_issue_234_to_blocker:
  false`, so it stays `severity: important`.
- Three screens that were written down wrong, each corrected by a measurement
  rather than a reading of the source. #237's check 2 cannot be taken on
  `project.task.description` (`sanitize_tags=True` strips the `<head>`, so the
  value renders the plain path -- check 1's screen measured twice); its check 1
  is not on the To-do form (`project_todo`'s controller whitelists its cog items
  and filters *Version History* out); and #240's is not the user signature,
  which on this build is served by `o_field_html_mail` and renders an **empty**
  editor, leaving no text to select and so no floating toolbar. Also measured:
  `?debug=1` does **not** survive a navigation here, so it belongs on the form
  navigation itself -- without it the toolbar comes up with seven groups and no
  code view, which reads exactly like a missing button.
- What the run leaves owed, each with an issue rather than a sentence: the
  collaboration transport never delivered on either pair, so #234's `CLEAN` is
  about the save path and not a delivered peer snapshot (#265); `probe` writes
  the field it says it does not, and its constant marker made one reading a
  false `delivered` (#263); the hand-driven drivers emit no `.ambient.json`, so
  #256's accounting has a hole (#264); and two of #239's three lines are still
  unmeasured, one of them needing a fixture carrying `data-original-src` (#266).
- **#239's other two lines are measured, and all four media checks now build what
  they measure** (#266, no Release and no Deploy -- the rules were already in
  0.4.10, and the run reads `rule_in_served_method` **and**
  `legacy_rule_in_served_method` as `true` under Ingress and `false` on the Public
  origin rather than trusting the version number). `media-image-website` builds a
  `website.page` whose stored arch carries one attachment's own `image_src` in
  **both** `src` and `data-original-src` -- the only screen on which that attribute
  can arrive prefixed, because the generic HTML location's `src="/` is a bare
  substring and claims the tail of the longer attribute name, while a field value
  over `call_kw` has its quotes escaped and is untouched. Ingress reads it prefixed
  and selects its tile; the Public origin reads it root-relative and selects the
  same one. A ninth check, `media-document-mailing`, reads the document tile on the
  **legacy** dialog, which the mail designer opens: both surfaces select the
  fixture's tile, and the control the open list implied, `#media-replace`, turns out
  to be **present and hidden** -- the legacy editor hides its whole toolbar for a
  media whose `data-mimetype` is not an image, and the dialog's own
  `createElements` always stamps one on a document, so a double-click is the way in.
  The current editor stays unreachable by construction and now says so from a
  fixture rather than from an empty record.
- Two readings in that first record exist because either would otherwise produce a
  false pass, and both are new: `data-original-src` is read **again after the
  element is selected**, because `ImageTools._initializeImage` deletes the whole
  `data-original-*` group when the attribute fails to load; and the fixture carries
  `data-mimetype-before-conversion`, because without it `loadImageInfo` overwrites
  `data-original-src` with the root-relative value the ORM just returned -- so the
  branch would compare two unprefixed values and pass whether or not the rule
  shipped.
- Why **all four** media checks build their fixtures and not only the two #266
  named: the two it named could measure nothing because the host carries nothing
  for their branches to execute on, and the two it did not could no longer measure
  anything because #243's fixtures were made by hand and correctly cleaned up --
  so the next run found a static module asset with no `ir.attachment` behind it and
  an empty description, and could only say so. Both first attempts are kept in the
  evidence as the reason. Each fixture is one public `ir.attachment` plus one
  record, named after the run, removed by `--cleanup`; `public=True` is what lists
  it whatever record the dialog was opened from, and `order: 'id desc'` with a
  limit of 30 is what makes it the first tile rather than something to search for.
- **One divergence found beside them, filed as #271 rather than against #239.**
  Under Ingress the Documents tab lists every generated asset bundle:
  `DocumentSelector.attachmentsDomain` excludes them with
  `!['url', '=like', '/web/assets/%']`, and that pattern is a string literal in the
  same bundle as the URL literals the Ingress asset location rewrites, so it
  arrives prefixed (the served getter is 383 bytes against 320 -- one prefix
  insertion) and the exclusion matches no stored `url`. The finding is the class:
  a generic literal rewrite reaches **ORM domain literals**, not only URLs.
  #239's severity does not move for it -- the preselection is correct on both
  surfaces and a search domain travels in a request body, so nothing is stored.
- This is also the markup family's first `.ambient.json`, which is what #243's
  evidence said the next run of this family owed: 22 lines beside 22 records,
  `website.track` and `website.visitor` deltas **0** on every line including the
  website editor's five navigations per surface, absolute counts 198 and 59 on
  either side of every window.
- **Every Live driver now names the ambient rows it left, not only the adapter**
  (#264, found by the run above). #256 made the figure the run's own — count
  `website.track` and `website.visitor` after the login and again on the way out,
  write the delta beside the records under their own name with `.ambient.json`
  for its extension (`ingress-open.jsonl` → `ingress-open.ambient.json`) — and
  built it in `crawl` and `open`, which left the three hand-driven drivers
  reconstructing it on the host afterwards: that is exactly what #243's evidence
  had to do, an absolute `website.track` 198 with no before-reading and so no
  delta. `e2e_ingress_markup_live.py` now writes one line per surface per check,
  `e2e_collab_peer_snapshot_live.py`'s `run` one per pair, and
  `e2e_ingress_hand_checks.py` one per invocation — so **a figure file is read one
  JSON object per line**, and the adapter's own, which truncates with its records,
  is the one-line case of that rather than a second format under the same
  extension. The counts go over the
  session's own `search_count` and never over `ssh` (`Operation.COUNT_ROWS`, the
  same seam `SurfaceDriver.count_rows` passes through), and the shared parts live
  in `e2e_menu_action_adapter.py` rather than in three copies: `ambient_accounting`
  takes a `SessionAmbientDriver` wrapping any session with an `rpc` and a
  `context`, and the `True`-is-an-`int` guard that would record a refusing
  controller's boolean as "one row" is `validated_count`, in one place.
- The navigation denominator is **counted and not estimated**, and the record now
  says which quantity it is (`navigation_basis`, a new field in the schema).
  `SurfaceDriver._goto` is the adapter's one navigation call and the hand-driven
  drivers have no equivalent — the hand checks' `editbtn` navigates by clicking a
  link, the markup driver drives a website editor whose preview iframe fetches
  documents on its own account, and the peer snapshot opens a form on two
  sessions — so for those the denominator is every document GET the browser
  context made under the surface's base, off Playwright's `request` event. That
  is an upper bound on page views rather than a count of them, because a redirect
  hop is a document GET that renders nothing, and the field carries that sentence
  beside the number so two files' `navigations` are not read as the same thing. A
  two-session run counts rows over session A — the models are database-wide, so a
  row cannot be attributed to one of two open sessions — sums both sessions'
  navigations, and records the pair name in `surface`.
- `probe` keeps no records, so `ambient_accounting` takes `out_path=None` and the
  figure is printed on stderr rather than written. It opens only `/odoo/...`
  backend routes, so its delta is expected to be zero, and reading it anyway is
  the point: **a zero that is read is a reading and a zero that is assumed is
  not**, which is the distinction #256 drew about `crawl`. `visit` is the
  opposite case and the one subcommand where the figure is the measurement rather
  than the accounting — it exists to make the tracking write, and `U-C5` is
  judged from the row. Nothing about judging moved: `read_records` still refuses
  the schema, `diff` never reads the file, and the §10.6 and §12 conservation
  figures do not move for it. `docs/agents/live-tier.md`, ADR 0012's 2026-10-01
  postscript and the parity plan's §12 say it of every driver now, and
  `docs/testing/evidence/2026-10-02-issue-243/README.md` is **annotated** rather
  than rewritten: the absolute count it read is still what that run read. The
  pure parts are driven at the Static tier. No image change and no version bump.
- **The collaboration transport has now been seen to deliver, and a delivered peer
  snapshot does put the Ingress prefix in a record** (#265, on Release 0.4.10, the
  version #243 measured). Both pairs delivered. `ingress-ingress` is `CLEAN` *after
  a delivered snapshot*, which is the sentence #234's row had been quoted for and
  which no run had made; `ingress-public` stored
  `/api/hassio_ingress/<the add-on's token>` on both of the to-do's images —
  `FOREIGN-PREFIX-STORED`, the write #234 has described since 2026-10-01, measured
  for the first time — and the Ingress session's next save removed it, both `src`
  root-relative. So both halves of "the fix heals the record rather than preventing
  the write" are measured, the write itself is registered as `G-08` in the parity
  plan's §11, and `report` escalates on it: #234's criterion is a *confirmed*
  stored foreign token, so the rule reads every value the run read and not only the
  last, with the heal reported beside it rather than instead of it. #234 read that
  and **stays `severity: important`**, closed: the token entered the row and the next
  Ingress save removed it, which is all this fix ever claimed. What stays open is
  `G-08`'s shape — a record a Public peer wrote and no Ingress session saves again.
  Evidence:
  `docs/testing/evidence/2026-10-02-issue-265/`; #243's directory is **annotated**,
  not rewritten. No image change and no version bump.
- **`G-10` is recorded rather than fixed, and the direction it rests on is pinned at
  the Static tier** (#296; no Release, no Deploy, no host write). There is no
  admissible Ingress-side fix: the prefixed value is in `project.task.description`
  the moment the Public-origin peer saves it, and ADR 0003 keeps that surface
  unchanged, so what the add-on decides is only whether the field stays prefixed too
  -- and #234's strip, which turns "a prefixed live field, indefinitely" into "a
  clean field plus one history entry that ages out", is a strict improvement.
  `G-08` is therefore not re-graded; #234 is told by comment that its standing
  sentence is **partial by construction** and its disposition is left alone. The two
  prefixed revisions on the host stay untouched as a decision: editing the store a
  reading comes from is the move ADR 0014 refuses a stored-prefix valve under, with
  fewer witnesses, and the only ways in are `super(HtmlFieldHistory, rec).write(...)`
  or SQL, neither auditable from the record.
- `odoo18ce/tests/test_html_field_history_prefix.py` keeps the claim from drifting
  silently. `diff_utils.py` imports only `re` and `difflib`, so the pinned package's
  own `generate_patch` and `apply_patch` -- captured verbatim with
  `html_field_history_mixin.py` under the new `odoo18ce/tests/fixtures/server/` -- are
  **executed** over `project.task(5).description` exactly as #282's `markup.jsonl`
  recorded it: the Public peer's store patch carries no prefix, the Ingress heal's
  patch carries both pictures, and `apply_patch` reconstructs a prefixed document from
  the clean value the field holds today, which is what the Version History dialog drew.
  Two store-and-heal pairs replayed offline leave the prefix in the *second* revision
  of each, the host's revision 13 and 16 shape, and the residue is gone once
  `_html_field_history_size_limit` further revisions exist. The source shape the
  direction rests on is pinned with `ast` rather than text, so prose cannot satisfy
  it: the pre-write capture precedes `super().write(vals)`, `generate_patch` is called
  new-then-old, `_patch_generator` appends only `old_content_lines`, the
  reconstruction starts from the current field value, and both `create` and `write`
  drop `html_field_history` out of the incoming vals.

### Fixed
- **`media-document-mailing` could not run on a database with no draft
  mailing** (#274, found by #271's Live run). It built its own attachment and
  only *looked up* its mailing -- `editable_mailing_id`, a `search` for
  `state in ('draft','in_queue')` with `limit=1` -- so it was the one member of
  the media family still resting on a record it did not create, which is
  precisely what #266 moved the other three away from. `odoo_parity` happens to
  carry a draft mailing, so every recorded run had found one; #271's run was
  pointed at `catchup164b`, where `mass_mailing` had been installed minutes
  earlier, and the first attempt recorded
  `{"verdict": "NOT-RUN", "notes": "no mailing.mailing in state draft or
  in_queue on this database"}`. That run seeded a mailing by hand over
  `odoo shell` and passed, which is the only thing that stopped it being
  unattended -- and a fixture made by hand is not named after the run, not
  removed by `--cleanup`, and in no record's `fixture` block.
- The check now **creates** a draft mailing when the database has none, named
  the way every other scratch record here is
  (`WOOW scratch (delete me) <run id>`), recorded under `extra["fixture"]`
  beside the attachment with its id, subject and state, and deleted under
  `--cleanup` with the outcome in `fixture_removed.mailing`. `subject` is the
  only field the create has to pass: every other `required=True` field on
  `mailing.mailing` has a default or a stored `precompute` compute, and
  `mailing_model_id`'s default is `mass_mailing.model_mailing_list` -- the very
  record #271's hand seeding searched for, passed anyway when the search finds
  it so the create does not rest on a module data ref resolving.
- **The distinction the fix is about is "restore what I borrowed" against
  "delete what I made".** A mailing this run created is deleted and *not*
  restored -- writing its old body back would put `body_restored: true` in a
  record where nothing was borrowed. A mailing it found is restored and *never*
  deleted, because #266's own lesson is that a check which deletes what it did
  not create is how the next run ends up with nothing to measure. `--mailing-id`
  keeps its meaning exactly: reuse this one, do not look, do not create, do not
  delete, and do not second-guess the state the operator named. Which of the
  three it was is now a reading of its own, `extra["mailing_source"]`
  (`given` / `found` / `created`).
- **A scratch mailing an earlier surface or run left behind is *reclaimed*, not
  borrowed.** Without this, `--surface both` without `--cleanup` had the ingress
  surface leave its scratch mailing, the public surface's `search` find it, and
  the run record it as `found`: it would then restore *this run's own* fixture
  body while reporting `body_restored: true` -- evidence saying a real campaign
  was put back when nothing was borrowed -- and the row would be permanent,
  because every later run would read it the same way and no `--cleanup` could
  reach it. The test is the subject's `SCRATCH_NAME_PREFIX`, which is sound
  because this check is the only thing in the repository that creates a
  `mailing.mailing`; a real campaign whose subject merely *mentions* the words
  keeps every protection a borrowed row has.
- **`email_from` is the one required field whose precompute can come back
  empty**, and a required stored field is `NOT NULL` in Postgres
  (`fields.apply_required`), so that would be an `IntegrityError` on the create
  rather than an odd record. With no `mail_server_id` the compute resolves to
  `create_uid.email_formatted or env.user.email_formatted`
  (`mailing.py:260-275`), and `email_formatted` is `False` for a user whose
  partner has no email -- exactly the fresh or catch-up database this seed
  exists for, so #274's fix would have failed in its own headline case. The
  compute is left to do its job wherever it can and an unroutable
  `.invalid` placeholder is passed only where the value it would reach is
  empty.
- Two smaller things the same seam fixes. The created row's `state` is **read
  back** and the row removed if it is not one of `EDITABLE_MAILING_STATES` --
  the designer's body field is `readonly="state in ('sending','done')"`, so a
  row outside those two would give the check a readonly screen that reads like
  a fixture which did not survive its field; and the attachment `create`, the
  `before` read and the `body_arch` write now sit **inside** the seeder's
  guard, where they were below it. `run_check` discards a handler's return
  value when it raises, so a failure in any of those three used to leave a
  public `ir.attachment` on the host with nothing in the evidence naming it --
  the trap #266's review caught twice in the other checks. A compensating
  removal that *itself* fails now prints what it left to stderr, because
  `run_check` discards the handler's return value on a raise and the evidence
  can carry no `fixture_removed` from there.
- **`mailing-editable` could not run on a database with no draft mailing
  either, and it saved over a mailing it did not create** (#276, found while
  implementing #274, which deliberately left this check alone). The first half
  is #274's reading unchanged: the check only *looked up* a `draft` or
  `in_queue` mailing, so on a fresh install, a catch-up database or the local
  add-on's own it recorded `NOT-RUN` and measured nothing. The second half is
  worse here than it was there. This check does not merely overwrite a borrowed
  `body_arch` over RPC: it types in the mail designer and **clicks save**,
  because #238's whole subject *is* the save seam -- `body_arch` through
  `getEditingValue`, and `body_html`, which `commitChanges` inlines separately
  and which is the field that leaves the installation with the mail. So a run
  stored this run's marker body in **both** fields of somebody's campaign, and
  while `--cleanup` and the handler's error path write them back, neither covers
  a run killed between the save and the restore or taken without the flag, which
  is optional. What is left then is a real campaign whose body is
  `WOOW-MARKUP hand check <run id>` plus a company logo.
- **The decision is not the same as #274's: this check builds its own mailing
  and borrows nothing** unless `--mailing-id` names one. Nothing measured is
  lost -- the designer, `getEditingValue` and `commitChanges` do not care which
  record they are on -- and a run that never touches a real campaign needs no
  restore to be correct. #274 kept the find-first order for
  `media-document-mailing` because that check does not save (it *discards* the
  form and reads the record back to prove it); here that order is what created
  the risk. The two checks now share one seam, `fixture_mailing`, whose `borrow`
  parameter is where each of them answers the question, and the answer is
  reported in `extra["mailing_source"]` as before (`given` / `found` /
  `reclaimed` / `created`).
- A scratch mailing an earlier surface or run left behind is still **reclaimed**
  rather than left to accumulate -- `--cleanup` is optional and `--surface both`
  runs this check twice -- but a check that borrows nothing cannot find it with
  `editable_mailing_id`, which would hand it a campaign. `scratch_mailing_id`
  searches for the subject prefix with `=like`, anchored, so a real campaign
  that merely *mentions* the words is not a match, and bounded by
  `EDITABLE_MAILING_STATES`, because a reclaimed row the designer renders
  readonly reads exactly like a fixture that did not survive its field.
- Two things fixed on the way, both in the same window. **Every exit from the
  check now undoes its seed**: the body is written over RPC *before* the first
  navigation and three of the browser half's four exits are give-up paths, while
  the restore used to sit only on the path that had saved -- so a `--cleanup` run
  that gave up at the iframe left this run's marker body in a borrowed
  `body_arch`. And the check now **leaves the form clean**, through the discard
  `media-document-mailing` already used: an Odoo form persists a dirty editor on
  `beforeunload` and on an ungated `visibilitychange` (#263 is the same mechanism
  on the To-do form), and `run_check` closes the session *after* the handler has
  returned, so a save made there would fall outside every reading the check took
  and would undo the restore it had just made.
- **The discard was on the wrong half of three checks** (#276 review). It sat on
  the exits that go through a leaving function and on none of the handlers'
  recovery paths -- which are the paths that matter *more*, because the typing is
  already done by the time a later step can fail, so the form is certainly dirty.
  Concretely: `mailing-editable --mailing-id 42` whose `save.click()` times out
  restored the operator's campaign, returned, and then had `run_check`'s own
  `side.close()` fire `beforeunload` on the still-dirty form and write this run's
  marker body straight back -- while the record said `body_restored: true`. Both
  mailing handlers and `do_codeview` now discard first on both recovery paths.
- **`do_codeview` had the same window on its success path, over a record it can
  neither delete nor rebuild**: a real `ir.actions.act_window.help`. It recorded
  `unsaved_after_save` and acted on it nowhere, so a `--cleanup` run whose save
  left the form dirty put this run's marked help text back on that action
  permanently, with `help_restored: true` beside it. The discard now sits between
  the read-back (which is the reading) and the restore. Found by the same review;
  the rule it breaks is the one #276 states generally, so it is fixed here rather
  than filed.
- **A `body_html` the save never inlined no longer reads as a pass.** Building the
  row makes `False` the baseline for that field, and an empty field is `CLEAN`
  -- correctly, since there is no prefix in it -- so a save that stored
  `body_arch` and never ran `commitChanges` would have scored `PARITY` for rule
  8's field, the one that leaves the installation with the mail. The new
  `extra["body_html_inlined"]` reading is the marker the designer **typed**,
  which is in no RPC-seeded value; it is recorded and not judged, because a
  verdict there would make this check's `PARITY` turn on a mechanism that is not
  its subject. Presence alone turns out not to be that reading on a *reclaimed*
  row, whose `body_html` already holds this run's marker -- filed as #279 and
  fixed in the entry below.
- One thing the review found that is not fixed in #276 itself: a *reclaimed*
  scratch mailing's body links the public `ir.attachment` an **earlier** run
  created, and that attachment is in no fixture dict the reclaiming run holds, so
  nothing removes it. It predates #276 -- #274's reclaim is where it starts --
  and the two mailing checks now sharing one scratch-subject prefix only adds a
  second way to reach it. Filed as #277 and fixed in the entry below.
- **A reclaim deleted the mailing and stranded the attachment its body linked**
  (#277). `--cleanup` removed two things: `fixture["attachment"]`, the attachment
  *this* run created, and the scratch `mailing.mailing`, whoever made it. So a
  run of `media-document-mailing` taken without `--cleanup` left scratch mailing
  M carrying `<a href="/web/content/<A>" ...>` for the public attachment A it
  had created; a later run reclaimed M, deleted it, and A survived -- reachable
  from nothing, because a fixture attachment is only ever named in the `fixture`
  block of the run that made it. The one-check case is #274's; #276 added the
  second way to reach it, since both mailing checks now write the same
  `SCRATCH_NAME_PREFIX` subject and so `mailing-editable` can reclaim a row
  `media-document-mailing` left.
- The litter is host hygiene and not a misreading: a stranded `public=True`
  attachment named `woow-document-fixture-<run id>.txt` is listed **first** by
  the media dialog's own `order: 'id desc'` -- exactly the property
  `create_fixture_attachment` relies on -- so an old run's leftover is what the
  next run's tile list shows until that run creates its own. Nothing is
  misjudged either way, because every media check reads the tile it built *by
  name*.
- The fix reads the ids out of the body it is about to overwrite.
  `reclaimable_scratch_mailing` now reads `body_arch` in the same call as the
  subject test -- the last moment that value says anything, because the seeder's
  own body write replaces the href and the delete takes the row -- and
  `reclaim_stranded_attachments` takes `/web/content/(\d+)` out of it and unlinks
  those rows. **The bound is `scratch_mailing`'s own `body_arch`, and it is what
  makes reading ids out of markup sound**: only a row whose subject carried
  `SCRATCH_NAME_PREFIX` has that key, so the body is this driver's own fixture
  body and the ids in it are this driver's. A row this run created carries no
  body, and a row it borrowed -- `found`, or named by `--mailing-id` -- has no
  `scratch_mailing` dict at all, so neither a real campaign's attachments nor a
  real company's can reach the list.
- **The removal goes with the reclaim and not with `--cleanup`**, which is the
  asymmetry the fix turns on and the second half of the leak. `--cleanup` asks
  "leave the host as this run found it", and for a row this run made that is the
  whole question; these attachments are an *earlier* run's, already abandoned,
  and the seeding destroys the only handle on them whatever the flag says. A
  reclaim without `--cleanup` therefore left a mailing that no longer named the
  attachment, and the next `--cleanup` run read a body naming nothing and deleted
  the row -- stranding it exactly as before. It is also the first step inside the
  seeder's guard, ahead of the attachment this run builds, because every step
  below it can fail and the compensation that follows deletes the reclaimed row
  the ids are read from.
- Two details are deliberate. The pattern is **unanchored**, because the litter
  was left by a check that *saves* and #238's whole subject is that a save may
  store the href prefixed. And the ids are filtered through a `search` before the
  `unlink`, because unlinking an id that is already gone is a `MissingError` and
  a body naming a deleted attachment is reachable -- it is what a run whose
  mailing unlink failed leaves behind, and failing a reclaim over litter that is
  already gone would keep the live litter alive.
- Scoping the subject prefix per check was the alternative and is **not** the
  fix: it addresses only the cross-check half and leaves the one-check case,
  which is the one that already existed. The ids and the outcome are recorded in
  `extra["fixture"]` (`reclaimed_attachment_ids`,
  `reclaimed_attachments_removed`) and the seeders' compensation path prints both
  when the removal came back `false` -- `run_check` discards a handler's return
  value on a raise, so that console line is the only place they can appear from
  there, and the reclaim's outcome cannot ride in `fixture_removed` because the
  reclaim ran before anything in the seeder could fail. The module's
  "`--cleanup` removes all five" no longer declares a gap beside it.
- **A generic literal rewrite reached an ORM *search pattern*, so the media
  dialog's Documents tab listed every generated asset bundle** (#271, found by
  #266's run beside #239's document line and filed separately because it is not
  #239's rule). `DocumentSelector.attachmentsDomain` excludes those bundles with
  `!['url', '=like', '/web/assets/%']`, naming the reason in its own comment --
  and that is a string literal in an ORM domain, living in the same bundle as
  the URL literals the Ingress asset location has prefixed since #166. nginx's
  `sub_filter` is a byte-level substring search with no idea what a literal is
  *for*, so it prefixed this one too; the exclusion then read
  `NOT (url =like '<prefix>/web/assets/%')`, which matches no stored `url`
  because every bundle attachment is `/web/assets/...` in the database, and the
  `'|' ['url', '=', null]` beside it let all of them through. Under Ingress the
  first page of 30 tiles filled with `mass_mailing.assets_wysiwyg.min.js` and
  its siblings while the Public origin listed the one document; on a database
  with more than 30 bundles a user's own files were unreachable without a
  search. Nothing was stored -- a search domain travels in a request body.
- The fix is **two counter-rules, one per quote style**, each its own pattern
  spelled as its own replacement: the job is to claim those bytes before a
  generic rule can. `sub_filter` tracks one match attempt at a time, so the
  pattern starting at the earlier byte wins and the inner `"/web/` never gets a
  turn; the rules are also written *ahead* of the generic ones, which is the
  other half of the same rule (#158: two patterns starting at the same byte go
  by written order). Identity rather than a cleverer spelling, because the Live
  probe's reading is `domain.includes("/web/assets/")` -- the evidence that this
  is fixed is "the literal is present and carries no prefix", and a split
  spelling would make that field read `false`.
- Why not a narrower generic rule, which is the other option ADR 0004's
  2026-10-02 postscript had to choose between: the measurement says the class
  has **two** sites today, and `/web/assets/...` is also a genuine address the
  generic rule is there to prefix (`loadBundle` asks for one by that path), so
  narrowing would have to distinguish operand positions -- which is exactly
  what a substring filter cannot do.
- **Six pattern literals measured, not the four the issue named, and a third
  selector found.** Quote style turns out to be per *site*, not per file -- the
  legacy `web_editor` image selector writes its two shape literals
  *double*-quoted while writing `/%/static/%` single-quoted -- and
  `html_editor`'s `FileDocumentsSelector`, the compatibility override for the
  `/file` command, carries three of the six, which is why a bundle holds a shape
  literal three times and not twice. Only the two `/web/assets/%` are reached by
  any shipped rule: `/html_editor/shape/%` and `/%/static/%` are reached by
  nothing, and `/web_editor/shape/%` survives because the rule needs `/web/` and
  `/web_editor/` has `_` where the rule has `/`. Every count is per bundle in
  `odoo18ce/tests/fixtures/bundles/README.md`, derived from the pinned package
  through Odoo's own serve path and checked by reproducing #239's and #240's
  tables row for row first.
- **Measured on the test host through a local build, with no Release**
  (2026-10-03, `local_odoo18ce` `0.4.10-202610031232`, database `catchup164b`,
  Ingress only, run `WOOW-MARKUP-20261003T124016Z`;
  `docs/testing/evidence/2026-10-03-issue-271/`). The fix only moves the Ingress
  side and the Public reading was already taken by #266 the day before, so the
  local build is the whole verification and no version was bumped.
  `media-document-mailing` read `served_domain_asset_exclusion_prefixed`
  **`false`** with `served_domain_has_web_assets_literal` still `true`, the
  getter **320** bytes against the **383** the Released 0.4.10 served, and the
  Documents tab listing **1** tile and selecting it. 320 is also the captured
  fixture's length and the number #266 read on the Public origin, so the Static
  and Live tiers agree on one figure; the add-on's own prefix length came back
  from the Supervisor as **63**, so 383 minus 320 was exactly one insertion.
  `stored_verdict` `CLEAN` on `body_arch` and `body_html`, 0 prefixes each, the
  designer discarded and the fields read back; ambient `website.track` and
  `website.visitor` deltas **0** over 1 navigation.
- The other half is measured over that database's own rows rather than inferred:
  **18** `ir.attachment` bundles, **all 18** excluded by the unprefixed clause
  and **none** by the prefixed one, and no stored `url` carrying a prefix at
  all. That is why the tab would have held 19 tiles there and held 1.
- One gap the run found in the driver, recorded rather than fixed because #271's
  brief puts driver changes out of scope: `media-document-mailing` builds its
  own attachment but **looks up** the mailing, so it returns `NOT-RUN` on any
  database with no draft mailing -- invisible on `odoo_parity`, where one
  happens to exist. It is the only thing that stopped this run being unattended.
- `test_ingress_media_dialog_domain.py` serves all five captured getters through
  a **real nginx** carrying this location's own rule set, in both directions:
  with the fix every one of the six literals must leave the gateway
  byte-identical, and with this issue's own rules removed the two document
  literals must be shown gaining a prefix. So a future generic rule that starts
  claiming one of the three left alone turns that test red instead of silently
  changing which attachments a picker lists. The consequence is executed rather
  than asserted -- each getter is run, the domain it built is read against
  stored `ir.attachment` rows through a port of Odoo's own `normalize_domain`
  and the two `_condition_to_sql` NULL rules, and the tab must list the document
  alone as served and the document plus every bundle when the literal is
  prefixed. A sixth test serves a pattern literal and two real addresses side by
  side and requires exactly the two addresses to gain a prefix.
- **The peer snapshot never focused its receiving session, which is why nothing had
  ever been delivered to it** (#265, the third defect #243's run exposed in this
  driver). No view that shows `project.task.description` sets
  `collaborative_trigger`, so the collaboration plugin joins the peer network on the
  editable's `focus` event and nowhere else, and a session that has not joined
  discards every signalling notification it receives — the other session's
  `ptp_join` included, with no log and nothing in the DOM
  (`collaboration_odoo_plugin.js:91-99`, `:156-158`). The sending session joined by
  accident, because typing needs focus; the receiving one was first focused *after*
  the 30-second wait expired. `stage` now focuses it, with `focus()` and not
  `click()` — a click lands in the middle of the onboarding to-do, whose middle is a
  checklist that toggles through `/web_editor/checklist`, a write on the command
  that claims to make none.
- A `delivered: false` is now attributed by the run that reads it. #243's two
  records carried the bare boolean and the account that went into ADR 0004, the
  parity plan and that run's own README — "the two sessions never became
  collaboration peers" — was an inference from a timeout. Both commands now read
  each session's own state (is the field collaborative, is the bus worker connected,
  which channel, did it join, how many connected peers) and count the signalling
  each posted to `/html_editor/bus_broadcast` off the wire, and
  `transport_diagnosis` names the first rung that holds. The three questions #265
  asked are each a value in the record.
- `do_run` has the two-step healing read ADR 0004 asked for on `ingress-public` and
  #243 could not take: the Ingress session discards its leftover, **reloads the
  record** so its editor holds what the Public peer stored, and saves once; the
  record carries `loaded_prefixes` (the reading that says the heal had a subject),
  the second verdict, and a reason when it could not be taken. The escalation rule
  reads **every** value the run read, because #234's criterion is a *confirmed*
  stored foreign token: a prefix the heal removed was still confirmed in the record,
  and the first spelling of this -- which read only the value the record ends with
  -- answered `false` on the run that had just watched a Supervisor token reach the
  field. The heal is reported beside it as `foreign_prefix_healed`, with
  `foreign_prefix_still_stored` for what is in the field now, and neither is folded
  into the clean count. `report` also splits `CLEAN` into `with_a_delivered_transport` and
  `with_no_delivery` with a sentence beside it, so the two things #243's run was
  quoted as having said cannot be written as one again.
- A marker now carries the **pair** as well as the run id. One run is one
  `--run-id` across both pairs and `run` stores its marker, so the second pair
  opened a record that already held the first pair's `<run-id>-A`: the baseline
  guard #263 added refused the match and returned without waiting, which made that
  transport reading **void** rather than negative. Found by #265's own first
  attempt, whose records are kept beside the final ones, and
  `transport_diagnosis` grew a `marker-collision` rung so the shape is named
  instead of reading as `unattributed` beside two plainly connected sessions.
- The peer snapshot's `probe` no longer writes the field it reports it does not,
  and no longer reports a delivery that never happened (#263, both found by
  #243's run). It wrote on **every** run: it typed a marker into
  `project.task.description` and navigated away without saving, and a dirty To-do
  form persists the editor's content on that navigation -- so "only a save writes
  the field", which the step's own comment gave as the reason it was safe, is not
  true of this form. It now clicks the form's own **Discard** on both sessions
  before it leaves and then reads `description` back and reports `wrote_nothing`,
  so the claim is measured rather than asserted; a `probe` that did write exits
  non-zero. `run` discards the sending session's leftover for the same reason,
  leaving the stored value exactly what the receiving session saved. The
  mechanism is read from the pinned package rather than guessed: every form
  controller registers `beforeunload` unconditionally, the handler calls
  `record.urgentSave()`, the html field answers `WILL_SAVE_URGENTLY` by
  committing the editor's uncommitted content, and the urgent path writes with
  `navigator.sendBeacon` -- which no request interception sees and nothing
  cancels. Waiting for the form to report itself clean before leaving is
  load-bearing for the same reason: `discard()` is async and `click()` returns
  long before it resolves.
- **The read-back is the guarantee, and the discard is only the means.** Odoo
  saves a form on `visibilitychange` as well, that handler is **not** gated on the
  record being dirty, and the sending session is necessarily dirty while the
  receiving one opens -- so a backgrounded page can write with no navigation at
  all. This measurement cannot remove that and no longer claims to: the field is
  read back on every `probe`, so a write that happens anyway is detected and
  named instead of assumed away. Recorded in the module, in
  `docs/agents/live-tier.md`, and pinned.
- The second defect compounded the first and is the one that produced a wrong
  reading. `probe` staged the **constant** `WOOW-PEER-PROBE`, so once it had
  stored that string the next probe found it in the receiving editable on its
  first poll and recorded `{"delivered": true, "waited_seconds": 0.0}` on
  `ingress-public` -- while the same-surface pair had just waited the full 30 s
  and correctly failed. A constant marker makes `delivered` unfalsifiable once
  the field has ever held it, which is exactly the step's own argument ("nothing
  has stored that marker, so its presence is the transport") turned off. Two
  halves, both pinned: every marker now comes from one `marker(run_id, label)`
  helper that `probe` and `run` share, with `probe` minting a
  `WOOW-PEER-PROBE-<UTC timestamp>` when `--run-id` is not given; and the wait
  takes a **baseline** -- the sending session's editable read *before* it typed --
  and refuses to read a match already in it as a delivery
  (`marker_pre_existing: true`), without waiting. A `waited_seconds` of 0.0 stays
  a legitimate reading, because the receiver joins after the sender typed and its
  snapshot can carry the marker on the first poll; it is recorded as the shape to
  distrust rather than reduced to a boolean (parity plan §12). A record's `notes`
  now carries *which* way the transport failed instead of one fixed sentence: the
  old wording said the receiver "never saw the sender's unsaved marker" either
  way, which would have been a false account of a pre-existing marker -- that
  case says the run id collided, which makes the whole record suspect rather than
  only its transport half.
- Four things the review caught, each one a way the fix could still mislead a
  reader. A form the driver **could not** discard now fails the probe even when
  the field reads back clean, because the read-back only sees writes that already
  happened and a still-dirty session gets written afterwards -- `wrote_nothing:
  true` with an armed write was the one outcome left that said "safe" and meant
  "not yet". Discarding goes through a wrapper that cannot throw, so one session's
  failed cleanup no longer costs the other its discard or the run its whole
  report, and `run` appends and prints its record **before** cleaning up, so a
  cleanup timeout cannot throw away a measurement that needed a deploy and a host.
  `probe` reports the labels of the prefixes in the field and deliberately **no**
  verdict: `classify` is relative to the session that saved, nothing saved here,
  and asking it anyway read every prefix as `FOREIGN-PREFIX-STORED` on
  `ingress-ingress` -- the verdict that escalates #234 to `blocker` -- because that
  pair's two sessions share one prefix and so one label. And the discard button is
  matched with `>> visible=true`, this repository's existing idiom for it, rather
  than `.first`, which takes the first DOM match whatever its state and would
  silently skip the real button behind a hidden earlier one.
- The three documents that stated the old behaviour are corrected and pinned to
  the code, since a reader acted on them: the module and `do_probe` docstrings,
  `docs/agents/live-tier.md`, and the parity plan's §12 and #234 row. The pure
  parts -- the marker helper, the wait's refusal and the probe's verdict -- are
  driven at the Static tier, and the steps a host is needed to watch are held
  there by shape, including that the navigation which did the writing is gone.
  `docs/testing/evidence/2026-10-02-issue-243/README.md` is **annotated** rather
  than rewritten: its Writes row is what that run left, and what changes is the
  attribution.
- **`body_html_inlined` could read `true` from a reclaimed row's earlier marker**
  (#279, found by the review of #277 and not introduced by it -- the reading is
  #276's). That reading asks whether rule 8 ran at all, and it asked it as
  "`marker_for(run_id)` is in the `body_html` read back". `--run-id` is one value
  for the whole invocation and `--surface both` drives the check on both surfaces
  against one database, so without `--cleanup` the ingress surface left scratch
  mailing M with its marker inlined in `body_html`, the public surface's
  `scratch_mailing_id` reclaimed that same M -- by design, the subject is this
  run's -- and a second save that stored `body_arch` and never ran
  `commitChanges` read as inlined off the first surface's value. The same thing
  happened on a re-run of one surface under one run id.
- The fix judges the marker **newly** present: in the value read back and not in
  `fixture["before"]["body_html"]`, which the seeder already reads before it
  writes `body_arch`, so it costs no further RPC. Scoping the typed marker per
  surface was the alternative and is **not** the fix -- it closes the
  cross-surface case only, leaves the one-surface re-run, and changes the value
  other readings compare against. Nothing else about the reading changes: it
  stays **recorded and not judged**, for `_media_verdict`'s reason, so no verdict
  moves either way. What it protects is the evidence a reader uses to tell
  "inlined, and root-relative" from "never inlined", since `stored_verdict(False)`
  is `CLEAN` and an empty `body_html` already scores a pass on its own.
- **#279 left the reading `false` on a reclaimed row whichever way that save
  went** -- read #286 below for where that ends up, since both land in this
  release -- and the record says so rather than leaving it to be worked out: the
  new `extra["body_html_marker_before"]` is read where the `before` read happens,
  so the two `false`s -- "the save never inlined" and "the marker was already in
  the field, so this row cannot say" -- are told apart from the record itself.
  That is the direction to fail in for a reading whose job is to refuse a false
  pass, and under #279 alone a positive reading on that row wanted `--cleanup` or
  a run id of its own.
  Clearing `body_html` beside the `body_arch` seed would make both readings
  possible on it and was deliberately not done in #279, though gated on
  `fixture["scratch_mailing"]` it could be: what it changes is the **write**, and
  through it the `stored["mailing.mailing.body_html"]` that `stored_verdict`
  *judges* -- the judged half of the same stale value, which #279 puts out of
  scope and which is real rather than hypothetical, since on a reclaimed row the
  public surface's `PREFIX-STORED` or `CLEAN` can be the ingress surface's
  leftover value. That half is #286 below, which makes the clear -- so the
  reading is two-way on a reclaimed row after all.
- **`_discard_unsaved_form` could not report a discard that failed, and its
  click was unbounded** (#280, with #281 folded into it -- both defects are in
  that one function, and the timeout belongs on the very click whose reporting
  the other half restructures; found by the review of #277, and the code is
  #276's and its review commit's). The function swallowed every exception and
  only ever wrote `extra["discarded"] = True`, while its docstring made the
  **absence** of the key mean "a page with nothing to discard". So `UNSAVED`
  matching and `discard.click()` timing out -- a modal over the button, a page
  that stopped responding -- recorded exactly what an already-clean form does.
  That reading matters most on the recovery paths #276's review added the call
  to: the typing is already done when a later step fails, so the form is
  *certainly* dirty, and the step after the discard is the restore, which still
  stamps `body_restored: true` (`help_restored: true` in `do_codeview`) even
  though `run_check`'s own `side.close()` can fire `beforeunload` on the
  still-dirty form and write this run's marker body straight back over it.
- There are now three readings rather than two: no key for a page with nothing
  to discard, `true` for a discard that came off, and `false` once `UNSAVED` has
  matched and the form did not come clean -- a click that failed, no visible
  discard button to click, or an unsaved indicator still up afterwards. The
  restore's own reading is then checkable against it. The `settle` that followed
  was not one of those causes: it ran *after* the indicator had gone hidden, so
  the question this key answers was already answered, and a page that closed
  during that sleep may not turn a confirmed `true` back into the reading that
  says the form was left dirty. (That sleep was "there for the restore's RPC";
  #288 below establishes that no caller wanted it and removes it, so the order
  this paragraph is about is now simply the end of the function.) This is the
  trap `_remove_mailing_fixture` already reports each removal to avoid, and the
  pair `discard_quietly` in `e2e_collab_peer_snapshot_live` has always reported.
  A page that cannot be read at all (a frame that navigated away, a context that
  closed) still adds no key: there "was there anything to discard" is unknown,
  which is not the same reading as a discard that failed.
- **`true` means the form came clean, not that the click did not raise.** The
  discard is confirmed by waiting for `UNSAVED` to go hidden -- the indicator
  carries `invisible` again once the record is clean, and a locator with no
  element counts as hidden, which is how `discard_form` has always read the same
  outcome. Without it a discard that did not take (a dialog raised over it, an
  invalid record the form will not leave) recorded `true` while `side.close()`
  still had a dirty form to save, which is the reading this issue is about with a
  different cause. The button is matched `>> visible=true` for the same reason
  `discard_form` matches it that way rather than with `.first`: `.first` takes
  the first DOM match whatever its state, so one hidden earlier button -- a
  dialog's, a sub-form's -- passes `count()`, spends the new bound on an element
  that can never be clicked, and leaves the real button unclicked.
- The two waits are now bounded explicitly: `DISCARD_TIMEOUT` (2 s) on the
  click, which needs nothing but an actionable button and has just matched one
  `visible=true`, and `DISCARD_CLEAN_TIMEOUT` (15 s) on the indicator clearing,
  which waits on much more. `_discard` is purely local -- it resets `_changes`
  from the save point and re-renders, with no RPC, so there is no reload to wait
  on (`web/static/src/model/relational_model/record.js:565`). What the indicator
  waits on is the line above it: `discard()` (`:183`) does
  `await this.model._askChanges()` first, which raises `NEED_LOCAL_CHANGES`, and
  the html field answers that by pushing `commitChanges()` into the promise list
  (`html_editor/static/src/fields/html_field.js:78`). On the mail designer that
  override clones the editable into an `srcdoc` iframe, awaits that iframe's
  `load`, runs `toInline` and writes the result back
  (`mass_mailing/static/src/js/mass_mailing_html_field.js:147-186`) -- the same
  inlining pipeline the **save** path budgets `side.settle(6000)` for, and
  `extra["save_incomplete"]` exists because that is sometimes still not enough.
  A bound tighter than the save's would therefore record `discarded: false` for
  a discard that did come off, so this one sits above it, with a Static-tier test
  pinning the relation. No `set_default_timeout` is applied anywhere in this
  driver -- `TIMEOUT` is only ever passed explicitly to `wait_for` -- so each
  wait would otherwise take Playwright's 30 s default, and `do_codeview`'s
  `except BaseException` runs the discard *ahead* of the RPC that puts a real
  `ir.actions.act_window.help` back. On Ctrl+C mid-check those 30 s sat between
  the interrupt and the only restore that record was going to get, and a second
  Ctrl+C inside the window raises `KeyboardInterrupt`, which neither the
  discard's `except Exception` nor the handler's own catches -- leaving the marker
  text on that action with nothing restoring it. The other two handlers' recovery
  paths share the same function and so the same bounds.
- **The bounds shorten this seam's contribution to that window and not the
  window.** Two larger costs sat in it and were outside this one function:
  `side.root` is a property that re-resolves through `_find_frame(wait_s=60)`
  whenever the Ingress iframe is detached -- which is the interrupt scenario
  itself -- and the `side.settle(2000)` after a successful discard spent an 8 s
  `networkidle` that Odoo's open bus normally runs out before sleeping. Both are
  out of that window as of #288 below, which says what the window now is -- and
  where the resolve the seam reaches for stops being `side.root` at all. What
  *this* change takes out is the triple exposure: the seam resolved `side.root`
  once and worked through the frame it got, instead of reaching for the property at
  each of its three steps, so the old seam's three *chances* to pay a minute became
  one. (One minute, not three: `_find_frame` returns as soon as a matching
  frame exists and raises after a single 60 s sweep when none appears, so a
  persistently detached frame cost the old code 60 s once too -- three sweeps
  needed two re-resolves each landing at the end of its own window.)
- **And the hold is a correctness fix, not only a latency one.** `IngressSide`
  already caches the frame and re-resolves only when it is detached, so the three
  reads returned the same object in every case but one: a panel that re-mounted
  its Ingress iframe between the first read and the confirmation wait. There the
  old code re-resolved to the **replacement** frame, whose freshly loaded
  document has no `.o_form_status_indicator_buttons:not(.invisible)` -- so
  `wait_for(state="hidden")` on a zero-match locator returned at once, raised
  nothing, and recorded `discarded: true` while the dirty form sat in the frame
  that had just gone, whose detach is exactly when `beforeunload` fires. That is
  this issue's own misreading, by a third door. Held, the detached frame raises
  and the reading stays `false`. Nothing after the seam wanted the incidental
  re-resolve either: `Side.rpc` posts through the request context rather than a
  frame, so the restore does not need a resolvable frame at all. An interrupt that does land leaves
  `discarded: false` in `extra` on its way out rather than nothing -- not in an
  evidence line, since `run_check` catches `Exception` only and so writes no
  record at all for a surface a `KeyboardInterrupt` left; the reading is there
  for every other path that does write one. A global `set_default_timeout` is
  **not** the fix -- it would change every wait in the driver -- and neither is
  skipping the restore after a failed discard: it is still the record's only
  chance, so what changes here is the reading and not the order.
- **A reclaimed row's stored `body_html` was judged as this save's** (#286, the
  judged half of the stale value #279 fixed the recorded half of, and the issue
  that bullet asks for; raised by the review of #277 and still on `main` after
  #279). `mailing-editable` means that field's **Stored reading** to be
  *write-bounding*: a prefix in it is this save's `commitChanges` leaking (#238
  rule 8). On a **Reclaimed row** whose save stored only `body_arch` it was not --
  the value read back was the earlier surface's inlined body -- and
  `stored_verdict` judges every field it is handed, with a `PREFIX-STORED`
  promoted to the check's whole verdict ahead of every other branch (#237 check
  4). So the *ingress* surface's save could be reported as `PREFIX STORED by
  mailing-editable/public`, exit 1 -- on the surface where a stored prefix means
  a `sub_filter` leaked out of the Ingress asset location, which is a different
  and more serious claim. The clean direction landed too: a clean leftover scored
  `CLEAN` for a `body_html` that save never wrote.
- **The fix is at the write, and `docs/adr/0014-a-stored-prefix-is-never-suppressed.md`
  is why it is not at the verdict.** Teaching `stored_verdict` to skip a field
  known to be stale is indistinguishable, in the code and in the evidence, from
  erasing a stored prefix -- the finding this module exists to surface, and what
  #237 check 4 exists to forbid. So the seeder now clears `body_html` in the same
  `write` that seeds `body_arch`, and what the save leaves in that field is this
  save's own output. `stored_verdict`, `evidence_record` and `do_report` are
  untouched.
- **The clear is gated on the fixture carrying a scratch row, which is
  `_restore_borrowed_mailing_body`'s own guard inverted.** The two are exact
  inverses, so the clear can never blank a value the restore would have put back:
  `created` is a no-op (the field is already `False`), `reclaimed` is the case
  this fixes -- this driver's own litter -- `given` is the row `--mailing-id`
  named and is left exactly as it was found, with the restore still running under
  `--cleanup` only, and `found` is unreachable because this check passes
  `borrow=False`. `fixture["before"]` keeps the **true pre-run value**: it is both
  the restore source and the evidence of what was on the row, and the same fixture
  shape is shared with the document-mailing seeder, so the clear gets a reading of
  its own (`fixture["seeded"]`, read by the new `body_html_baseline`) rather than
  overwriting one. `extra["body_html_marker_before"]` is unchanged in meaning and
  in position -- the marker was on the row before this run touched it -- and is
  still read before the write.
- **`body_html_inlined` can now read `true` on a reclaimed row**, which #279 could
  not give it: the clear turns #279's deliberate one-way reading there -- `false`
  whichever way the save went -- back into a two-way one, measured against what
  the seed left the field as rather than against the pre-run value. It stays
  **recorded and not judged**, for `_media_verdict`'s reason, so no verdict moves
  on that account either. Nothing is cleared in the **document**-mailing seeder:
  that check never saves, its read-back exists to prove the discard worked, and
  clearing the field would destroy the baseline it compares against. The readings
  that take a **State-bounding reading** and have it judged as if it were
  write-bounding are the same family by the other admissible correction,
  attribution, and are #289 -- which found that the clear's own gate leaves this
  check's `body_html` in that family too, under `--mailing-id`.
- **Five read-back sites had a State-bounding reading judged as the reading
  check's own write** (#289,
  filed out of #286's triage round, which settled one instance and found the
  class while checking whether the defect was local). `stored_verdict` judges
  every field a check hands it and `evidence_record` promotes a `PREFIX-STORED`
  to that check's whole verdict ahead of every other branch -- #237 check 4's
  rule, and not in question. What the record could not say is **which kind of
  reading** it had just judged. A **Write-bounding reading** is on a field the
  check itself wrote, so a prefix there is that check's own save leaking; a
  **State-bounding reading** is on a field it did not, so a prefix is a leak
  whoever caused it and the check is the witness rather than the author
  (`CONTEXT.md` carries both terms). Both were reported identically, as a
  `PREFIX-STORED` attributed to the check and surface that merely looked --
  which for `readonly-plain` and `mailing-readonly` means the evidence
  contradicted itself, since the register declares both of them `writes: False`
  and the report named them as the author of a write. It was never a false
  *finding*: the prefix really is in the database. It was a false
  **attribution**, and the direction matters -- on the Public origin a stored
  prefix is the leaked-`sub_filter` finding, a different and more serious claim
  than "this row has held a prefix since before the run".
- **The fix is attribution, which ADR 0014 named and #286 could not use.** A flow
  declares, per field, which kind of reading it took, in a `readings` mapping
  beside `stored`; `evidence_record` pairs the two and the per-field entry gains
  a `reading` key. Per *field* and not per check, because the register's `writes`
  flag is not the discriminator: `media-document-mailing` is one check with one
  field of each kind. The five are `readonly-plain`, `mailing-readonly`,
  `media-document-mailing`'s `body_html`, `readonly-iframe` under `--task-id` and
  `mailing-editable`'s `body_html` under `--mailing-id` -- the last being the row
  #286's clear is gated away from, so the two corrections close the family
  between them and neither subsumes the other. ADR 0014 carries a postscript with
  the corrected count and the two decisions below.
- **Both kinds still fail the run, and no verdict moves.** `screen_verdict`,
  `summarise` and the exit code are untouched: a State-bounding prefix is
  reported, counted and still exits non-zero, because a per-check "judge but do
  not fail" policy is the valve ADR 0014 refuses one layer out -- the finding
  would still vanish from the exit code, the tally and the sweep gate. What
  changes is the sentence: `report` now prints `PREFIX STORED by
  readonly-plain/public in project.task.description (state-bounding)`, and names
  only the fields that carry the prefix rather than every field read back. The
  schema stays `woow.ingress-markup/v1` -- the key is additive, every record in
  this repo's three markup evidence files is `CLEAN`, and a record written before
  the key existed reports as `kind not recorded` rather than being rejected.
- **Not folded into the verdict string**, which is where this differs from the
  peer snapshot driver's `classify`. There the kind *is* the verdict --
  `OWN-`/`FOREIGN-`/`UNKNOWN-PREFIX-STORED` are three findings with a severity
  order between them -- so `classify` is the precedent for the shape and not for
  the mechanism: it attributes by session, this attributes by whether the flow
  wrote the field at all. And `--task-id`/`--mailing-id` do not make a third
  kind: they reach the second one by a different road, which is a *reading*, and
  each of those sites already records it.
- **One declaration is derived rather than declared**, and it is the site where a
  flat one would have thrown the reading away. `media-document-mailing` never
  writes `body_html`, so on a borrowed draft the value is the campaign's own --
  but if the discard did not hold, the save that got through is exactly what
  inlines that field, and a prefix in what *it* wrote is the check's own leak.
  Which of the two happened is not declarable in advance and not guessable from
  the value; it is **the change** that separates them, measured against the
  pre-run `fixture["before"]` that is already in hand as the restore source. A
  fixture that never reached that read declares state-bounding, and not as the
  cautious answer: a handler that got no further than its seed never navigated.
- **No default kind, because the site a default is wrong at is the one nobody
  looked at.** `evidence_record` raises for a field in `stored` with no
  declaration, for a declaration naming a field that was not read back, for a
  kind this module does not name, and for a `write-bounding` declaration from a
  check the register says writes nothing -- that last pairing being #289's own
  false claim, made by the flow instead of inferred by a reader. Like the
  `RESERVED_RECORD_KEYS` collision, these land in `run_check`'s outer `except`
  and cost a surface its record rather than stopping a run, so the guard that
  keeps the six read-back sites honest is a Static-tier test that enumerates them
  from the source and pins what each declares. Static tier only: no handler's
  browser behaviour changed, no verdict moved, and nothing here is falsifiable by
  a host -- the declarations get their first live exercise on #282's run, which
  this does not gate.
- **The Ctrl+C-to-restore window was bounded by `side.root` and `side.settle`, not
  by the discard's own waits** (#288, raised by review round 3 of #280 and
  confirmed against the pinned package rather than inferred). #280 bounded the two
  waits *inside* `_discard_unsaved_form` -- 2 s on the click, 15 s on the
  confirmation -- and said so, that the window those bounds sit in was not
  shortened. The two costs in it were measured and not estimated, with fake pages
  driving the real `IngressSide._find_frame` and `Side.settle`: an Ingress frame
  that cannot be resolved costs **exactly 120 iterations of a 500 ms wait = 60 s**
  and then raises, which the seam's outer `except Exception` swallows into no
  reading at all; and `settle(2000)` is an 8 s `networkidle` Odoo's open bus always
  runs out, *then* the 2 s sleep -- **about 10 s on every successful discard**. So
  `do_codeview`'s `except BaseException` spent up to ~87 s, and ~10 s even when
  everything went right, between an operator's Ctrl+C and the only write that puts
  a real `ir.actions.act_window.help` back -- with a second Ctrl+C anywhere inside
  it raising through both catches and leaving this run's marker text on the action.
- **`Side.root_now`: a resolve that never waits for a panel to load.** The default
  is on the base class and is `root` itself, so the public side and the other four
  Live drivers on this layer are byte-for-byte unchanged; `IngressSide` is the one
  override, and it hands back the frame the side is already holding **without**
  consulting `is_detached()` and without ever entering the waiting frame search. A
  side that has not resolved a frame yet falls back to the waiting resolve -- a
  panel still loading is a legitimate thing to wait for, which is why `root`, its
  cache and `_find_frame`'s 60 s default are untouched, and why this is a second
  property rather than a smaller `wait_s`. `_discard_unsaved_form` takes this
  resolve for its single read, so a detached frame raises on the first locator call
  and the existing `except` keeps the reading negative.
- **And that is a correctness fix at the *entry* read, which is #280's misreading
  by a third door.** With a detached held frame and a panel that has re-mounted,
  `root` returns the **replacement** frame in no time at all; its freshly loaded
  document has no unsaved-indicator match, so the seam returned with **no
  `discarded` key** -- the "already clean" reading -- while the dirty form sat in
  the frame that went, whose detach is exactly when `beforeunload` fires. Holding
  the frame the side already has turns that into the honest "could not be read"
  reading, which is the same absent key finally meaning what it says.
- **The seam no longer settles on a caller's behalf.** The `side.settle(2000)` was
  there for the step *after* the discard -- the restore's RPC, "which wants the
  page quiet". It does not: `read_field`/`write_field`, the borrowed-body restore,
  the fixture removal and the document check's record read-back all go through
  `Side.rpc`, which posts through the browser context's request API and touches
  neither a page nor a frame. The quiet page had no beneficiary.
- **Nor did that sleep protect the restore from a page-initiated save**, which is
  worth being exact about because it is the seam's whole subject -- and the first
  draft of this entry was not. There are two such saves. The confirmation covers
  the ones that go through `model.mutex`, because `Record.discard` awaits
  `_askChanges`, which resolves `this.mutex.getUnlockedDef()` as well as the field
  commits (`relational_model.js:209-213`) -- and that includes the **ungated
  `visibilitychange`** save of #263, which is `root.save()`
  (`form_controller.js:483-496`), itself `mutex.exec` (`record.js:226-229`). The
  one it does not cover is `urgentSave`, which calls `_save` **outside** the mutex
  (`record.js:267-272`). But `urgentSave` is wired to `beforeunload` only
  (`form_controller.js:507`), and the form view sets
  `useSendBeaconToSaveUrgently: true` (`:383`), so it leaves over
  `navigator.sendBeacon` and is fire-and-forget (`record.js:1014-1033`): no wait
  on this side ever bounded it, and 10 s of sleep only made losing that race less
  likely. Its window is `run_check`'s own `side.close()` -- which is what the
  discard exists to find nothing to save in. The document check's read-back is not
  given a `settle` of its own for the same reasons, and
  `_document_mailing_leaving` now records that judgement.
- **So those two bounds are now the only waits the seam asks for: `<= 2 s` +
  `<= 15 s`, and about nothing when the discard comes off at once.** Not a bound in
  every case, and the comment says so rather than implying one again (#280's own
  lesson): the seam's two `Locator.count()` calls take no `timeout=` because
  `count()` does not wait for anything, but they do need the renderer to answer, so
  on one of the conditions this function reports `false` for -- "a page that stopped
  responding" -- nothing here is bounded, as nothing was before. The seam's three
  readings are unchanged in shape and in cause --
  no key for a clean page or a page that cannot be read, `true` once the indicator
  has gone hidden, `false` for a failed click, no visible button, or an indicator
  that never cleared, with a `KeyboardInterrupt` still propagating and still
  leaving `discarded: false` behind -- and `true` is still written where nothing
  after it can fail, which is now the end of the function. `DISCARD_TIMEOUT` and
  `DISCARD_CLEAN_TIMEOUT` keep their values, and the Static-tier test pinning the
  second at or above the save path's budget for the same inlining pipeline is
  untouched. Not re-tuned here, and still a watch item: that bound can only ever be
  calibrated, never proven, so a mutating Live run watches for `discarded: false`
  recorded **together with** `body_html_inlined: true` -- a discard reported as
  failed on a surface whose save demonstrably completed the inlining would mean the
  15 s is short. Also left standing and filed rather than folded in: the sibling
  seam `discard_form` in `e2e_collab_peer_snapshot_live` read `side.root`
  three times and so had both halves of this issue, the latency one and the
  detached-frame misreading that reports `dirty: false` for a form that went with
  its frame. `Side.root_now` is on the shared layer and is what that seam
  needs; it is a different driver's reading and got its own issue, #292 below.
- **`discard_form` resolves its frame once, through `root_now`, so a re-mounted
  Ingress panel can no longer make a dirty form report `dirty: false`** (#292,
  raised by the review of #288 and confirmed without a host). The sibling seam
  reached for `side.root` at each of its three steps -- the dirty read, the button,
  the confirmation wait -- and on `IngressSide` that is a *search*: it re-enters
  `_find_frame(wait_s=60)` whenever the held frame reports detached. An add-on
  panel that has re-mounted its Ingress iframe makes that resolve answer with the
  **replacement** frame, whose freshly loaded document has no `UNSAVED` match, so
  the entry read counted zero and the function returned `{"dirty": False,
  "discarded": False}` -- "the form was never dirty" -- for a form that went with
  its frame, at the moment `beforeunload` fires the `sendBeacon` save this function
  exists to head off. `probe` then reported a run whose forms were never dirty,
  which its own docstring defines as having exercised nothing: the reading hides
  the write instead of naming it. The same door was open at the confirmation wait,
  where a replacement frame has no indicator to go hidden and so records a discard
  that never happened as `true`. One `side.root_now`, held and worked through,
  shuts both: a frame that has gone raises at the first locator call, and
  `discard_quietly`'s `except Exception` already turns that into `{"dirty": True,
  "discarded": False, "error": ...}` -- unknown reported as dirty, the direction
  the verdict must fail in. The three readings are unchanged on every ordinary
  path, and `>> visible=true` stays for the reason the function gives.
- **The latency half is real here and smaller, and the two waits are deliberately
  left alone.** This module has no `except BaseException` and its discard sits
  ahead of no restore, so none of it is in a Ctrl+C-to-restore window -- which is
  why the misreading and not the minute is what motivated the change. The
  confirmation deliberately waits on the whole asynchronous
  `FormController.discard()`, and this driver's budget is not the markup driver's,
  so the click keeps Playwright's default and the confirmation keeps `TIMEOUT`.
  `root`, its cache and `_find_frame`'s 60 s default are untouched, as in #288.
- **The seam is now driven and not only pinned at its shape.** It had one
  executing double -- a side whose `root` raises -- and source assertions for
  everything else, and a reading taken from the wrong frame is exactly what those
  cannot see. Seven Static-tier tests, and all seven enumerated because this entry
  is the audit trail for them: the two resolves counted on every path (`root_now`
  exactly once, `root` never); a side holding a detached frame whose waiting
  resolve hands back a clean replacement -- the old code reads
  `{"dirty": False, "discarded": False}` there, which is the defect itself; one
  each for the four ordinary paths (a clean form, a discard that came off, a dirty
  form with no visible button, and a confirmation that never arrives); and one
  holding the explanation of why the resolve is `root_now`, since that is what the
  next reader of this seam has to not undo. Static tier only, no Live run and no
  Release: 1781 passed, 1 skipped, this driver's module 124 -> 131.
- **One trap worth recording, because it is not confined to this file.**
  `test_a_discard_is_only_clicked_on_a_form_that_shows_the_button` asserted that
  `is_visible()` appears in `inspect.getsource(discard_form)`, and the function has
  never called it -- it uses `count()`. The test was green only because
  `is_visible()` appeared inside one of the comments this change rewrites.
  `getsource` returns comments and docstrings as well as code, so an assertion of
  that shape can be satisfied by prose: it can go red on a comment-only edit, and
  it can stay green over code that never does the thing. The assertion is now
  re-pointed at the mechanism the code actually uses -- the `button.count()` check
  ahead of the click -- rather than keeping a comment phrase to feed the grep; and
  the unreadable-side double gained a `root_now` mirroring the base class's default
  so it keeps modelling `Side` instead of pinning an `AttributeError`.
- **What #263-#292 left unverified is measured on the host** (#282, no Release, no
  add-on build and no Deploy -- every fix in that block is in a driver, and the
  drivers run locally against the add-ons already installed). The eight driver
  fixes of 2026-10-02/04 had all shipped Static-tier only, two of them saying in
  their own commit bodies that the host proof was this run's. Evidence:
  `docs/testing/evidence/2026-10-04-issue-282/`, Release 0.4.10 on `odoo_parity`
  (both surfaces, run `WOOW-MARKUP-20261004T104350Z`) and the local build
  `0.4.10-202610031232` on `catchup164b` (Ingress only, run
  `WOOW-MARKUP-20261004T111302Z`).
- The readings that were only ever asserted: `mailing-editable` records
  `mailing_source: created` on the first surface and `reclaimed` on the second,
  with `body_html_marker_before: true` **and** `body_html_inlined: true` on the
  reclaimed row -- the two-way reading #279 alone could not give, which #286's
  clear is what makes possible -- and `reading: write-bounding` on both of its
  stored fields. `media-document-mailing` records `discarded: true` on the mail
  designer on all four of its records, so 15 s of `DISCARD_CLEAN_TIMEOUT` is
  enough for the whole `commitChanges` pipeline on a loaded host (#280), and
  #288's `root_now` seam read back `CLEAN` with every mailing restored to its own
  body and 0 `hassio_ingress` occurrences in any of them. #277's two-run sequence
  stranded attachment 362 and then reclaimed it:
  `reclaimed_attachment_ids: [362]`, `reclaimed_attachments_removed: true`, and
  the host read afterwards finds it gone. All 18 read-back records carry a
  per-field `reading` kind, 28 declarations in total, including
  `media-document-mailing`'s derived `state-bounding` (#289).
- The two drivers #264 had not reached: the hand checks wrote their **first**
  `.ambient.json` (`visit`: `website.track` +1 over one navigation -- the figure
  that is the measurement rather than the accounting; `editbtn` +2 over six, which
  is the contrast a subcommand that writes no business rows still leaves), and the
  peer snapshot's `discard_form` reports `dirty: true` with `discarded: true` on
  the session that typed, with no `WOOW-PEER-PROBE-` marker on the host afterwards
  (#292, #263's shape of confirmation).
- **`mailing-readonly` ran, which the issue did not expect**, because
  `odoo_parity` carries two mailings in state `done` -- so #289's second
  declaration site is exercised for the first time. Its screen verdict is `ABSENT`
  on both surfaces and the cause is the fixture, not the prefix: those bodies are
  166 bytes with `<img` appearing zero times.
- **Two findings, neither of them in the eight fixes.** `readonly-plain` reads
  `ESCAPED` on the Public origin because two of `project.task(5)`'s 17 html-field
  history revisions carry an Ingress prefix, while the `description` those records
  judge is `CLEAN`. Registered as `G-10` in the parity plan's section 11, with the
  mechanism #296's triage established against the pinned package rather than the
  one first written down here: `html.field.history.mixin.write` stores
  `generate_patch(new_content, old_content)` and `_patch_generator` embeds
  `old_content_lines`, so a revision is a **reverse** patch carrying the value as
  it was *before* that write -- which makes the Ingress save that **heals** the
  field the author of the prefixed revision, and the Public peer's own store the
  author of a clean one. It therefore recurs once per `G-08` store-and-heal cycle,
  and `_html_field_history_size_limit = 300` evicts it after 300 further revisions
  of `project.task.description`, the only versioned field in the package. And `do_codeview`'s success-path restore is gated on
  `--cleanup` while its error and interrupt paths restore unconditionally, so the
  first invocation of this run left a real `ir.actions.act_window.help` holding the
  run's marker until it was written back by hand; both the unrestored and the
  restored records are kept, because they are what was read.
- What the run does **not** say, recorded rather than implied: #289's `report`
  sentence is unexercised (`stored_prefix_found=no` on both record files -- no
  field carried a prefix, so the line naming the kind never printed, and
  manufacturing one would mean writing a prefix into the database on purpose); and
  the interrupt path of #280/#288 stays unmeasured, deliberately, because
  measuring it means arranging the outcome that leaves a marker on a real action
  with nothing to restore it. The 76-item conservation tally does not move:
  `woow.ingress-markup/v1` and `woow.peer-snapshot.v1` do not feed `conservation`,
  and `G-10` is a gap registration rather than a plan item.
- `probe`'s reading order in `e2e_collab_peer_snapshot_live` is now **driven**
  rather than pinned at its shape. A behavioural test drives `do_probe` through
  doubles where the editable answers `DELIVERED-...` while the form is dirty and
  `STORED-...` once a discard has reset it, so a `do_probe` that discards before
  it reads records the second and fails. The source assertion beside it now
  matches the whole call line rather than the bare name `discard_quietly`, and
  the reason is narrower than #292's `is_visible()` case: a plain reorder was
  already caught, because the call text contains the name and carries the first
  match with it. What the bare name does not survive is the call leaving the call
  site -- renamed, or extracted into a helper -- while the comment above it still
  names `discard_quietly`; then `index()` resolves in prose and the ordering
  claim is satisfied by a sentence. Matching the whole line turns that into a red
  `assertIn` somebody has to re-point on purpose. This is the instance #292 left
  unfiled, and the first claim about it -- that the old pin held over a
  discard-first `do_probe` -- was wrong and is corrected here.
- **A borrowed record goes back whatever `--cleanup` says** (#297, Static tier
  only -- this is driver behaviour and no Live run can show it that #282's did
  not already pay for). Three success paths gated the restore of a record the
  driver had only *borrowed* on the flag whose job is deleting what a check
  **created**, so a successful run taken without it left that record holding this
  run's marker, with the absence of a key as the only sign. #282's run found the
  first of the three on `odoo_parity`: see its evidence README, "Host state this
  run leaves". The three are now restore-always, remove-under-the-flag.
- `do_codeview` is the one the ticket names and the worst-shaped of the three:
  `pick_help_action` creates nothing, it borrows the lowest-id
  `ir.actions.act_window` and seeds a record the installation owns. The restore
  moves into `_restore_borrowed_help`, which all three of its paths call -- the
  success path included -- and which keeps the reading three-valued: `true` when
  the write took, `false` when it did not, **absent** when the handler never got
  as far as seeding. It reports a failed write rather than raising it, because
  raising would drop the success path into the handler's `except Exception` and
  rewrite a measured record as `NOT-RUN`. The discard still goes first (#276,
  #280, #288); that order is not in question.
- **`--cleanup` now means nothing for `codeview`, and the signature says so.**
  Neither `do_codeview` nor `_codeview_after_seeding` takes the parameter any
  more -- `run_check` passes it to every handler and `**_` absorbs it -- because
  a flag threaded through to no reader reads as a gate somebody forgot. Its
  meaning is unchanged for every other check: delete what this check created.
- The audit the ticket asked for found the same gate on **both** mailing checks,
  and both are fixed with it. `media-document-mailing` borrows on its `found`
  branch, which is every run on a database carrying a draft; `mailing-editable`
  borrows only the row `--mailing-id` names, and that is the costliest of the
  three because it is the check that *saves* -- a real campaign in `draft` or
  `in_queue`, a row that can still be sent, kept this run's marker in `body_arch`
  and in the inlined `body_html` that leaves the installation with the mail.
  `_restore_borrowed_mailing_body` is a no-op on a scratch or Reclaimed row, so
  calling it on every path cannot restore what the run owns -- the flag was never
  what protected that, the function's own first line is.
- Left alone deliberately: every `--cleanup` gate on a **created** fixture
  (`readonly-iframe`'s scratch `mail.template`, the two media to-dos, the website
  page and view, the scratch mailings, the fixture attachments) -- leaving those
  named after the run is the legible choice #183's and #265's evidence make on
  purpose. `readonly-iframe` under `--task-id` needs no restore at all: it seeds
  nothing there and only reads the named template back, which is why #289 calls
  that reading state-bounding.
- Guards: four behavioural tests drive `_restore_borrowed_help` (the value back,
  an empty `help` back as `False` rather than the seed, the `false` reading on a
  write that failed, and the key written in exactly one place), three drive the
  two mailing sites without the flag, and one parametrized source check holds all
  three restores at their function's own indentation -- nested under a gate they
  would be four spaces deeper. Mutation-checked, each against the assertion named:
  the gate back on `codeview` (the indentation check and the signature check),
  on `mailing-editable` (the indentation check and the `--mailing-id` behavioural
  test), on `media-document-mailing` (the indentation check and the `found`
  behavioural test), a raising restore (the `false` reading and the one-writer
  check), a second inline writer (the one-writer check), and the restore moved
  ahead of the discard (the ordering check, re-pointed off `if cleanup:` and onto
  the call with its arguments, for the reason #282 item 5 records).

## 0.4.10 — 2026-10-01

### Added
- A targets file may now aim at a GET-writing route only when that route's write
  **converges** — a second visit re-derives the same state and renders the same
  screen, a recompute or a re-store, never an accumulation and never a
  consumption. #225 decided the rule (being *bounded* to `odoo_parity` never made
  a write *cross-surface deterministic*: the first surface's visit can edit the
  very screen the second surface then judges), and this is it in the tree. Every
  `GET_WRITING_ROUTES` entry now carries a class beside its citation, and the
  guard reads nothing else: `CONVERGENT` keeps today's `odoo_parity` bound,
  `FIXTURE_CONSUMING` and `UNCLASSIFIED` are refused **on every database**,
  `odoo_parity` included. Because convergence makes each surface's render include
  the effect of its own write, the rule is order-independent — no ordering of the
  two surfaces is fixed, and none may become load-bearing — and `ensure_cart`,
  which leaves a non-empty cart exactly as it is, is the precedent it was read
  off.
- `/shop/payment/validate` is the one fixture-consuming route and is now refused
  everywhere rather than bounded: `website_sale/controllers/main.py:1978-1979`
  confirms the draft order into a sale and `request.website.sale_reset()` drops
  the cart, so the surface that opens it second has no cart to judge and
  `ensure_cart` would silently build a *different* order. The refusal happens
  before a browser launches — it reads the target list and no database, so there
  is nothing to wait for the login to report.
- The two routes #225 left pending were read against the criterion at the pinned
  Odoo (18.0.20260930) and **both are promoted to `CONVERGENT`**. `/shop/cart`:
  `main.py:796` has nothing left to unlink on a second visit and the first
  surface already rendered the cart without those lines, `:767`
  `sale_get_order()` moves the order onto the logged-in partner only while the
  two disagree (`website_sale/models/website.py:455-457`), and `:798` reaches
  `sale/controllers/portal.py:270`, whose `_portal_ensure_token()` stores an
  `access_token` only when the order has none
  (`portal/models/portal_mixin.py:31-33`). `/my/orders/`: the same guarded
  re-store, from `:270` and from the pager at `:199`
  (`portal/controllers/portal.py:93` and `:100`). Each route has exactly one
  branch that does **not** converge — the cart's abandoned-cart revival
  (`main.py:785-786`, which moves an abandoned order's lines and cancels it) and
  the order page's "Quotation viewed by customer" note
  (`sale/controllers/portal.py:168`, one per session) — and a query is the only
  way to reach either (`access_token`, `revive`), which `_TARGET_QUERY` refuses: a
  target may carry a view chooser and nothing else. That dependency is the
  promotion's footing, so a static test ties the two together; if the query rule
  ever widens, both entries have to be read again. A key is a prefix, so the
  promotions reach the siblings too, and what bounds those is that `open` makes a
  GET and nothing else: `/shop/cart/update` (`:803`), `/shop/cart/update_json`
  (`:838`), `/shop/cart/quantity` (`:948`), `/shop/cart/clear` (`:954`),
  `/my/orders/<id>/accept` (`sale/controllers/portal.py:279`), `/decline`
  (`:329`), `/transaction` (`:382`) and `/my/orders/reorder_modal_content`
  (`website_sale/controllers/reorder.py:38`) are each `type='json'` or
  `methods=['POST']`, and the two siblings a GET does reach — `/my/orders/page/<n>`
  and `/my/orders/<id>/document/<n>` — are the ones already recorded as writing
  nothing.
- `/shop/cart`'s promotion is load-bearing, which #225 did not know when it wrote
  that no targets file aims at either route:
  `docs/testing/evidence/2026-09-30-issue-213/targets.jsonl` aims at `/shop/cart`,
  and it is the Live check PR #229 owes. Refusing the route would have made that
  check unrunnable, so the audit is what the check now rests on.
- The 15 portal and `mail` prefixes #226 and #247 added carry no classification
  and are therefore `UNCLASSIFIED` — refused on `odoo_parity` too, where they used
  to be allowed. Nothing aims at any of them (the two targets files in the
  evidence tree name `/shop/payment` and `/shop/cart`, both convergent), reading
  them against the criterion is out of #228's scope, and over-refusing is the
  direction this guard errs in. Classifying one is a one-line promotion plus its
  citation.
- The rule is recorded where it is used: the convergence criterion, the three
  classes route-by-route with the reason for each, `ensure_cart` as the precedent
  and order-independence are stated beside `GET_WRITING_ROUTES` and in the
  adapter's module docstring; the operator's command sheet
  (`docs/testing/INGRESS_VS_PUBLIC_PARITY.md`, appendix A) says it in two lines;
  and `docs/adr/0012-sweeps-verify-on-the-test-host.md` gains a dated
  postscript recording the constraint on its write accounting, its original text
  unchanged. Guard-only; no behaviour change in the add-on and no version bump.
  Issue #228, decided on #225, parent #148.
- `open`'s write bound now covers `mail`'s remaining **16 controllers** — the
  sweep #226 stopped in front of. Of the five GET-reachable routes in them, three
  write and two are clean, and the three write the same way: in a decorator they
  share, not in their bodies. `@add_guest_to_context`
  (`mail/models/discuss/mail_guest.py:18`) updates the guest's timezone at
  `:30-33` through a raw `UPDATE mail_guest` (`:105-114`) on **every route it
  decorates**, from two cookies and no query: the `dgid` a Discuss public page
  left behind (`:136`) and a `tz` naming a zone `pytz` knows (`:90`). Nothing in
  the pinned Odoo sets `tz` itself, so the write is dormant on a browser that has
  only ever been here — but under Ingress the page is served from the Home
  Assistant origin, where another application's cookie reaches Odoo, and a cookie
  is not a bound this list can see. The list gains four prefixes, three of them
  for that decorator: `/discuss/channel/` (the attachment and image streams,
  `mail/controllers/discuss/binary.py:12` and `:35`), `/web/image` (`web`'s image
  route in all 17 of its spellings, `web/controllers/binary.py:164-182`, which
  `mail` re-exposes with a bare `@route()` at `discuss/binary.py:65` whose body is
  a plain `super()` call — the decorator is the only thing the override adds),
  `/mail/message/` (`mail/controllers/mail.py:237`) and `/mail/view` (`:182`,
  which carries no decorator and writes anyway: `_redirect_to_record` asks the
  record for its access action at `:129`/`:131`, and
  `portal/models/portal_mixin.py:68` answers a share user — which an
  `auth='public'` visitor is — with `_get_share_url()` at `:99`, whose
  `_portal_ensure_token()` stores a fresh `access_token` at `:33`). The list goes
  from 22 prefixes to 26.
- `/discuss/channel/<id>` was recorded clean by #226 and is not clean: it carries
  the same decorator (`mail/controllers/discuss/public_page.py:53`). The claim is
  corrected where it was made, and the new `/discuss/channel/` key bounds that
  page along with the two streams under it. The bodies of all three are clean, and
  that is why the decorator is the entry: they search a channel and stream an
  attachment through `ir.binary`, which has no create, write or unlink at the
  pinned Odoo, resizes in memory (`base/models/ir_binary.py:160`) and reaches an
  `ir.attachment` whose `validate_access` (`:723`) and `_to_http_stream` (`:805`)
  write nothing either.
- Read clean, so the next sweep need not read them again: the two worklet routes
  (`mail/controllers/discuss/rtc.py:111` and `discuss/voice.py:10`), which answer
  with a file read off the disk through `file_open`, reach no model at all and
  carry no decorator.
- A second reason `readonly=True` is not a write bound, and this one belongs to
  the add-on rather than to Odoo. The decorator's guard is
  `not req.env.cr.readonly`, and on this product that cursor is **not** readonly:
  `Registry.cursor(readonly=True)` returns a read-only cursor only when
  `_db_readonly` is set (`odoo/modules/registry.py:1015` and `:1028`), which needs
  a `db_replica_host` (`:166`) that cont-init never writes
  (`rootfs/etc/cont-init.d/10-odoo-config.sh:97-100`). So the guard that reads as
  a write bound on a replica holds nothing here, and nothing raises
  `ReadOnlySqlTransaction` to say so. A `readonly=True` route is not merely rolled
  back and re-run after a write (`odoo/http.py:2157-2168`) — here it was never on
  a read-only cursor at all.
- The sweep also read the two routes in `mail/controllers/mail.py` that #226
  counted as read while recording only `/mail/unfollow` out of it; both are the
  new entries above. And the stop-line now points where the decorator goes next:
  `im_livechat` applies it to 13 routes, `cloud_storage` and `website_livechat` to
  one each, and `im_livechat` is an installed module — so the next sweep reads a
  `type=`/`methods=` line per route rather than 13 bodies, because the write is
  already read. Guard-only; no behaviour change and no version bump.
- `odoo18ce/tests/e2e_collab_peer_snapshot_live.py`, the two-session Live-tier
  run #243 needs for that row and the first script here that opens two sessions
  on one record: session A types an unsaved marker, session B joins and the run
  waits for that marker to arrive (the transport's own evidence, since nothing
  stored it), B saves, and `project.task.description` is read back with every
  prefix in it classified as the saving session's, the other session's, or one
  nobody claims. `--pair ingress-public` is the pair that can produce a foreign
  prefix on this host. **It has not been run** -- this Iteration was told not to
  deploy and not to take the measurement -- and no token can reach its output:
  every value passes through a redaction that puts a session's label where its
  prefix was. Its pure parts are tested at the Static tier
  (`tests/test_e2e_collab_peer_snapshot.py`), including that the prefix shape it
  looks for is the gateway's own.
- The **Live tier** gained a driver for the Ingress checks that are an action
  rather than a screen: `tests/e2e_ingress_hand_checks.py`, with `visit`,
  `editbtn` and `todosave`. The menu/action adapter judges one screen against
  the same screen on the other surface, and three things #235 had to see are
  not that shape -- a page view whose result is a `website.track` row, a click
  that has to land in the web client, and a save whose result is in
  `project.task.description`. The driver borrows the adapter's own
  `SurfaceDriver`, so the Ingress session, the database reading and the
  `Masker` that hides credentials and origins are the ones every other record
  is written with, and it judges a **Prefix escape** with the adapter's
  `is_prefix_escape` rather than a second opinion -- a review of the first
  version caught exactly that: asking whether a request reached the Home
  Assistant origin *outside* the prefix answers "no" for the doubled prefix of
  `U-A2`, which is the shape #211 is about. `tests/test_e2e_ingress_hand_checks.py`
  pins that case and the rest of the pure parts. Live tier only: no change to
  the image and no version bump.
- **What a "read-only" Live run actually bounds is now written down**, as a dated
  postscript on `docs/adr/0012-sweeps-verify-on-the-test-host.md` (2026-10-01,
  #227), with the operational pointer in `docs/agents/live-tier.md`. A read-only
  run makes **no business writes**; it does not leave **zero rows**, and never
  has on a database with `website` installed. The target-seam guard #212 built
  bounds *navigations to routes that write by design*, and two writes sit outside
  that seam which no list keyed on a route can bound. Visitor tracking upserts a
  `website.visitor` and inserts a `website.track` row on any tracked page's GET
  (`website/models/ir_http.py:203`), gated on the template the response rendered
  rather than on the route — so every run that opens a website page makes it,
  `open` with a website target and the hand-check driver's `visit` alike, and
  only `crawl` never does. And a page writes through its own markup and
  JavaScript: the header cart link (`website_sale/views/templates.xml:13`) and
  `/shop/products/recently_viewed_update`
  (`website_sale/static/src/js/website_sale_recently_viewed.js:44`). Both carry
  page-view telemetry and no business state, which is why the guarantee is
  restated rather than withdrawn, and the 2026-10-01 #235 run had already counted
  them: 19 new `website.track` rows, one of which its `U-C5` check reads back as
  its measurement. The `GET_WRITING_ROUTES` comment now points at that postscript
  instead of carrying the only copy, and is nine lines shorter for it. Making a
  run *name* those ambient writes in its own evidence — a count delta per run —
  is the entry below (#256). Documentation and one static test: no behaviour
  change, no image change, no version bump.
- A run now **names the ambient rows it left**, in counts. The postscript above
  records two writes no targets file can bound — serving a tracked page upserts a
  `website.visitor` and inserts a `website.track` row, and a page's own markup and
  JavaScript write too — and how many rows a run left was a figure reconstructed
  on the host afterwards, which is how #235 got its 19. `crawl` and `open` now
  count both models after the login and again after the last navigation and write
  the delta beside their evidence, under the records' own name with
  `.ambient.json` for its extension (`ingress-open.jsonl` →
  `ingress-open.ambient.json`), with the run id, the surface, the subcommand and
  how many navigations the delta is over — the driver's own count of them, since
  one target can be several page views and each of those is what writes. The reading
  is a count and nothing else: no URL, no visitor identity, nothing to mask. A
  `crawl`'s figure is the interesting zero — it navigates `/odoo/action-<id>`,
  which renders no tracked page, so the postscript's claim that a crawl leaves
  nothing is measured per run instead of asserted.
- The counts are read over the session's own `search_count`, the read-only RPC the
  shared layers' Live harness already uses — the adapter acquires no database
  connection and takes nothing over `ssh`. It passes through the same policy every
  other thing this driver does passes through (`Operation.COUNT_ROWS`, still a
  member of `NON_MUTATING_OPERATIONS`), and a `call_kw` POST renders no template,
  so the reading cannot add to the rows it is counting. A model this database does
  not hold, or one this user may not count, leaves its reason in the record
  instead of a zero — per model, so a reading that got one count keeps it — and
  the summary is written on the way out, so a run that failed still accounts for
  what it left.
- The figure is **accounting and not a verdict**, and three things hold it there:
  its own schema (`odoo-parity-ambient/v1`) in its own file, a `diff` that never
  reads that file and a `read_records` that refuses the schema, and the parity
  plan's §12 declaring it outside `conservation` the way `woow.peer-snapshot.v1`
  already is. Both surfaces visit the same pages, so an unequal delta is an
  ordering artefact — the visitor row the first run upserted is already there for
  the second — and judging it would raise a Blocker on the order two runs happened
  to run in. The record carries that sentence itself, beside the one saying the
  delta is net: another session writing during the run is inside it, and the
  `website.visitor` GC cron can take rows out of it, so a delta below zero is a
  vacuum and not a deletion the run made. No image change and no version bump.

### Fixed
- The markup strip that keeps the Ingress prefix out of a saved html field now
  removes **any** prefix the gateway would accept, not only the one this page
  was handed. The To-do description is a collaborative field: the collaboration
  transport ships serialised nodes -- each attribute's value byte for byte --
  and the peer that joins second is handed the first peer's whole document, so
  the sending page's prefix arrives in the receiving editable (through
  `setAttribute`, which the shim wraps and which prefixes it *again*, so the
  value carries two) and the receiving session's save is what would store it.
  `__WOOW_INGRESS_MARKUP_OUT__` now strips every occurrence of
  `__INGRESS_PATH__` **and** every match of the shape nginx's
  `$safe_ingress_path` map validates, so a prefix a value arrived with is
  removed whoever put it there. One authority for that shape: the map is where
  it is written, and a test derives both patterns from the template and refuses
  a difference. A token longer than the map accepts is left alone rather than
  cut to the bound, because a URL with bytes taken out of its middle is worse
  than the escape. No new global and no new rewrite: every save site of #210
  and #238 calls this helper, the mailing's inlined `body_html` included.
- The issue's premise was corrected on the way: the token in an Ingress path is
  the **add-on's** `ingress_token`, one persisted secret per installed add-on,
  not the user's and not the session's (the per-user session is a separate
  secret carried in the `ingress_session` cookie). So two Ingress sessions on
  one add-on edit under the same prefix and #210's strip already covered that
  pair. A prefix this page never saw comes from a reinstall or a restored
  backup minting a new token, a second add-on or a second Home Assistant on the
  same database, or **a peer on the Public origin**, which serves no shim and
  no rewrite and therefore stores what it is sent. The Ingress side cannot
  prevent that write; what this change does for it is heal the record on the
  next Ingress save. The Public origin is untouched, and `U-A6`'s probe list is
  not extended. The same reading corrects two rows of the parity plan that
  called that token a *session* token (`RC-15`, `G-07`); both keep their
  severity and their advice, because the path still carries a credential and a
  link pasted to a colleague still does not open -- what refuses it is the
  `ingress_session` cookie their browser does not have. No version bump. Issue
  #234, ADR 0004 (third 2026-10-01 postscript), parent #148.
- The `open` subcommand now **reports** the write it has been bounding. A target
  on a `GET_WRITING_ROUTES` route writes while its screen renders — Odoo edits
  the draft order on a plain GET — and since #212 that write has been held to
  `odoo_parity` and named in no record: ADR 0012's "every mutation is
  accounted" lived in the bound alone, and `_judge`'s "records written"
  comparison, the one that raises a Blocker on a cross-surface difference,
  compared "none" with "none" on both surfaces, so a real divergence in what
  the GET wrote could never fire. After such a navigation the driver now reads
  the session's draft order — the same cart reading a failed cart step takes,
  factored out so both readers share it — and puts it in the record's `writes`
  as an ordinary `{"model": "sale.order", "id", "items", "how"}` row, on both
  surfaces, so `diff` judges it exactly as it judges a cart-write difference.
  No new evidence format. The row is a *state* reading and says so: its `how`
  names the prefix and quotes `GET_WRITING_ROUTES` for the write that was read,
  because two aimable prefixes write elsewhere (`/my/orders/` stores an
  `access_token`, `/website/lang` writes the order's lines) and `writes` still
  covers `sale.order` and nothing else. A target under no listed prefix takes
  no reading at all and records exactly what it did before — the reading is
  itself a `/shop/cart` navigation, which writes, so it is bounded to
  `odoo_parity` like every other write in this driver and costs one more
  navigation per GET-writing target. A cart page that would not answer leaves
  no row and the reason on the record's `result`, rather than the silence this
  change exists to end; a reading that failed on one surface only is then a
  write difference at Blocker severity, which is the verdict a comparison that
  could not be made deserves, and the `result` beside it in the joined record
  says it was the reading and not the database that differed. A visit that left
  no draft order at all leaves no row either, for #213's reason: a row naming
  `sale.order:0` would claim a record nobody created, and "none" on both
  surfaces is what the visit actually left. Future runs only: the #163 evidence
  is not rewritten. Issue #224, parent #148.
- Reopening the **media dialog** on an existing image highlights the attachment
  it came from again, under Ingress as on the Public origin.
  `ImageSelector.isInitialMedia` compares the element's `src` — which carries the
  Ingress prefix, put there by the shim's `setAttribute` wrapper on an image the
  dialog just inserted and by `__WOOW_INGRESS_MARKUP_IN__` on one that came out
  of the record — with `attachment.image_src`, which is
  `ir.attachment._compute_image_src`'s root-relative
  `/web/image/<id>-<checksum>/<name>` delivered over `call_kw`. So it never
  matched: the grid opened with nothing selected and the file had to be found
  again. The element side now goes through `__WOOW_INGRESS_MARKUP_OUT__`, the
  same move #210 made for `/html_editor/get_image_info`'s argument — one URL
  authority, no new global, a no-op on a value with no prefix, and #234's shape
  strip for free, so an image a collaborative peer sent matches too. Two
  `sub_filter` rules for that line, because Odoo 18 ships the media dialog
  **twice** (`html_editor`'s, which a backend form opens, and the legacy
  `web_editor`'s, which `wysiwyg.js` and the website editor's snippet options
  open) and the two files are the same code with different quote characters.
  Display state only: nothing is stored either way. Issue #239, ADR 0004 (fourth
  2026-10-01 postscript), parent #148.
- The same method's **other** branch, which is the one reached for any image the
  image tools have touched, had the same defect from a different direction — and
  the `src` fix alone would not have reached it, because that branch `return`s
  first. `isInitialMedia` compares `dataset.originalSrc` with
  `attachment.image_src`, and nothing in the Runtime shim prefixes
  `data-original-src` (the markup helper's attribute test is an exact name, so it
  is not a `data-src`). What prefixes it is the **generic HTML location**: its
  rule is written for `src="/`, and `sub_filter` being a plain substring search it
  matches inside the longer attribute name `data-original-src="/…` — no
  neighbouring rule claims that position first. Odoo ships that attribute inside
  stored arch (every themed image in
  `mass_mailing_themes/views/mass_mailing_themes_templates.xml` has one), so
  markup delivered as an HTML response carries a prefixed `data-original-src`
  while the same attribute on a field value does not. One more `sub_filter`,
  which serves both dialogs because it is the single line they spell identically.
  Found by a review round, not by the issue.
- Toggling the HTML editor's **code view back off** no longer re-inserts the
  record's markup with no Ingress prefix. `HtmlField.toggleCodeView` assigns
  `this.value` straight into the editable, which is a sixth markup insertion with
  none of #210's five rules on it, so every root-relative URL in the record was
  fetched from the Home Assistant root and answered 404 — the same escape as the
  To-do form's two onboarding pictures, on the same field, reached a different
  way. One `sub_filter` on the Ingress asset location, through
  `__WOOW_INGRESS_MARKUP_IN_VALUE__`: #237's helper and not #210's plain `IN`,
  because `get value()` returns `markup(newVal)` whenever the record's value is a
  `Markup` — which it is for every html field — and `IN` returns a non-string as
  it came, so the obvious rule would have matched its pattern, changed the bytes
  and fixed nothing. A test drives that rule and shows the picture still fetched
  from the Home Assistant root. Nothing is stored by the site: what stores is
  `_commitChanges` on the next blur, where #210's rule 2 strips the prefix again,
  and the round trip is executed on those shipped bytes rather than asserted —
  including the same round trip through Odoo's *unrewritten* `updateValue`, which
  is what #210 stands between this rule and the database for. Issue #240, ADR
  0004 (fifth 2026-10-01 postscript), parent #148.
- The bound on that site is **debug mode**, not "no shipped view sets the
  option": `codeview: Boolean(odoo.debug && options.codeview)` needs both, and
  five shipped views set the option, on four fields — `res.users.signature` in
  both of `base`'s user forms, `ir.actions.act_window`'s `help` (#158's field),
  `mail.template`'s `body_html` and `hr_recruitment`'s send-mail wizard body, the
  last two through `html_mail`, a subclass of the same field. #240 and #238's postscript both said otherwise.
  The label stays `severity: minor` on what survives: a developer in debug mode
  and nobody else. One shape of that screen would also produce a false pass and is
  driven in the Static tier for it — a value whose parse yields a non-empty
  `<head>` turns `sandboxedPreview` on, the field renders through the readonly
  `HtmlViewer` (#237) and `this.editor` is undefined, so the toggle runs and this
  site is never reached.

### Changed
- ADR 0004's open list named **two** media dialog comparisons; the method behind
  the first makes three, and doing to the third what the list said would have
  broken it. `DocumentSelector.fetchAttachments` compares the element's `href` with
  `` `/web/content/${attachment.id}` ``, and that template literal begins
  `` `/web/ `` — one of the generic literal rules the Ingress asset location has
  shipped since #166. So the bundle reaches the browser with the prefix already
  spliced into the literal, the comparison is prefixed-against-prefixed, and it
  has been highlighting the right document all along; an `OUT` on the `href`
  alone would have stripped one side and left the other. Measured by serving all
  four captured excerpts through a real nginx carrying every rule of that
  location: the two document ones come back with the prefix inside the literal,
  the two image ones changed by nothing but this family's own three rules,
  because `attachment.image_src` is an ORM value and the element's reads are DOM
  reads, so no generic rule can reach either operand.
  `tests/test_ingress_media_dialog_preselect.py` (40 tests) runs that nginx
  measurement and requires its answer to equal, byte for byte, what the drivers'
  own `str.replace` produced; derives the `` `/web/ `` rule from the template
  rather than quoting it; asserts it is the **only** generic rule reaching the
  excerpt; runs the comparison in node and reads back which attachment was
  selected; executes the one-sided strip and shows it selecting nothing; and
  refuses any `sub_filter` that names the `href` read, so the rule the open list
  asked for cannot arrive later by a reader following the list. Five patterns
  measured, three rewritten; `tests/fixtures/bundles/README.md` carries the
  per-bundle counts, including `html_editor.assets_media_dialog`, the nineteenth
  bundle this family added. No version bump: the Release and the Live rerun
  belong to #243.
- The general rule this one earned, recorded in ADR 0004: a comparison is not a
  URL site with a known direction, so measure **both** operands as the browser
  receives them before teaching one about the prefix. A literal in a bundle is
  subject to every generic rule in the asset location; a DOM read to every
  generic rule in the HTML location *as well as* to the shim's wrappers; an ORM
  value to none. Both of this Iteration's surprises were that mistake in
  opposite directions — one operand assumed clean that was not, one assumed
  dirty that was not — and "nothing in the shim touches it" is not "nothing
  touches it".

## 0.4.9 — 2026-10-01

### Added
- `open`'s write bound now covers the **portal** controllers of every module the
  add-on installs, not just `website_sale` plus the one `sale` route #212 read on
  the way. `GET_WRITING_ROUTES` went from 11 prefixes to 22, each new one citing
  the write it was read from in the pinned Odoo: `/my/invoices/`,
  `/my/purchase/`, `/my/projects/` and `/my/tasks/` (the portal pager stores an
  `access_token` on the records either side of the one being viewed --
  `portal/controllers/portal.py:93`, `:100`, `portal/models/portal_mixin.py:33`
  -- and the project and task pages also token every attachment they are about to
  render, `project/controllers/portal.py:209` and `:556`),
  `/my/invoices/overdue` (which bumps the company's batch payment sequence,
  `account/models/company.py:272`), `/my/project/` and `/my/task/` (the outdated
  spellings, which redirect into the two writing pages, and `page.goto` follows a
  30x), `/mail/unfollow` (`mail/controllers/mail.py:225` unlinks a follower) and
  `/digest/` (which unsubscribes a user and sets a digest's periodicity on a
  plain GET).
- `/chat/` and `/meet/` are bounded too, and they are the first entries on that
  list that **no query rule bounds**: `mail`'s Discuss public pages create a
  `mail.guest` and a `discuss.channel.member` from a channel uuid in the path
  alone (`mail/controllers/discuss/public_page.py:96`), and create the
  `discuss.channel` itself from an unknown token (`:69`) -- with a
  `request.env.cr.commit()` on the concurrent-insert path (`:81`) that a rollback
  cannot take back. The Runtime shim already rewrites the invitation link that
  leads there (`nginx.conf.template:591`), so it is a route this product
  navigates. Every other GET write the audit deferred needs a query that
  `parse_targets` refuses; these two need nothing.
- The list's comment now records which controllers were read and **found clean**
  -- every portal list page, `/my/account` and `/my/security` (whose writes are
  POST-only), the payment result pages, the downloads, the chatter avatar and
  both rating pages -- which two are clean only on a bare GET (`/payment/pay` and
  `/my/payment_method` store an invoice token when the query names an
  `invoice_id`, `account_payment/controllers/payment.py:149`), and where the
  audit stopped, so the next one does not re-read the same routes and knows to
  start on `mail`. That stop-line first put `mail`'s unread controllers at eight
  and they are **16** -- `controllers/discuss/` is a directory of eight of its
  own, and a listing of the top level alone misses it, which is the same
  directory `/chat/` was found in. Corrected, and sized: those 16 carry 51
  `@route` declarations of which 5 are GET-reachable, all 5 carrying a
  `readonly=True` that is not a write bound. #247 holds that sweep. Guard-only;
  no behaviour change and no version bump.
- The static tier measures how much of nginx's 4096-byte configuration token
  buffer the Runtime shim's prefix script has left, and fails while there is
  still room to act. That script is one single-quoted parameter, and every
  Issue that adds a wrapper to it makes it longer: #174 recorded "~200 bytes
  short of" the buffer in a comment, later softened to "a few hundred bytes",
  and by #210 the real figure was **148**. Nothing measured it -- the next
  addition over the line would have been found by `nginx -t` failing with
  `too long parameter`, which names no budget, and an addition under the line
  would have been found by nothing at all. `tests/test_nginx_parameter_budget.py`
  now measures every quoted parameter in the template with cont-init's
  substitutions applied, holds a 64-byte reserve on the shim, says in the
  failure that the way back is to move a part of the script into a `map` of
  its own (nginx concatenates variables after parsing, so a reference costs
  only its own length), pins the limit against a real nginx, and refuses any
  comment that states the headroom in prose -- which is the shape the stale
  claims took. The two comments that carried a figure now point at the
  measurement.
- A review round found two overstatements in that measurement, both now
  corrected. The nginx it drives is the one on the **Static tier**'s PATH,
  installed from the runner's base and not from the image's, so it pins the
  constant against a real nginx without proving it is the nginx the image
  ships; a differing buffer in the image surfaces on a **Deploy**, as an
  add-on that does not start. And the budget's worst case for
  `%%CANONICAL_URL%%` was an assumption, not a bound: `public_url` is an
  add-on option, and cont-init's check reads the value's shape and never its
  length, so an origin of a legal shape but 4000 bytes long would have been
  rendered into a parameter nginx refuses -- the exact failure the budget
  exists to catch early, reported as headroom. `10-odoo-config.sh` now caps
  the **Canonical URL** at the budgeted 2048 bytes and drops an over-long
  value the way it already drops a misshapen one (a warning, and a **Runtime
  shim** that publishes nothing), and a test reads the cap out of the script
  so the two numbers cannot drift apart. That cap is the one behaviour change
  here; it needs no version bump of its own.
- The **Build tier** now reads the gateway config with the nginx the add-on
  ships. Correcting the docstring above said where the measurement stops; this
  moves the stopping point. `tests/in_image/gateway_config_loads.py` runs
  inside the image this build produced and checks three things against
  `/usr/sbin/nginx` there: that the token buffer is the size the budget assumes
  (a token at the limit parses, one byte more does not), that the shipped
  template loads for every start shape -- `public_url` set, unset, and unset
  with no LAN address -- for an empty **Generated rewrite** file and a
  populated one, and that a **Canonical URL** at the new cap still loads while
  one far over the cliff does not. Every number comes from the file that states
  it: `TOKEN_LIMIT` from the budget test, `CANONICAL_URL_MAX` from the shipped
  cont-init. So the budget's worst case for the Canonical URL is now verified
  against a real nginx rather than assumed, and a differing buffer in the
  image's nginx fails a pull request instead of a **Deploy**.
- The renderer behind both tiers exists once, in `tests/gateway_render.py`
  (stdlib only, because the probe imports it inside the image where pytest and
  PyYAML are not). `test_dual_gateway.py` renders through it, so the **Static
  tier** and the Build tier cannot measure different files.
  `tests/test_gateway_config_in_image.py` proves the probe's own logic against
  the runner's nginx -- including both ways it goes red, each injected from the
  real defect it stands for -- and pins the Build-tier step to the
  unconditional amd64 build, this build's image, and a timeout. A probe that
  silently broke would otherwise pass in the one tier nothing watches.

### Changed
- The weekly bump bot keeps `odoo18ce/odoo-deb-depends.txt` current. It reads
  `Depends` out of the same Odoo package it hashes and **merges** it into the
  committed list instead of regenerating it: the `deferred`, `dropped`,
  `alternatives` and `satisfied-by` notes are state the `.deb` cannot supply
  -- which member of an alternatives group bookworm's apt resolves is a fact
  about the base image, `python3-lxml-html-clean | python3-lxml` resolving to
  the *second* name -- and a regenerate loses them and turns the layer guard
  red three ways. A dependency the nightly **gains** is appended with a
  `deferred` note naming the bump, so layer (a) is untouched and the static
  tier stays **green**: the build jobs need it, and a red one would cost the
  bump pull request the image build ADR 0002's human merge rests on. One the
  nightly **loses** keeps its line with a `dropped` note while layer (a) still
  installs it, and goes only when (a) does not. The pull request body gains a
  section naming what was added, removed, deferred or dropped, and says so in
  one line when nothing moved. The one question the bot refuses is which
  member of an alternatives group apt resolves: a group whose recorded member
  the new spelling no longer names, or one the list records nothing of, is left
  untouched and asked about in the body, because the answer is in `apt-cache
  policy` inside the base image and not in the `.deb`. Nothing in the step can
  fail the bump either -- a failed step stops the ones after it, so an
  unreadable `Depends` or a list the merge cannot parse would cost the weekly
  bump its pull request and its image build; instead the list is left as it is
  and the body says a human is needed. The merge is a script with unit tests,
  down to a no-op against the real `Depends` of the currently pinned package,
  and tests that hold its readers equal to the guard test's. Issue #156,
  parent #153, ADR 0013 (new postscript). CI only: no change to the image and
  no version bump.
- The weekly bump bot proposes the Debian **base-image** bump in a pull
  request of its own, labelled `base-image`, instead of folding it into the
  weekly Odoo pin. The base sits below every layer of the image, so moving its
  tag rebuilds all of them -- layer (a) included, which an Odoo bump leaves
  alone -- and the Release that carries it is a full download of the whole
  image, about 700 MiB, for every host on both architectures. That is the
  download that failed twice in #153, and bundling it with the routine weekly
  bump made the routine bump cost the same. `odoo-bump.yml` now runs two
  independent paths: the Odoo path rewrites only the two `ODOO_DEB_*` lines on
  `chore/odoo-nightly-bump` as before, and the base-image path starts from a
  clean tree, rewrites only `BASE_IMAGE_TAG` on `chore/base-image-bump`, and
  says in its body what merging it costs and that it is merged quarterly or on
  a security need. Neither is auto-merged (ADR 0002, new postscript), the
  base-image pull request is rewritten in place rather than reopened, and both
  bullets go through one CHANGELOG writer that merges into whatever
  `## Unreleased` already holds. CI only: no change to the image and no
  version bump.

### Fixed
- Under Ingress, the **legacy `web_editor` editor** -- the one Email
  Marketing's mail designer runs -- now loads a record's markup under the
  Ingress prefix and stores it root-relative again. Odoo 18 ships two HTML
  editors: #210 and #237 rewrote `html_editor`, and ADR 0004's postscript had
  already noted that this editor "carries none of these expressions". That was
  literally true -- its load and save sites are different expressions, so not
  one of those eight rules fired on it -- so a mailing body's pictures and
  linked documents were fetched from the Home Assistant root and answered 404,
  and, worse, **saving a mailing under Ingress stored the Supervisor token** in
  `body_arch` and in the inlined `body_html` that goes out with the mail. Ten
  rewrites close it: six putting the prefix on where markup becomes DOM
  (`Wysiwyg.startEdition`, `OdooEditor.resetContent`, the three branches of the
  readonly iframe a *sent* mailing renders through, and the `t-out` of the
  field's own readonly template) and four taking it off where a value becomes a
  record (`getEditingValue`, mass_mailing's inlined second field, and the code
  view's two writes). All six insertions go through
  `__WOOW_INGRESS_MARKUP_IN_VALUE__`, the helper #237 added, because every value
  here is an OWL `Markup` object; no new global is published. The strip sits on
  `getEditingValue` rather than on the `record.update` beside it, because
  `updateValue` compares the editing value with the record's before writing:
  strip later and every commit looks dirty and writes the field. Three widgets
  reach this editor, and checking which found one the issue had not named --
  `account_payment_register_html`, Register Payment's installments note, whose
  own value holds no URL but whose render path is now covered; `html_legacy`,
  by contrast, has no shipped view behind it at all. The mail designer's own
  iframe is built by `document.write`, so no Runtime shim runs in it, and it
  turns out to carry none of these files -- every rewritten expression runs in
  the page's realm, which is a measurement in the fixtures' README rather than
  an assumption. Two of the ten patterns start mid-identifier because nginx
  reads a `$` in a parameter as a variable and this is jQuery-era code; a test
  proves each is really the tail of the expression it names. The Public origin
  is unchanged and `html_editor` keeps behaving exactly as #237 left it. No
  version bump. Issue #238, ADR 0004 (second 2026-10-01 postscript), parent
  #148; the Live rerun is #243's.
- Under Ingress, a **readonly html field** now renders its record's pictures
  and linked documents under the Ingress prefix, down both of the paths it has.
  #210 fixed the editable path; this is the readonly `HtmlViewer`, which ADR
  0004's postscript named as the markup site that "reaches markup twice over"
  -- `t-out="state.value"` on the plain path and `iframeTarget.innerHTML` on
  the `hasFullHtml`/`cssAssetId` one -- and it is the more common of the two: a
  field is readonly on every form the user cannot edit, on every record a
  portal shows (the project-sharing client serves the same bytes) and in the
  html field's history dialog, which mounts the same component. Every
  root-relative URL in the stored markup was resolved against the Home
  Assistant root and answered 404. Nothing was ever stored wrong and nothing is
  now: a viewer has no save, so there is no strip half here, and the value the
  component holds still carries the record's own bytes -- the prefix goes on as
  the markup is inserted. Both rewrites call one new Runtime shim helper,
  `__WOOW_INGRESS_MARKUP_IN_VALUE__`, because the value a readonly html field
  renders is an OWL `Markup` object and #210's `__WOOW_INGRESS_MARKUP_IN__`
  returns a non-string as it came -- calling it here would have been a silent
  no-op. The new helper prefixes through that one and puts the wrapper back
  through the value's own constructor, since OWL inserts a `Markup` as HTML and
  escapes anything else. One of the two rewrites is the gateway template's
  first rewrite of an **OWL template**: its pattern comes from the bytes the xml
  bundle serves rather than from the source file, because lxml re-serialises
  the template on the way (the file's double space and its space before `/>`
  are not there), it anchors on the whole `<div>` because `t-out="state.value"`
  alone also occurs in the monetary field, and its fallback is an arrow
  function because OWL rewrites a `function`'s parameter into a `ctx` lookup
  and would take the component out at compile time. The `hasFullHtml` iframe's
  `sandbox` is untouched and unaffected: the helper runs in the page's realm on
  a string. The Public origin is unchanged. No version bump. Issue #237,
  ADR 0004, parent #148.
- Under Ingress, a website page view again records the page's **Canonical
  URL**. The fix that first shipped in 0.4.6 was applied on the test host and
  changed nothing there: every Ingress page view still stored the Home
  Assistant host (`U-C5`, root cause `RC-9`), and the add-on's own Odoo log
  carried both the module's "patched" line at startup *and* its "the request's
  url could not be replaced" warning on every one of those page views. The
  replacement was the no-op, not the patch. `request.httprequest` is not the
  werkzeug request: it is `odoo.http.HTTPRequest`, which wraps one and installs
  a plain `property` for each attribute it forwards, `url` included. A plain
  `property` is a data descriptor and never reads an instance's `__dict__`, so
  the value the module wrote there was read back by nobody. It now **assigns**
  to the attribute, which the wrapper forwards to the werkzeug request behind
  it, and puts the address the browser really used back after the page view is
  recorded -- by writing it again, because a forwarded attribute has no
  deleter. A request that refuses the assignment, or accepts it and goes on
  reporting the old address, is recorded as it arrived and said so in the log,
  as before. Every pull request's in-image check now also builds the request
  Odoo itself builds in that image, has this module replace that request's URL
  and put the arrived address back, and reads the URL itself after each,
  instead of only reading the flag the patch sets: reading the flag is what
  called this green while the host was unfixed. Nothing else changes -- the stored URL is still
  built on `website.get_base_url()`, a visit that already arrives on the
  Canonical URL still stores exactly what it stored before, and **page views
  stored before this version keep the Home Assistant host**: they are not
  rewritten and not deleted. No version bump. Issue #160, parent #148.
- Under Ingress, the **"Edit this content"** link on a website page now
  carries the Ingress prefix once instead of twice. `/@/<website path>` is
  Odoo 18's route from a website page into the web client, and it is the one
  route whose tail is itself a website path rather than a URL to fetch. Odoo
  builds the link by splicing `location.pathname` -- already prefixed under
  Ingress -- into that tail, so the tail read `/@<INGRESS_PREFIX>/shop/payment`
  and the prefix went on a second time, giving
  `<INGRESS_PREFIX>/@<INGRESS_PREFIX>/shop/payment`: the web client was asked
  to open `/api/hassio_ingress/<token>/shop/payment` as a website path (the
  doubled prefix of `U-A2`, a `GAP` the #163 run recorded on `/shop/payment`).
  It was never specific to the checkout -- the button is on every website page
  whose viewer may edit it. Two rewrites on the Ingress listener's asset
  location fix it: the link is now built from the canonical path with the
  prefix put on once, at the front, which is the value every consumer of it
  needs -- the anchor, the two `window.location.replace` redirects behind
  `?enable_editor` and alt+A, and the website editor's link popover, which
  hands `window.open` a `URL` object the Runtime shim does not prefix. The
  popover's own "this link is already in backend form" check now recognises a
  prefixed `/@/` path as well, so a link that is already there is followed
  rather than reopened, exactly as on the Public origin. The Public origin
  gets neither rule. No version bump. Issue #211, parent #148.
- Under Ingress, the **To-do** form's description now shows its two
  pictures instead of two broken images. The onboarding to-do Odoo creates
  for every user carries
  `<img src="/project_todo/static/img/todo_access.png">` and one more like
  it inside `project.task.description`, the browser resolved both against
  the Home Assistant root, and Home Assistant answered 404 --
  `route_escape=2`, `http_4xx_5xx=2` and `console_error=2` on a screen that
  is clean on the Public origin (a Prefix escape, root cause `RC-1`). Those
  URLs are record content in the database, not a bundle asset, and the HTML
  editor inserts them as markup -- the one path the Runtime shim leaves
  alone on purpose, because the editor saves the same value back and a hook
  there would write the token-bearing Ingress prefix into the record. So
  the shim now publishes two markup helpers,
  `__WOOW_INGRESS_MARKUP_IN__` and `__WOOW_INGRESS_MARKUP_OUT__` (string
  functions, read-only, Ingress-only, prefixing through the same `path()`
  the `fetch`, XHR and attribute wrappers already use), and five rewrites
  on the Ingress listener's asset location call them: the prefix goes on at
  both places the editor renders a stored value -- when the field opens, and
  when the collaboration plugin resets a stale document from the server --
  comes off again on every value the field writes to the record and on the
  clone the urgent save compares against it, and comes off the `src` the
  image tools send to `/html_editor/get_image_info`, which only recognises
  an attachment from a path beginning `/web/image`. The prefix goes only on URL
  attributes inside a start tag, so prose and escaped code samples keep
  their bytes, and it comes off every occurrence in the stored string, so
  neither the editor nor a pasted image can put an Ingress URL -- token and
  all -- into a record. The value that reaches the database is the value
  the Public origin would have saved, so a to-do edited under Ingress still
  shows its pictures on both surfaces. Two consequences worth knowing: a
  URL in record HTML that was not already in normal form comes back
  percent-encoded or with a `..` segment collapsed the first time it is
  edited under Ingress (the same address, different bytes), and text that
  looks like an Ingress prefix is removed when the field is saved, because
  that prefix carries the Supervisor token. The same round trip covers
  every field the Odoo 18 HTML editor drives in the backend web client; the
  legacy `web_editor` editor behind `html_legacy` and `mass_mailing_html`
  carries none of these expressions and is unchanged, as is the readonly
  preview of an html field. The Public origin gets neither the shim nor the
  rules. No version bump. Issue #210, parent #148.

## 0.4.8 — 2026-09-30

### Fixed
- The Release build no longer reads the GitHub Actions cache, only the
  `:buildcache` on ghcr, so a layer it reports as cached is the layer the
  previous Release shipped. CI writes the Actions cache from builds that
  never publish, and on aarch64 it held a different blob for the
  stable-packages layer than the one 0.4.6 shipped; the 0.4.7 build took
  that blob, so updating to 0.4.7 on aarch64 re-sent the layer (720.9 MiB
  instead of about 380 MiB). No version bump. Issue #219, parent #153.

## 0.4.7 — 2026-09-30

### Changed
- Odoo nightly package 18.0.20260914 -> 18.0.20260930. The first Odoo
  bump on the three-layer image (0.4.6): updating downloads the Odoo
  package layer and the layers under it, about 380 MiB, and reuses the
  stable-packages layer. The `Depends` of the new package is unchanged,
  so `odoo-deb-depends.txt` stays as it is. Issue #153.

## 0.4.6 — 2026-09-30

### Changed
- Release builds keep their layer cache on **ghcr**, and the Release
  notes report the download size. The build cache used to be the GitHub
  Actions one, which is evicted after 7 days unused and LRU-evicted past
  10 GB, and which every pull request writes to; a Release that missed it
  rebuilt layers nobody had asked to change, and because a rebuild runs
  `apt-get update` and gets new bytes, every rebuilt layer arrived with a
  new digest and every host downloaded it again -- 0.4.1 to 0.4.2 re-sent
  718 MiB on aarch64 and 0 MiB on amd64, from the same Dockerfile. The
  Release build now reads and writes
  `ghcr.io/woowtech/woow-ha-odoo-<arch>:buildcache`, on the same package
  as the version images, and writes it only from `main`, so a manual
  images-only run on another ref cannot become the cache the next Release
  starts from. CI reads the same cache -- the package is public, so with
  no ghcr login and no new permission -- and still writes only to the
  Actions cache, which both sides keep reading behind the registry one so
  that the first build after this change does not start cold. The image's compression (`gzip`) and the BuildKit
  version are pinned as well, because both decide what a layer's bytes
  are: changing either is a deliberate change that rebuilds every layer,
  and the workflow says so where the pins are. Every Release also carries
  a table of what updating costs a host, per architecture, against each
  of the last three Releases, computed from the published manifests and
  so correct even when a build was skipped because the image already
  existed; over 100 MiB from the previous Release the run gets a warning.
  The table can never block a Release: if it cannot be computed the notes
  say `Download size: not computed` and the tag, the GitHub Release and
  the store sync happen as before. No version bump. Issue #155, parent
  #153.
- The image is built as three layers instead of one, so that a small
  package or an Odoo bump no longer re-sends the whole thing. One `RUN`
  used to install PostgreSQL 16, the pinned Odoo nightly `.deb`, the
  fonts and every tool together, in one ~690 MiB compressed layer;
  adding `python3-yaml` in 0.4.3 and `python3-pycryptodome` in 0.4.4
  changed that layer, so both updates downloaded all of it again, and on
  a slow link the Supervisor's pull failed twice with `unexpected EOF`.
  The Dockerfile now installs **(a)** the stable packages — PostgreSQL
  16, the fonts, the tools, and the pinned `.deb`'s own dependencies,
  listed in the new `odoo18ce/odoo-deb-depends.txt` — then **(b)** the
  Odoo `.deb` alone, with `ARG ODOO_DEB_VERSION` and `ARG
  ODOO_DEB_SHA256` declared between the two, then **(c)** the small apt
  additions. A weekly Odoo bump now re-sends about 270 MiB instead of
  about 690 MiB -- the 235 MiB package and the layers below it -- and a
  small package re-sends only those, about 33 MiB: (c) itself, the
  add-ons clone at 30.8 MiB, the rootfs overlay and the permissions
  step. Those savings hold while CI's build cache still holds layer (a):
  a build that finds it gone rebuilds the layer and the update is a full
  download again, which is why a cache that does not expire is being
  chosen separately (#153). `ARG LAYER_A_REFRESH` above (a) is the one
  deliberate way to rebuild the big layer, for a security notice about
  something it installs; a fix that lives below it, in the base image or
  beside `curl`, still arrives with a base-image bump. The rule is
  written down in
  `docs/adr/0013-small-apt-additions-go-in-the-last-apt-layer.md`, and a
  new Static-tier test freezes the Dockerfile's instruction order and
  keeps layer (a)'s package list equal to the dependency file. **The
  next update downloads the full image once**, because every layer below
  the split is built anew; the one after it is small again. The set of
  packages in the image is unchanged; what changes is which layer each
  one lands in. No version bump. Issue #154, parent #153.

### Fixed
- A website page view opened through **Ingress** now records the page's
  **Canonical URL** instead of the Home Assistant host. Odoo's visitor
  tracking stored `request.httprequest.url`, whose host under Ingress is the
  Home Assistant one -- the add-on runs Odoo with `proxy_mode` and the
  Ingress listener forwards that host as `X-Forwarded-Host`. The Supervisor
  had already removed the Ingress prefix, so the path was right and only the
  scheme and host were wrong, and no Ingress token was ever stored; but
  Website > Visitors listed addresses that cannot open the page (`U-C5`,
  root cause `RC-9`), while the same screen's Public origin rows were
  correct. The image now ships a second server-wide module,
  `woow_visitor_url`, beside `woow_base_url_guard`: Odoo loads it in every
  process, installs it in no database, and it rebuilds the stored URL on
  what `website.get_base_url()` returns -- the website's `domain` when set,
  otherwise the frozen `web.base.url` -- keeping the request's own path and
  query. A visit that already arrives on the Canonical URL stores exactly
  what it stored before, and a database with no Canonical URL yet stores the
  path and query with no host at all. **Page views stored before this
  version keep the Home Assistant host**: they are not rewritten and not
  deleted. Every pull request now also starts Odoo in the image it builds
  and fails when the patch is not applied, the in-image contract ADR 0010
  established for the Canonical URL guard. Issue #160, parent #148.

## 0.4.5 — 2026-09-29

### Added
- Documentation only: what to do when an update fails on a slow link, for
  both audiences. DOCS.md "Updates and images" gains "When an update fails
  on a slow connection": how to recognize it in the Supervisor log
  (`Could not pull image`, `unexpected EOF`, under Settings → System →
  Logs), that the add-on keeps running the old version and the data is
  untouched, that "backup before update" should be switched off before a
  retry because every failed attempt leaves another full backup behind, and
  the two ways to reach WOOWTECH — GitHub Issues on `WOOWTECH/Woow_ha_odoo`
  and `woowtech@designsmart.com.tw`. For staff, `docs/runbooks/` gains
  `SLOW_LINK_DEPLOY.md` and `slow-link-pull.sh`: the script downloads the
  Release image's blobs from ghcr with `curl -C -`, so a dropped connection
  resumes from the last byte instead of restarting the 693 MiB layer that
  makes the Supervisor's own pull never converge on a slow link. It takes a
  fresh anonymous token on every attempt, never reuses the expiring signed
  storage URL, requires a 206 for a resume, verifies the size and sha256 of
  the manifest, the config and every blob, streams a docker-archive into
  `docker load`, and only prints the `ha apps update` command once the
  loaded image ID equals the manifest's config digest — it never runs the
  update itself. The runbook is zh-TW and covers the prerequisites, the
  backup that is the only way back, the disk space, running the script from
  a pinned Release tag, verifying, updating, rolling back, and the versions
  it was validated on (Docker 28.3.3, overlay2, Supervisor 2026.09.2).
  DOCS.md does not link the runbook. CI's shellcheck step now covers the
  script. No version bump. Issue #157, parent #153.

### Changed
- Documentation only: a tab Odoo opens in the browser from Ingress — a
  survey's Test button, a link that opens a new tab, "open in new tab" — is
  now recorded as a Structural gap instead of a defect. The tab is a
  top-level page, and through Ingress every top-level page lives under the
  add-on's own address, so the tab's address carries the session token and
  opens only for the person who pressed the button. DOCS.md "What only the
  Public origin can do" gains a row saying to open the same screen on the
  Public origin and share that address; the parity plan's `U-C23` rule and
  its new `G-07` row say the same, and the Live check now records
  `STRUCTURAL` with the Public origin's path. Nothing about the tab itself
  changes: it keeps its Ingress address and keeps working for the person who
  opened it. Issue #168.

### Fixed
- Under Ingress, **Action menu > Download > PDF** on a posted invoice now
  downloads the PDF instead of losing both the file and the screen. The web
  client navigated the whole Ingress frame to
  `<HA_BASE>/account/download_invoice_documents/<id>/pdf` -- the Home
  Assistant root, no Ingress prefix -- Home Assistant answered 404, and the
  invoice form was gone with it, while the same menu item downloaded the file
  on the Public origin (`U-E4`, a Prefix escape, root cause `RC-1`). No
  `window.open` was involved: the item is a plain `ir.actions.act_url` dict
  from `account.move.get_extra_print_items`, and `ActionMenus.onItemSelected`
  runs `browser.location=item.url` for an item that carries a `url` and no
  `action`. The Runtime shim cannot intercept a write to `location`, and a
  rewrite cannot prefix a URL that arrives over RPC and so is nowhere in the
  bundle -- so the shim now publishes its own URL helper to the page as
  `__WOOW_INGRESS_URL__` (read-only, Ingress-only, the same `path()` the
  `fetch`, XHR and `window.open` wrappers already use), and two rewrites on
  the Ingress listener's asset location hand it the URL before the
  navigation: `browser.location=item.url`, and `browser.location.assign(url)`
  -- which is both the `target: self` branch of the generic
  `ir.actions.act_url` executor and, byte for byte, the `home` client action,
  so all three sites stay under the prefix. Each rewritten expression falls
  back to the raw value when the global is absent, so a page whose shim did
  not run still navigates. The Public origin gets neither the shim nor the
  rules and is unchanged; **Download > PDF without Payment**, which takes the
  `/report/...` path, worked on both surfaces before and still does. No
  version bump. Issue #174, parent #148.
- Under Ingress, the website editor's Blocks panel now shows its snippet
  thumbnails instead of 36 blank tiles. Website > Edit asked the Home
  Assistant root for every one of them --
  `<HA_BASE>/website/static/src/img/snippets_thumbs/<snippet>.svg` -- and got
  404: 36 Prefix escapes and 36 console errors per editor open, with the same
  panel loading its pictures on the Public origin (`U-D2`, root cause
  `RC-1`/`RC-12`/`RC-14`). Editing itself worked and there was no
  `AssetsLoadingError`. The editor draws each tile with an OWL template,
  `t-attf-style="background-image: url({{snippet.thumbnailSrc}});"`, and a
  `url(` inside a `style` attribute is one of the ways the Runtime shim does
  not wrap by decision (ADR 0004's 2026-09-28 postscript, #169): the website
  editor saves record content back through those same paths, so a hook there
  would write the token-bearing Ingress prefix into the database. The fix is
  one rewrite on the Ingress listener's asset location, over that exact
  template text, which puts the Ingress prefix in front of a value beginning
  `/` and leaves anything else -- a snippet with no thumbnail arrives as the
  literal `oe-thumbnail` -- as it was. It rewrites the template and **not**
  the snippet catalogue response, because the value comes back: "Save block"
  hands `thumbnailSrc` to `ir.ui.view.save_snippet`, which writes it into the
  new snippet view's arch, so prefixing the response would store a Supervisor
  token in the database and break the block on the Public origin. A custom
  block therefore still saves exactly what it saved before and shows its
  thumbnail on both surfaces. Odoo 18 serves its OWL templates inside the
  asset bundle, unminified, which is what makes the template text reachable
  from there; the text occurs once, in `web_editor.assets_wysiwyg`, and the
  bytes it was measured against are kept as a test fixture. The Public origin
  listener, the catalogue response and `save_snippet` are untouched. The
  protocol-relative limit every other prefix rule has is inherited and belongs
  to #166. One picture on the same panel is not covered and is recorded rather
  than fixed: the static `snippet_disabled.svg` shown for an undroppable
  snippet, which no rule prefixes and which the measured run did not reach.
  No version bump. Issue #170, parent #148.
- Under Ingress, sending a website form now ends on its thank-you page
  instead of a Home Assistant 404. Contact Us and a job application were sent
  -- the lead and the applicant were created -- and then the page went to
  `<HA_BASE>/contactus-thank-you` or `<HA_BASE>/job-thank-you` at the Home
  Assistant root, which answered 404: the person saw an error where the
  confirmation belonged, while the same form on the Public origin opened its
  thank-you page (`U-D6` for `shared|generic` and
  `hr_recruitment|job application`, root cause `RC-1`/`RC-10`). Every form
  built on the website form snippet carries its confirmation target as an
  attribute of the server-rendered page --
  `data-success-mode="redirect" data-success-page="/contactus-thank-you"` --
  and the form script assigns that root-relative path to the page location
  once the submit RPC answers. The Ingress HTML rules rewrote `href`, `src`,
  `action`, `data-src` and `srcset` and no other attribute, the Runtime shim
  wraps no location assignment (ADR 0004 records that as a decision, not an
  omission), and the Rewrite scan reads asset bundles and not page HTML, so
  the value reached the browser bare. The Ingress listener's generic HTML
  location now carries two more rules beside those five, for
  `data-success-page="/` and for the pre-Odoo-14 spelling
  `data-success_page="/` that the form script still falls back to when
  `data-success-mode` is absent, so a form carried over by a database upgrade
  is covered as well; the copy of that location for `/web/action/load` carries
  them too, being that location plus its own escaped-quote rules. The rules
  belong to the attribute and not to any one form or path, so they cover every
  website form on every website page, including one a user builds in the
  editor. A value that is a same-page anchor (`#thanks`) or an absolute URL is
  left exactly as it was, no JSON or JavaScript response is affected, and the
  Public origin serves the attribute byte for byte. A protocol-relative value
  (`//host/path`) is prefixed and breaks, which is the limit every such rule in
  the gateway shares and which #166 fixes for all of them at once or not at
  all; unlike the others this one is typed by a person in the editor's redirect
  field rather than written by Odoo, and the template says so. The survey's own
  form was never affected: it redirects server-side, where `proxy_redirect`
  already adds the prefix. The Static tier gains the template contract for both
  rules -- on the Ingress listener, beside the attribute group they join, and
  absent from the asset location and from the origin listener -- and the
  live-nginx HTML test now serves a form page through both sockets and checks
  every shape. The maintainer reruns `U-D6` for both forms on the test host
  after deploy. No version bump. Issue #167, parent #148.
- Under Ingress, an action's help pictures load instead of 404ing. A window
  action's `help` field is HTML kept in the database, and Odoo's own help
  carries root-relative addresses: the Surveys screen of an empty survey list
  shows four `<img src="/survey/static/src/img/survey_sample_*.png">` tiles.
  That HTML reaches the browser inside a JSON-RPC response and the web client
  inserts it as markup, so the Runtime shim -- which adds the Ingress prefix
  when a page asks for a URL through an API it wraps -- never sees it, and the
  Rewrite scan, which reads asset bundles, never sees it either. The browser
  asked the Home Assistant root for the four pictures and got 404: eight
  Prefix escapes, eight 4xx and eight console errors on each of the two survey
  menus, with the Public origin clean (`U-C12`, root cause `RC-1`/`RC-12`).
  The Ingress listener now carries an exact-match location for
  `/web/action/load`, holding every directive of the generic Ingress location
  plus escaped-quote rules for `href`, `src`, `action`, `data-src` and
  `srcset`, because inside JSON the attribute quote is escaped
  (`src=\"/survey/...`) and the generic raw-quote rules never matched a byte
  of it. Each attribute also gets an identity rule written ahead of its
  general rule, so a URL that already carries the prefix is not prefixed
  twice. Two other routes deliver the same help and are deliberately left
  alone -- `/web/action/run` and `/web/dataset/call_button/<model>/<method>` --
  because they answer with an action computed at call time, and a computed
  action carries record content in its `context` as wizard defaults: prefixing
  those would put the Supervisor token into the database the first time a user
  saved the wizard. Help reached through those two keeps escaping, which is
  the smaller harm. No other JSON response is affected and the Public origin
  is unchanged. Verified on the test host against a local build of the branch:
  with the location removed the two survey menus record 8/8/8, with it in
  place every signal is 0 and the four pictures answer 200
  (`docs/testing/evidence/2026-09-28-issue-158/`). ADR 0004 gains the
  postscript that records why this is a route-scoped rewrite and not a shim
  hook. No version bump. Issue #158, parent #148.
- Public origin: the browser keeps its `Secure`, `SameSite=Lax` session
  cookie when the web client opens its bus socket. Odoo saves the session on
  its websocket route too and answers the `101` handshake with a
  `Set-Cookie: session_id=...; HttpOnly; Path=/` of its own, without `Secure`
  and without `SameSite`. The 8069 `location = /websocket` and the whole 8072
  listener proxied that response through untouched, so the bare cookie
  replaced the one `location /` had just rewritten: after login plus one
  screen the Public cookie read `Secure=False` until the next ordinary page
  response restored it, and again after the next socket (`U-B2`, root cause
  RC-4). Cookie rewriting is a property of the surface, not of one location,
  so every location that proxies to Odoo now carries its surface's rewriting:
  on the origin listeners `proxy_cookie_flags session_id
  $woow_origin_cookie_secure httponly samesite=lax` -- the websocket
  locations, the LAN-only database lifecycle locations and `/jsonrpc` beside
  the `location /` that already had it -- and on the Ingress listener
  `proxy_cookie_path / $safe_ingress_path/` with
  `proxy_cookie_flags session_id $ingress_cookie_secure httponly
  samesite=lax`, on its websocket and asset locations as well. The
  `$woow_origin_cookie_secure` and `$ingress_cookie_secure` maps are
  unchanged and stay the only source of the `Secure` decision, so the LAN
  tier over plain http still receives a cookie without `Secure` -- marking it
  Secure there means the browser never sends it back, which reads as a login
  that bounces straight to the login page -- and Ingress over plain http is
  unaffected. The Ingress half was hardening: the parity run observed its
  attributes as expected. Odoo's own cookie behaviour is untouched. The
  Static-tier contract no longer asserts the directive as a bare substring of
  the template: it parses the template into `server` and `location` blocks,
  pins the ten locations that proxy upstream across the 8069, 8072 and 5691
  listeners -- every `proxy_pass` in the file goes to Odoo -- and fails when
  any of them lacks the rewriting of its surface. A second test checks the
  rule against two mutated copies of the template: one with a directive
  removed and one with a location added, each answered with exactly that
  location, so neither a vacuous parse nor a route added with an unfamiliar
  target passes silently. `nginx -t` over both rendered
  `public_url` shapes still passes. The maintainer reruns `U-B2` generic on
  the test host after deploy. No version bump. Issue #165, parent #148.
- Ingress: a website page whose snippet stores its background in an inline
  style -- the Contact Us parallax, a cover, any image background set in the
  editor -- now loads the picture under the prefix instead of asking the
  Home Assistant root for it. The generic HTML location already rewrote
  `url(/`, `url('/` and `url("/`, but QWeb escapes attribute values with
  markupsafe, so the page arrives as
  `style="background-image: url(&#39;/web/image/website.s_parallax_default_image&#39;)"`
  and no rule matched an entity-encoded quote: one prefix escape, one 404 and
  one console error per visit, and a blank section. Four `sub_filter` rules
  now sit beside the three, one per form the escaper can produce --
  `&#39;`, `&#34;`, `&quot;`, `&#x27;` -- each keeping the entity exactly as
  it was. The existing three are untouched, so the bare and raw-quote forms
  rewrite as before, and a `url(` that is already absolute
  (`url(https://...)`) or relative (`url(img.png)`) is still left alone.
  The rules are hand-written in the generic HTML location only: asset
  bundles carry no HTML entities, so the `/web/assets/` location is
  unchanged, and the Rewrite scan, which reads bundles, learns nothing
  about page HTML. They inherit the one limit of the three beside them --
  a plain-string `sub_filter` cannot say "root-relative but not `//`", so
  a protocol-relative `url(&#39;//cdn/x.png&#39;)` is prefixed and breaks;
  Odoo writes none, and the template comment records it. The Runtime shim is unchanged -- it never
  sees markup the server sent -- so a `style` attribute the browser builds
  (#169, #170) stays where it is. The Static-tier template contract asserts
  the four rules, and the live-nginx content-type test serves an HTML
  upstream body in every form and asserts the prefix lands inside the entity
  quotes with no double prefix. The Public origin has no such rules and is
  unchanged. No version bump. Issue #166, parent #148.
- Ingress: the Event Registration Desk's barcode error sound plays again on a
  failed scan. The desk builds it with
  `new Audio(url("/barcodes/static/src/audio/error.ogg"))`, which resolves
  against the browser origin, and the Runtime shim wrapped nothing for media,
  so under Ingress the request reached the Home Assistant root and answered
  404 — one console error, one HTTP 4xx and one prefix escape, on a screen
  whose scanner was then silent when a scan failed. The `/mail/` sound on the
  next line was never affected, because `/mail/` is one of the template's
  shipped prefix rewrites. The shim now wraps the `Audio` constructor and the
  `src` setter of `HTMLMediaElement.prototype` (`<audio>` and `<video>`) and
  of `HTMLSourceElement.prototype`, through the same `path()` helper and the
  same property-setter helper it already uses for `href`/`src`/`srcset`: an
  already prefixed, cross-origin, `blob:`, `data:` or fragment-only value is
  untouched, a `URL` object is prefixed the way `fetch` and `sendBeacon` take
  one, `new Audio()` with no argument is left alone, an absent constructor is
  left absent, and the wrapper keeps `prototype` — as the `Worker` wrapper
  does — so `new Audio(...) instanceof HTMLAudioElement` still holds. One shim change covers every media prefix at once (POS sounds,
  `/barcodes/`, any future app), where a generated rewrite would cover one
  prefix at a time, so the Rewrite scan is unchanged and `/barcodes/` stays
  `INFO`. `<track>`, `<embed>`/`<object>`, `poster`, `srcObject`,
  `HTMLSourceElement.srcset` (the responsive `<picture>` candidate list, not a
  media source) and CSS `url(...)` media have not been reported escaping and
  stay uncovered, and `U-A6`'s probe list is unchanged: the guard for the media
  wrappers is the Static-tier contract plus the Registration Desk's own crawler
  record. The wrappers live in the
  same nginx map as the injection-way hooks, the tail of the prefix script's
  closure, because that script is a few hundred bytes short of nginx's
  4096-byte parameter buffer. ADR 0004 gains a 2026-09-28 media-sources
  postscript, and a Static-tier test executes the rendered shim against a DOM
  stand-in for each case above. The Public origin gets no shim and is
  unchanged. No version bump. Issue #159, parent #148.
- Ingress: a root-relative URL sent through `navigator.sendBeacon`, opened
  as an `EventSource`, or used as an SVG `<use>` reference set through
  `setAttribute("xlink:href", ...)`, `setAttribute("href", ...)` or
  `setAttributeNS(...)` now keeps the Ingress prefix instead of reaching the
  Home Assistant root. The Runtime shim wraps each of them the way it
  already wraps `fetch`, `XMLHttpRequest.open`, `Worker` and `WebSocket`,
  through the same `path()` helper: an already prefixed, cross-origin,
  `blob:`, `data:` or fragment-only value is untouched, an absent
  `sendBeacon` or `EventSource` is left absent, and `EventSource` keeps its
  prototype and its `CONNECTING`/`OPEN`/`CLOSED` constants. The hooks live
  in an nginx map of their own, spliced into the prefix script's closure,
  because that script is a few hundred bytes short of nginx's 4096-byte
  parameter buffer.
  The shim deliberately still touches nothing that inserts HTML as markup
  (`innerHTML`, `insertAdjacentHTML`, `outerHTML`), the `style` attribute or
  the text of a dynamic `<style>` element: the HTML editor and the website
  editor save record content through those paths, so a prefix written there
  would reach the database and carry the Ingress token. A screen that hits
  one of them gets a route-scoped Literal rewrite of its own instead (#158,
  #170). ADR 0004 has a 2026-09-28 postscript with both groups, and a
  Static-tier test asserts the shim has no hook for the second one.
  The Live-tier `U-A6` audit now declares each way with its group, probes
  the covered ways through the API the shim hooks rather than through
  markup, adds a `style` attribute probe, and reports `GAP` only for a
  covered way escaping under Ingress or any way escaping on the Public
  origin; an accepted escape is recorded as `PARITY` with the ways and
  their screen issues in the notes. No version bump. Issue #169, parent
  #148.
- A `website` module installed after the add-on started now gets the
  Canonical URL as the default website's domain within five minutes,
  without a restart. The maintenance bootstrap mirrors the value once, at
  start, and only when the module is already installed; a `website` added
  later through the Apps screen kept an empty domain, so under Ingress the
  home page's canonical, `og:url`, `og:image` and `twitter:image` links
  carried the Home Assistant address. The Rewrite scan service's round now
  ends with a Canonical URL catch-up: a `psql` read per database, and the
  maintenance library through `odoo shell` only for a database whose domain
  is empty or differs. The add-on log shows the same
  `maintenance db=<name>: … website.domain=<Canonical URL>` line the start
  writes. The maintenance library now also signals the running workers
  after its commit, the way an RPC request does; without that the home
  page kept `og:url` and `og:image` on the old address until the next
  restart. Issue #164.

## 0.4.4 — 2026-09-24

### Added
- The image now carries `python3-pycryptodome`, so WOOWTECH's ECPay
  e-invoice module (`ecpay_invoice_tw` from `ecpay_odoo18`, placed in
  `/share/odoo_addons/`) can be installed. It declares `pycryptodomex` and
  imports `Cryptodome`; Odoo refused it with "External dependency
  pycryptodomex not installed". The Debian package registers as
  `pycryptodomex` and provides `Cryptodome`, so no pip install is involved.
  The PR gate now runs Odoo's own external-dependency check for it in the
  built image. Issue #141.

### Changed
- The add-on's config folder is now mapped as `app_config:rw`, the name
  Supervisor 2026.07.1 gave it, instead of the legacy `addon_config:rw`.
  Nothing moves: Supervisor binds the same host folder to `/config`
  either way, and a local build no longer logs the legacy map-type
  warning. **The add-on now requires Supervisor 2026.07.1 or later**;
  older Supervisors reject the manifest and the store cannot load the
  add-on. Supported installs update Supervisor automatically. Issue #126.

## 0.4.3 — 2026-09-23

### Added
- The add-on now checks at every start that its database manager is closed
  to the Cloudflare tunnel. Once nginx answers, it requests
  `/web/database/manager` the way the tunnel does: from its own add-on
  network address (learned from the Supervisor, never loopback, which is
  LAN tier), on port 8069, with the host of `public_url` as `Host`. It
  starts normally on `404` with `public_url` set, or on `503` without it,
  and logs one line. On any other answer — `200`, a 5xx, or none at all —
  it logs an error naming the status and the route, sends a Home Assistant
  notification, and stops the container. This replaces the nightly
  Perimeter check's outside view. ADR 0005, issue #79.
- The Rewrite scan now tells you in Home Assistant when it acts. A round
  that adds Generated rewrites creates a persistent notification naming the
  new prefixes, and a round whose generation, validation or reload failed
  creates one naming the step; a round that changes nothing, and every
  round with **Apply Generated Rewrites** off, sends nothing. Ingress
  tokens are masked, a failure repeated every five minutes replaces its own
  notification rather than stacking, and a notification that cannot be
  sent is logged without changing the round. The add-on now asks for
  `homeassistant_api`, which this needs. ADR 0005, issue #78.
- The Rewrite scan now runs by itself. A new service scans once at start,
  as soon as PostgreSQL is ready, and every five minutes after that, so an
  application installed while the add-on is running has its navigation
  prefixes rewritten within five minutes and without a restart. Every
  round is written to the add-on log: the status of each database (`ok`,
  `failed`, `no bundles`) by name, whether the scan was complete, and —
  when bundles were read — what each one contains at each level, the
  exception hits and the prefixes now in the include file, with every
  Ingress token masked. A round that fails is a warning in the log and
  nothing more: the rules already in place stay live, Odoo is untouched,
  and the next round runs five minutes later. This is the first service in
  the image that does not stop the container when it exits, because Odoo
  must start and keep running whatever the scan does. ADR 0009, issue #94.
- The Rewrite scan now applies what it finds: the navigation prefixes no
  shipped rule covers become an nginx `include` file, which is validated
  with `nginx -t` against a rendered configuration that loads the candidate
  and is moved into place and reloaded only when nginx accepts it. A page
  that navigates to an address the Ingress rules do not cover yet is
  therefore fixed on the host, without a new Release. Four refusals guard
  it: an incomplete scan is never applied, a bundle whose bytes are missing
  fails its database, an unchanged generation is neither written nor
  reloaded, and a candidate nginx refuses leaves the last good file in
  place with Odoo still running. The new option **Apply Generated
  Rewrites** (`literal_rewrite_auto`, default on) freezes application: the
  scan and its report keep running and the rules already in place stay
  live. The image gains `python3-yaml`, because the exception list that
  ADR 0005 keeps applying is YAML and the container had no reader for it.
  ADR 0008, issue #93.
- A one-shot `odoo-rewrite-scan` command in the image prints, for every
  Odoo database, the asset bundle attachments it serves with their
  checksums, a per-database status, and whether a Rewrite scan is due. It
  is the read half of the Generated rewrites in ADR 0005 and it only
  reads: nothing is applied and no nginx rule changes yet. The bundles are
  read with one `psql` query plus the filestore rather than by starting an
  Odoo registry, which is about 60× cheaper per round and was measured
  before the choice was made. ADR 0007, issue #92.
- Ingress: the Runtime shim now publishes the Canonical URL to the page as
  a read-only `window.__WOOW_CANONICAL_URL__`. Odoo 18 builds some links
  for people outside in the browser, from the address in the address bar,
  and through Ingress that is the Home Assistant host, so the link is a
  Home Assistant 404 for whoever receives it; the lock on `web.base.url`
  cannot reach those values because they never pass through the server.
  This change publishes the value only. It moves no link yet — each one is
  moved onto that base by its own exact-expression rewrite, starting with
  the Discuss invitation link. Without a Canonical URL (Ingress-only and
  the Supervisor reports no LAN address) the global is empty and nothing
  changes. The Public origin is untouched. The rule that chooses the value
  stays in `canonical_url()` in the maintenance library, which the config
  rendering now calls through `odoo-canonical-url` and the maintenance
  bootstrap still calls for `web.base.url`. ADR 0006, issue #70.

### Fixed
- A LAN address that arrives a moment after the add-on starts no longer
  costs that start its Canonical URL. Without `public_url`, the address
  came from one Supervisor read at boot, and bashio caches an empty answer
  for the life of the container, so a DHCP lease that landed a few seconds
  late left the Runtime shim with no Canonical URL and `web.base.url`
  unwritten until the next restart. The read now waits up to 30 seconds,
  two seconds apart, with bashio's cache flushed in between; the published
  port is read again only while the Supervisor request itself fails; and
  the address and port the start settles on are handed to the maintenance
  bootstrap through the container environment, so one start has one LAN
  address and one port on both sides and the bootstrap never asks the
  Supervisor on its own. When no address comes, the start takes the
  no-Canonical-URL path it always took, and the log says the add-on
  waited. With `public_url` set nothing waits. Hosts
  that never have an IPv4 address (a bridge, bond, WWAN or tun uplink, an
  unmanaged interface, IPv6-only) pay the 30 seconds once per start, and
  so does a Supervisor that cannot be asked at all: the address and the
  port share the one budget. Issue #108.
- The Rewrite scan's Home Assistant notification now covers every step of
  a round. A state file or a database scan that raised used to end the
  round with a traceback and no notification; both now notify, naming the
  step (`state`, `scan`). A failure in the writes (the candidate, the move
  into place, the state write) is reported as the `apply` step, and one
  that came after the move says that the rules on disk are the new ones,
  naming them and whether nginx loaded them, instead of claiming the
  include file is untouched; the add-on log says the same, and the
  service's own failure line no longer claims the file kept its old rules.
  And a round that added rules before nginx was up says they take effect
  when nginx starts rather than that they are live now. Issue #120.
- The start-time self-check no longer stops a correct install because the
  Supervisor answered empty once. It read the add-on's own network address
  a single time at boot, and bashio caches an empty answer for the life of
  the container, so one late Supervisor reply became a failed check, a
  notification and a stopped add-on. The read is now retried for up to
  30 seconds, two seconds apart, with bashio's cache flushed in between,
  and only once nginx is up, so the Supervisor has the whole Odoo boot to
  learn the address first (`/usr/local/lib/supervisor-read.sh`, written
  for the LAN-address reads of issue #108 to use next). The Supervisor's
  placeholder `0.0.0.0`, which it answers
  before it has seen the container on the network, counts as no answer
  too, and the check refuses it and any loopback address the way it
  refuses an empty one. An address that never comes still fails the check,
  the log says the add-on waited and, when the Supervisor refused the
  request, what it said; the empty answer is not left in the cache. On pass the service logs one line; the "waiting for nginx" line
  moved to debug. Issue #119.
- A database created through the database manager on a host with no
  Canonical URL no longer has Odoo's install default,
  `http://localhost:8070`, locked in as its `web.base.url`. The start-up
  bootstrap now leaves that value unfrozen and logs a warning, so the next
  start that has a LAN address writes the Canonical URL over it; a value
  someone set is still kept and frozen as before. Issue #89.
- Ingress: a page's Share block no longer posts the Supervisor token to
  Facebook, X or WhatsApp on a host with no Canonical URL. The rewrite
  already moved the link onto that base; it now drops the Ingress prefix
  whether or not the base exists, because the alternative was handing a
  credential to a third party in exactly the deployment shapes where it is
  easiest to end up — an uplink that is a bridge, bond, WWAN or tun device,
  an interface NetworkManager does not manage, IPv6-only networking, or a
  DHCP lease that arrives after the add-on starts. Without a Canonical URL
  the link still points at the Home Assistant host and still does not work;
  it simply carries no token. ADR 0006 amendment, issues #70 and #108.
- Ingress: the three links Odoo builds in the browser for somebody
  outside to open now carry the Canonical URL instead of the Home
  Assistant host — the Discuss channel invitation link, the base shown
  before a page's path in Website → Pages, and the address a page's Share
  block hands to Facebook, X or WhatsApp. The share block was the worst of
  the three: it posted the full Ingress URL, Supervisor token included.
  Each one is moved by its own exact-expression rewrite, measured against
  the bundles the control group serves with the parity plan's 25
  applications installed and kept as a fixture; Odoo's shared URL helper is
  left alone, because it also builds the in-Ingress addresses for images,
  attachments and RPC. Without a Canonical URL nothing changes, and the
  Public origin is untouched. ADR 0006, issue #70.
- Three Prefix escapes under Ingress found by the Literal rewrite gate
  once the parity plan's 25 applications were installed on the control
  group: eCommerce's `redirect('/shop/cart')`, the payment flow's
  `window.location='/payment/status'` and a website tour's
  `window.location.href='/contactus'`. `/shop/`, `/payment/` and
  `/contactus` are now rewritten in the Ingress asset location in the
  three quote variants. Issue #58.
- Ingress: Odoo's copy buttons (share links, Discuss invitations, copy-to-
  clipboard widgets) work again when Home Assistant is opened over plain
  http on the LAN. That page is not a secure context, so the browser hides
  `navigator.clipboard` inside the Ingress iframe and every copy button
  failed silently or with "Oops! Something went wrong". The Runtime shim
  now supplies a `writeText` backed by `document.execCommand("copy")`
  whenever `navigator.clipboard` is absent; HA over https and the Public
  origin are untouched. Issue #60.
- A database created between two add-on starts no longer takes its
  Canonical URL from the first administrator login. Odoo writes
  `web.base.url` from the request it authenticated whenever
  `web.base.url.freeze` is unset, which is the state of every database the
  database manager creates after a start; through Ingress the value it
  wrote was the Home Assistant host, so every email, share, portal and
  report link pointed at Home Assistant until the next restart. The image
  now ships a server-wide module, `woow_base_url_guard`, that Odoo loads
  into every process and installs in no database and that removes the
  guess on every surface. The maintenance bootstrap stays the only writer
  of the Canonical URL; writing the value explicitly from Settings or over
  RPC is unaffected. Issue #67.

### Changed
- The Debian base image is pinned in the Dockerfile (`ARG BASE_IMAGE_TAG`,
  composed into `FROM` with `BUILD_ARCH`) and `build.yaml` is gone.
  Supervisor had deprecated `build.yaml` and passes a modernized local
  build only `BUILD_ARCH`, so a Dockerfile that took its base from
  `BUILD_FROM` could not be built on a host any more. The tag is the same
  `bookworm-2026.08.0` for both architectures; CI, the publish action and
  the weekly `odoo-bump` now read and write that one line instead of the
  YAML file. A local build on a host no longer logs the `build.yaml`
  deprecation warning. Issue #124, part of #110.
- The two Live-tier workflows, the Perimeter check and the Literal rewrite
  gate, no longer run on the nightly schedule; both are dispatch-only. The
  add-on now does both jobs on the host itself — the start-time self-check
  for the database-manager routes, the in-container Rewrite scan for the
  Literal rewrite — and the test host that served as the control group is
  being stopped, so a scheduled run would have had nothing to run against.
  `workflow_dispatch` stays on both for whenever a control group exists
  again, and release.yml still dispatches the perimeter check after a
  Release. ADR 0005, issue #80.
- The Literal rewrite gate CLI takes `--include-file`, a copy of the
  Generated rewrite include file the host under test applied, and merges
  its rules with the template's before evaluating. A run against a host
  that applied Generated rewrites then reports 0 unregistered `FAIL`
  instead of re-reporting the prefixes the add-on already covers there.
  Issue #80.

### Testing
- The Literal rewrite gate now identifies a bundle by its URL path, from
  `/web/assets/` on, instead of its file name. Odoo serves one name under a
  website-scoped `/web/assets/1/<unique>/<name>` and an unscoped
  `/web/assets/<unique>/<name>` with different content; the gate fetched
  and scanned only the first it saw, so a navigation literal in the other
  passed unreported. Both are now scanned, saved to separate files, kept
  apart by `--from-dir`, and named apart in the report. Results of earlier
  runs are a floor, not a complete count. Issue #98.
- The PR gate now fails when the Canonical URL guard is not applied. The
  `build (amd64)` job, which every pull request runs, including the Odoo
  nightly bumps, starts `odoo shell` in the image it just built, with the
  server-wide modules the add-on renders and no database, and checks that
  `res.users.authenticate` carries `woow_base_url_guard`'s flag. It runs a
  second time without the guard in `--load` and must then report it not
  applied. Before, a nightly that moved `authenticate` merged green: the
  guard's `ImportError` does not stop Odoo, whose server-wide loader logs
  it and serves unguarded. Issue #88.
- The Canonical URL guard gate proves more than the flag. The in-image
  probe now checks the last `res.users` class in Odoo's `res_users` module
  that declares `authenticate` (the one the registry runs), not the first
  flagged one, and checks that the upstream `authenticate` the wrapper
  wrapped still takes what the wrapper forwards by position (an added
  optional parameter fits; a renamed, reordered or keyword-only one does
  not), so a nightly that redefines the method later in the module or
  changes its parameters goes red instead of shipping the guess back or
  breaking every login. `build (amd64)` has a 30-minute limit, each
  `docker run` a 300 s one, and a container that never reaches the probe
  is reported as a container failure, not as the guard missing. Issue #121.
- New static-tier contract test `test_ingress_clipboard_fallback.py`
  executes the whole Runtime shim in a node `vm` context against a DOM
  stand-in and pins the clipboard fallback: absent clipboard resolves
  through one `execCommand("copy")`, removes its textarea and hands focus
  back; a present clipboard keeps the same reference; a refused copy
  rejects. It also fails when any quoted parameter in
  `nginx.conf.template` reaches nginx's 4096-byte limit, which a missing
  local nginx used to hide. Issue #60.
- New Live-tier Literal rewrite gate, `tests/e2e_literal_rewrite_gate.py`
  (issue #58, ADR 0004). It logs in to the control group's Public origin,
  collects every asset bundle the backend, Discuss, the website and each
  installed app's landing page load, extracts every root-relative string
  literal, classifies each by how the bundle consumes it (`FAIL` whole-page
  navigation, `WARN` path comparison, `INFO` anything the Runtime shim
  intercepts) and compares the prefixes against the `sub_filter` rules in
  the Ingress asset location of `nginx.conf.template`, parsed from the
  template itself. An unlisted prefix in a whole-page navigation fails the
  run unless `rootfs/usr/local/lib/literal_rewrite_exceptions.yaml`
  records it with a reason. Ingress tokens are masked in the output.
- The pure stages (extraction, classification, nginx rule parsing,
  exception matching, evaluation) ship in the image as
  `rootfs/usr/local/lib/literal_rewrite_gate.py`, next to the maintenance
  library, so the same code can serve inside the container and out. The
  static tier pins them in `test_literal_rewrite_gate.py`, which loads the
  module from the image the way the maintenance bootstrap tests do.
  Issue #75.
- New static-tier contract test `test_workflow_triggers.py`: the Perimeter
  check and the Literal rewrite gate declare `workflow_dispatch` and no
  `schedule`. `test_literal_rewrite_gate.py` gains the effective-rules
  cases — the include file parses as bare `sub_filter` lines, merged rules
  union the quote variants per prefix, and the CLI run with
  `--include-file` reports a `FAIL` prefix the file rewrites as covered.
  Issue #80.
- New workflow `literal-rewrite-gate.yml` runs the gate on demand against
  every origin in `ODOO_PUBLIC_URLS` with the `ODOO_TEST_LOGIN` /
  `ODOO_TEST_PASSWORD` secrets, failing early with the name of any missing
  secret.
- New static-tier test `test_base_url_guard.py` drives the patched login
  path against a stand-in of Odoo's `res.users`: a `user_agent_env`
  carrying a `base_location` produces no `web.base.url` write while the
  authentication result comes back unchanged, and the same stand-in is
  shown to make the write when nothing guards it. The config-script
  contract in `test_dual_gateway.py` now also pins the
  `server_wide_modules` line and the module's directory on the rendered
  `addons_path`. Issue #67.

## 0.4.2 — 2026-09-16

### Security
- The maintenance bootstrap now writes and freezes `web.base.url` on every
  Odoo database on every start, in every install shape. Before, it only did
  so when both `public_url` and `default_db` were set; an Ingress-only
  install was unprotected, and one admin login through Ingress wrote the
  Supervisor path `/api/hassio_ingress/<token>` into `web.base.url`, from
  where the token reached every email, share link, portal link and report.
  Without `public_url` the Canonical URL is now the Home Assistant host's
  LAN address with the published 8069 port, read from the Supervisor. A
  stored value that carries an Ingress token is never kept: it is replaced
  when a Canonical URL exists and removed otherwise. Issue #57.

### Added
- The default website's `domain` is set to the Canonical URL on every
  start when the `website` module is installed, so website-generated
  absolute links match email links.
- Manifest `hassio_api: true`, needed for the LAN-address fallback. The
  default role is enough; no `hassio_role` is requested.
- `DOCS.md`: a "Canonical URL" section explaining the three shapes, the
  Supervisor permission and the Ingress-only fallback.

### Changed
- `public_url` without `default_db` is a valid configuration; the add-on
  no longer refuses to start with "default_db is required". `default_db`
  is still required for `auto_update_module` and for the one-shot
  maintenance account file, which is now kept (with a warning) until a
  start with `default_db` set consumes it.
- A failure while processing one database is logged with the database
  name and the bootstrap continues with the next one; Odoo always starts.
  Only the `bootstrap-user.json` policy violations remain fatal.

### Testing
- New static-tier module `test_maintenance_bootstrap.py` runs the full
  decision matrix (`public_url` set/unset × `default_db` set/unset ×
  stored value clean/leaked/absent × LAN address available/unavailable)
  against the pure decision functions in
  `rootfs/usr/local/lib/odoo-maintenance.py`, without Odoo or the
  Supervisor.
- The perimeter check no longer reports a bare Odoo login page as blank. It
  polls for rendered body text instead of sampling once at `domcontentloaded`,
  where a database without `website` showed only "Powered by Odoo".

## 0.4.1 — 2026-09-14

First Release produced entirely by the pipeline: the weekly bump proposed
the Odoo package, a human merged it, and the Release workflow did the rest.
No database migration: none of the installed modules changed version
upstream in this window.

### Changed
- Odoo nightly package 18.0.20260806 -> 18.0.20260914.
- Debian base image bookworm -> bookworm-2026.08.0.
- `HEALTHCHECK` uses the exec (JSON) form. Same probe, no shell; hadolint
  3.5 flags the shell form (DL3025).

### Added
- Perimeter check workflow: after each Release and daily at 05:30 Taipei, a
  GitHub runner confirms from outside that every public origin listed in the
  `ODOO_PUBLIC_URLS` repository variable keeps `/web/database/*` and the
  XML-RPC/JSON-RPC database services closed, and that its basic pages load.
- Weekly Odoo nightly bump workflow: finds the newest 18.0 nightly package
  and dated Debian base-image tag, pins them with a fresh SHA256, records
  the change here, and opens a pull request that the PR gate builds. Never
  merged automatically.

## 0.4.0 — 2026-09-10

This Release changes how the add-on is installed. Supervisor now pulls a
prebuilt image instead of building the Dockerfile on your device, so this
update downloads an image once and later updates are pulls, not rebuilds.
Your database, filestore and options are untouched.

### Changed
- `image: ghcr.io/woowtech/woow-ha-odoo-{arch}`: prebuilt images for amd64
  and aarch64, published by the Release workflow with an immutable version
  tag. No more 245 MB Odoo download and PostgreSQL install on every update,
  and a released version stays installable even after nightly.odoo.com
  drops its package.
- The manifest `watchdog` URL is replaced by a Docker `HEALTHCHECK` that
  fetches the login page through nginx on loopback every 60 s, with a
  10-minute start period so first-boot database creation and post-upgrade
  module updates are not mistaken for a hang. The Watchdog toggle on the
  add-on page keeps working; it now reads container health.
- `webui` removed: with Ingress enabled the OPEN WEB UI button opens the
  sidebar panel. Direct LAN access on port 8069 is unchanged and documented
  under "LAN access".
- The Home Assistant add-on linter is now a blocking check.

### Added
- GitHub Actions PR gate: hadolint, shellcheck, yamllint, the Home Assistant
  add-on linter, a CRLF check, the static test tier, and an amd64 image build
  on every pull request. A pull request that bumps the version also builds
  aarch64 before it can merge.
- Release bookkeeping enforced by CI: the `config.yaml` version must head the
  CHANGELOG, versions must descend, and both translation files must cover the
  option schema exactly. An `## Unreleased` section is allowed only while the
  version is unchanged.
- LGPL-3.0 `LICENSE` file, matching the licence the README has always named.
- Dependabot for GitHub Actions, weekly, grouped into one pull request.
- Release workflow: a version bump merged to `main` now builds and pushes
  `ghcr.io/woowtech/woow-ha-odoo-{amd64,aarch64}:<version>` (version tag
  only, never overwritten), creates the `v<version>` tag and a GitHub
  Release from this file's section, and asks the App Store to sync at once.
  Supervisor keeps building on-device until `image:` is added to
  `config.yaml` in a later Release.
- Image labels (`io.hass.*`, `org.opencontainers.image.*`) filled in by the
  publish workflow.
- The Home Assistant add-on linter runs on every pull request as advisory
  output. It also asks for `webui` to go (Ingress is enabled) and for
  `watchdog` to become a Docker `HEALTHCHECK`; both change runtime
  behaviour and are deferred to the 0.4.0 Release, after which the linter
  becomes blocking.

### Changed
- `config.yaml` no longer states `startup: application`, `boot: auto` and
  `panel_admin: true`; these are Supervisor defaults and the linter rejects
  restating them. Nothing changes for installed add-ons.
- The static tests are pytest modules under `odoo18ce/tests/` with one
  entrypoint, `pytest odoo18ce/tests`, replacing `test-dual-gateway.sh`.
- The Settings E2E harness no longer defaults to a real deployment; the HA
  and public URLs must be supplied through the environment.
- Dockerfile: `pipefail` for the piped downloads, `--no-install-recommends`
  on the PostgreSQL install, apt lists removed from the first layer, and the
  unused `lsb-release` package dropped. No runtime behaviour changes.

## 0.3.39 — 2026-09-08

### Changed
- Rename the add-on from `Odoo 18 CE` to `Woow Odoo 18`, matching every other
  WoowTech add-on in the store (`Woow EMQX`, `Woow Immich`, `Woow Nextcloud`,
  `Woow n8n`, …). The slug stays `odoo18ce`: Home Assistant keys an installed
  add-on by slug, so changing it would strand the running instance and its
  Odoo database behind a new identity. Supervisor picks the new name up on the
  next add-on update; no configuration or data changes.

## 0.3.38 — 2026-09-08

### Security
- Remove the add-on network bridge address `172.30.32.1` from the LAN tier.
  0.3.36 treated it as LAN so the Home Assistant host could reach Odoo directly,
  on the assumption the Cloudflare tunnel arrives from its own container
  address. On a real deployment the tunnel add-on is host-networked and arrives
  from the bridge, so it inherited the LAN tier and `/web/database/manager`
  answered `200` to the public internet. Traffic from the bridge is now off-LAN;
  anything on the host that needs the full application uses the ingress panel.

### Testing
- Assert the bridge address carries no LAN entry, so it cannot be promoted back.

## 0.3.37 — 2026-09-08

### Fixed
- Answer on the published `8072` host port. Odoo binds every listener to
  `http_interface`, which is loopback, so the gevent worker could never serve
  that port itself and it refused every LAN connection even with `workers` > 0.
  nginx now owns `8072` and the worker moves to an internal `8073`.

### Security
- The `8072` origin is behind the same source-address gate as `8069`, so the
  WebSocket worker is not exposed unfiltered to whatever can reach the host.

### Testing
- Assert nginx owns `8072`, that gevent is off it, and that both origins carry
  the deny gate.

## 0.3.36 — 2026-09-08

### Added
- Reach Odoo directly from the LAN on the published `8069` host port. The origin
  listener now classifies callers by source address — which Docker preserves on a
  published port — and serves the LAN the full application, database manager
  included, while the Cloudflare tunnel keeps its restricted tier.
- `lan_networks`: space-separated IPv4/IPv6 CIDRs that define the trusted LAN
  (default `192.168.0.0/16 10.0.0.0/8 172.16.0.0/12`). Malformed entries fail
  start-up rather than reaching the nginx `geo` block.

### Changed
- Publish `8069` and `8072` on the HA host by default. The privilege split is
  enforced by source address inside nginx, not by leaving the ports unmapped.
- Default `workers` is now `2`. The gevent WebSocket on `8072` only listens while
  Odoo runs multi-process, so a published `8072` was previously always dead.
- The 8069 origin forwards the scheme the caller actually used and only marks the
  session cookie `Secure` when that scheme is HTTPS. A `Secure` cookie is never
  returned over plain LAN http, which previously would have made a successful
  login bounce straight back to the login page.

### Security
- The Cloudflare tunnel reaches the add-on from inside the add-on network, which
  the default LAN range `172.16.0.0/12` contains. `172.30.32.0/23` and the
  add-on network's IPv6 prefix are carved out of the LAN tier explicitly so the
  tunnel can never inherit LAN privileges, and the carve-out is asserted in the
  test suite.
- IPv6 callers are denied unless an operator adds their own prefix, keeping the
  default fail-closed on a dual-stack LAN.
- With `public_url` unset, no `Host` maps to the public tier, so an off-LAN
  caller is refused instead of falling through to the LAN tier.

### Testing
- Assert the add-on network carve-out, the LAN-only gate on every database
  lifecycle route, the tier-selected RPC upstream, and the conditional cookie and
  forwarded scheme.
- Render and `nginx -t` both configurations — `public_url` set and unset — rather
  than only the configured one.

## 0.3.35 — 2026-09-03

### Fixed
- Prefix root `/web/assets/` `href` and `src` attributes only inside JSON-escaped Document Layout preview HTML on HA Ingress.
- Retry an explicitly allowlisted HA Settings control once when its direct ingress iframe is temporarily replaced by the Home Assistant authorization frame.

### Testing
- Extend the live nginx response harness to parse the rewritten preview JSON and prove its escaped asset attributes and the public response remain correct.
- Add credential-free Settings retry classification contracts for the authorization-frame condition and its approval, surface, and retry limits.

## 0.3.34 — 2026-09-03

### Fixed
- Restrict the HA Ingress runtime `<head>` shim to `text/html` upstream responses so Document Layout preview HTML embedded in JSON remains parseable, while retaining ingress JSON URL and icon rewrites.

### Testing
- Add a live nginx content-type response-filter harness covering HTML shim injection, JSON preview integrity, and JSON asset URL rewriting.

## 0.3.33 — 2026-09-03

### Fixed
- Prefix the exact SettingsViewCompiler fallback icon expression in HA Ingress assets and the encoding-independent General Settings icon path in Settings view responses.
- Open Settings once in the HA E2E flow, then reacquire only the current direct ingress frame for every dynamically discovered tab instead of repeatedly invoking the app action.
- Wait for a visible Odoo login form or an already loaded navbar so document rendering cannot be mistaken for an authenticated backend.

### Testing
- Add focused ingress-only contracts for generated module icons and explicit General Settings logos while proving the public listener is unchanged.

## 0.3.32 — 2026-09-03

### Fixed
- Normalize a cloned HA Ingress URL before Odoo Router parsing, so token-prefixed Settings routes retain their action instead of falling back to Discuss.
- Make Odoo's internal route-click predicate accept only exact token-prefixed `/odoo` path segments while rejecting lookalikes such as `/odoox`.
- Preserve fragment-only Settings links and remove the competing Settings-specific DOM click workaround.

### Testing
- Add Router contracts for prefix parsing, original-URL immutability, fragment routing, external/non-Odoo rejection, and exact path boundaries.
- Add real HA/Public Settings E2E with direct-frame reacquisition, secure diagnostics, HTTP failure capture, and dynamic discovery of current and future Settings tabs.
- Render the final nginx template and require `nginx -t` in the dual-gateway suite.

## 0.3.31 — 2026-09-02

### Fixed
- Replace the Settings CSS selector containing a single-quoted `#` inside nginx's single-quoted replacement string. The generated nginx config parsed `#` as invalid syntax and watchdog-restarted the add-on.

### Testing
- Release requires both extracted JavaScript `node --check` and fully rendered `nginx -t`; neither check alone is sufficient.

## 0.3.30 — 2026-09-02

### Fixed
- Rewrite Settings `module.imgurl` values so section icons stay under HA Ingress.
- Normalize Settings hash-tab anchors to the current tokenized `/odoo/settings#<section>` URL before browser default navigation, preventing clicks from restoring stale Discuss history.

## 0.3.29 — 2026-09-02

### Fixed
- Correct a missing closing brace in the injected ingress service-worker cleanup block. The whole early shim failed with `Unexpected token 'catch'`, disabling fetch/history/Worker/WebSocket URL rewriting and allowing native Odoo service-worker registration errors.

### Testing
- Extract and run `node --check` on the injected nginx JavaScript during gateway tests so malformed shims cannot be released again.

## 0.3.28 — 2026-09-02

### Fixed
- Support HA Ingress through both public HTTPS and VPN-direct HTTP origins. Preserve the browser-visible `X-Forwarded-Proto`, generate matching HTTP/WS or HTTPS/WSS semantics, and add/remove the session cookie `Secure` flag conditionally. VPN users opening `http://<tailscale-ip>:8123` can now retain Odoo login sessions.

## 0.3.27 — 2026-09-02

### Fixed
- Keep Odoo bus `params.serverURL` equal to `window.origin` and prefix only the SharedWorker script and WebSocket endpoint expressions. Prefixing `serverURL` triggered Odoo's cross-origin data-URL worker branch; Chromium could fail before requesting the worker bundle, producing a null `UncaughtClientError` immediately after mail initialization.

## 0.3.26 — 2026-09-02

### Fixed
- Replace the SharedWorker bundle cache-buster match containing JavaScript `${...}` syntax with a simple `websocket_worker_bundle?v=` substitution. nginx parsed the former as an invalid variable and stopped the add-on at startup.

## 0.3.25 — 2026-09-02

### Fixed
- Version the Discuss SharedWorker/Worker name and imported worker-bundle URL. Browsers keep a named SharedWorker alive across iframe/add-on reloads; reusing `odoo:websocket_shared_worker` preserved the pre-fix root `/websocket` target and emitted a null `UncaughtClientError` even after transformed assets were refreshed.

## 0.3.24 — 2026-09-02

### Fixed
- Prefix Calendar and Settings (`/calendar/*`, `/base_setup/*`) RPC literals discovered by recursive app-launcher testing.
- Rewrite module icon JSON values and responsive image `srcset` URLs so Apps icons do not escape to HA root.

### Verified
- Recursive app-launcher crawl now includes Discuss, Calendar, Dashboards, Point of Sale, Invoicing, Website, Inventory, Apps and Settings as a release-gating ingress operation.

## 0.3.23 — 2026-09-02

### Fixed
- Rewrite `{"src": "/web/assets/..."}` values returned by `/web/bundle`. Website editor injects WYSIWYG JS/CSS into a child iframe whose DOM prototypes do not inherit the parent ingress shim; unrewritten bundle JSON therefore loaded root HA URLs and raised `AssetsLoadingError`.

## 0.3.22 — 2026-09-02

### Fixed
- Unregister stale Odoo service workers whose `/odoo` scope or `/web/service-worker.js` script can keep intercepting transformed ingress assets after updates. Perform one version-scoped reload after cleanup, without touching Home Assistant's own service worker registrations or unrelated CacheStorage.

## 0.3.21 — 2026-09-02

### Fixed
- Cache-bust rewritten ingress JS/CSS references with the add-on version and mark transformed assets `no-store`. Odoo asset hashes remain unchanged when only the proxy transformation changes, so browsers otherwise retained the pre-fix bus `serverURL` bundle and continued reporting real-time loss after update.

## 0.3.20 — 2026-09-02

### Fixed
- Remove the older `/bus` literal substitutions after prefixing `busParametersService.serverURL`. Applying both mechanisms generated a double ingress token for the SharedWorker bundle, so the bundle returned 404 before it could open `/websocket`.

## 0.3.19 — 2026-09-02

### Fixed
- Prefix Odoo bus `serverURL` in the rewritten backend asset bundle. Discuss passed a root-origin `wss://<ha-host>/websocket` URL into its SharedWorker, bypassing window-level WebSocket shims and causing “Real-time connection lost” with no `/websocket` request reaching the add-on.

## 0.3.18 — 2026-09-02

### Diagnostics
- Log sent/upstream X-Frame-Options plus ingress Host and forwarded scheme without query strings, enabling live differentiation between frame denial, mixed-content headers and URL rewriting failures.

## 0.3.17 — 2026-09-02

### Fixed
- Remove Odoo backend's `X-Frame-Options: DENY` only on the HA Ingress listener. Chromium rejected the authenticated `/odoo` iframe before loading any assets, producing the broken-page icon while nginx logged only `GET /odoo 200`.

## 0.3.16 — 2026-09-02

### Fixed
- Force the documented HTTPS scheme on the HA Ingress upstream headers. Supervisor connects to the add-on over internal HTTP and may omit `X-Forwarded-Proto`; falling back to nginx `$scheme` made Odoo emit mixed-content/incorrect absolute URLs and could leave the embedded page as a browser error placeholder.

## 0.3.15 — 2026-09-02

### Fixed
- Keep portal `/my/*` counters and authenticated Website operations inside the HA ingress prefix.
- Stabilize logout/protected-route browser assertions by waiting for Odoo's lazy login form.

### Verified
- Recursive authenticated ingress journey passes: backend, Discuss, Website home, Shop, Cart, Contact, Portal and back to backend, followed by logout and protected-route redirect; zero failed requests, 5xx or console errors.

## 0.3.14 — 2026-09-02

### Fixed
- Allow the HA Ingress token root to proxy Odoo Website `/` instead of forcing every root navigation back to `/odoo`; this fixes backend-to-Website transitions and authenticated frontend pages.

### Testing
- Add an adversarial recursive browser matrix covering unauthenticated/authenticated Website, backend, shop, cart, contact, portal, logout, redirects, assets, console/network errors, DB-manager denial, APIs and navigation transitions.

## 0.3.13 — 2026-09-02

### Security
- Add a localhost JSON-RPC filter that rejects public `service: db` calls while preserving object/common API services; HA Ingress retains database service access.
- Fail the public origin closed until an HTTPS `public_url` supplies an exact Host guard and canonical scheme.
- Remove Referer from access logs and pin WOOWTECH custom addons to a reviewed commit.

## 0.3.12 — 2026-09-02

### Security
- Block public XML-RPC database services in addition to `/web/database/*`.
- Remove unused Supervisor API access and read-write backup mount.
- Enforce configured public hostname and canonical scheme at the internal Cloudflare origin.
- Remove query strings from nginx access logs to avoid leaking URL-carried tokens.
- Validate one-shot bootstrap file type, ownership, mode and password length.
- Preserve standard WebSocket static constants in the ingress shim.
- Create generated secret configuration under restrictive umask.
- Replace local PostgreSQL `trust` authentication with `peer` authentication.
- Fail clearly when `public_url`, maintenance bootstrap or module auto-update lacks a target `default_db`.

## 0.3.11 — 2026-09-02

### Fixed
- Scope root-route substitutions to `/web/assets/` responses so Odoo login hidden redirect values remain unmodified.
- Prefix authenticated HTML's inline menu/translation prefetch URLs.
- Patch Odoo router `stateToUrl` origin composition so OWL navigation remains under the Supervisor ingress token.

### Verified
- Actual rendered nginx template behind an HTTPS Supervisor-prefix simulator: login, authenticated `/odoo/discuss`, menus, translations, assets and browser console all pass with zero relevant 4xx/5xx, failed requests or console errors.

## 0.3.10 — 2026-09-02

### Fixed
- Remove broad server-side JavaScript route substitution after moving the runtime shim before Odoo assets; keeping both mechanisms double-prefixed OWL navigation. Early fetch/history/Worker shims are now the single runtime URL authority.

## 0.3.9 — 2026-09-02

### Fixed
- Inject the ingress runtime shim immediately after `<head>`, before Odoo's synchronous backend asset bundles capture browser APIs.
- Handle URL objects passed to History API and rewrite all quote variants of `/mail` and `/odoo` routes.

## 0.3.8 — 2026-09-02

### Fixed
- Rewrite Odoo login form's HTML-entity-encoded inline `this.action = '/web/login'`; this assignment bypassed both the static action attribute and some browser property interception paths.

## 0.3.7 — 2026-09-02

### Fixed
- Rewrite Odoo's computed `${serverURL}/bus/websocket_worker_bundle` path, which is not a simple quoted root literal.
- Provide a complete inert service-worker controller/registration shape so Odoo does not dereference a null controller in the embedded Ingress UI.

## 0.3.6 — 2026-09-02

### Fixed
- Keep Odoo bus SharedWorker/Worker bundle URLs inside the HA ingress prefix.
- Disable Odoo service-worker registration under Ingress because its root scope crosses the Supervisor token boundary; offline/PWA caching is unnecessary for the embedded admin UI.

## 0.3.5 — 2026-09-02

### Fixed
- Preserve relative redirect targets with named nginx regex captures and disable absolute redirects on the ingress listener.
- Rewrite Odoo root-absolute RPC/worker bundle routes (`/web`, `/websocket`, `/report`, `/mail`, `/website`) that execute outside window-level URL shims.
- Added an actual nginx + HTTPS Supervisor-prefix Playwright harness during validation, covering login and authenticated OWL startup.

## 0.3.4 — 2026-09-02

### Fixed
- Post-test user downgrade now removes both Settings (`base.group_system`) and Access Rights (`base.group_erp_manager`) privileges, leaving a normal Internal User.

## 0.3.3 — 2026-09-02

### Fixed
- Normalize duplicate HA ingress prefixes produced when Odoo's lazy asset loader combines an already rewritten `data-src` with the document base URL.
- Playwright token-prefix reproduction now renders the Odoo login form with all Odoo assets inside the ingress prefix.

## 0.3.2 — 2026-09-02

### Fixed
- Remove the empty `public_url` default; Home Assistant correctly rejects an explicitly present empty value for an optional `url?` field.

## 0.3.1 — 2026-09-02

### Added
- `public_url` option freezes Odoo `web.base.url` to the canonical Cloudflare HTTPS origin
- Secure one-shot `/config/bootstrap-user.json` maintenance hook for repeatable E2E account provisioning and post-test privilege downgrade

## 0.3.0 — 2026-09-02

### Added
- Home Assistant Ingress on port 5691, opening the Odoo backend at `/odoo`
- Dual nginx gateways for HA Ingress and the Cloudflare full public origin
- Ingress rewriting for Odoo/OWL assets, JSON-RPC, forms, redirects, cookies, history, and WebSocket
- Worker-aware `/websocket` routing (HTTP port for workers=0, gevent 8072 for workers>0)
- Focused dual-gateway regression tests

### Security
- Odoo is bound to localhost:8070 and trusts forwarded headers only from bundled nginx
- HA host mappings for 8069/8072 are disabled; cloudflared uses add-on internal DNS
- Public Cloudflare gateway blocks `/web/database/*`; HA Ingress retains database management access
- Odoo package pinned to 18.0.20260806 with SHA-256 verification

## 0.2.0 — 2026-05-25

### Changed
- Upgraded PostgreSQL 15 → 16 (aligned with Odoo 18 official image)

### Added
- Timezone (`TZ`) configuration for Odoo and PostgreSQL
- Resource limit settings: `max_cron_threads`, `limit_memory_hard`,
  `limit_memory_soft`, `limit_time_cpu`, `limit_time_real`
- Configurable extra addons path (`odoo_extra_addons`)
- Auto-create database on first startup when `default_db` is set
- Dynamic addons_path with automatic directory creation
- Translations: English (`en.yaml`) and Traditional Chinese (`zh-Hant.yaml`)
- `DOCS.md` — detailed configuration reference and architecture documentation
- `README.md` — installation guide and quick start
- Cold backup support with cache/logs/sessions exclusion

### Fixed
- Missing `/share/odoo_addons` directory causing module icon 500 errors
- All addons_path directories are now auto-created if they don't exist

## 0.1.0 — 2026-05-22

### Added
- Initial release
- Odoo 18 Community Edition from nightly APT
- PostgreSQL 15 bundled in the same container
- s6-overlay service management (cont-init.d + services.d)
- Auto-sync PostgreSQL password on every boot
- Configurable SMTP settings
- Auto-update modules on startup (`auto_update_module`)
- CJK fonts + wkhtmltopdf for PDF report generation
- WOOWTECH odoo-addons pre-installed from GitHub main branch
- Support for user custom modules via `/share/odoo_addons`
- Multi-architecture support: amd64 + aarch64
