# Changelog

## 2.4.3

Three bundled components move to their latest upstream releases:

| Component | 2.4.2 | 2.4.3 |
|---|---|---|
| `woow_zha_quirks` | 1.2.0 | 1.4.1 |
| `nodered` | 4.2.3 (plus 11 later commits) | 4.3.2 |
| `pyscript` | 2.0.1 (plus 25 later commits) | 2.1.0 |

The other 18 components are unchanged.

`woow_zha_quirks` 1.4 and later is set up from Settings → Devices & services
instead of a `woow_zha_quirks:` key in `configuration.yaml`. As before, none of
the three is set up by the add-on: add them from the UI when you need them.

### What happens on upgrade

On every start, before Home Assistant, the add-on checks
`custom_components/woow_zha_quirks`:

- **1.x before 1.4, not in use**: the folder is deleted and 1.4.1 is copied in.
  The add-on log shows a line starting with
  `[woow_seed] replaced custom_components/woow_zha_quirks`. The add-on never adds
  the `configuration.yaml` key, so on a factory instance the old version never
  loaded and nothing that was set up is lost.
- **1.x before 1.4, in use**: left exactly as it is, and Home Assistant keeps
  loading it as before. The log shows a line starting with
  `[woow_seed] kept custom_components/woow_zha_quirks` that names the reason.
  It counts as in use when `configuration.yaml` has a top-level
  `woow_zha_quirks:` key, or a `woow_zha_quirks` config entry exists.
- **1.4 or later, or not 1.x**: left exactly as it is.
- **Version cannot be read, or the check fails** (for example an unreadable
  `.storage/core.config_entries`): counts as in use and is left as it is; the
  log says so.
- **No `woow_zha_quirks` folder**: 1.4.1 is copied in, as before.

Only the `custom_components/woow_zha_quirks` code folder is ever deleted;
`.storage`, config entries and YAML are never touched. If the folder cannot be
removed, it is left as it is, the log says so, and Home Assistant starts as
usual.

To upgrade a `woow_zha_quirks` that is in use:

1. Make a backup.
2. Delete `custom_components/woow_zha_quirks`.
3. Restart the add-on. It copies in 1.4.1.
4. Home Assistant shows a repair notification about the `woow_zha_quirks:` YAML
   key. Confirm it; that creates the config entry. You can then remove the
   key from `configuration.yaml`.

`nodered` and `pyscript` are only new on new instances. An existing folder is
never replaced, so an existing instance keeps the version it has. To update
one, delete its folder in `custom_components` and restart the add-on, which
copies in the new version, or update it yourself with HACS.

## 2.4.2

HACS can now be set up. Up to 2.4.1 the bundled `hacs` was HACS's source code,
which lacks the `hacs_frontend/` folder that HACS only adds to its release
download; without it the integration fails to load, so adding HACS showed an
error. 2.4.2 bundles the complete HACS 2.0.5 release.

### What happens on upgrade

On every start, before Home Assistant, the add-on checks
`custom_components/hacs`:

- **No `hacs_frontend/` folder** (as 2.4.1 seeded it): the folder is deleted and
  the complete HACS 2.0.5 is copied in. The add-on log shows a line starting
  with `[woow_seed] replaced custom_components/hacs`. This HACS could never
  load, so nothing that was set up is lost.
- **Has `hacs_frontend/`** (for example HACS you reinstalled yourself): left
  exactly as it is.
- **No `hacs` folder**: HACS 2.0.5 is copied in, as before.

Only the `custom_components/hacs` code folder is ever deleted; `.storage`,
config entries and YAML are never touched. If the folder cannot be removed, it
is left as it is, the log says so, and Home Assistant starts as usual.

HACS still needs to be added from Settings → Devices & services and authorized
with GitHub; the add-on does not set it up.

## 2.4.1

The bundled custom components move to the consolidated upstream layout. Ten
split components are replaced by three:

| Group | Old components | Replaced by |
|---|---|---|
| permission | `ha_permission_manager` 1.0.3, `ha_area_control`, `ha_label_control` | `ha_permission_manager` 2.0.15 |
| records | `ha_finance`, `ha_asset_record`, `ha_health_record`, `ha_note_record` | `woow_ha_records` 3.0.0 |
| protocol | `woow_dmx`, `woow_knx`, `woow_modbus` | `woow_multi_protocol` 3.0.0 |

The other 18 components are unchanged.

### What happens on upgrade

On every start, before Home Assistant, the add-on checks each group whose old
component folders are in `custom_components`:

- **Not in use**: the old folders are deleted and the new component is copied in.
  An instance that has the old components installed but never set up (the
  factory state) ends up with the new layout and notices no difference.
- **In use**: the group is left exactly as it is and the new component is not
  copied in. The add-on log shows a line starting with `[woow_seed] kept the old
  <group> components` that names the reason.

A group counts as in use when any of these is true: a config entry of an old
component exists; `.storage/` has a file whose name starts with an old
component's domain (the permission group's is `ha_permission_manager`); for the
protocol group, `/config/dmx`, `/config/knx` or `/config/modbus` exists and is
not empty; `configuration.yaml` has a top-level key named after an old
component. Once `ha_permission_manager` 2.x is present in `custom_components`,
the config entry and `.storage` file it shares with 1.x no longer count. If the
check cannot be made (for example `core.config_entries` or the
`ha_permission_manager` manifest cannot be read), the group counts as in use.
When that manifest cannot be read, the log names the file and says to check
or replace that folder; if the check cannot run at all, the log names each
group kept. Only component code folders are ever deleted; config entries,
`.storage` and YAML are never touched.

New installations get the three new components directly.

### Migrating a group that is in use

Upstream made the new components a clean break: they use different domains and
do not import data from the old ones (`ha_permission_manager` keeps its domain
and its stored permissions). To move a group over by hand:

1. Make a backup of the add-on.
2. In Settings → Devices & services, delete the old group's integrations, then
   delete their folders from `custom_components` in the add-on's config folder
   (`/addon_configs/<slug>` on the host, `/config` inside the add-on).
3. Restart the add-on. The new component is copied in on start; add it from
   Settings → Devices & services.
4. Re-enter the data in the new component.

Per group:

- **permission**: delete the `ha_area_control` and `ha_label_control`
  integrations and the folders `ha_area_control`, `ha_label_control` and
  `ha_permission_manager`. Keep the `ha_permission_manager` integration: 2.0.15
  reads the existing permissions unchanged. Since 2.0.1 a `panel_lovelace`
  permission is ignored; grant `panel_home` instead.
- **records**: the old finance, asset, health and note records are not carried
  over to `woow_ha_records`.
- **protocol**: the old device YAML lives in `/config/dmx`, `/config/knx` and
  `/config/modbus`; `woow_multi_protocol` reads `/config/woow_multi_protocol/<protocol>/`.
  Set the devices up again there; the old folders are left in place.
