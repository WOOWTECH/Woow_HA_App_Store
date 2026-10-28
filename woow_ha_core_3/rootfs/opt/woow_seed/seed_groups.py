"""Replace unused old split components with their consolidated upstream successor.

Called by woow_seed.sh before the seed-if-missing copy. For each component group
whose old folders are present in /config/custom_components:

- not in use: delete the group's old folders, so the copy that follows seeds the
  successor;
- in use (or the check could not be made): leave the group alone and print the
  successor's name on stdout, so the copy skips it (keep()).

Each group is handled on its own: an error in one keeps only that group.

Only component code folders are ever deleted; config entries, .storage and YAML
are never touched. A missing core.config_entries means Home Assistant never ran
with these components, so it does not count as in use. Log lines go to stderr.
See the CHANGELOG entry that replaced the split components.

Usage: python seed_groups.py <config_dir>
"""

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

PREFIX = "[woow_seed]"
TRASH = ".woow_seed_removed"  # under /config, outside custom_components
DONE = ".done"  # suffix of a group's trash folder once all its moves succeeded


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
    storage = config / ".storage"
    entries_file = storage / "core.config_entries"
    if entries_file.exists():
        entries = json.loads(entries_file.read_text(encoding="utf-8"))["data"]["entries"]
        for entry in entries:
            if entry.get("domain") in domains:
                return f"config entry {entry['domain']}"

    if storage.is_dir():
        for path in sorted(storage.iterdir()):
            if path.name.startswith(domains):
                return f".storage/{path.name}"

    for name in group.data_dirs:
        path = config / name
        if (path.is_dir() and any(path.iterdir())) or (path.is_file() and path.stat().st_size):
            return f"/config/{name} not empty"

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

    <group>.done holds a group whose folders were all moved out: it is deleted.
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


def main(config):
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


if __name__ == "__main__":
    main(Path(sys.argv[1]))
