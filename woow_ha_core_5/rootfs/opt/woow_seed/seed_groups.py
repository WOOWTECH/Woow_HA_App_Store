"""Replace unused old split components with their consolidated upstream successor.

Called by woow_seed.sh before the seed-if-missing copy. For each component group
whose old folders are present in /config/custom_components:

- not in use: delete the group's old folders, so the copy that follows seeds the
  successor;
- in use (or the check could not be made): leave the group alone and print the
  successor's name on stdout, so the copy skips it (keep()).

Each group is handled on its own: an error in one keeps only that group.

It then removes a hacs folder that has no hacs_frontend/ (replace_hacs()), so the
copy seeds the complete hacs; an error there keeps hacs as it is.

Last, it removes a woow_zha_quirks before 1.4 that is not in use (replace_zha_quirks()),
so the copy seeds the seed's 1.4 or later: a config entry of woow_zha_quirks, or a
top-level configuration.yaml key, counts as in use. An error, or a manifest version
that cannot be read, keeps it as it is.

Only component code folders are ever deleted; config entries, .storage and YAML
are never touched. A missing core.config_entries means Home Assistant never ran
with these components, so it does not count as in use. Log lines go to stderr.
See the CHANGELOG entries that replaced the split components, hacs and woow_zha_quirks.

Usage: python seed_groups.py <config_dir> <seed_dir>
"""

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

PREFIX = "[woow_seed]"
TRASH = ".woow_seed_removed"  # under /config, outside custom_components
DONE = ".done"  # suffix of a group's trash folder once all its moves succeeded
HACS = "hacs"
FRONTEND = "hacs_frontend"  # built at HACS release time; not in the repository source
ZHA_QUIRKS = "woow_zha_quirks"  # not Home Assistant's own zha integration
ZHA_QUIRKS_UI = (1, 4)  # the first woow_zha_quirks set up from the UI, not configuration.yaml


@dataclass(frozen=True)
class Group:
    name: str
    old_domains: tuple
    successor: str
    data_dirs: tuple = ()  # old data directories under /config, not named after a domain


GROUPS = [
    Group("permission", ("ha_permission_manager", "ha_area_control", "ha_label_control"),
          "ha_permission_manager"),
    Group("records", ("ha_finance", "ha_asset_record", "ha_health_record", "ha_note_record"),
          "woow_ha_records"),
    # woow_dmx/knx/modbus 2.x keep their YAML in /config/<protocol>.
    Group("protocol", ("woow_dmx", "woow_knx", "woow_modbus"), "woow_multi_protocol",
          data_dirs=("dmx", "knx", "modbus")),
]
# woow_seed.sh repeats GROUPS in COMPONENT_GROUPS, for when this script cannot run;
# tests/test_seed.py checks they match.


def log(message):
    print(f"{PREFIX} {message}", file=sys.stderr, flush=True)


class UnreadableManifest(ValueError):
    """A successor-domain folder whose manifest version cannot be read."""


def is_successor(path):
    """Whether a folder of the successor's domain is the successor, not an old version.

    Only ha_permission_manager keeps its domain: 2.x is the successor, 1.x is old.
    Raises UnreadableManifest when the manifest cannot be read, so the group is kept.
    """
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        return int(str(manifest["version"]).split(".")[0]) >= 2
    except (OSError, ValueError, KeyError, TypeError) as err:
        raise UnreadableManifest(
            f"custom_components/{path.name}/manifest.json cannot be read ({err})") from err


def old_folders(group, custom_components, successor_in_old_folder):
    """The group's old folders present in custom_components."""
    return [name for name in group.old_domains
            if (custom_components / name).is_dir()
            and not (name == group.successor and successor_in_old_folder)]


def in_use_reason(group, config, domains):
    """Why the group counts as in use, or None. Raises when that cannot be told.

    Any one of these counts, for the given old domains: a config entry; a .storage
    file named after one; a non-empty old data directory; a top-level
    configuration.yaml key.
    """
    reason = config_entry_reason(config, domains)
    if reason:
        return reason

    storage = config / ".storage"
    if storage.is_dir():
        for path in sorted(storage.iterdir()):
            if path.name.startswith(domains):
                return f".storage/{path.name}"

    for name in group.data_dirs:
        path = config / name
        if (path.is_dir() and any(path.iterdir())) or (path.is_file() and path.stat().st_size):
            return f"/config/{name} not empty"

    return yaml_key_reason(config, domains)


def config_entry_reason(config, domains):
    """'config entry <domain>' if core.config_entries has one of the domains, else None.

    Raises when the file exists but cannot be read.
    """
    entries_file = config / ".storage" / "core.config_entries"
    if entries_file.exists():
        entries = json.loads(entries_file.read_text(encoding="utf-8"))["data"]["entries"]
        for entry in entries:
            if entry.get("domain") in domains:
                return f"config entry {entry['domain']}"
    return None


def yaml_key_reason(config, domains):
    """'configuration.yaml key <domain>' if one of the domains is a top-level key, else None.

    Raises when the file exists but cannot be read.
    """
    configuration = config / "configuration.yaml"
    if configuration.exists():
        for line in configuration.read_text(encoding="utf-8-sig").splitlines():
            if line[:1] in ("", " ", "\t"):  # not a top-level key
                continue
            key, colon, _ = line.partition(":")
            key = key.strip().strip("\"'")
            if colon and key in domains:
                return f"configuration.yaml key {key}"
    return None


def keep(group, reason, hint=""):
    """Log why the group is kept and print its successor, so the copy skips it."""
    log(f"kept the old {group.name} components: {reason}; {group.successor} not seeded.{hint}")
    print(group.successor, flush=True)


def recover(custom_components, trash):
    """Finish what an interrupted boot left in the trash. Returns the groups not restored.

    <name>.done holds what was all moved out (a group's folders, or hacs): it is deleted.
    <group> holds a group interrupted while moving out or back: its folders are
    moved back, so a group is never left half deleted.
    """
    stuck = set()
    if not trash.is_dir():
        return stuck
    names = {group.name for group in GROUPS}
    for path in sorted(trash.iterdir()):
        if path.name.endswith(DONE):
            shutil.rmtree(path, ignore_errors=True)
            continue
        if path.name not in names:
            continue
        for folder in sorted(path.iterdir()):
            try:
                if (custom_components / folder.name).exists():
                    raise OSError("a folder of that name is in custom_components")
                folder.rename(custom_components / folder.name)
                log(f"restored {folder.name} after an interrupted removal")
            except OSError as err:
                log(f"could not restore {folder.name} from {TRASH}/{path.name} ({err})")
                stuck.add(path.name)
        if path.name not in stuck:
            path.rmdir()
    return stuck


def remove(group, old, custom_components, trash):
    """Move the group's old folders out of custom_components, then delete them.

    The moves are undone if one fails, and the error is raised; a move back that
    fails too is retried by recover() on every boot until it succeeds, and the
    group is kept meanwhile.
    """
    pending = trash / group.name
    done = trash / (group.name + DONE)
    shutil.rmtree(done, ignore_errors=True)
    pending.mkdir(parents=True, exist_ok=True)
    moved = []
    try:
        for name in old:
            (custom_components / name).rename(pending / name)
            moved.append(name)
        pending.rename(done)
    except OSError:
        for name in reversed(moved):
            try:
                (pending / name).rename(custom_components / name)
            except OSError as undo_err:
                log(f"could not move {name} back ({undo_err}); retried on the next start")
        raise
    shutil.rmtree(done, ignore_errors=True)


def replace(group, config, custom_components, trash):
    """Remove the group's old folders if it is not in use; otherwise keep() it."""
    successor = custom_components / group.successor
    successor_in_old_folder = (group.successor in group.old_domains
                               and successor.is_dir() and is_successor(successor))
    old = old_folders(group, custom_components, successor_in_old_folder)
    if not old:
        return
    # Signals of the successor's own domain belong to the successor once it is present.
    domains = group.old_domains
    if successor_in_old_folder:
        domains = tuple(d for d in domains if d != group.successor)
    try:
        reason = in_use_reason(group, config, domains)
    except Exception as err:  # noqa: BLE001 - any doubt keeps the group
        reason = f"could not check ({err})"
    if reason:
        keep(group, f"in use ({reason})", " Migrate by hand, see the CHANGELOG.")
        return
    try:
        remove(group, old, custom_components, trash)
    except OSError as err:
        keep(group, f"could not remove them ({err})")
        return
    for name in old:
        log(f"removed old component: {name} ({group.name} group not in use)")


def replace_hacs(custom_components, seed_components, trash):
    """Remove a hacs folder that has no hacs_frontend/, so the copy seeds a complete one.

    hacs imports hacs_frontend/ at module level, and that folder only exists in a
    HACS release asset; a hacs without it cannot load, so nobody can be using it.
    Nothing is removed unless the seed's own hacs has hacs_frontend/. The folder is
    moved out first, so it is either removed whole or left as it is.
    """
    hacs = custom_components / HACS
    if not hacs.is_dir() or (hacs / FRONTEND).is_dir():
        return
    if not (seed_components / HACS / FRONTEND).is_dir():
        return
    discard(hacs, trash)
    log(f"replaced custom_components/{HACS}: it has no {FRONTEND}/, so HACS could not load")


def discard(folder, trash):
    """Move a component folder out to the trash, then delete it: removed whole or not at all."""
    done = trash / (folder.name + DONE)
    shutil.rmtree(done, ignore_errors=True)
    trash.mkdir(exist_ok=True)
    folder.rename(done)
    shutil.rmtree(done, ignore_errors=True)


def manifest_version(path):
    """A component folder's manifest.json version, as text and as (major, minor)."""
    text = str(json.loads((path / "manifest.json").read_text(encoding="utf-8"))["version"])
    major, minor = text.split(".")[:2]
    return text, (int(major), int(minor))


def replace_zha_quirks(config, custom_components, seed_components, trash):
    """Remove a woow_zha_quirks before 1.4 that is not in use, so the copy seeds the seed's.

    1.4 moved its setup from a configuration.yaml key to a config entry made in the UI.
    The add-on never adds the key, so a factory instance has 1.x but never loaded it.
    """
    quirks = custom_components / ZHA_QUIRKS
    if not quirks.is_dir():
        return
    version, release = manifest_version(quirks)
    if release[0] != 1 or release >= ZHA_QUIRKS_UI:
        return
    seed_version, seed_release = manifest_version(seed_components / ZHA_QUIRKS)
    if seed_release < ZHA_QUIRKS_UI:
        return
    reason = (config_entry_reason(config, (ZHA_QUIRKS,))
              or yaml_key_reason(config, (ZHA_QUIRKS,)))
    if reason:
        keep_zha_quirks(f"in use ({reason})", version)
        return
    try:
        discard(quirks, trash)
    except OSError as err:
        keep_zha_quirks(f"could not remove it ({err})", version)
        return
    log(f"replaced custom_components/{ZHA_QUIRKS} {version} with {seed_version}: not in use")


def keep_zha_quirks(reason, version=""):
    """Log why woow_zha_quirks is kept and where the manual upgrade is described."""
    shown = f" {version}" if version else ""
    log(f"kept custom_components/{ZHA_QUIRKS}{shown}: {reason}. To upgrade it, see the CHANGELOG.")


def main(config, seed):
    custom_components = config / "custom_components"
    trash = config / TRASH
    try:
        stuck = recover(custom_components, trash)
    except Exception as err:  # noqa: BLE001 - any doubt keeps the group
        log(f"could not recover {TRASH} ({err})")
        stuck = {group.name for group in GROUPS}
    for group in GROUPS:
        if group.name in stuck:
            keep(group, "an interrupted removal could not be undone")
            continue
        try:
            replace(group, config, custom_components, trash)
        except UnreadableManifest as err:
            keep(group, f"check failed ({err})",
                 f" Check or replace custom_components/{group.successor}.")
        except Exception as err:  # noqa: BLE001 - one group's error keeps only that group
            keep(group, f"check failed ({err})")
    try:
        replace_hacs(custom_components, seed / "custom_components", trash)
    except Exception as err:  # noqa: BLE001 - any doubt keeps hacs as it is
        log(f"could not replace custom_components/{HACS} ({err}); kept it as it is.")
    try:
        replace_zha_quirks(config, custom_components, seed / "custom_components", trash)
    except Exception as err:  # noqa: BLE001 - any doubt counts as in use
        keep_zha_quirks(f"could not check ({err})")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
