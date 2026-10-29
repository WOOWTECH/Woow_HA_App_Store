"""Constants shared by the integration, importable without side effects.

This module exists so ``config_flow.py`` never has to import the package ``__init__``.
That import is not free here: ``__init__`` registers ~35 quirks into the v2 quirk registry
and monkey-patches ``DeviceRegistry.register`` **at module-import time**, so pulling it in
from the config flow would make Home Assistant do all of that merely to render the
"add integration" list. Keep this file free of Home Assistant and zigpy imports.

See docs/adr/0005-config-entry-setup.md.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "woow_zha_quirks"

# Platforms this integration forwards its config entry to.
PLATFORMS: Final = ["climate"]

# Repair-issue id for a leftover `woow_zha_quirks:` key in configuration.yaml.
# Removable together with the YAML detection itself -- see the ADR's "When the YAML
# detection can be removed".
ISSUE_YAML_REMOVED: Final = "yaml_setup_removed"

# Notification id raised by async_remove_entry: the quirks, the priority guard and the
# light_effects patch survive until Home Assistant restarts.
NOTIFY_RESTART_REQUIRED: Final = f"{DOMAIN}_restart_required"
