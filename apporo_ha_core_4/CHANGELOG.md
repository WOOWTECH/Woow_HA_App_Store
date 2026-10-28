# Changelog

## 2.4.1

No change in what the add-on does. The check that replaces unused old component
groups was tidied up, and its tests also cover commented and tab-indented
`configuration.yaml` keys (these do not count as in use). The log line for a group that is kept in use now says "see the
CHANGELOG" (the 2.4.0 entry below) instead of naming a version.

## 2.4.0

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
  copied in. The add-on log shows a line starting with `[apporo_seed] kept the old
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
