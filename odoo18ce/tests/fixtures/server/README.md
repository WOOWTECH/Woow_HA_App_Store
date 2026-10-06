# Server source fixtures

Files taken **verbatim** from the pinned Odoo package — the same discipline as
`fixtures/bundles/`, one layer down: those are the bytes the control group
*serves*, these are the Python the add-on's Odoo *runs*. They exist so a claim
about server behaviour can be driven rather than argued, with no host and no
Odoo importable.

Captured 2026-10-04 from `ODOO_DEB_VERSION=18.0.20260930` (the version
`odoo18ce/Dockerfile` pins and both add-on containers run), out of the deb
itself:

```sh
dpkg-deb --fsys-tarfile odoo_18.0.20260930_all.deb \
  | tar -x --wildcards './usr/lib/python3/dist-packages/odoo/addons/web_editor/models/*'
```

| File | Source in the package | sha256 |
|---|---|---|
| `web_editor_diff_utils.py` | `web_editor/models/diff_utils.py` | `742f7e0909983616577ae2e5f3394145daf49e92696f1c5d28eca647ce8bd003` |
| `web_editor_html_field_history_mixin.py` | `web_editor/models/html_field_history_mixin.py` | `eb592cc6bd4caab2bf02cca5b75ca0b03b3d0ec6f591cb8fa68e59e5d348917f` |
| `project_task_5_description.html` | not from the package — see below | — |

`test_html_field_history_prefix.py` re-hashes both files against the digests
in this table on every run, and checks that the deb version above is still
the one `odoo18ce/Dockerfile` pins — a capture nobody can re-check is a copy
rather than evidence, and every claim in that test is driven from these
bytes.

Both Python files keep Odoo's own copyright header. `diff_utils.py` imports
only `re` and `difflib`, so `test_html_field_history_prefix.py` loads it by
path and **executes** it; the mixin imports `odoo` and is therefore only
parsed, with `ast`, to pin the shape of the call that decides which value a
revision carries.

## `project_task_5_description.html`

The html field `G-10` was measured on: `project.task(5).description` on
`odoo_parity`, byte-for-byte as `docs/testing/evidence/2026-10-04-issue-282/
markup.jsonl` recorded it in the `readonly-plain` record's `stored_values`
(run `WOOW-MARKUP-20261004T104350Z`, 2026-10-04, #282, Release 0.4.10). A test
asserts the two are identical, so this copy cannot drift away from the record
it came from. It is the **clean** value — the field itself carries no Ingress
prefix, which is exactly what makes `G-10` a reading about the *history* and
not about the field.

The `<redacted>` in it is the evidence record's own redaction, carried over
unchanged; it sits in text, not in a URL, and the patch helpers treat it as
one more line boundary.

## Why these two files

`G-10` (#296, §11 of the parity plan): the html field's Version History dialog
draws a document carrying an Ingress prefix on the Public origin, while the
field itself is clean. `html.field.history.mixin.write` stores
`generate_patch(new_content, old_content)` and `_patch_generator` embeds
`old_content_lines`, so a revision is a **reverse** patch and carries the value
as it was *before* that write — which makes the Ingress save that *heals* the
field the author of the prefixed revision, and the Public peer's own save the
author of a clean one. Both halves of that sentence are executed against these
files.

Two bounds come from the same source and are pinned alongside it:
`_html_field_history_size_limit = 300`, so the residue is evicted once 300
further revisions exist on that field; and the scope — a scan of all 8274
Python files in the pinned package finds `html.field.history.mixin` in the
mixin itself, in the `test_html_field_history` test module, and in exactly one
shipped model, `project/models/project_task.py`, whose `_get_versioned_fields`
returns `[Task.description.name]`. No mailing body, website page or mail
template has a history to read.
